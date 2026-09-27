"""Fenêtre principale : onglets, barre d'état et pilotage des tâches.

Les tâches longues (auto-clic, lecture) tournent dans des threads ; les
écouteurs pynput (raccourcis, enregistrement) aussi. Toute communication vers
l'interface passe par une file de messages lue régulièrement par la boucle Tk,
seule autorisée à toucher aux widgets.
"""

from __future__ import annotations

import logging
import queue
import re
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional

from .. import APP_NAME, __version__
from ..core.actions import Action, color_to_rgb, format_seconds, rgb_to_color
from ..core.backend import InputBackend, InputError, PynputBackend
from ..core.clicker import AutoClicker
from ..core.hotkeys import HotkeyManager, hotkey_keys
from ..core.keys import hotkey_label, parse_hotkey
from ..core.macro import Macro, analyze
from ..core.player import MacroPlayer, PlaybackOptions
from ..core.recorder import MacroRecorder
from ..core.screen import ScreenCapture, available_engine
from ..core.settings import HOTKEY_LABELS, Settings
from ..core.storage import (
    MacroLibrary,
    data_dir,
    load_settings,
    save_settings,
    settings_path,
    setup_logging,
)
from ..core.tasks import BackgroundTask
from .about_tab import AboutTab
from .clicker_tab import ClickerTab
from .dialogs import capture_hotkey
from .log_tab import LogTab
from .macro_tab import MacrosTab
from .overlay import ScreenPicker, flash_point, flash_rectangle
from .settings_tab import SettingsTab
from .theme import apply_theme, palette

ASSETS = Path(__file__).resolve().parent.parent / "assets"
DEFAULT_GEOMETRY = "1180x740"


class _QueueLogHandler(logging.Handler):
    def __init__(self, events: "queue.Queue") -> None:
        super().__init__(logging.INFO)
        self.events = events

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.events.put(("log", record.levelno, record.getMessage()))
        except Exception:
            pass


class App:
    POLL_MS = 40

    def __init__(self, root: tk.Tk, *, data_folder: Optional[Path] = None,
                 backend: Optional[InputBackend] = None, enable_input: bool = True) -> None:
        self.root = root
        self.data_folder = Path(data_folder) if data_folder else data_dir()
        self.log = logging.getLogger("autoclique")
        self.log_path = setup_logging(self.data_folder)
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self._log_handler = _QueueLogHandler(self.events)
        self.log.addHandler(self._log_handler)

        self.settings_file = settings_path(self.data_folder)
        first_run = not self.settings_file.exists()
        self.settings = load_settings(self.settings_file)
        self.library = MacroLibrary(self.data_folder / "macros")
        if first_run and not self.library.names():
            self._create_examples()

        self.clipboard: List[Action] = []
        self.task: Optional[BackgroundTask] = None
        self.task_kind: Optional[str] = None
        self.clicker: Optional[AutoClicker] = None
        self.player: Optional[MacroPlayer] = None
        self.playing_name: Optional[str] = None
        self._playing_repeat = 1
        self.recorder: Optional[MacroRecorder] = None
        self._record_options = None
        self._returned_at: Optional[float] = None
        self._away = False
        self._countdown_job: Optional[str] = None
        self._countdown: Optional[tuple] = None
        self._settings_job: Optional[str] = None
        self._window_rect = None
        self._tick = 0
        self._closing = False

        self.backend = backend
        self.input_error = ""
        if self.backend is None and enable_input:
            try:
                self.backend = PynputBackend()
            except InputError as exc:
                self.input_error = str(exc)
        self.hotkeys: Optional[HotkeyManager] = None
        if enable_input and self.backend is not None:
            try:
                self.hotkeys = HotkeyManager(self._on_hotkey, is_synthetic=self.backend.recently_injected)
                self.hotkeys.start()
            except Exception as exc:
                self.hotkeys = None
                self.input_error = f"Raccourcis globaux indisponibles : {exc}"
        self.screen = ScreenCapture()

        root.report_callback_exception = self._report_exception
        self.palette = apply_theme(root, self.settings.theme)
        self._build()
        self.update_hotkeys()
        self.apply_window_settings()
        self._set_running_ui(None)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._poll_job = root.after(self.POLL_MS, self._poll)
        self.set_status("Prêt.")
        if self.input_error:
            self.log.warning(self.input_error)
        self.log.info("%s %s démarré.", APP_NAME, __version__)

    # ================================================================== construction

    def _build(self) -> None:
        root = self.root
        root.title(APP_NAME)
        root.minsize(1000, 640)
        try:
            root.geometry(self._safe_geometry(self.settings.geometry))
        except tk.TclError:
            root.geometry(DEFAULT_GEOMETRY)
        self._set_icon()

        if self.input_error:
            banner = ttk.Frame(root, padding=(14, 8))
            banner.pack(fill="x")
            ttk.Label(banner, text="⚠  " + self.input_error, style="Error.TLabel", wraplength=1000,
                      justify="left").pack(anchor="w")

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        self.clicker_tab = ClickerTab(self.notebook, self)
        self.macros_tab = MacrosTab(self.notebook, self)
        self.settings_tab = SettingsTab(self.notebook, self)
        self.log_tab = LogTab(self.notebook, self)
        self.about_tab = AboutTab(self.notebook, self)
        for tab, text in ((self.clicker_tab, "Auto-clic"), (self.macros_tab, "Macros"),
                          (self.settings_tab, "Paramètres"), (self.log_tab, "Journal"),
                          (self.about_tab, "Aide")):
            self.notebook.add(tab, text=f"  {text}  ")

        status = ttk.Frame(root, padding=(14, 6))
        status.pack(fill="x")
        self.status_dot = tk.Label(status, text="●", font=("TkDefaultFont", 12), borderwidth=0)
        self.status_dot.pack(side="left")
        self.status_text = ttk.Label(status, text="")
        self.status_text.pack(side="left", padx=(6, 0))
        self.status_hint = ttk.Label(status, text="", style="Muted.TLabel")
        self.status_hint.pack(side="right")

        root.bind("<Configure>", self._on_configure, add="+")
        root.bind("<Map>", self._on_return_to_app, add="+")
        root.bind("<FocusIn>", self._on_return_to_app, add="+")
        root.bind("<Unmap>", self._on_leave_app, add="+")
        root.bind("<FocusOut>", self._on_leave_app, add="+")
        for index in range(5):
            root.bind(f"<Control-Key-{index + 1}>", lambda _e, i=index: self.notebook.select(i))

    def _safe_geometry(self, geometry: str) -> str:
        """Géométrie mémorisée, sans position si la fenêtre tomberait hors écran
        (écran secondaire débranché, changement de résolution…)."""
        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", geometry or "")
        if not match:
            return DEFAULT_GEOMETRY
        width, height, x, y = (int(v) for v in match.groups())
        try:
            left, top, screen_w, screen_h = self.screen.virtual_screen()
        except Exception:
            left, top = 0, 0
            screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width = max(800, min(width, screen_w))
        height = max(560, min(height, screen_h))
        visible = (left - width + 150 <= x <= left + screen_w - 150) and (top <= y <= top + screen_h - 100)
        return f"{width}x{height}+{x}+{y}" if visible else f"{width}x{height}"

    def _set_icon(self) -> None:
        icon = ASSETS / "icon.png"
        if not icon.exists():
            return
        try:
            self._icon = tk.PhotoImage(file=str(icon))
            self.root.iconphoto(True, self._icon)
        except tk.TclError:
            pass

    def _create_examples(self) -> None:
        example = Macro(
            "Exemple — 10 clics",
            [
                Action.new("comment", text="Clique 10 fois là où se trouve la souris, "
                                           "une fois toutes les 0,5 s. Modifiez-moi !"),
                Action.new("loop_start", count=10),
                Action.new("click"),
                Action.new("wait", duration=500),
                Action.new("loop_end"),
            ],
        )
        try:
            self.library.save(example)
        except (OSError, ValueError):
            self.log.exception("Création de la macro d'exemple impossible")

    # ================================================================== boucle d'événements

    def _poll(self) -> None:
        if self._closing:
            return
        try:
            while True:
                self._handle_event(self.events.get_nowait())
        except queue.Empty:
            pass
        self._tick += 1
        if self._tick % 3 == 0:
            self._update_progress()
        self._poll_job = self.root.after(self.POLL_MS, self._poll)

    def _handle_event(self, event: tuple) -> None:
        kind = event[0]
        try:
            if kind == "hotkey":
                self._hotkey_action(event[1], event[2])
            elif kind == "done":
                self._task_done(event[1], event[2])
            elif kind == "log":
                self.log_tab.append(event[1], event[2])
        except Exception:
            self.log.exception("Erreur lors du traitement de %s", kind)

    def _on_hotkey(self, binding: str, kind: str) -> None:
        # Appelé depuis le thread de l'écouteur clavier : on passe par la file.
        self.events.put(("hotkey", binding, kind))

    def _hotkey_action(self, binding: str, kind: str) -> None:
        if self.recorder is not None:
            # Pendant l'enregistrement, seul le raccourci d'enregistrement agit :
            # toutes les autres touches font partie de la macro.
            if binding == "record" and kind == "press":
                self.stop_recording(from_ui=False)
            return
        if binding == "stop_all":
            if kind == "press":
                self.stop_all()
            return
        if binding == "clicker":
            if self.settings.clicker.hotkey_mode == "hold":
                if kind == "press" and not self.is_busy():
                    self.start_clicker()
                elif kind == "release" and self.task_kind == "clicker":
                    self.stop_clicker()
            elif kind == "press":
                self.toggle_clicker()
            return
        if kind != "press":
            return
        if binding == "record":
            self.toggle_recording(from_ui=False)
        elif binding == "play":
            self.toggle_playback()
        elif binding.startswith("macro:"):
            self.toggle_macro(binding[len("macro:"):])

    def _update_progress(self) -> None:
        if self.task_kind == "clicker" and self.clicker is not None:
            clicker = self.clicker
            self.clicker_tab.update_stats(clicker.clicks, clicker.elapsed(), clicker.waiting_start)
        elif self.task_kind == "macro" and self.player is not None:
            player = self.player
            index = player.current_index
            if self.playing_name == self.macros_tab.macro_name and index >= 0:
                self.macros_tab.highlight(index)
            repeat = self._playing_repeat
            iteration = f"répétition {player.iteration}" + (f"/{repeat}" if repeat else "")
            text = f"Lecture de « {self.playing_name} » — étape {index + 1}, {iteration}"
            if player.waiting_for:
                text += f" — {player.waiting_for}"
            self.set_status(text, "playing", update_title=False)
        elif self.task_kind == "record" and self.recorder is not None:
            self._refresh_window_rect()
            key = hotkey_label(self.settings.hotkeys.get("record", ""))
            hint = f" — {key} pour arrêter" if key != "Aucun" else ""
            self.set_status(f"Enregistrement en cours : {self.recorder.count} événement(s){hint}",
                            "recording", update_title=False)

    # ================================================================== état

    def is_busy(self) -> bool:
        return self.task is not None or self.recorder is not None or self._countdown_job is not None

    def _warn_busy(self) -> None:
        what = {"clicker": "L'auto-clic", "macro": "Une macro", "record": "Un enregistrement"}.get(
            self.task_kind or "", "Une action")
        self.set_status(f"{what} est déjà en cours : arrêtez-le d'abord.", "error")
        self.root.bell()

    def set_status(self, text: str, kind: str = "idle", update_title: bool = True) -> None:
        pal = palette()
        color = {"idle": pal["idle"], "running": pal["ok"], "ok": pal["ok"], "playing": pal["playing"],
                 "recording": pal["recording"], "error": pal["error"], "warn": pal["warn"]}.get(kind, pal["idle"])
        self.status_dot.configure(foreground=color, background=pal["bg"])
        self.status_text.configure(text=text)
        if update_title:
            busy_title = {"clicker": "auto-clic en cours", "macro": "lecture en cours",
                          "record": "enregistrement"}.get(self.task_kind or "")
            self.root.title(f"{APP_NAME} — {busy_title}" if busy_title else APP_NAME)

    def _set_running_ui(self, kind: Optional[str]) -> None:
        self.clicker_tab.set_running(kind == "clicker")
        self.macros_tab.set_running(kind)

    def _require_input(self) -> bool:
        if self.backend is not None:
            return True
        messagebox.showerror(APP_NAME, "Le contrôle de la souris et du clavier est indisponible :\n\n"
                             + (self.input_error or "raison inconnue."), parent=self.root)
        return False

    def _minimize(self) -> None:
        if self.settings.minimize_on_run:
            try:
                self.root.iconify()
            except tk.TclError:
                pass

    def _restore(self) -> None:
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    # ================================================================== tâches

    def _begin_task(self, kind: str, target: Callable, name: str) -> None:
        self.task_kind = kind
        self.task = BackgroundTask(target, name, on_done=lambda t: self.events.put(("done", kind, t)))
        self._set_running_ui(kind)
        self._minimize()
        self.task.start()

    def _task_done(self, kind: str, task: BackgroundTask) -> None:
        if task is not self.task:
            return
        self.task = None
        self.task_kind = None
        self._set_running_ui(None)
        result = task.result
        if task.error is not None:
            self.set_status(f"Erreur : {task.error}", "error")
            self.log.error("Erreur inattendue : %s", task.error)
            self._restore()
        elif kind == "clicker":
            self._clicker_done(result)
        elif kind == "macro":
            self._macro_done(result)
        self.clicker = None
        self.player = None
        self.macros_tab.highlight(None)

    def stop_all(self) -> None:
        if self._countdown_job is not None:
            self._cancel_countdown()
        if self.task is not None:
            self.task.stop()

    # --- Auto-clic ---------------------------------------------------------------------

    def start_clicker(self) -> None:
        if self.is_busy():
            self._warn_busy()
            return
        if not self._require_input():
            return
        try:
            config = self.clicker_tab.read_config()
        except ValueError as exc:
            self.set_status(str(exc), "error")
            messagebox.showerror("Auto-clic", str(exc), parent=self.root)
            return
        self.clicker = AutoClicker(self.backend, config, failsafe=self.settings.failsafe)
        self._begin_task("clicker", self.clicker.run, "auto-clic")
        self.set_status(f"Auto-clic en cours — {config.summary()}", "running")
        self.log.info("Auto-clic démarré : %s.", config.summary())

    def stop_clicker(self) -> None:
        if self.task_kind == "clicker" and self.task is not None:
            self.task.stop()

    def toggle_clicker(self) -> None:
        if self.task_kind == "clicker":
            self.stop_clicker()
        else:
            self.start_clicker()

    def _clicker_done(self, result) -> None:
        self.clicker_tab.update_stats(result.clicks, result.elapsed)
        summary = f"{result.clicks} clic(s) en {format_seconds(result.elapsed)}"
        if result.status == "error":
            self.set_status(f"Auto-clic interrompu : {result.message}", "error")
            self.log.error("Auto-clic interrompu : %s", result.message)
            self._restore()
        elif result.status == "failsafe":
            self.set_status(f"Arrêt de sécurité (coin de l'écran) — {summary}.", "warn")
            self.log.warning("Auto-clic : arrêt de sécurité après %s.", summary)
        elif result.status == "stopped":
            self.set_status(f"Auto-clic arrêté — {summary}.", "idle")
            self.log.info("Auto-clic arrêté : %s.", summary)
        else:
            self.set_status(f"Auto-clic terminé — {summary}.", "ok")
            self.log.info("Auto-clic terminé : %s.", summary)

    # --- Lecture -------------------------------------------------------------------------

    def play_current(self, start_index: int = 0) -> None:
        if self.is_busy():
            self._warn_busy()
            return
        macro = self.macros_tab.macro_for_playback()
        if macro is None:
            self.set_status("Aucune macro sélectionnée.", "error")
            return
        self.play_macro(macro, start_index)

    def toggle_playback(self) -> None:
        if self.task_kind == "macro":
            self.task.stop()
        elif self._countdown is not None and self._countdown[0] == "macro":
            self._cancel_countdown()
        else:
            self.play_current()

    def toggle_macro(self, name: str) -> None:
        if self.task_kind == "macro" and self.playing_name == name:
            self.task.stop()
            return
        if self.is_busy():
            self._warn_busy()
            return
        if name == self.macros_tab.macro_name:
            macro = self.macros_tab.macro_for_playback()
        else:
            macro = self.library.get(name)
        if macro is None:
            self.set_status(f"Macro introuvable : « {name} ».", "error")
            return
        self.play_macro(macro)

    def _collect_submacros(self, macro: Macro) -> Dict[str, Macro]:
        """Charge à l'avance les macros appelées (figées pendant la lecture)."""
        found: Dict[str, Macro] = {}
        pending = [macro]
        while pending:
            current = pending.pop()
            for action in current.actions:
                if action.type != "run_macro":
                    continue
                name = action.params.get("macro", "")
                if not name or name in found:
                    continue
                sub = self.macros_tab.macro_for_playback() if name == self.macros_tab.macro_name else self.library.get(name)
                if sub is not None:
                    found[name] = sub
                    pending.append(sub)
        return found

    def play_macro(self, macro: Macro, start_index: int = 0) -> None:
        if self.is_busy():
            self._warn_busy()
            return
        if not self._require_input():
            return
        info = analyze(macro.actions)
        if not info.ok:
            if macro.name == self.macros_tab.macro_name:
                self.macros_tab.show_step(info.errors[0][0])
            messagebox.showerror("Macro invalide", f"« {macro.name} » contient des erreurs :\n\n"
                                 + info.error_text(), parent=self.root)
            return
        if not macro.actions:
            self.set_status(f"La macro « {macro.name} » est vide.", "error")
            return
        library = self._collect_submacros(macro)
        options = PlaybackOptions.from_macro(macro, start_index=start_index, failsafe=self.settings.failsafe)
        player = MacroPlayer(self.backend, screen=self.screen, resolve_macro=library.get)

        def start() -> None:
            self.player = player
            self.playing_name = macro.name
            self._playing_repeat = macro.repeat
            self._begin_task("macro", lambda stop: player.run(macro, options, stop), "lecture")
            self.set_status(f"Lecture de « {macro.name} »…", "playing")
            self.log.info("Lecture de « %s » (%s).", macro.name,
                          "sans fin" if macro.repeat == 0 else f"{macro.repeat} fois")

        self._with_countdown("macro", f"Lecture de « {macro.name} »", start)

    def _macro_done(self, result) -> None:
        name = self.playing_name
        elapsed = format_seconds(result.elapsed)
        if result.status == "error":
            message = f"« {name} » interrompue : {result.message}"
            self.set_status(message.replace("\n", " "), "error")
            self.log.error(message)
            if result.error_index is not None and name == self.macros_tab.macro_name:
                self.macros_tab.show_step(result.error_index)
            self._restore()
        elif result.status == "failsafe":
            self.set_status(f"« {name} » : arrêt de sécurité (coin de l'écran).", "warn")
            self.log.warning("« %s » : arrêt de sécurité.", name)
        elif result.status == "aborted":
            self.set_status(f"« {name} » : {result.message}", "warn")
            self.log.warning("« %s » : %s", name, result.message)
        elif result.status == "stopped":
            self.set_status(f"Lecture de « {name} » arrêtée après {elapsed}.", "idle")
            self.log.info("Lecture de « %s » arrêtée après %s.", name, elapsed)
        else:
            detail = f" {result.message}" if result.message else ""
            self.set_status(f"« {name} » terminée en {elapsed} ({result.iterations} exécution(s)).{detail}", "ok")
            self.log.info("« %s » terminée en %s (%d exécution(s)).%s", name, elapsed, result.iterations, detail)
        self.playing_name = None

    # --- Enregistrement ------------------------------------------------------------------

    def toggle_recording(self, from_ui: bool = True) -> None:
        if self.recorder is not None:
            self.stop_recording(from_ui=from_ui)
        elif self._countdown is not None and self._countdown[0] == "record":
            self._cancel_countdown()
        else:
            self.start_recording()

    def start_recording(self) -> None:
        if self.is_busy():
            self._warn_busy()
            return
        if not self._require_input():
            return
        options = self.macros_tab.record_options()
        record_hotkey = self.settings.hotkeys.get("record", "")
        keys, buttons = hotkey_keys([record_hotkey]) if record_hotkey else (set(), set())

        def start() -> None:
            self._refresh_window_rect()
            recorder = MacroRecorder(options, ignore_keys=keys, ignore_buttons=buttons,
                                     exclude_region=lambda: self._window_rect)
            try:
                recorder.start()
            except Exception as exc:
                self.log.exception("Démarrage de l'enregistrement impossible")
                messagebox.showerror("Enregistrement", f"Impossible d'enregistrer :\n{exc}", parent=self.root)
                return
            self.recorder = recorder
            self._record_options = options
            self._returned_at = None
            self._away = bool(self.settings.minimize_on_run)
            self.task_kind = "record"
            self._set_running_ui("record")
            self.set_status("Enregistrement en cours…", "recording")
            self.log.info("Enregistrement démarré.")
            self._minimize()
            self.root.after(300, self._refresh_window_rect)

        self._with_countdown("record", "Enregistrement", start)

    def stop_recording(self, from_ui: bool = True) -> None:
        recorder = self.recorder
        if recorder is None:
            return
        self.recorder = None
        self.task_kind = None
        discard = None
        if from_ui and self._returned_at is not None:
            discard = self._returned_at - 0.4
        try:
            actions = recorder.stop(discard_after=discard)
        except Exception as exc:
            self.log.exception("Arrêt de l'enregistrement impossible")
            actions = []
            self.set_status(f"Erreur d'enregistrement : {exc}", "error")
        self._set_running_ui(None)
        self._restore()
        if not actions:
            self.set_status("Enregistrement terminé : aucune action capturée.", "warn")
            self.log.warning("Enregistrement terminé sans action.")
            return
        self.macros_tab.receive_recording(actions, self._record_options)
        self.notebook.select(self.macros_tab)
        self.set_status(f"Enregistrement terminé : {len(actions)} action(s).", "ok")
        self.log.info("Enregistrement terminé : %d action(s) dans « %s ».", len(actions),
                      self.macros_tab.macro_name)

    def _on_return_to_app(self, event) -> None:
        """Mémorise le moment où l'utilisateur revient dans Autoclique pendant un
        enregistrement : les clics et touches qui ont servi à y revenir (barre des
        tâches, Alt+Tab…) seront retirés s'il arrête l'enregistrement avec le bouton."""
        if self.recorder is None:
            return
        if event.type == tk.EventType.Map and event.widget is not self.root:
            return
        if self._away:
            self._away = False
            self._returned_at = self.recorder.clock()

    def _on_leave_app(self, event) -> None:
        if self.recorder is None:
            return
        if event.type == tk.EventType.Unmap:
            if event.widget is self.root:
                self._away = True
            return
        self.root.after(60, self._check_away)

    def _check_away(self) -> None:
        if self.recorder is None:
            return
        try:
            focused = self.root.focus_get()
        except (KeyError, tk.TclError):  # focus dans une fenêtre qui n'est pas à nous
            focused = None
        if focused is None:
            self._away = True

    def _on_configure(self, event) -> None:
        if event.widget is self.root:
            self._refresh_window_rect()

    def _refresh_window_rect(self) -> None:
        """Mémorise la zone de notre fenêtre : les clics qui y tombent pendant un
        enregistrement (bouton « Arrêter »…) ne sont pas enregistrés.

        Le résultat est lu par le thread de l'enregistreur, qui ne doit jamais
        appeler Tk lui-même."""
        try:
            if self.root.winfo_viewable():
                # On inclut la barre de titre (environ 40 px au-dessus de la zone cliente).
                self._window_rect = (self.root.winfo_rootx(), self.root.winfo_rooty() - 40,
                                     self.root.winfo_width(), self.root.winfo_height() + 40)
            else:
                self._window_rect = None
        except tk.TclError:
            pass

    # --- Compte à rebours -----------------------------------------------------------------

    def _with_countdown(self, kind: str, label: str, start: Callable[[], None]) -> None:
        seconds = int(self.settings.start_countdown)
        if seconds <= 0:
            start()
            return
        self._countdown = (kind, label, start, seconds)
        self._set_running_ui(kind)
        self._countdown_tick()

    def _countdown_tick(self) -> None:
        if self._countdown is None:
            return
        kind, label, start, remaining = self._countdown
        if remaining <= 0:
            self._countdown = None
            self._countdown_job = None
            self._set_running_ui(None)
            start()
            return
        stop = hotkey_label(self.settings.hotkeys.get("stop_all", ""))
        self.set_status(f"{label} dans {remaining} s…" + (f" ({stop} pour annuler)" if stop != "Aucun" else ""),
                        "recording" if kind == "record" else "playing")
        self._countdown = (kind, label, start, remaining - 1)
        self._countdown_job = self.root.after(1000, self._countdown_tick)

    def _cancel_countdown(self) -> None:
        if self._countdown_job is not None:
            try:
                self.root.after_cancel(self._countdown_job)
            except tk.TclError:
                pass
        self._countdown_job = None
        self._countdown = None
        self._set_running_ui(None)
        self.set_status("Démarrage annulé.")

    # ================================================================== écran

    def _hide_for_screen(self, parent: Optional[tk.Misc]) -> List[tk.Misc]:
        windows = [self.root]
        if parent is not None:
            top = parent.winfo_toplevel()
            if top is not self.root:
                windows.append(top)
        return windows

    def _pick(self, mode: str, callback: Callable, parent: Optional[tk.Misc]) -> None:
        windows = self._hide_for_screen(parent)
        dialog = windows[1] if len(windows) > 1 else None

        def done(result) -> None:
            if dialog is not None:
                try:
                    dialog.grab_set()
                    dialog.focus_force()
                except tk.TclError:
                    pass
            callback(result)

        def failed(message: str) -> None:
            messagebox.showerror("Capture d'écran", message, parent=dialog or self.root)

        ScreenPicker(self.root, self.screen, mode, done, hide=windows, on_error=failed).start()

    def pick_point(self, callback: Callable, parent: Optional[tk.Misc] = None) -> None:
        """Choix d'un point à l'écran ; ``callback((x, y, (r, g, b)))`` ou ``callback(None)``."""
        self._pick("point", callback, parent)

    def pick_region(self, callback: Callable, parent: Optional[tk.Misc] = None) -> None:
        """Choix d'une zone ; ``callback((x, y, largeur, hauteur, pixels))`` ou ``None``."""
        self._pick("region", callback, parent)

    def flash_point(self, x: int, y: int) -> None:
        flash_point(self.root, x, y)

    def flash_rect(self, x: int, y: int, width: int, height: int) -> None:
        flash_rectangle(self.root, x, y, width, height, color="#57c8ff")

    def _with_hidden_windows(self, parent: tk.Misc, work: Callable[[], Callable[[], None]]) -> None:
        """Masque nos fenêtres, exécute ``work`` puis les réaffiche et appelle la
        fonction renvoyée par ``work`` (affichage du résultat)."""
        windows = self._hide_for_screen(parent)
        dialog = windows[1] if len(windows) > 1 else None
        for window in windows:
            try:
                window.grab_release()
                window.withdraw()
            except tk.TclError:
                pass

        def run() -> None:
            try:
                show = work()
            except Exception as exc:
                message = str(exc)

                def show() -> None:
                    messagebox.showerror("Test", f"Échec du test :\n{message}", parent=dialog or self.root)
            for window in windows:
                try:
                    window.deiconify()
                except tk.TclError:
                    pass
            if dialog is not None:
                try:
                    dialog.lift()
                    dialog.grab_set()
                except tk.TclError:
                    pass
            show()

        self.root.after(350, run)

    def test_image(self, parent: tk.Misc, data: str, confidence: int, region) -> None:
        threshold = confidence / 100.0

        def work():
            started = time.perf_counter()
            match = self.screen.best_match(data, region, threshold)
            duration = time.perf_counter() - started
            target = parent.winfo_toplevel()

            def show() -> None:
                if match is None:
                    messagebox.showwarning("Test de l'image", "L'image est plus grande que la zone de "
                                           "recherche.", parent=target)
                    return
                score = round(match.score * 100)
                found = match.score >= threshold
                flash_rectangle(self.root, match.left, match.top, match.width, match.height,
                                color="#2ecc71" if found else "#ff3b30", duration=2500)
                timing = f"Recherche en {duration * 1000:.0f} ms."
                if found:
                    messagebox.showinfo("Test de l'image", f"Image trouvée en ({match.x}, {match.y}) "
                                        f"avec {score} % de ressemblance.\n{timing}", parent=target)
                else:
                    messagebox.showwarning(
                        "Test de l'image",
                        f"Image non trouvée : la zone la plus ressemblante (encadrée en rouge) n'atteint "
                        f"que {score} % (minimum demandé : {confidence} %).\n{timing}\n\n"
                        "Recapturez l'image ou baissez la ressemblance minimale.", parent=target)
            return show

        self._with_hidden_windows(parent, work)

    def test_pixel(self, parent: tk.Misc, pos, color: str, tolerance: int) -> None:
        def work():
            x, y = pos
            actual = self.screen.pixel(x, y)
            target = color_to_rgb(color)
            gap = max(abs(a - b) for a, b in zip(actual, target))
            top = parent.winfo_toplevel()

            def show() -> None:
                flash_point(self.root, x, y, color="#2ecc71" if gap <= tolerance else "#ff3b30")
                verdict = "correspond" if gap <= tolerance else "ne correspond pas"
                messagebox.showinfo(
                    "Test de la couleur",
                    f"Couleur actuelle en ({x}, {y}) : {rgb_to_color(actual)}\n"
                    f"Couleur attendue : {color} (tolérance {tolerance})\n\n"
                    f"Écart maximal : {gap} → la couleur {verdict}.", parent=top)
            return show

        self._with_hidden_windows(parent, work)

    def image_engine(self) -> str:
        return available_engine()

    # ================================================================== raccourcis

    def _bindings(self) -> Dict[str, str]:
        mapping = {binding: value for binding, value in self.settings.hotkeys.items() if value}
        for name, value in self.library.hotkeys().items():
            mapping[f"macro:{name}"] = value
        return mapping

    def update_hotkeys(self) -> None:
        if self.hotkeys is not None:
            self.hotkeys.set_bindings(self._bindings())
            for binding, error in self.hotkeys.matcher.invalid.items():
                self.log.warning("Raccourci invalide pour %s : %s", binding, error)
        self.clicker_tab.refresh_hotkey()
        self.macros_tab.refresh_hotkeys()
        self.settings_tab.refresh_hotkeys()
        self.about_tab.refresh()
        hints = []
        for binding, short in (("clicker", "auto-clic"), ("record", "enregistrer"), ("play", "lire"),
                               ("stop_all", "arrêt")):
            value = self.settings.hotkeys.get(binding, "")
            if value:
                hints.append(f"{hotkey_label(value)} {short}")
        text = "   ·   ".join(hints)
        if self.hotkeys is None:
            text = "Raccourcis globaux indisponibles"
        self.status_hint.configure(text=text)

    def edit_global_hotkey(self, binding: str) -> None:
        result = capture_hotkey(self.root, self.hotkeys, current=self.settings.hotkeys.get(binding, ""),
                                title=HOTKEY_LABELS.get(binding, "Raccourci"))
        if result is None:
            return
        self.set_global_hotkey(binding, result)

    def set_global_hotkey(self, binding: str, value: str) -> None:
        if value and not self.resolve_hotkey_conflict(value, binding):
            return
        self.settings.hotkeys[binding] = value
        self.save_settings_soon()
        self.update_hotkeys()

    def resolve_hotkey_conflict(self, value: str, owner: str) -> bool:
        """Vérifie qu'un raccourci n'est pas déjà pris ; propose de le libérer."""
        try:
            wanted = parse_hotkey(value)
        except ValueError:
            return True
        conflicts = []
        for binding, text in self.settings.hotkeys.items():
            if binding != owner and text:
                try:
                    if parse_hotkey(text) == wanted:
                        conflicts.append(("global", binding, HOTKEY_LABELS.get(binding, binding)))
                except ValueError:
                    pass
        for name, text in self.library.hotkeys().items():
            if f"macro:{name}" != owner:
                try:
                    if parse_hotkey(text) == wanted:
                        conflicts.append(("macro", name, f"la macro « {name} »"))
                except ValueError:
                    pass
        if not conflicts:
            return True
        users = "\n".join(f"• {label}" for _kind, _key, label in conflicts)
        if not messagebox.askyesno("Raccourci déjà utilisé",
                                   f"{wanted.label()} est déjà utilisé par :\n{users}\n\n"
                                   "Le réattribuer ?", parent=self.root):
            return False
        for kind, key, _label in conflicts:
            if kind == "global":
                self.settings.hotkeys[key] = ""
            else:
                self.macros_tab.clear_macro_hotkey(key)
        self.save_settings_soon()
        return True

    # ================================================================== paramètres

    def save_settings_soon(self) -> None:
        if self._settings_job is not None:
            try:
                self.root.after_cancel(self._settings_job)
            except tk.TclError:
                pass
        self._settings_job = self.root.after(800, self.save_settings_now)

    def save_settings_now(self) -> None:
        self._settings_job = None
        try:
            save_settings(self.settings, self.settings_file)
        except OSError as exc:
            self.log.error("Enregistrement des paramètres impossible : %s", exc)

    def apply_window_settings(self) -> None:
        try:
            self.root.attributes("-topmost", bool(self.settings.always_on_top))
        except tk.TclError:
            pass

    def set_theme(self, name: str) -> None:
        self.settings.theme = name
        self.palette = apply_theme(self.root, name)
        self.macros_tab.refresh_theme()
        self.log_tab.refresh_theme()
        self.about_tab.refresh()
        self.set_status(self.status_text.cget("text"))
        self.save_settings_soon()

    def replace_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.set_theme(settings.theme)
        self.clicker_tab.load_config(settings.clicker)
        self.settings_tab.load()
        self.apply_window_settings()
        self.update_hotkeys()
        self.save_settings_now()

    def open_data_folder(self) -> None:
        from ..core.system import open_folder

        try:
            open_folder(str(self.data_folder))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"{self.data_folder}\n\n{exc}", parent=self.root)

    def open_log_file(self) -> None:
        from ..core.system import open_target

        if self.log_path is None or not self.log_path.exists():
            messagebox.showinfo(APP_NAME, "Le fichier journal n'existe pas encore.", parent=self.root)
            return
        try:
            open_target(str(self.log_path))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"{self.log_path}\n\n{exc}", parent=self.root)

    # ================================================================== fermeture

    def _report_exception(self, exc_type, exc, tb) -> None:
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        self.log.error("Erreur inattendue dans l'interface :\n%s", details)
        try:
            self.set_status(f"Erreur inattendue : {exc}", "error")
        except Exception:
            pass

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._countdown_job is not None:
            self._cancel_countdown()
        task = self.task
        if task is not None:
            task.stop()
            task.join(1.5)
        if self.recorder is not None:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self.recorder = None
        if self.hotkeys is not None:
            self.hotkeys.stop()
        try:
            self.macros_tab.flush_save()
        except Exception:
            self.log.exception("Sauvegarde finale de la macro impossible")
        try:
            if self.root.state() == "normal":
                self.settings.geometry = self.root.geometry()
        except tk.TclError:
            pass
        if self._settings_job is not None:
            self.root.after_cancel(self._settings_job)
        self.save_settings_now()
        self.log.removeHandler(self._log_handler)
        try:
            self.root.after_cancel(self._poll_job)
        except (tk.TclError, AttributeError):
            pass
        self.root.destroy()
