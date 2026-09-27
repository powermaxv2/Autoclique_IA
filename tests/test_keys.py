import pytest

from autoclique.core.keys import (
    Hotkey,
    KeyRef,
    hotkey_label,
    hotkey_name_from_event,
    hotkey_name_of_ref,
    key_label,
    normalize_key,
    numpad_code,
    numpad_name,
    parse_hotkey,
    record_key_from_event,
    split_pynput_key,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Entrée", "enter"),
        ("entree", "enter"),
        ("Échap", "esc"),
        ("escape", "esc"),
        (" ", "space"),
        ("Espace", "space"),
        ("A", "a"),
        ("é", "é"),
        ("É", "é"),
        ("1", "1"),
        ("&", "&"),
        ("F5", "f5"),
        ("f24", "f24"),
        ("Key.shift", "shift"),
        ("<f6>", "f6"),
        ("<65>", "vk:65"),
        ("VK:13", "vk:13"),
        ("Maj", "shift"),
        ("ctrl", "ctrl"),
        ("Contrôle", "ctrl"),
        ("Win", "cmd"),
        ("page up", "page_up"),
        ("Flèche haut", "up"),
        ("num5", "num5"),
        ("Pavé num. 5", "num5"),
        ("Suppr", "delete"),
    ],
)
def test_normalize_key(text, expected):
    assert normalize_key(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "blabla", "ctrl+c", "f99"])
def test_normalize_key_rejects_unknown(text):
    with pytest.raises(ValueError):
        normalize_key(text)


def test_key_labels():
    assert key_label("enter") == "Entrée"
    assert key_label("a") == "A"
    assert key_label("vk:65") == "Code 65"
    assert key_label("mouse_x1") == "Souris 4"
    assert key_label("num3") == "Pavé num. 3"
    assert key_label(";") == ";"


def test_parse_hotkey_basic():
    hk = parse_hotkey("Ctrl+Maj+F6")
    assert hk == Hotkey(frozenset({"ctrl", "shift"}), "f6")
    assert str(hk) == "ctrl+shift+f6"
    assert hk.label() == "Ctrl+Maj+F6"
    assert parse_hotkey(str(hk)) == hk


def test_parse_hotkey_variants():
    assert parse_hotkey("F6") == Hotkey(frozenset(), "f6")
    assert parse_hotkey("alt+A").key == "a"
    assert parse_hotkey("ctrl++").key == "+"
    assert parse_hotkey("+").key == "+"
    assert parse_hotkey("Souris 4").key == "mouse_x1"
    assert parse_hotkey("ctrl+mouse_x2") == Hotkey(frozenset({"ctrl"}), "mouse_x2")
    assert parse_hotkey("ctrl_l+c").mods == frozenset({"ctrl"})
    assert parse_hotkey("mouse_x1").is_mouse


@pytest.mark.parametrize("text", ["", "ctrl", "ctrl+maj", "f6+ctrl", "ctrl++c+", "a+b"])
def test_parse_hotkey_invalid(text):
    with pytest.raises(ValueError):
        parse_hotkey(text)


def test_hotkey_label_fallbacks():
    assert hotkey_label("") == "Aucun"
    assert hotkey_label("esc") == "Échap"
    assert hotkey_label("n'importe quoi+") == "n'importe quoi+"


def test_hotkey_name_from_event():
    assert hotkey_name_from_event("ctrl_l", None, None) == "ctrl"
    assert hotkey_name_from_event("f6", None, None) == "f6"
    # Ctrl+A sous Windows : caractère de contrôle, mais code virtuel 0x41
    assert hotkey_name_from_event(None, "\x01", 0x41, "win32") == "a"
    assert hotkey_name_from_event(None, "&", 0x31, "win32") == "1"
    assert hotkey_name_from_event(None, "A", 65, "linux") == "a"
    assert hotkey_name_from_event(None, " ", None, "linux") == "space"
    assert hotkey_name_from_event(None, "1", 0x61, "win32") == "num1"
    assert hotkey_name_from_event(None, None, 0xFFB5, "linux") == "num5"
    assert hotkey_name_from_event(None, None, 250, "linux") == "vk:250"
    assert hotkey_name_from_event(None, None, None) is None


def test_record_key_from_event():
    assert record_key_from_event("shift", None, None) == KeyRef("shift")
    assert record_key_from_event(None, "A", 0x41, "win32") == KeyRef("a", 0x41)
    assert record_key_from_event(None, "A", 65, "linux") == KeyRef("a")
    assert record_key_from_event(None, "\x03", 0x43, "win32") == KeyRef("c", 0x43)
    assert record_key_from_event(None, " ", 0x20, "win32") == KeyRef("space")
    assert record_key_from_event(None, "1", 0x61, "win32") == KeyRef("num1")
    assert record_key_from_event(None, None, 0xBA, "win32") == KeyRef("vk:186")
    assert record_key_from_event(None, None, None) is None


def test_numpad_codes_roundtrip():
    for platform in ("win32", "linux", "darwin"):
        for i in range(10):
            code = numpad_code(f"num{i}", platform)
            assert numpad_name(code, platform) == f"num{i}"
    assert numpad_code("num1", "plan9") is None
    assert numpad_name(None) is None


def test_hotkey_name_of_ref():
    assert hotkey_name_of_ref(KeyRef("shift_r")) == "shift"
    assert hotkey_name_of_ref(KeyRef("a", 0x41)) == "a"
    assert hotkey_name_of_ref(KeyRef("f9")) == "f9"


class _FakeKeyCode:
    def __init__(self, char=None, vk=None):
        self.char = char
        self.vk = vk


class _FakeKey:
    def __init__(self, name):
        self.name = name


def test_split_pynput_key():
    assert split_pynput_key(None) == (None, None, None)
    assert split_pynput_key(_FakeKeyCode("a", 65)) == (None, "a", 65)
    assert split_pynput_key(_FakeKey("esc")) == ("esc", None, None)
