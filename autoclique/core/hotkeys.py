"""Raccourcis clavier globaux (actifs même quand la fenêtre n'a pas le focus).

:class:`HotkeyMatcher` contient toute la logique de détection et ne dépend
pas de pynput ; :class:`HotkeyManager` l'alimente avec les événements des
écouteurs pynput.

Règles :

* un raccourci se déclenche à l'appui de sa touche principale si tous ses
  modificateurs sont enfoncés ; s'il y a plusieurs candidats, le plus
  spécifique l'emporte (Ctrl+F6 plutôt que F6) ;
* la répétition automatique d'une touche maintenue est ignorée ;
* le relâchement est signalé (mode « maintenir pour cliquer »).
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, List, Optional, Set, Tuple

from .keys import (
    MODIFIER_OF,
    MOUSE_HOTKEYS,
    Hotkey,
    KeyRef,
    hotkey_name_from_event,
    parse_hotkey,
    record_key_from_event,
    split_pynput_key,
)

log = logging.getLogger("autoclique")

Trigger = Tuple[str, str]  # (identifiant du raccourci, "press" ou "release")


class HotkeyMatcher:
    def __init__(self) -> None:
        self.bindings: Dict[str, Hotkey] = {}
        self.invalid: Dict[str, str] = {}
        self.mods: Set[str] = set()
        self.down: Set[str] = set()
        self.active: Dict[str, List[str]] = {}

    def set_bindings(self, mapping: Dict[str, str]) -> None:
        bindings, invalid = {}, {}
        for binding_id, text in mapping.items():
            if not text:
                continue
            try:
                bindings[binding_id] = parse_hotkey(text)
            except ValueError as exc:
                invalid[binding_id] = str(exc)
        self.bindings = bindings
        self.invalid = invalid

    @property
    def uses_mouse(self) -> bool:
        return any(h.is_mouse for h in self.bindings.values())

    def reset(self) -> None:
        self.mods.clear()
        self.down.clear()
        self.active.clear()

    def feed(self, name: str, pressed: bool) -> List[Trigger]:
        """Traite un appui/relâchement ; renvoie les raccourcis déclenchés."""
        if name in MODIFIER_OF:
            modifier = MODIFIER_OF[name]
            if pressed:
                self.mods.add(modifier)
            else:
                self.mods.discard(modifier)
            return []
        if pressed:
            if name in self.down:
                return []
            self.down.add(name)
            candidates = [(bid, hk) for bid, hk in self.bindings.items()
                          if hk.key == name and hk.mods <= self.mods]
            if not candidates:
                return []
            best = max(len(hk.mods) for _bid, hk in candidates)
            chosen = [bid for bid, hk in candidates if len(hk.mods) == best]
            self.active[name] = chosen
            return [(bid, "press") for bid in chosen]
        self.down.discard(name)
        return [(bid, "release") for bid in self.active.pop(name, [])]

    def combo_for(self, name: str) -> str:
        """Raccourci formé par les modificateurs enfoncés et ``name``."""
        return str(Hotkey(frozenset(self.mods), name))


class HotkeyManager:
    """Écoute le clavier (et la souris si nécessaire) pour les raccourcis.

    ``on_trigger(binding_id, "press"|"release")`` est appelé depuis le thread
    de l'écouteur : il doit rester très court (déposer un message dans une
    file, par exemple).
    """

    def __init__(
        self,
        on_trigger: Callable[[str, str], None],
        is_synthetic: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.on_trigger = on_trigger
        self.is_synthetic = is_synthetic
        self.matcher = HotkeyMatcher()
        self.enabled = True
        self._keyboard = None
        self._mouse = None
        self._capture: Optional[Tuple[str, Callable[[object], None]]] = None
        self._lock = threading.Lock()

    # --- Cycle de vie ----------------------------------------------------------------

    def start(self) -> None:
        from pynput import keyboard

        if self._keyboard is None:
            self._keyboard = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._keyboard.daemon = True
            self._keyboard.start()
        self._update_mouse_listener()

    def stop(self) -> None:
        for listener in (self._keyboard, self._mouse):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
        self._keyboard = None
        self._mouse = None

    @property
    def running(self) -> bool:
        return self._keyboard is not None

    def set_bindings(self, mapping: Dict[str, str]) -> None:
        with self._lock:
            self.matcher.set_bindings(mapping)
        if self.running:
            self._update_mouse_listener()

    def _update_mouse_listener(self) -> None:
        needed = self.matcher.uses_mouse or (self._capture is not None and self._capture[0] == "combo")
        if needed and self._mouse is None:
            from pynput import mouse

            self._mouse = mouse.Listener(on_click=self._on_click)
            self._mouse.daemon = True
            self._mouse.start()
        elif not needed and self._mouse is not None:
            self._mouse.stop()
            self._mouse = None

    # --- Capture d'un nouveau raccourci ---------------------------------------------

    def begin_capture(self, callback: Callable[[object], None], mode: str = "combo") -> None:
        """Le prochain raccourci (``mode="combo"``, rappel avec une chaîne) ou la
        prochaine touche (``mode="key"``, rappel avec un :class:`KeyRef`) est
        transmis à ``callback`` au lieu de déclencher une action."""
        with self._lock:
            self._capture = (mode, callback)
        if self.running:
            self._update_mouse_listener()

    def cancel_capture(self) -> None:
        with self._lock:
            self._capture = None
        if self.running:
            self._update_mouse_listener()

    @property
    def capturing(self) -> bool:
        return self._capture is not None

    # --- Rappels pynput --------------------------------------------------------------

    def _dispatch(self, triggers: List[Trigger]) -> None:
        if not self.enabled:
            return
        for binding_id, kind in triggers:
            try:
                self.on_trigger(binding_id, kind)
            except Exception:
                log.exception("Erreur dans le traitement du raccourci %s", binding_id)

    def _handle(self, name: Optional[str], pressed: bool, key=None) -> None:
        if name is None:
            return
        if pressed and self.is_synthetic is not None and self.is_synthetic(name):
            return
        captured: object = None
        with self._lock:
            capture = self._capture
            if capture is not None and pressed:
                mode = capture[0]
                if mode == "key" and key is not None:
                    captured = record_key_from_event(*split_pynput_key(key))
                elif mode == "combo" and name not in MODIFIER_OF:
                    captured = self.matcher.combo_for(name)
                    self.matcher.down.add(name)
                if captured is not None:
                    self._capture = None
            if captured is None:
                triggers = self.matcher.feed(name, pressed)
        if captured is not None:
            try:
                capture[1](captured)
            except Exception:
                log.exception("Erreur dans la capture de raccourci")
            if self.running:
                self._update_mouse_listener()
            return
        if capture is None:  # pendant une capture, aucun raccourci ne se déclenche
            self._dispatch(triggers)

    def _on_press(self, key, injected=False):
        try:
            self._handle(hotkey_name_from_event(*split_pynput_key(key)), True, key)
        except Exception:
            log.exception("Erreur de l'écouteur clavier")

    def _on_release(self, key, injected=False):
        try:
            self._handle(hotkey_name_from_event(*split_pynput_key(key)), False, key)
        except Exception:
            log.exception("Erreur de l'écouteur clavier")

    def _on_click(self, x, y, button, pressed, injected=False):
        name = {"middle": "mouse_middle", "x1": "mouse_x1", "x2": "mouse_x2",
                "button8": "mouse_x1", "button9": "mouse_x2"}.get(getattr(button, "name", ""))
        if name is None:
            return
        try:
            self._handle(name, pressed)
        except Exception:
            log.exception("Erreur de l'écouteur souris")


def hotkey_keys(texts: List[str]) -> Tuple[Set[str], Set[str]]:
    """Touches principales et boutons de souris utilisés par des raccourcis."""
    keys, buttons = set(), set()
    for text in texts:
        try:
            hotkey = parse_hotkey(text)
        except ValueError:
            continue
        if hotkey.key in MOUSE_HOTKEYS:
            buttons.add(hotkey.key[len("mouse_"):])
        else:
            keys.add(hotkey.key)
    return keys, buttons


__all__ = ["HotkeyMatcher", "HotkeyManager", "KeyRef", "hotkey_keys"]
