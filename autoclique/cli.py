"""Ligne de commande d'Autoclique IA.

Exemples ::

    autoclique                          # interface graphique
    autoclique list                     # macros de la bibliothèque
    autoclique play "Ma macro" -r 3     # lire une macro trois fois
    autoclique play macro.json --dry-run
    autoclique click -i 50 -n 200       # 200 clics, un toutes les 50 ms
    autoclique record sortie.json       # enregistrer jusqu'à l'appui sur F8

Pendant une exécution, Ctrl+C ou la touche d'arrêt d'urgence (Échap par
défaut) arrêtent tout.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from . import APP_NAME, __version__


def _library(args):
    from .core.storage import MacroLibrary, data_dir

    folder = Path(args.data) if getattr(args, "data", None) else data_dir()
    return MacroLibrary(folder / "macros"), folder


def _settings(folder: Path):
    from .core.storage import load_settings, settings_path

    return load_settings(settings_path(folder))


def _load_macro(args):
    from .core.macro import Macro

    library, folder = _library(args)
    target = args.macro
    path = Path(target)
    if path.suffix.lower() == ".json" and path.exists():
        return Macro.from_json(path.read_text(encoding="utf-8")), library, folder
    macro = library.get(target)
    if macro is None:
        raise SystemExit(f"Macro introuvable : « {target} ». Utilisez « autoclique list ».")
    return macro, library, folder


class _StopKeys:
    """Arrêt par Ctrl+C ou par une touche globale."""

    def __init__(self, stop: threading.Event, hotkey: str, backend=None) -> None:
        self.stop = stop
        self.manager = None
        if not hotkey:
            return
        try:
            from .core.hotkeys import HotkeyManager

            guard = backend.recently_injected if backend is not None else None
            self.manager = HotkeyManager(lambda _b, kind: kind == "press" and stop.set(), guard)
            self.manager.set_bindings({"stop": hotkey})
            self.manager.start()
        except Exception as exc:
            print(f"(raccourci d'arrêt indisponible : {exc})", file=sys.stderr)
            self.manager = None

    def close(self) -> None:
        if self.manager is not None:
            self.manager.stop()


def _run_task(target, stop: threading.Event):
    """Exécute ``target(stop)`` dans un thread ; Ctrl+C lève ``stop``."""
    result = {}

    def runner() -> None:
        result["value"] = target(stop)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    try:
        while thread.is_alive():
            thread.join(0.1)
    except KeyboardInterrupt:
        print("\nArrêt demandé…")
        stop.set()
        thread.join(5)
    return result.get("value")


def _backend(args):
    if getattr(args, "dry_run", False):
        from .core.backend import FakeBackend

        return FakeBackend()
    from .core.backend import InputError, PynputBackend

    try:
        return PynputBackend()
    except InputError as exc:
        raise SystemExit(str(exc))


def _countdown(seconds: float) -> None:
    remaining = int(seconds)
    while remaining > 0:
        print(f"Démarrage dans {remaining}…", flush=True)
        time.sleep(1)
        remaining -= 1


# --- Commandes ------------------------------------------------------------------------


def cmd_list(args) -> int:
    from .core.keys import hotkey_label

    library, folder = _library(args)
    names = library.names()
    if not names:
        print(f"Aucune macro dans {folder / 'macros'}")
        return 0
    hotkeys = library.hotkeys()
    for name in names:
        macro = library.get(name)
        count = len(macro.actions) if macro else 0
        suffix = f"  [{hotkey_label(hotkeys[name])}]" if name in hotkeys else ""
        print(f"{name}  ({count} action{'s' if count > 1 else ''}){suffix}")
    return 0


def cmd_play(args) -> int:
    from .core.macro import analyze
    from .core.player import MacroPlayer, PlaybackOptions
    from .core.screen import ScreenCapture

    macro, library, folder = _load_macro(args)
    info = analyze(macro.actions)
    if not info.ok:
        print(f"La macro contient des erreurs :\n{info.error_text()}", file=sys.stderr)
        return 2
    settings = _settings(folder)
    backend = _backend(args)
    options = PlaybackOptions.from_macro(macro, repeat=args.repeat, speed=args.speed,
                                         failsafe=settings.failsafe and not args.dry_run)
    player = MacroPlayer(backend, screen=ScreenCapture(), resolve_macro=library.get)
    stop = threading.Event()
    stopper = None if args.dry_run else _StopKeys(stop, settings.hotkeys.get("stop_all", ""), backend)
    if args.delay:
        _countdown(args.delay)
    print(f"Lecture de « {macro.name} »…", flush=True)
    try:
        result = _run_task(lambda s: player.run(macro, options, s), stop)
    finally:
        if stopper is not None:
            stopper.close()
    if args.dry_run:
        for event in backend.events:
            print("  ", *event)
    if result is None:
        return 1
    labels = {"finished": "terminée", "stopped": "arrêtée", "aborted": "interrompue",
              "failsafe": "arrêt de sécurité", "error": "erreur"}
    message = f" — {result.message}" if result.message else ""
    print(f"Lecture {labels.get(result.status, result.status)} en {result.elapsed:.2f} s "
          f"({result.iterations} exécution(s)){message}")
    return 0 if result.status in ("finished", "stopped") else 1


def cmd_click(args) -> int:
    from .core.clicker import AutoClicker, ClickerConfig

    config = ClickerConfig(
        interval_ms=args.interval,
        random_ms=args.random,
        mode="key" if args.key else "mouse",
        key=args.key or "space",
        button=args.button,
        clicks=2 if args.double else 1,
        hold_ms=args.hold,
    )
    if args.count:
        config.repeat, config.count = "count", args.count
    elif args.duration:
        config.repeat, config.duration_s = "duration", args.duration
    if args.at:
        config.position, (config.x, config.y) = "fixed", args.at
    errors = config.validate()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    _library_obj, folder = _library(args)
    settings = _settings(folder)
    backend = _backend(args)
    clicker = AutoClicker(backend, config, failsafe=settings.failsafe and not args.dry_run)
    stop = threading.Event()
    stopper = None if args.dry_run else _StopKeys(stop, settings.hotkeys.get("stop_all", ""), backend)
    if args.delay:
        _countdown(args.delay)
    print(f"{config.summary()} — Ctrl+C pour arrêter.", flush=True)
    try:
        result = _run_task(clicker.run, stop)
    finally:
        if stopper is not None:
            stopper.close()
    if result is None:
        return 1
    print(f"{result.clicks} clic(s) en {result.elapsed:.2f} s ({result.status}).")
    return 0 if result.status in ("finished", "stopped") else 1


def cmd_record(args) -> int:
    from .core.hotkeys import HotkeyManager, hotkey_keys
    from .core.keys import hotkey_label, parse_hotkey
    from .core.macro import Macro
    from .core.recorder import MacroRecorder, RecordOptions

    try:
        stop_key = str(parse_hotkey(args.stop_key))
    except ValueError as exc:
        raise SystemExit(str(exc))
    options = RecordOptions(record_moves=not args.no_moves, simplify=not args.raw)
    keys, buttons = hotkey_keys([stop_key])
    done = threading.Event()
    manager = HotkeyManager(lambda _b, kind: kind == "press" and done.set())
    manager.set_bindings({"stop": stop_key})
    if args.delay:
        _countdown(args.delay)
    recorder = MacroRecorder(options, ignore_keys=keys, ignore_buttons=buttons)
    try:
        manager.start()
        recorder.start()
    except Exception as exc:
        raise SystemExit(f"Enregistrement impossible : {exc}")
    print(f"Enregistrement… appuyez sur {hotkey_label(stop_key)} pour terminer.", flush=True)
    try:
        while not done.wait(0.2):
            pass
    except KeyboardInterrupt:
        pass
    actions = recorder.stop()
    manager.stop()
    macro = Macro(Path(args.output).stem, actions)
    Path(args.output).write_text(macro.to_json(), encoding="utf-8")
    print(f"{len(actions)} action(s) enregistrée(s) dans {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autoclique", description=f"{APP_NAME} — auto-clic et macros.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--data", help="dossier des données (par défaut : dossier utilisateur)")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="ouvrir l'interface graphique (par défaut)")
    sub.add_parser("list", help="lister les macros de la bibliothèque")

    play = sub.add_parser("play", help="lire une macro (nom ou fichier .json)")
    play.add_argument("macro")
    play.add_argument("-r", "--repeat", type=int, help="nombre de répétitions (0 = sans fin)")
    play.add_argument("-s", "--speed", type=float, help="vitesse (2 = deux fois plus vite)")
    play.add_argument("--delay", type=float, default=0, help="compte à rebours avant de commencer (s)")
    play.add_argument("--dry-run", action="store_true", help="simuler sans toucher à la souris ni au clavier")

    click = sub.add_parser("click", help="auto-clic")
    click.add_argument("-i", "--interval", type=int, default=100, help="intervalle en ms (défaut 100)")
    click.add_argument("--random", type=int, default=0, help="variation aléatoire ± en ms")
    click.add_argument("-n", "--count", type=int, help="nombre de clics")
    click.add_argument("-d", "--duration", type=float, help="durée en secondes")
    click.add_argument("-b", "--button", default="left", choices=["left", "right", "middle", "x1", "x2"])
    click.add_argument("--double", action="store_true", help="double clic")
    click.add_argument("--hold", type=int, default=0, help="durée d'appui en ms")
    click.add_argument("--at", type=int, nargs=2, metavar=("X", "Y"), help="position fixe")
    click.add_argument("-k", "--key", help="appuyer sur une touche au lieu de cliquer (ex. espace, f5)")
    click.add_argument("--delay", type=float, default=0, help="compte à rebours avant de commencer (s)")
    click.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)

    record = sub.add_parser("record", help="enregistrer une macro dans un fichier .json")
    record.add_argument("output")
    record.add_argument("--stop-key", default="f8", help="touche de fin d'enregistrement (défaut F8)")
    record.add_argument("--no-moves", action="store_true", help="ne pas enregistrer les mouvements")
    record.add_argument("--raw", action="store_true", help="ne pas simplifier (appuis/relâchements bruts)")
    record.add_argument("--delay", type=float, default=0, help="compte à rebours avant de commencer (s)")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.selftest:
        from .app import run_selftest

        return run_selftest()
    if args.command in (None, "gui"):
        from .app import run_gui

        if args.data:
            os.environ["AUTOCLIQUE_HOME"] = args.data
        return run_gui(Path(args.data) if args.data else None)
    commands = {"list": cmd_list, "play": cmd_play, "click": cmd_click, "record": cmd_record}
    try:
        return commands[args.command](args)
    except ValueError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
