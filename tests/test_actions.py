import base64
import io
import json

import pytest

from autoclique.core.actions import (
    ACTION_TYPES,
    BLOCK_CLOSERS,
    CATEGORIES,
    Action,
    color_to_rgb,
    format_ms,
    image_size,
    normalize_color,
    rgb_to_color,
    uses_external_program,
)
from autoclique.core.keys import PLATFORM, KeyRef
from autoclique.core.macro import Macro


def _png(width=7, height=5):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 0, 0)).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_every_type_has_valid_category_and_roundtrips():
    for type_id, spec in ACTION_TYPES.items():
        assert spec.category in CATEGORIES
        action = Action.new(type_id, delay=120)
        data = action.to_dict()
        json.dumps(data)  # sérialisable
        again = Action.from_dict(data)
        assert again.type == type_id
        assert again.params == action.params
        assert again.delay == (120 if spec.has_delay else 0)
        assert isinstance(action.describe(), str)


def test_block_closers_exist():
    for opener, closer in BLOCK_CLOSERS.items():
        assert ACTION_TYPES[opener].block in ("open_loop", "open_if")
        assert ACTION_TYPES[closer].block in ("close_loop", "close_if")


def test_new_rejects_unknown():
    with pytest.raises(ValueError):
        Action.new("teleport")
    with pytest.raises(ValueError):
        Action.new("click", colour="red")


def test_coercion_and_clamping():
    action = Action.from_dict({
        "type": "click", "delay": "250", "button": "right", "count": "2",
        "pos": ["10", 20.6], "hold": -5,
    })
    assert action.delay == 250
    assert action.params == {"button": "right", "count": 2, "pos": [10, 21], "hold": 0}
    bad = Action.from_dict({"type": "click", "button": "nose", "count": 9, "pos": "abc"})
    assert bad.params["button"] == "left"
    assert bad.params["count"] == 1
    assert bad.params["pos"] is None  # position facultative -> position actuelle
    move = Action.from_dict({"type": "move", "pos": None})
    assert move.params["pos"] == [0, 0]  # position obligatoire -> valeur par défaut
    wait = Action.from_dict({"type": "wait", "duration": True})
    assert wait.params["duration"] == 1000
    region = Action.from_dict({"type": "wait_image", "region": [1, 2, 0, 5]})
    assert region.params["region"] is None


def test_disabled_flag_roundtrip():
    action = Action.new("wait", duration=10)
    action.enabled = False
    data = action.to_dict()
    assert data["enabled"] is False
    assert Action.from_dict(data).enabled is False
    assert "enabled" not in Action.new("wait").to_dict()


def test_hidden_vk_fields():
    action = Action.new("key_press", key="a", vk=0x41, vk_os="win32")
    assert action.to_dict()["vk"] == 0x41
    ref = action.key_ref()
    if PLATFORM == "win32":
        assert ref == KeyRef("a", 0x41)
    else:
        assert ref == KeyRef("a")
    plain = Action.new("key_press", key="b")
    assert "vk" not in plain.to_dict()


def test_descriptions():
    assert Action.new("click", pos=[3, 4]).describe() == "Clic gauche à (3, 4)"
    assert Action.new("click", count=2, button="right").describe() == "Double clic droit à la position du curseur"
    assert Action.new("wait", duration=1500, random=200).describe() == "1,5 s ± 200 ms"
    assert Action.new("loop_start", count=0).describe() == "indéfiniment"
    assert Action.new("key_press", key="enter", hold=0).describe() == "Entrée"
    assert Action.new("hotkey", keys="ctrl+shift+s").describe() == "Ctrl+Maj+S"
    assert "7×5" in Action.new("click_image", image=_png()).describe()
    assert Action.new("scroll", dy=-2).describe() == "↓ 2 crans"
    assert Action.new("move", pos=[5, -3], relative=True).describe() == "De (+5, -3)"
    long_text = Action.new("type_text", text="x" * 100).describe()
    assert long_text.endswith("… »")


def test_format_ms():
    assert format_ms(0) == "0 ms"
    assert format_ms(999) == "999 ms"
    assert format_ms(1000) == "1 s"
    assert format_ms(1250) == "1,25 s"
    assert format_ms(125000) == "2 min 5 s"
    assert format_ms(3_600_000) == "1 h 00 min"


def test_colors():
    assert normalize_color("#abc") == "#AABBCC"
    assert normalize_color("ff0000") == "#FF0000"
    assert normalize_color("rgb(1, 2, 300)") == "#0102FF"
    assert color_to_rgb("#0A0B0C") == (10, 11, 12)
    assert rgb_to_color((255, 128, 0)) == "#FF8000"
    with pytest.raises(ValueError):
        normalize_color("#12")
    with pytest.raises(ValueError):
        normalize_color("zzzzzz")


def test_image_size():
    assert image_size(_png(31, 17)) == (31, 17)
    assert image_size("") is None
    assert image_size("pas une image") is None


def test_uses_external_program():
    actions = [Action.new("open", target="calc.exe"), Action.new("click")]
    assert uses_external_program(actions) == ["calc.exe"]


def test_macro_roundtrip():
    macro = Macro("Test", [Action.new("click", pos=[1, 2]), Action.new("wait", duration=5)],
                  hotkey="ctrl+f1", repeat=3, speed=2.0, loop_delay=10, humanize=5)
    again = Macro.from_json(macro.to_json())
    assert again.to_dict() == macro.to_dict()


def test_macro_invalid():
    with pytest.raises(ValueError):
        Macro.from_json("{pas du json")
    with pytest.raises(ValueError):
        Macro.from_dict({"format": "autre-chose"})
    with pytest.raises(ValueError, match="Étape 2"):
        Macro.from_dict({"actions": [{"type": "click"}, {"type": "inconnu"}]})
    clamped = Macro.from_dict({"repeat": -4, "speed": 1000, "humanize": "x"})
    assert (clamped.repeat, clamped.speed, clamped.humanize) == (0, 100.0, 0)
