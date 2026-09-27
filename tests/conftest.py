import threading

import pytest

from autoclique.core.backend import FakeBackend
from autoclique.core.player import MacroPlayer
from autoclique.core.screen import Match
from autoclique.core.timing import FakeClock


class FakeScreen:
    """Écran factice : couleurs et images programmables."""

    def __init__(self):
        self.pixels = {}
        self.pixel_sequence = None  # liste de couleurs renvoyées successivement
        self.matches = []  # résultats successifs de locate (None = introuvable)
        self.pixel_calls = 0
        self.locate_calls = 0

    def pixel(self, x, y):
        self.pixel_calls += 1
        if self.pixel_sequence:
            return self.pixel_sequence.pop(0) if len(self.pixel_sequence) > 1 else self.pixel_sequence[0]
        return self.pixels.get((x, y), (0, 0, 0))

    def locate(self, data, confidence=0.9, region=None):
        self.locate_calls += 1
        if not self.matches:
            return None
        result = self.matches.pop(0) if len(self.matches) > 1 else self.matches[0]
        if result is None:
            return None
        x, y = result
        return Match(x, y, 0.99, x - 5, y - 5, 10, 10)


class FakeSystem:
    def __init__(self):
        self.opened = []
        self.windows = []
        self.focused = []

    def open_target(self, target, args=""):
        self.opened.append((target, args))

    def focus_window(self, title):
        if any(title.lower() in w.lower() for w in self.windows):
            self.focused.append(title)
            return True
        return False


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def backend(clock):
    return FakeBackend(clock=clock, position=(500, 500))


@pytest.fixture
def screen():
    return FakeScreen()


@pytest.fixture
def system():
    return FakeSystem()


@pytest.fixture
def make_player(backend, clock, screen, system):
    def factory(resolve=None, **kwargs):
        import random

        return MacroPlayer(backend, screen=screen, resolve_macro=resolve, clock=clock,
                           rng=random.Random(1), system=system, **kwargs)

    return factory


@pytest.fixture
def stop():
    return threading.Event()
