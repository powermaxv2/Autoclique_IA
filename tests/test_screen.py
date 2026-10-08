import numpy as np
import pytest

from autoclique.core import screen as screen_module
from autoclique.core.screen import (
    ScreenCapture,
    Shot,
    decode_png,
    encode_png,
    find_template,
)

ENGINES = ["numpy"]
try:
    import cv2  # noqa: F401

    ENGINES.append("opencv")
except Exception:
    pass


def make_scene(seed=0, height=300, width=500):
    """Fond en dégradé parsemé de rectangles colorés (ressemble à une interface)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:height, 0:width]
    img = np.stack([xx * 255 // width, yy * 255 // height, (xx + yy) % 256], axis=-1).astype(np.uint8)
    for _ in range(60):
        y, x = rng.integers(0, height - 30), rng.integers(0, width - 40)
        img[y:y + rng.integers(4, 30), x:x + rng.integers(4, 40)] = rng.integers(0, 256, 3)
    return img


def make_icon(size=24, seed=5):
    rng = np.random.default_rng(seed)
    icon = rng.integers(0, 256, (size, size, 3)).astype(np.uint8)
    icon[size // 3: 2 * size // 3, :] = (255, 255, 255)
    return icon


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("size", [8, 24, 64])
def test_find_exact(engine, size):
    scene = make_scene()
    icon = make_icon(size)
    scene[123:123 + size, 301:301 + size] = icon
    x, y, score = find_template(scene, icon, engine)
    assert (x, y) == (301, 123)
    assert score > 0.99


@pytest.mark.parametrize("engine", ENGINES)
def test_find_with_noise(engine):
    rng = np.random.default_rng(1)
    scene = make_scene()
    icon = make_icon(32)
    scene[40:72, 200:232] = icon
    noisy = np.clip(scene.astype(int) + rng.integers(-12, 13, scene.shape), 0, 255).astype(np.uint8)
    x, y, score = find_template(noisy, icon, engine)
    assert (x, y) == (200, 40)
    assert 0.8 < score < 1.0


@pytest.mark.parametrize("engine", ENGINES)
def test_absent_template_scores_low(engine):
    scene = make_scene(seed=2)
    icon = make_icon(20, seed=99)
    _x, _y, score = find_template(scene, icon, engine)
    assert score < 0.8


@pytest.mark.parametrize("engine", ENGINES)
def test_flat_color_template(engine):
    scene = np.full((200, 300, 3), 128, np.uint8)
    scene[50:90, 100:160] = (200, 30, 30)
    scene[120:160, 10:70] = (30, 200, 30)
    target = np.zeros((20, 20, 3), np.uint8)
    target[:] = (30, 200, 30)
    x, y, score = find_template(scene, target, engine)
    assert 10 <= x <= 50 and 120 <= y <= 140
    assert score > 0.99
    red = np.zeros((20, 20, 3), np.uint8)
    red[:] = (255, 0, 0)
    _x, _y, score = find_template(scene, red, engine)
    assert score < 0.8  # la couleur la plus proche est trop différente


def test_color_distinguishes_same_shapes():
    """Deux boutons de même forme mais de couleurs différentes."""
    scene = np.full((120, 240, 3), 240, np.uint8)
    button = np.full((30, 60, 3), 240, np.uint8)
    button[5:25, 5:55] = (200, 40, 40)
    button[12:18, 15:45] = (255, 255, 255)
    green = button.copy()
    green[5:25, 5:55] = (40, 160, 40)
    green[12:18, 15:45] = (255, 255, 255)
    scene[10:40, 10:70] = button
    scene[70:100, 150:210] = green
    for engine in ENGINES:
        x, y, score = find_template(scene, green, engine)
        assert (x, y) == (150, 70), engine
        assert score > 0.99


@pytest.mark.parametrize("engine", ENGINES)
def test_many_similar_labels(engine):
    """Des dizaines d'« étiquettes » presque identiques (comme du texte)."""
    rng = np.random.default_rng(7)
    base = (rng.random((16, 48)) > 0.5).astype(np.uint8) * 255
    scene = np.full((400, 600, 3), 255, np.uint8)
    positions = [(20 + (i // 8) * 60, 10 + (i % 8) * 70) for i in range(40)]
    variants = []
    for index, (y, x) in enumerate(positions):
        label = base.copy()
        r, c = divmod(index, 12)
        label[r * 4:r * 4 + 4, c * 4:c * 4 + 4] ^= 255  # petite différence
        variants.append(label)
        scene[y:y + 16, x:x + 48] = label[..., None]
    target_index = 29
    needle = np.repeat(variants[target_index][..., None], 3, axis=2)
    x, y, score = find_template(scene, needle, engine)
    assert (y, x) == positions[target_index]
    assert score > 0.99


def test_template_too_big():
    assert find_template(np.zeros((10, 10, 3), np.uint8), np.zeros((20, 5, 3), np.uint8)) is None
    with pytest.raises(ValueError):
        find_template(np.zeros((10, 10), np.uint8), np.zeros((2, 2), np.uint8))


def test_png_roundtrip():
    icon = make_icon(13)
    data = encode_png(icon)
    assert np.array_equal(decode_png(data), icon)


def test_shot_coordinates():
    shot = Shot(np.zeros((200, 400, 3), np.uint8), left=-100, top=50, scale=2.0)
    assert shot.to_screen(0, 0) == (-100, 50)
    assert shot.to_screen(200, 100) == (0, 100)
    assert shot.to_image(0, 100) == (200, 100)
    assert shot.crop(-100, 50, 10, 5).shape == (10, 20, 3)


def test_locate_with_fake_grab(monkeypatch):
    scene = make_scene(seed=4)
    icon = make_icon(16)
    scene[200:216, 50:66] = icon
    capture = ScreenCapture(engine="numpy")
    monkeypatch.setattr(capture, "grab", lambda region=None: Shot(scene, 1000, 0, 1.0))
    data = encode_png(icon)
    match = capture.locate(data, 0.9)
    assert (match.x, match.y) == (1000 + 50 + 8, 208)
    assert (match.left, match.top, match.width, match.height) == (1050, 200, 16, 16)
    assert capture.locate(encode_png(make_icon(16, seed=77)), 0.95) is None
    assert capture.template(data) is capture.template(data)  # cache


def test_available_engine_is_known():
    assert screen_module.available_engine() in ("numpy", "opencv")
