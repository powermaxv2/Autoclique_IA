"""Envoi des événements de souris et de clavier.

:class:`PynputBackend` pilote réellement la souris et le clavier (Windows,
macOS, Linux/X11). :class:`FakeBackend` se contente de noter les événements :
il sert aux tests et au mode simulation.

La classe de base garde la trace des boutons et touches maintenus pour pouvoir
tout relâcher en fin de lecture (aucune touche ne reste « coincée »), et des
touches récemment envoyées, pour que la détection des raccourcis ignore les
touches produites par les macros elles-mêmes.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Dict, List, Optional, Tuple

from .keys import NUMPAD_KEYS, KeyRef, hotkey_name_of_ref, key_label, numpad_code


class InputError(Exception):
    """Erreur de contrôle de la souris ou du clavier (message en français)."""


def _char_hotkey_name(ch: str) -> str:
    return {"\n": "enter", "\r": "enter", "\t": "tab", " ": "space"}.get(ch, ch.lower())


class InputBackend:
    GUARD_WINDOW = 0.3  # secondes pendant lesquelles une touche envoyée est ignorée

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._held_buttons: List[str] = []
        self._held_keys: List[KeyRef] = []
        self._recent: Dict[str, float] = {}

    # --- Primitives à implémenter -------------------------------------------------

    def position(self) -> Tuple[int, int]:
        raise NotImplementedError

    def _move(self, x: int, y: int) -> None:
        raise NotImplementedError

    def _press_button(self, button: str) -> None:
        raise NotImplementedError

    def _release_button(self, button: str) -> None:
        raise NotImplementedError

    def _click(self, button: str, count: int) -> None:
        for _ in range(count):
            self._press_button(button)
            self._release_button(button)

    def _scroll(self, dx: int, dy: int) -> None:
        raise NotImplementedError

    def _press_key(self, ref: KeyRef) -> None:
        raise NotImplementedError

    def _release_key(self, ref: KeyRef) -> None:
        raise NotImplementedError

    def _type_char(self, ch: str) -> None:
        raise NotImplementedError

    # --- API publique --------------------------------------------------------------

    def _mark(self, name: str) -> None:
        self._recent[name] = time.monotonic()

    def recently_injected(self, name: str) -> bool:
        """Vrai si cette touche (nom de raccourci) vient d'être envoyée par nous."""
        t = self._recent.get(name)
        return t is not None and time.monotonic() - t < self.GUARD_WINDOW

    def move_to(self, x: int, y: int) -> None:
        self._move(int(round(x)), int(round(y)))

    def mouse_down(self, button: str) -> None:
        with self._lock:
            self._mark("mouse_" + button)
            self._press_button(button)
            if button not in self._held_buttons:
                self._held_buttons.append(button)

    def mouse_up(self, button: str) -> None:
        with self._lock:
            self._mark("mouse_" + button)
            self._release_button(button)
            if button in self._held_buttons:
                self._held_buttons.remove(button)

    def click(self, button: str, count: int = 1) -> None:
        with self._lock:
            self._mark("mouse_" + button)
            self._click(button, max(1, int(count)))

    def scroll(self, dx: int, dy: int) -> None:
        if dx or dy:
            self._scroll(int(dx), int(dy))

    def key_down(self, ref: KeyRef) -> None:
        with self._lock:
            self._mark(hotkey_name_of_ref(ref))
            self._press_key(ref)
            if ref not in self._held_keys:
                self._held_keys.append(ref)

    def key_up(self, ref: KeyRef) -> None:
        with self._lock:
            self._mark(hotkey_name_of_ref(ref))
            self._release_key(ref)
            if ref in self._held_keys:
                self._held_keys.remove(ref)

    def type_char(self, ch: str) -> None:
        with self._lock:
            self._mark(_char_hotkey_name(ch))
            self._type_char(ch)

    def held(self) -> Tuple[List[str], List[KeyRef]]:
        with self._lock:
            return list(self._held_buttons), list(self._held_keys)

    def release_all(self) -> None:
        """Relâche tout ce qui a été enfoncé et pas encore relâché."""
        with self._lock:
            for ref in reversed(self._held_keys):
                try:
                    self._release_key(ref)
                except Exception:
                    pass
            for button in reversed(self._held_buttons):
                try:
                    self._release_button(button)
                except Exception:
                    pass
            self._held_keys.clear()
            self._held_buttons.clear()


class FakeBackend(InputBackend):
    """Backend factice : enregistre les événements au lieu de les envoyer."""

    def __init__(self, clock=None, position: Tuple[int, int] = (0, 0)) -> None:
        super().__init__()
        self.clock = clock
        self.pos = tuple(position)
        self.events: List[tuple] = []
        self.times: List[float] = []

    def _log(self, *event) -> None:
        self.events.append(event)
        self.times.append(self.clock.now() if self.clock is not None else 0.0)

    def position(self) -> Tuple[int, int]:
        return int(self.pos[0]), int(self.pos[1])

    def _move(self, x: int, y: int) -> None:
        self.pos = (x, y)
        self._log("move", x, y)

    def _press_button(self, button: str) -> None:
        self._log("down", button)

    def _release_button(self, button: str) -> None:
        self._log("up", button)

    def _click(self, button: str, count: int) -> None:
        self._log("click", button, count)

    def _scroll(self, dx: int, dy: int) -> None:
        self._log("scroll", dx, dy)

    def _press_key(self, ref: KeyRef) -> None:
        self._log("key_down", ref.name)

    def _release_key(self, ref: KeyRef) -> None:
        self._log("key_up", ref.name)

    def _type_char(self, ch: str) -> None:
        self._log("type", ch)

    def kinds(self) -> List[str]:
        return [e[0] for e in self.events]


def explain_input_error(exc: BaseException) -> str:
    """Message d'aide lorsque pynput ne peut pas être initialisé."""
    text = str(exc) or exc.__class__.__name__
    if sys.platform.startswith("linux"):
        import os

        if not os.environ.get("DISPLAY"):
            if os.environ.get("WAYLAND_DISPLAY"):
                return ("Session Wayland détectée : le contrôle de la souris et du clavier "
                        "nécessite une session X11 (choisissez « Xorg » à l'écran de connexion).")
            return "Aucun affichage X11 détecté (variable DISPLAY absente)."
        return f"Impossible d'accéder au serveur X11 : {text}"
    if sys.platform == "darwin":
        return ("Autorisez Autoclique (ou votre terminal) dans Réglages Système > "
                "Confidentialité et sécurité > Accessibilité et Surveillance de l'entrée. "
                f"Détail : {text}")
    return f"Contrôle de la souris et du clavier indisponible : {text}"


class PynputBackend(InputBackend):
    """Contrôle réel de la souris et du clavier via pynput."""

    def __init__(self) -> None:
        super().__init__()
        try:
            from pynput import keyboard, mouse

            self._mouse = mouse.Controller()
            self._keyboard = keyboard.Controller()
        except Exception as exc:  # ImportError, erreur X11, etc.
            raise InputError(explain_input_error(exc)) from exc
        self._Button = mouse.Button
        self._Key = keyboard.Key
        self._KeyCode = keyboard.KeyCode
        self._key_cache: Dict[KeyRef, object] = {}

    def position(self) -> Tuple[int, int]:
        pos = self._mouse.position
        if pos is None:
            return 0, 0
        return int(pos[0]), int(pos[1])

    def _move(self, x: int, y: int) -> None:
        self._mouse.position = (x, y)

    def _button(self, name: str):
        buttons = self._Button
        if name in ("x1", "x2"):
            fallback = "button8" if name == "x1" else "button9"
            button = getattr(buttons, name, None) or getattr(buttons, fallback, None)
        else:
            button = getattr(buttons, name, None)
        if button is None:
            raise InputError(f"Bouton de souris non pris en charge sur ce système : {name}.")
        return button

    def _press_button(self, button: str) -> None:
        self._mouse.press(self._button(button))

    def _release_button(self, button: str) -> None:
        self._mouse.release(self._button(button))

    def _click(self, button: str, count: int) -> None:
        self._mouse.click(self._button(button), count)

    def _scroll(self, dx: int, dy: int) -> None:
        self._mouse.scroll(dx, dy)

    def _key(self, ref: KeyRef):
        cached = self._key_cache.get(ref)
        if cached is not None:
            return cached
        key_code = self._KeyCode
        name = ref.name
        if ref.vk is not None:
            key = key_code.from_vk(ref.vk)
        elif name.startswith("vk:"):
            key = key_code.from_vk(int(name[3:]))
        elif name in NUMPAD_KEYS:
            code = numpad_code(name)
            if code is None:
                raise InputError(f"Touche non prise en charge sur ce système : {key_label(name)}.")
            key = key_code.from_vk(code)
        elif len(name) == 1:
            key = key_code.from_char(name)
        else:
            key = getattr(self._Key, name, None)
            if key is None:
                raise InputError(f"Touche non prise en charge sur ce système : {key_label(name)}.")
        self._key_cache[ref] = key
        return key

    def _press_key(self, ref: KeyRef) -> None:
        self._keyboard.press(self._key(ref))

    def _release_key(self, ref: KeyRef) -> None:
        self._keyboard.release(self._key(ref))

    def _type_char(self, ch: str) -> None:
        try:
            self._keyboard.type(ch)
        except Exception as exc:
            raise InputError(f"Impossible de taper le caractère « {ch} » : {exc}") from exc


_shared_backend: Optional[InputBackend] = None


def get_backend() -> InputBackend:
    """Backend réel partagé (créé à la première utilisation)."""
    global _shared_backend
    if _shared_backend is None:
        _shared_backend = PynputBackend()
    return _shared_backend
