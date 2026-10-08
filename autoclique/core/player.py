"""Lecture des macros.

Le lecteur exécute la liste d'actions comme un petit interpréteur : les
boucles (« Répéter » … « Fin de répétition »), les conditions (« Si » …
« Sinon » … « Fin si »), les sorties de boucle et les appels d'autres macros
sont résolus grâce à :func:`autoclique.core.macro.analyze`.

Le délai de chaque action est mesuré sur une horloge « idéale » : les petites
lenteurs d'exécution ne s'accumulent pas au fil d'une longue macro.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .actions import Action, color_to_rgb, format_seconds
from .backend import InputBackend, InputError
from .clicker import in_failsafe_corner
from .keys import MODIFIER_ORDER, KeyRef, normalize_key, parse_hotkey
from .macro import BlockInfo, Macro, analyze
from .timing import Clock, RealClock

log = logging.getLogger("autoclique")


class PlaybackError(Exception):
    """Erreur qui interrompt la lecture (message destiné à l'utilisateur)."""


class _Stopped(Exception):
    pass


class _MacroEnd(Exception):
    """Fin anticipée voulue par la macro (« Arrêter la macro », délai dépassé)."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class PlaybackOptions:
    repeat: int = 1  # 0 = indéfiniment
    speed: float = 1.0
    loop_delay: int = 0  # ms entre deux répétitions
    humanize: int = 0  # variation aléatoire des délais, en %
    start_index: int = 0  # première action exécutée (première répétition seulement)
    failsafe: bool = False

    @classmethod
    def from_macro(cls, macro: Macro, **overrides: Any) -> "PlaybackOptions":
        options = cls(
            repeat=macro.repeat,
            speed=macro.speed,
            loop_delay=macro.loop_delay,
            humanize=macro.humanize,
        )
        for name, value in overrides.items():
            if value is not None:
                setattr(options, name, value)
        return options


@dataclass
class PlaybackResult:
    status: str  # "finished", "stopped", "aborted", "failsafe" ou "error"
    message: str = ""
    iterations: int = 0
    steps: int = 0
    elapsed: float = 0.0
    error_index: Optional[int] = None


class MacroPlayer:
    MAX_DEPTH = 8
    PIXEL_POLL = 0.05
    IMAGE_POLL = 0.1
    WINDOW_POLL = 0.25

    def __init__(
        self,
        backend: InputBackend,
        *,
        screen: Any = None,
        resolve_macro: Optional[Callable[[str], Optional[Macro]]] = None,
        clock: Optional[Clock] = None,
        rng: Optional[random.Random] = None,
        system: Any = None,
    ) -> None:
        self.backend = backend
        self.screen = screen
        self.resolve_macro = resolve_macro
        self.clock = clock or RealClock()
        self.rng = rng or random.Random()
        if system is None:
            from . import system as system_module

            system = system_module
        self.system = system
        # Progression, lue par l'interface pendant la lecture.
        self.current_index = -1
        self.iteration = 0
        self.steps = 0
        self.waiting_for = ""
        self._stop = threading.Event()
        self._options = PlaybackOptions()
        self._anchor = 0.0
        self._handlers: Dict[str, Callable[[Action], None]] = {
            "click": self._do_click,
            "mouse_down": self._do_mouse_down,
            "mouse_up": self._do_mouse_up,
            "move": self._do_move,
            "scroll": self._do_scroll,
            "key_press": self._do_key_press,
            "key_down": self._do_key_down,
            "key_up": self._do_key_up,
            "hotkey": self._do_hotkey,
            "type_text": self._do_type_text,
            "wait": self._do_wait,
            "wait_pixel": self._do_wait_pixel,
            "wait_image": self._do_wait_image,
            "click_image": self._do_click_image,
            "open": self._do_open,
            "focus_window": self._do_focus_window,
        }

    # --- Point d'entrée -----------------------------------------------------------------

    def run(self, macro: Macro, options: PlaybackOptions, stop: threading.Event) -> PlaybackResult:
        self._stop = stop
        self._options = options
        self.current_index = -1
        self.iteration = 0
        self.steps = 0
        start = self.clock.now()
        info = analyze(macro.actions)
        if not info.ok:
            return PlaybackResult("error", "La macro contient des erreurs :\n" + info.error_text(),
                                  error_index=info.errors[0][0])
        if not any(a.enabled for a in macro.actions):
            return PlaybackResult("finished", "La macro ne contient aucune action.")
        self._anchor = self.clock.now()
        status, message, error_index = "finished", "", None
        try:
            iteration = 0
            while options.repeat <= 0 or iteration < options.repeat:
                iteration += 1
                self.iteration = iteration
                first = options.start_index if iteration == 1 else 0
                began = self.clock.now()
                self._execute(macro.actions, info, depth=0, start=first)
                more = options.repeat <= 0 or iteration < options.repeat
                if more and options.loop_delay > 0:
                    self._wait(self._scaled(options.loop_delay, humanize=True))
                elif more and self.clock.now() - began < 0.001:
                    self._wait(0.001)  # évite de monopoliser le processeur
        except _Stopped:
            status = "stopped"
        except _MacroEnd as end:
            status, message = end.status, end.message
        except (PlaybackError, InputError) as exc:
            status, message = "error", str(exc)
            error_index = self.current_index if self.current_index >= 0 else None
        except Exception as exc:  # erreur inattendue : on la signale sans planter
            log.exception("Erreur inattendue pendant la lecture")
            status, message = "error", f"Erreur inattendue : {exc}"
            error_index = self.current_index if self.current_index >= 0 else None
        finally:
            self.waiting_for = ""
            try:
                self.backend.release_all()
            except Exception:
                log.exception("Impossible de relâcher les touches")
        return PlaybackResult(status, message, self.iteration, self.steps,
                              self.clock.now() - start, error_index)

    # --- Interpréteur -------------------------------------------------------------------

    def _execute(self, actions: List[Action], info: BlockInfo, depth: int, start: int) -> None:
        loops: List[list] = []  # [indice du début, restant (None = infini), début d'itération]
        pc = max(0, start)
        count = len(actions)
        while pc < count:
            if self._stop.is_set():
                raise _Stopped()
            action = actions[pc]
            if depth == 0:
                self.current_index = pc
            if not action.enabled:
                pc += 1
                continue
            spec = action.spec
            if spec.has_delay and action.delay > 0:
                self._wait(self._scaled(action.delay, humanize=True))
            if self._options.failsafe and in_failsafe_corner(self.backend.position()):
                raise _MacroEnd("failsafe", "Arrêt de sécurité : curseur dans le coin supérieur gauche.")
            self.steps += 1
            kind = action.type
            if kind == "loop_start":
                repeat = int(action.params.get("count", 0))
                loops.append([pc, repeat if repeat > 0 else None, self.clock.now()])
                pc += 1
            elif kind == "loop_end":
                begin = info.match.get(pc)
                if loops and loops[-1][0] == begin:
                    top = loops[-1]
                    if top[1] is not None:
                        top[1] -= 1
                        if top[1] <= 0:
                            loops.pop()
                            pc += 1
                            continue
                    if self.clock.now() - top[2] < 0.001:
                        self._wait(0.001)  # boucle vide : ne pas saturer le processeur
                    top[2] = self.clock.now()
                    pc = begin + 1
                else:
                    pc += 1  # lecture commencée au milieu d'une boucle
            elif kind == "break":
                end = info.match[pc]
                begin = info.match.get(end)
                while loops and loops[-1][0] != begin:
                    loops.pop()
                if loops:
                    loops.pop()
                pc = end + 1
            elif kind in ("if_image", "if_pixel"):
                condition = self._check_condition(action)
                if action.params.get("negate"):
                    condition = not condition
                pc = pc + 1 if condition else info.match[pc] + 1
            elif kind == "else":
                pc = info.match[pc] + 1
            elif kind in ("end_if", "comment"):
                pc += 1
            elif kind == "stop":
                raise _MacroEnd("finished", "Macro arrêtée par l'action « Arrêter la macro ».")
            elif kind == "run_macro":
                self._run_submacro(action, depth)
                pc += 1
            else:
                handler = self._handlers.get(kind)
                if handler is None:
                    raise PlaybackError(f"Action non prise en charge : {spec.label}.")
                handler(action)
                pc += 1

    # --- Temps ----------------------------------------------------------------------------

    def _scaled(self, ms: float, humanize: bool = False) -> float:
        seconds = max(0.0, float(ms)) / 1000.0
        if humanize and self._options.humanize > 0:
            spread = self._options.humanize / 100.0
            seconds *= 1.0 + self.rng.uniform(-spread, spread)
        return seconds / max(0.01, float(self._options.speed))

    def _wait(self, seconds: float) -> None:
        """Attend ``seconds`` à partir de la fin idéale de l'action précédente."""
        now = self.clock.now()
        if now - self._anchor > 0.05:
            self._anchor = now  # gros retard : on se recale sans rattrapage en rafale
        deadline = self._anchor + max(0.0, seconds)
        if not self.clock.wait_until(deadline, self._stop):
            raise _Stopped()
        self._anchor = deadline

    def _resync(self) -> None:
        self._anchor = self.clock.now()

    def _poll(self, check: Callable[[], Any], timeout: float, interval: float, what: str) -> Any:
        """Répète ``check`` jusqu'à obtenir un résultat ou dépasser ``timeout``."""
        started = self.clock.now()
        try:
            while True:
                if self._stop.is_set():
                    raise _Stopped()
                result = check()
                if result:
                    return result
                elapsed = self.clock.now() - started
                if timeout > 0 and elapsed >= timeout:
                    return None
                self.waiting_for = f"{what} ({format_seconds(elapsed)})"
                if not self.clock.wait(interval, self._stop):
                    raise _Stopped()
        finally:
            self.waiting_for = ""
            self._resync()

    def _on_timeout(self, action: Action, message: str) -> None:
        if action.params.get("on_timeout") == "stop":
            raise _MacroEnd("aborted", f"{message} : arrêt de la macro.")
        log.warning("%s : la macro continue.", message)

    # --- Souris -----------------------------------------------------------------------------

    def _move_optional(self, pos) -> None:
        if pos is not None:
            self.backend.move_to(pos[0], pos[1])

    def _press_and_hold(self, button: str, hold_ms: float) -> None:
        self.backend.mouse_down(button)
        self._wait(self._scaled(hold_ms))
        self.backend.mouse_up(button)

    def _do_click(self, action: Action) -> None:
        p = action.params
        self._move_optional(p.get("pos"))
        count = int(p.get("count", 1))
        if p.get("hold", 0) > 0:
            for _ in range(count):
                self._press_and_hold(p["button"], p["hold"])
        else:
            self.backend.click(p["button"], count)

    def _do_mouse_down(self, action: Action) -> None:
        self._move_optional(action.params.get("pos"))
        self.backend.mouse_down(action.params["button"])

    def _do_mouse_up(self, action: Action) -> None:
        self._move_optional(action.params.get("pos"))
        self.backend.mouse_up(action.params["button"])

    def _do_move(self, action: Action) -> None:
        p = action.params
        x, y = p.get("pos") or (0, 0)
        if p.get("relative"):
            cx, cy = self.backend.position()
            x, y = cx + x, cy + y
        duration = self._scaled(p.get("duration", 0))
        if duration <= 0:
            self.backend.move_to(x, y)
            return
        sx, sy = self.backend.position()
        steps = max(2, min(1000, int(duration / 0.01)))
        for i in range(1, steps + 1):
            self._wait(duration / steps)
            t = i / steps
            eased = t * t * (3 - 2 * t)
            self.backend.move_to(sx + (x - sx) * eased, sy + (y - sy) * eased)

    def _do_scroll(self, action: Action) -> None:
        p = action.params
        self._move_optional(p.get("pos"))
        self.backend.scroll(int(p.get("dx", 0)), int(p.get("dy", 0)))

    # --- Clavier ----------------------------------------------------------------------------

    def _key(self, action: Action) -> KeyRef:
        ref = action.key_ref()
        try:
            name = normalize_key(ref.name)
        except ValueError as exc:
            raise PlaybackError(str(exc)) from None
        return KeyRef(name, ref.vk)

    def _do_key_press(self, action: Action) -> None:
        ref = self._key(action)
        self.backend.key_down(ref)
        hold = action.params.get("hold", 0)
        if hold > 0:
            self._wait(self._scaled(hold))
        self.backend.key_up(ref)

    def _do_key_down(self, action: Action) -> None:
        self.backend.key_down(self._key(action))

    def _do_key_up(self, action: Action) -> None:
        self.backend.key_up(self._key(action))

    def _do_hotkey(self, action: Action) -> None:
        try:
            combo = parse_hotkey(action.params.get("keys", ""))
        except ValueError as exc:
            raise PlaybackError(str(exc)) from None
        if combo.is_mouse:
            raise PlaybackError("Une combinaison de touches ne peut pas contenir de bouton de souris.")
        refs = [KeyRef(m) for m in MODIFIER_ORDER if m in combo.mods] + [KeyRef(combo.key)]
        for ref in refs:
            self.backend.key_down(ref)
        self._wait(0.02)
        for ref in reversed(refs):
            self.backend.key_up(ref)

    def _do_type_text(self, action: Action) -> None:
        text = str(action.params.get("text", "")).replace("\r\n", "\n")
        interval = self._scaled(action.params.get("interval", 0))
        for index, ch in enumerate(text):
            if self._stop.is_set():
                raise _Stopped()
            self.backend.type_char(ch)
            if interval > 0 and index < len(text) - 1:
                self._wait(interval)

    # --- Attentes et détection -------------------------------------------------------------

    def _do_wait(self, action: Action) -> None:
        p = action.params
        ms = float(p.get("duration", 0))
        spread = float(p.get("random", 0))
        if spread > 0:
            ms += self.rng.uniform(-spread, spread)
        self._wait(self._scaled(max(0.0, ms)))

    def _require_screen(self):
        if self.screen is None:
            raise PlaybackError("La capture d'écran n'est pas disponible.")
        return self.screen

    def _pixel_matches(self, action: Action) -> bool:
        p = action.params
        x, y = p.get("pos") or (0, 0)
        try:
            target = color_to_rgb(p.get("color", "#FFFFFF"))
        except ValueError as exc:
            raise PlaybackError(str(exc)) from None
        tolerance = int(p.get("tolerance", 0))
        try:
            actual = self._require_screen().pixel(int(x), int(y))
        except PlaybackError:
            raise
        except Exception as exc:
            raise PlaybackError(f"Lecture de l'écran impossible : {exc}") from exc
        return all(abs(int(a) - int(b)) <= tolerance for a, b in zip(actual, target))

    def _locate(self, action: Action):
        p = action.params
        if not p.get("image"):
            raise PlaybackError("Aucune image n'est définie pour cette action.")
        try:
            return self._require_screen().locate(p["image"], p.get("confidence", 90) / 100.0,
                                                 p.get("region"))
        except PlaybackError:
            raise
        except Exception as exc:
            raise PlaybackError(f"Recherche d'image impossible : {exc}") from exc

    def _check_condition(self, action: Action) -> bool:
        if action.type == "if_pixel":
            result = self._pixel_matches(action)
        else:
            result = self._locate(action) is not None
        self._resync()
        return result

    def _do_wait_pixel(self, action: Action) -> None:
        p = action.params
        found = self._poll(lambda: self._pixel_matches(action), float(p.get("timeout", 0)),
                           self.PIXEL_POLL, "Attente de la couleur")
        if not found:
            x, y = p.get("pos") or (0, 0)
            self._on_timeout(action, f"Couleur {p.get('color')} absente en ({x}, {y}) "
                                     f"après {format_seconds(p.get('timeout', 0))}")

    def _do_wait_image(self, action: Action) -> None:
        p = action.params
        found = self._poll(lambda: self._locate(action), float(p.get("timeout", 0)),
                           self.IMAGE_POLL, "Recherche de l'image")
        if not found:
            self._on_timeout(action, f"Image introuvable après {format_seconds(p.get('timeout', 0))}")

    def _do_click_image(self, action: Action) -> None:
        p = action.params
        match = self._poll(lambda: self._locate(action), float(p.get("timeout", 0)),
                           self.IMAGE_POLL, "Recherche de l'image")
        if not match:
            self._on_timeout(action, f"Image introuvable après {format_seconds(p.get('timeout', 0))}")
            return
        self.backend.move_to(match.x + int(p.get("offset_x", 0)), match.y + int(p.get("offset_y", 0)))
        self.backend.click(p.get("button", "left"), int(p.get("count", 1)))

    # --- Système et sous-macros ------------------------------------------------------------

    def _do_open(self, action: Action) -> None:
        try:
            self.system.open_target(action.params.get("target", ""), action.params.get("args", ""))
        except Exception as exc:
            raise PlaybackError(f"Impossible d'ouvrir « {action.params.get('target', '')} » : {exc}") from exc
        finally:
            self._resync()

    def _do_focus_window(self, action: Action) -> None:
        p = action.params
        title = p.get("title", "")

        def attempt() -> bool:
            try:
                return bool(self.system.focus_window(title))
            except Exception as exc:
                raise PlaybackError(f"Activation de fenêtre impossible : {exc}") from exc

        if not self._poll(attempt, float(p.get("timeout", 0)), self.WINDOW_POLL,
                          "Recherche de la fenêtre"):
            self._on_timeout(action, f"Fenêtre « {title} » introuvable")

    def _run_submacro(self, action: Action, depth: int) -> None:
        name = action.params.get("macro", "")
        if depth + 1 >= self.MAX_DEPTH:
            raise PlaybackError(f"Trop d'appels de macros imbriqués (maximum {self.MAX_DEPTH}).")
        macro = self.resolve_macro(name) if (self.resolve_macro and name) else None
        if macro is None:
            raise PlaybackError(f"Macro introuvable : « {name} ».")
        info = analyze(macro.actions)
        if not info.ok:
            raise PlaybackError(f"La macro « {name} » contient des erreurs :\n{info.error_text()}")
        for _ in range(max(1, int(action.params.get("repeat", 1)))):
            self._execute(macro.actions, info, depth + 1, 0)
