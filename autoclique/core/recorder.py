"""Enregistrement des actions de la souris et du clavier.

Les événements bruts (:class:`RawEvent`) sont capturés par des écouteurs
pynput, puis convertis en actions par :func:`build_actions`, une fonction pure
(testable sans affichage) qui :

* supprime les relâchements sans appui (touche du raccourci de démarrage) et
  les appuis jamais relâchés (raccourci d'arrêt) ;
* regroupe, si demandé, appui + relâchement en clic ou en appui de touche,
  les clics rapprochés en double/triple clic, et les crans de molette.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .actions import Action
from .keys import KeyRef, hotkey_name_from_event, record_key_from_event, split_pynput_key

log = logging.getLogger("autoclique")

CLICK_RADIUS = 4  # px : au-delà, un appui + relâchement devient un glisser
CLICK_HOLD_KEPT = 0.15  # s : durée d'appui conservée à partir de ce seuil
MULTI_CLICK_GAP = 0.35  # s : écart maximal entre deux clics d'un double clic
SCROLL_GAP = 0.25  # s : écart maximal entre deux crans de molette regroupés


@dataclass
class RecordOptions:
    record_moves: bool = True
    move_interval_ms: int = 10
    real_delays: bool = True
    fixed_delay_ms: int = 100
    simplify: bool = True
    destination: str = "new"  # "new" (nouvelle macro) ou "append" (macro ouverte)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "RecordOptions":
        options = cls()
        if isinstance(data, dict):
            for name, default in asdict(options).items():
                if name in data:
                    try:
                        setattr(options, name, type(default)(data[name]))
                    except (TypeError, ValueError):
                        pass
        return options


@dataclass
class RawEvent:
    t: float
    kind: str  # "move", "down", "up", "scroll", "key_down", "key_up"
    x: int = 0
    y: int = 0
    button: str = ""
    dx: int = 0
    dy: int = 0
    key: Optional[KeyRef] = None


def _key_identity(key: KeyRef) -> Tuple[str, Any]:
    # Sous Windows le code virtuel identifie la touche physique : Maj+& donne
    # « 1 » à l'appui mais « & » au relâchement si Maj est lâchée avant.
    return ("vk", key.vk) if key.vk is not None else ("name", key.name)


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def filter_unmatched(events: List[RawEvent]) -> List[RawEvent]:
    """Retire les relâchements sans appui, les répétitions automatiques et les
    appuis jamais relâchés."""
    keep = [True] * len(events)
    keys_down: Dict[Tuple[str, Any], int] = {}
    buttons_down: Dict[str, int] = {}
    for i, event in enumerate(events):
        if event.kind == "key_down":
            ident = _key_identity(event.key)
            if ident in keys_down:
                keep[i] = False  # répétition automatique d'une touche maintenue
            else:
                keys_down[ident] = i
        elif event.kind == "key_up":
            ident = _key_identity(event.key)
            if ident in keys_down:
                del keys_down[ident]
            else:
                keep[i] = False
        elif event.kind == "down":
            if event.button in buttons_down:
                keep[i] = False
            else:
                buttons_down[event.button] = i
        elif event.kind == "up":
            if event.button in buttons_down:
                del buttons_down[event.button]
            else:
                keep[i] = False
    for i in list(keys_down.values()) + list(buttons_down.values()):
        keep[i] = False
    return [event for event, ok in zip(events, keep) if ok]


@dataclass
class _Item:
    t: float
    kind: str  # move, down, up, scroll, key_down, key_up, click, key_press
    x: int = 0
    y: int = 0
    button: str = ""
    dx: int = 0
    dy: int = 0
    key: Optional[KeyRef] = None
    count: int = 1
    hold: float = 0.0  # durée conservée (s)
    last_t: float = 0.0  # instant du dernier événement regroupé

    @property
    def end(self) -> float:
        return self.t + self.hold


def _item(event: RawEvent) -> _Item:
    return _Item(event.t, event.kind, event.x, event.y, event.button, event.dx, event.dy,
                 event.key, last_t=event.t)


def _simplify(events: List[RawEvent]) -> List[_Item]:
    items: List[_Item] = []
    i = 0
    n = len(events)
    while i < n:
        event = events[i]
        if event.kind == "down":
            j = i + 1
            while j < n and events[j].kind == "move" and _dist(events[j], event) <= CLICK_RADIUS:
                j += 1
            if (j < n and events[j].kind == "up" and events[j].button == event.button
                    and _dist(events[j], event) <= CLICK_RADIUS):
                hold = events[j].t - event.t
                click = _Item(event.t, "click", event.x, event.y, event.button,
                              hold=hold if hold >= CLICK_HOLD_KEPT else 0.0, last_t=events[j].t)
                if not _merge_click(items, click):
                    items.append(click)
                i = j + 1
                continue
        elif event.kind == "key_down":
            if (i + 1 < n and events[i + 1].kind == "key_up"
                    and _key_identity(events[i + 1].key) == _key_identity(event.key)):
                items.append(_Item(event.t, "key_press", key=event.key,
                                   hold=max(0.0, events[i + 1].t - event.t), last_t=events[i + 1].t))
                i += 2
                continue
        elif event.kind == "scroll":
            previous = items[-1] if items else None
            if (previous is not None and previous.kind == "scroll"
                    and _dist(previous, event) <= CLICK_RADIUS
                    and event.t - previous.last_t <= SCROLL_GAP
                    and previous.dy * event.dy >= 0 and previous.dx * event.dx >= 0):
                previous.dy += event.dy
                previous.dx += event.dx
                previous.last_t = event.t
                i += 1
                continue
        items.append(_item(event))
        i += 1
    return items


def _merge_click(items: List[_Item], click: _Item) -> bool:
    """Fusionne ``click`` avec le clic précédent (double/triple clic)."""
    if click.hold:
        return False
    k = len(items) - 1
    while k >= 0 and items[k].kind == "move" and _dist(items[k], click) <= CLICK_RADIUS:
        k -= 1
    if k < 0:
        return False
    previous = items[k]
    if (previous.kind == "click" and previous.button == click.button and not previous.hold
            and previous.count < 3 and _dist(previous, click) <= CLICK_RADIUS
            and click.t - previous.last_t <= MULTI_CLICK_GAP):
        previous.count += 1
        previous.last_t = click.last_t
        del items[k + 1:]  # petits mouvements parasites entre les deux clics
        return True
    return False


def _to_action(item: _Item) -> Action:
    pos = [item.x, item.y]
    kind = item.kind
    if kind == "move":
        return Action.new("move", pos=pos)
    if kind == "click":
        return Action.new("click", button=item.button, count=item.count, pos=pos,
                          hold=int(round(item.hold * 1000)))
    if kind == "down":
        return Action.new("mouse_down", button=item.button, pos=pos)
    if kind == "up":
        return Action.new("mouse_up", button=item.button, pos=pos)
    if kind == "scroll":
        return Action.new("scroll", dx=item.dx, dy=item.dy, pos=pos)
    params: Dict[str, Any] = {"key": item.key.name}
    if item.key.vk is not None:
        params.update(vk=item.key.vk, vk_os="win32")
    if kind == "key_press":
        return Action.new("key_press", hold=int(round(item.hold * 1000)), **params)
    return Action.new(kind, **params)  # key_down / key_up


def build_actions(events: List[RawEvent], options: RecordOptions) -> List[Action]:
    events = filter_unmatched(sorted(events, key=lambda e: e.t))
    if not options.record_moves:
        events = [e for e in events if e.kind != "move"]
    items = _simplify(events) if options.simplify else [_item(e) for e in events]
    actions: List[Action] = []
    previous_end: Optional[float] = None
    for item in items:
        action = _to_action(item)
        if previous_end is None:
            delay = 0
        elif options.real_delays:
            delay = int(round(max(0.0, item.t - previous_end) * 1000))
        elif item.kind == "move":
            delay = min(int(round(max(0.0, item.t - previous_end) * 1000)), options.fixed_delay_ms)
        else:
            delay = options.fixed_delay_ms
        action.delay = delay
        actions.append(action)
        previous_end = item.end
    return actions


def _button_name(button) -> Optional[str]:
    name = getattr(button, "name", "")
    return {"left": "left", "right": "right", "middle": "middle", "x1": "x1", "x2": "x2",
            "button8": "x1", "button9": "x2"}.get(name)


class MacroRecorder:
    """Capture les événements de la souris et du clavier via pynput."""

    def __init__(
        self,
        options: RecordOptions,
        *,
        ignore_keys: Iterable[str] = (),
        ignore_buttons: Iterable[str] = (),
        exclude_region: Optional[Callable[[], Optional[Tuple[int, int, int, int]]]] = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.options = options
        self.ignore_keys = set(ignore_keys)
        self.ignore_buttons = set(ignore_buttons)
        self.exclude_region = exclude_region
        self.clock = clock
        self.events: List[RawEvent] = []
        self._lock = threading.Lock()
        self._last_move = (-1e9, None)
        self._listeners: List[Any] = []
        self.started_at: Optional[float] = None

    @property
    def count(self) -> int:
        return len(self.events)

    def _add(self, event: RawEvent) -> None:
        with self._lock:
            self.events.append(event)

    def _excluded(self, x: int, y: int) -> bool:
        if self.exclude_region is None:
            return False
        region = self.exclude_region()
        if not region:
            return False
        left, top, width, height = region
        return left <= x < left + width and top <= y < top + height

    # Rappels pynput (appelés depuis les threads des écouteurs).

    def _on_move(self, x, y, injected=False):
        now = self.clock()
        last_t, last_pos = self._last_move
        pos = (int(x), int(y))
        if pos == last_pos or (now - last_t) * 1000 < self.options.move_interval_ms:
            return
        self._last_move = (now, pos)
        self._add(RawEvent(now, "move", pos[0], pos[1]))

    def _on_click(self, x, y, button, pressed, injected=False):
        name = _button_name(button)
        if name is None or name in self.ignore_buttons or self._excluded(int(x), int(y)):
            return
        self._add(RawEvent(self.clock(), "down" if pressed else "up", int(x), int(y), name))

    def _on_scroll(self, x, y, dx, dy, injected=False):
        if self._excluded(int(x), int(y)):
            return
        self._add(RawEvent(self.clock(), "scroll", int(x), int(y), dx=int(dx), dy=int(dy)))

    def _on_key(self, key, pressed: bool) -> None:
        special, char, vk = split_pynput_key(key)
        if hotkey_name_from_event(special, char, vk) in self.ignore_keys:
            return
        ref = record_key_from_event(special, char, vk)
        if ref is not None:
            self._add(RawEvent(self.clock(), "key_down" if pressed else "key_up", key=ref))

    def _on_press(self, key, injected=False):
        self._on_key(key, True)

    def _on_release(self, key, injected=False):
        self._on_key(key, False)

    def start(self) -> None:
        from pynput import keyboard, mouse

        self.events = []
        self._last_move = (-1e9, None)
        mouse_listener = mouse.Listener(
            on_move=self._on_move if self.options.record_moves else None,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        keyboard_listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listeners = [mouse_listener, keyboard_listener]
        for listener in self._listeners:
            listener.start()
        for listener in self._listeners:
            listener.wait()
        self.started_at = self.clock()

    def stop(self, discard_after: Optional[float] = None) -> List[Action]:
        """Arrête l'enregistrement et renvoie les actions.

        ``discard_after`` (même horloge que ``clock``) ignore les événements
        postérieurs : clics et touches servant à revenir dans Autoclique pour
        arrêter l'enregistrement.
        """
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                log.exception("Arrêt d'un écouteur impossible")
        self._listeners = []
        with self._lock:
            events = list(self.events)
        if discard_after is not None:
            events = [e for e in events if e.t < discard_after]
        return build_actions(events, self.options)
