from autoclique.core.hotkeys import HotkeyManager, HotkeyMatcher, hotkey_keys
from autoclique.core.keys import KeyRef


def test_matcher_press_release():
    m = HotkeyMatcher()
    m.set_bindings({"clicker": "f6", "stop": "esc", "none": ""})
    assert m.feed("f6", True) == [("clicker", "press")]
    assert m.feed("f6", True) == []  # répétition automatique
    assert m.feed("f6", False) == [("clicker", "release")]
    assert m.feed("a", True) == []
    assert m.feed("esc", True) == [("stop", "press")]


def test_matcher_modifiers_and_specificity():
    m = HotkeyMatcher()
    m.set_bindings({"plain": "f6", "ctrl": "ctrl+f6", "ctrlshift": "ctrl+shift+f6"})
    assert m.feed("f6", True) == [("plain", "press")]
    m.feed("f6", False)
    m.feed("ctrl", True)
    assert m.feed("f6", True) == [("ctrl", "press")]
    m.feed("f6", False)
    m.feed("shift", True)
    assert m.feed("f6", True) == [("ctrlshift", "press")]
    m.feed("f6", False)
    m.feed("ctrl", False)
    # Maj seule enfoncée : F6 simple reste déclenché (modificateurs en trop tolérés)
    assert m.feed("f6", True) == [("plain", "press")]


def test_matcher_invalid_bindings():
    m = HotkeyMatcher()
    m.set_bindings({"bad": "ctrl+", "good": "alt+x", "mouse": "mouse_x1"})
    assert "bad" in m.invalid
    assert set(m.bindings) == {"good", "mouse"}
    assert m.uses_mouse
    m.feed("alt", True)
    assert m.feed("x", True) == [("good", "press")]


def test_matcher_combo_for():
    m = HotkeyMatcher()
    m.feed("ctrl", True)
    m.feed("alt", True)
    assert m.combo_for("f1") == "ctrl+alt+f1"


def test_hotkey_keys():
    keys, buttons = hotkey_keys(["ctrl+f8", "mouse_x2", "", "invalide+"])
    assert keys == {"f8"}
    assert buttons == {"x2"}


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


def test_manager_dispatch_and_synthetic_guard():
    triggered = []
    synthetic = {"esc"}
    manager = HotkeyManager(lambda b, k: triggered.append((b, k)), is_synthetic=lambda n: n in synthetic)
    manager.set_bindings({"clicker": "f6", "stop_all": "esc"})
    manager._on_press(FakeKey("f6"))
    manager._on_release(FakeKey("f6"))
    manager._on_press(FakeKey("esc"))  # envoyée par une macro : ignorée
    assert triggered == [("clicker", "press"), ("clicker", "release")]
    manager.enabled = False
    manager._on_press(FakeKey("f6"))
    assert len(triggered) == 2


def test_manager_capture_combo():
    triggered, captured = [], []
    manager = HotkeyManager(lambda b, k: triggered.append((b, k)))
    manager.set_bindings({"clicker": "f6"})
    manager.begin_capture(captured.append, "combo")
    assert manager.capturing
    manager._on_press(FakeKey("ctrl_l"))
    manager._on_press(FakeKeyCode("a", None))
    assert captured == ["ctrl+a"]
    assert not manager.capturing
    manager._on_release(FakeKeyCode("a", None))
    manager._on_release(FakeKey("ctrl_l"))
    # la capture n'a rien déclenché ; F6 fonctionne de nouveau ensuite
    manager._on_press(FakeKey("f6"))
    assert triggered == [("clicker", "press")]


def test_manager_capture_blocks_triggers_and_mouse():
    triggered, captured = [], []
    manager = HotkeyManager(lambda b, k: triggered.append((b, k)))
    manager.set_bindings({"clicker": "f6"})
    manager.begin_capture(captured.append, "combo")
    manager._on_click(0, 0, FakeButton("x2"), True)
    assert captured == ["mouse_x2"]
    manager.begin_capture(captured.append, "key")
    manager._on_click(0, 0, FakeButton("middle"), True)  # ignoré en mode touche
    manager._on_press(FakeKey("shift"))
    assert captured[-1] == KeyRef("shift")
    assert triggered == []


def test_manager_cancel_capture():
    captured = []
    manager = HotkeyManager(lambda b, k: None)
    manager.begin_capture(captured.append)
    manager.cancel_capture()
    manager._on_press(FakeKey("f1"))
    assert captured == []
