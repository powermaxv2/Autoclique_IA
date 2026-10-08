from autoclique.core.keys import KeyRef
from autoclique.core.recorder import (
    MacroRecorder,
    RawEvent,
    RecordOptions,
    build_actions,
    filter_unmatched,
)


def ev(t, kind, x=0, y=0, button="", dx=0, dy=0, key=None):
    return RawEvent(t, kind, x, y, button, dx, dy, KeyRef(key) if isinstance(key, str) else key)


def summary(actions):
    out = []
    for a in actions:
        p = a.params
        if a.type in ("click",):
            out.append((a.type, p["button"], p["count"], tuple(p["pos"]), p["hold"], a.delay))
        elif a.type in ("mouse_down", "mouse_up", "move"):
            out.append((a.type, tuple(p["pos"]), a.delay))
        elif a.type in ("key_press",):
            out.append((a.type, p["key"], p["hold"], a.delay))
        elif a.type in ("key_down", "key_up"):
            out.append((a.type, p["key"], a.delay))
        elif a.type == "scroll":
            out.append((a.type, p["dy"], tuple(p["pos"]), a.delay))
    return out


def test_filter_unmatched():
    events = [
        ev(0.0, "key_up", key="f8"),          # relâchement du raccourci de départ
        ev(0.1, "key_down", key="a"),
        ev(0.2, "key_down", key="a"),         # répétition automatique
        ev(0.3, "key_up", key="a"),
        ev(0.4, "up", button="left"),         # relâchement du clic sur « Enregistrer »
        ev(0.5, "down", button="left"),
        ev(0.6, "up", button="left"),
        ev(0.7, "key_down", key="ctrl"),      # modificateur du raccourci d'arrêt
    ]
    kept = filter_unmatched(events)
    assert [(e.kind, e.t) for e in kept] == [
        ("key_down", 0.1), ("key_up", 0.3), ("down", 0.5), ("up", 0.6),
    ]


def test_windows_vk_matching():
    # Maj+& donne « 1 » à l'appui, « & » au relâchement si Maj est lâchée avant.
    events = [ev(0, "key_down", key=KeyRef("1", 0x31)), ev(0.1, "key_up", key=KeyRef("&", 0x31))]
    actions = build_actions(events, RecordOptions())
    assert len(actions) == 1
    assert actions[0].type == "key_press"
    assert actions[0].params["vk"] == 0x31
    assert actions[0].params["vk_os"] == "win32"


def test_simplify_click_and_double_click():
    events = [
        ev(0.00, "move", 10, 10),
        ev(0.50, "down", 10, 10, "left"),
        ev(0.55, "move", 11, 10),
        ev(0.60, "up", 11, 10, "left"),
        ev(0.70, "down", 11, 10, "left"),
        ev(0.78, "up", 11, 10, "left"),
        ev(2.00, "down", 50, 50, "right"),
        ev(2.40, "up", 50, 50, "right"),
    ]
    actions = build_actions(events, RecordOptions())
    assert summary(actions) == [
        ("move", (10, 10), 0),
        ("click", "left", 2, (10, 10), 0, 500),
        ("click", "right", 1, (50, 50), 400, 1500),
    ]


def test_drag_is_kept():
    events = [
        ev(0.0, "down", 0, 0, "left"),
        ev(0.1, "move", 20, 0),
        ev(0.2, "move", 40, 0),
        ev(0.3, "up", 40, 0, "left"),
    ]
    actions = build_actions(events, RecordOptions())
    assert [a.type for a in actions] == ["mouse_down", "move", "move", "mouse_up"]
    assert [a.delay for a in actions] == [0, 100, 100, 100]


def test_drag_without_moves():
    events = [ev(0.0, "down", 0, 0, "left"), ev(0.1, "move", 20, 0), ev(0.3, "up", 40, 0, "left")]
    actions = build_actions(events, RecordOptions(record_moves=False))
    assert summary(actions) == [("mouse_down", (0, 0), 0), ("mouse_up", (40, 0), 300)]


def test_key_press_keeps_hold():
    events = [
        ev(1.0, "key_down", key="shift"),
        ev(1.1, "key_down", key="a"),
        ev(1.18, "key_up", key="a"),
        ev(1.3, "key_up", key="shift"),
    ]
    actions = build_actions(events, RecordOptions())
    assert summary(actions) == [
        ("key_down", "shift", 0),
        ("key_press", "a", 80, 100),
        ("key_up", "shift", 120),
    ]


def test_no_simplify():
    events = [ev(0, "down", 1, 1, "left"), ev(0.05, "up", 1, 1, "left"),
              ev(0.1, "key_down", key="a"), ev(0.2, "key_up", key="a")]
    actions = build_actions(events, RecordOptions(simplify=False))
    assert [a.type for a in actions] == ["mouse_down", "mouse_up", "key_down", "key_up"]
    assert [a.delay for a in actions] == [0, 50, 50, 100]


def test_fixed_delays():
    events = [ev(0, "down", 1, 1, "left"), ev(0.05, "up", 1, 1, "left"),
              ev(5.0, "move", 3, 3), ev(5.001, "move", 4, 4),
              ev(9.0, "key_down", key="a"), ev(9.1, "key_up", key="a")]
    actions = build_actions(events, RecordOptions(real_delays=False, fixed_delay_ms=150))
    assert [(a.type, a.delay) for a in actions] == [
        ("click", 0), ("move", 150), ("move", 1), ("key_press", 150),
    ]


def test_scroll_merge():
    events = [ev(0.0, "scroll", 5, 5, dy=-1), ev(0.1, "scroll", 5, 5, dy=-1),
              ev(0.2, "scroll", 6, 5, dy=-1), ev(0.3, "scroll", 6, 5, dy=1),
              ev(2.0, "scroll", 6, 5, dy=1)]
    actions = build_actions(events, RecordOptions())
    assert summary(actions) == [
        ("scroll", -3, (5, 5), 0),
        ("scroll", 1, (6, 5), 300),
        ("scroll", 1, (6, 5), 1700),
    ]


def test_triple_click_limit():
    events = []
    t = 0.0
    for _ in range(4):
        events += [ev(t, "down", 3, 3, "left"), ev(t + 0.05, "up", 3, 3, "left")]
        t += 0.15
    actions = build_actions(events, RecordOptions())
    assert [a.params["count"] for a in actions] == [3, 1]


class FakeKeyCode:
    def __init__(self, char=None, vk=None):
        self.char = char
        self.vk = vk


class FakeKey:
    def __init__(self, name):
        self.name = name


class FakeButton:
    def __init__(self, name):
        self.name = name


def test_recorder_callbacks_filter_and_exclude():
    clock_values = iter([i / 10 for i in range(100)])
    recorder = MacroRecorder(
        RecordOptions(move_interval_ms=0),
        ignore_keys={"f8"},
        exclude_region=lambda: (0, 0, 100, 100),
        clock=lambda: next(clock_values),
    )
    recorder._on_press(FakeKey("f8"))
    recorder._on_press(FakeKeyCode("a", 65))
    recorder._on_release(FakeKeyCode("a", 65))
    recorder._on_click(50, 50, FakeButton("left"), True)   # dans notre fenêtre : ignoré
    recorder._on_click(500, 500, FakeButton("left"), True)
    recorder._on_click(500, 500, FakeButton("left"), False)
    recorder._on_click(500, 500, FakeButton("button8"), True)
    recorder._on_click(500, 500, FakeButton("button8"), False)
    recorder._on_move(600, 600)
    recorder._on_move(600, 600)  # même position : ignorée
    recorder._on_scroll(10, 10, 0, -1)  # dans notre fenêtre : ignoré
    assert recorder.count == 7
    actions = recorder.stop()
    assert [a.type for a in actions] == ["key_press", "click", "click", "move"]
    assert actions[2].params["button"] == "x1"


def test_record_options_roundtrip():
    options = RecordOptions(record_moves=False, fixed_delay_ms=42, destination="append")
    assert RecordOptions.from_dict(options.to_dict()) == options
    assert RecordOptions.from_dict({"fixed_delay_ms": "x"}).fixed_delay_ms == 100


def test_stop_discards_late_events():
    times = iter([1.0, 2.0, 3.0, 4.0])
    recorder = MacroRecorder(RecordOptions(), clock=lambda: next(times))
    recorder._on_press(FakeKeyCode("a"))
    recorder._on_release(FakeKeyCode("a"))
    recorder._on_press(FakeKeyCode("b"))      # retour dans Autoclique…
    recorder._on_release(FakeKeyCode("b"))
    actions = recorder.stop(discard_after=2.5)
    assert [(a.type, a.params["key"]) for a in actions] == [("key_press", "a")]
