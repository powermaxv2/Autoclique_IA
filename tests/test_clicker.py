import random

import pytest

from autoclique.core.clicker import AutoClicker, ClickerConfig, in_failsafe_corner


def make(backend, clock, **config):
    return AutoClicker(backend, ClickerConfig(**config), clock=clock, rng=random.Random(3))


def test_count_mode(backend, clock, stop):
    t0 = clock.now()
    result = make(backend, clock, interval_ms=100, repeat="count", count=5).run(stop)
    assert result.status == "finished"
    assert result.clicks == 5
    assert backend.events == [("click", "left", 1)] * 5
    assert [round(t - t0, 3) for t in backend.times] == [0, 0.1, 0.2, 0.3, 0.4]


def test_duration_mode(backend, clock, stop):
    result = make(backend, clock, interval_ms=100, repeat="duration", duration_s=1.0).run(stop)
    assert result.clicks == 10
    assert result.elapsed == pytest.approx(1.0)


def test_long_interval_does_not_overrun_duration(backend, clock, stop):
    result = make(backend, clock, interval_ms=10_000, repeat="duration", duration_s=15).run(stop)
    assert result.clicks == 2
    assert result.elapsed == pytest.approx(15.0)


def test_double_click_and_button(backend, clock, stop):
    make(backend, clock, repeat="count", count=2, clicks=2, button="right").run(stop)
    assert backend.events == [("click", "right", 2)] * 2


def test_hold(backend, clock, stop):
    t0 = clock.now()
    make(backend, clock, repeat="count", count=1, hold_ms=250).run(stop)
    assert backend.events == [("down", "left"), ("up", "left")]
    assert backend.times[1] - t0 == pytest.approx(0.25)


def test_key_mode(backend, clock, stop):
    make(backend, clock, mode="key", key="Espace", repeat="count", count=2, hold_ms=30).run(stop)
    assert backend.events == [("key_down", "space"), ("key_up", "space")] * 2


def test_fixed_position_with_jitter_and_restore(backend, clock, stop):
    backend.pos = (1, 1)
    make(backend, clock, repeat="count", count=20, position="fixed", x=100, y=200,
         jitter_px=3, restore_cursor=True).run(stop)
    moves = [e for e in backend.events if e[0] == "move"]
    targets = moves[0::2]
    restores = moves[1::2]
    assert all(97 <= m[1] <= 103 and 197 <= m[2] <= 203 for m in targets)
    assert all(m[1:] == (1, 1) for m in restores)
    assert len({m[1:] for m in targets}) > 1


def test_points_cycle(backend, clock, stop):
    make(backend, clock, repeat="count", count=5, position="points",
         points=[[1, 1], [2, 2], [3, 3]]).run(stop)
    moves = [e[1:] for e in backend.events if e[0] == "move"]
    assert moves == [(1, 1), (2, 2), (3, 3), (1, 1), (2, 2)]


def test_random_interval(backend, clock, stop):
    t0 = clock.now()
    make(backend, clock, interval_ms=100, random_ms=20, repeat="count", count=30).run(stop)
    gaps = [b - a for a, b in zip([t0] + backend.times[:-1], backend.times)][1:]
    assert all(0.08 - 1e-9 <= g <= 0.12 + 1e-9 for g in gaps)


def test_start_delay(backend, clock, stop):
    t0 = clock.now()
    make(backend, clock, repeat="count", count=1, start_delay_s=3).run(stop)
    assert backend.times[0] - t0 == pytest.approx(3)


def test_stop_event(backend, clock, stop):
    clicker = make(backend, clock, interval_ms=100)
    original = clock.wait_until

    def wait_until(deadline, event):
        if clicker.clicks >= 4:
            event.set()
        return original(deadline, event)

    clock.wait_until = wait_until
    result = clicker.run(stop)
    assert result.status == "stopped"
    assert result.clicks == 4


def test_failsafe(backend, clock, stop):
    backend.pos = (0, 1)
    result = AutoClicker(backend, ClickerConfig(), clock=clock, failsafe=True).run(stop)
    assert result.status == "failsafe"
    assert result.clicks == 0
    assert in_failsafe_corner((1, 0)) and not in_failsafe_corner((2, 0))


def test_validation():
    assert ClickerConfig().validate() == []
    errors = ClickerConfig(interval_ms=0, position="points", repeat="count", count=0).validate()
    assert len(errors) == 3
    assert ClickerConfig(mode="key", key="touche bizarre").validate()


def test_invalid_config_returns_error(backend, clock, stop):
    result = make(backend, clock, interval_ms=0).run(stop)
    assert result.status == "error"
    assert backend.events == []


def test_config_roundtrip_and_summary():
    config = ClickerConfig(interval_ms=250, points=[[1, 2]], repeat="count", count=7, clicks=2)
    again = ClickerConfig.from_dict(config.to_dict())
    assert again == config
    assert ClickerConfig.from_dict({"interval_ms": "abc", "clicks": 2}).interval_ms == 100
    assert ClickerConfig.from_dict(None) == ClickerConfig()
    assert config.summary() == "Double clic gauche toutes les 250 ms, 7 fois"
    assert "Espace" in ClickerConfig(mode="key", key="space").summary()
