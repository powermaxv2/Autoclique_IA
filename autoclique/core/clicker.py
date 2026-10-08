"""Auto-clic : clics (ou appuis de touche) répétés à intervalle régulier."""

from __future__ import annotations

import random
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .actions import format_ms, format_seconds
from .backend import InputBackend, InputError
from .keys import MOUSE_BUTTONS, KeyRef, key_label, normalize_key
from .timing import Clock, RealClock


@dataclass
class ClickerConfig:
    interval_ms: int = 100
    random_ms: int = 0  # variation aléatoire ± de l'intervalle
    mode: str = "mouse"  # "mouse" ou "key"
    button: str = "left"
    clicks: int = 1  # 1 = simple, 2 = double, 3 = triple
    hold_ms: int = 0  # durée d'appui de chaque clic
    key: str = "space"
    repeat: str = "infinite"  # "infinite", "count" ou "duration"
    count: int = 100
    duration_s: float = 60.0
    position: str = "current"  # "current", "fixed" ou "points"
    x: int = 0
    y: int = 0
    points: List[List[int]] = field(default_factory=list)
    jitter_px: int = 0  # décalage aléatoire ± de la position (positions fixes)
    restore_cursor: bool = False
    start_delay_s: float = 0.0
    hotkey_mode: str = "toggle"  # "toggle" (appuyer pour démarrer/arrêter) ou "hold"

    def validate(self) -> List[str]:
        errors = []
        if self.interval_ms < 1:
            errors.append("L'intervalle doit être d'au moins 1 ms.")
        if self.random_ms < 0:
            errors.append("La variation aléatoire ne peut pas être négative.")
        if self.mode not in ("mouse", "key"):
            errors.append("Type d'action inconnu.")
        if self.mode == "mouse" and self.button not in MOUSE_BUTTONS:
            errors.append("Bouton de souris inconnu.")
        if self.mode == "key":
            try:
                normalize_key(self.key)
            except ValueError as exc:
                errors.append(str(exc))
        if self.clicks not in (1, 2, 3):
            errors.append("Le type de clic doit être simple, double ou triple.")
        if self.repeat == "count" and self.count < 1:
            errors.append("Le nombre de clics doit être d'au moins 1.")
        if self.repeat == "duration" and self.duration_s <= 0:
            errors.append("La durée doit être positive.")
        if self.position == "points" and not self.points:
            errors.append("Ajoutez au moins un point à la liste des positions.")
        if self.hold_ms < 0 or self.start_delay_s < 0 or self.jitter_px < 0:
            errors.append("Les durées et décalages ne peuvent pas être négatifs.")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ClickerConfig":
        config = cls()
        if not isinstance(data, dict):
            return config
        for name, default in asdict(config).items():
            if name not in data:
                continue
            value = data[name]
            try:
                if isinstance(default, bool):
                    value = bool(value)
                elif isinstance(default, int):
                    value = int(value)
                elif isinstance(default, float):
                    value = float(value)
                elif isinstance(default, str):
                    value = str(value)
                elif isinstance(default, list):
                    value = [[int(p[0]), int(p[1])] for p in value]
            except (TypeError, ValueError, IndexError):
                continue
            setattr(config, name, value)
        return config

    def summary(self) -> str:
        if self.mode == "key":
            try:
                what = f"Touche {key_label(normalize_key(self.key))}"
            except ValueError:
                what = "Touche"
        else:
            kind = {1: "Clic", 2: "Double clic", 3: "Triple clic"}.get(self.clicks, "Clic")
            what = f"{kind} {MOUSE_BUTTONS.get(self.button, self.button).split(' (')[0].lower()}"
        text = f"{what} toutes les {format_ms(self.interval_ms)}"
        if self.random_ms:
            text += f" (± {format_ms(self.random_ms)})"
        if self.repeat == "count":
            text += f", {self.count} fois"
        elif self.repeat == "duration":
            text += f", pendant {format_seconds(self.duration_s)}"
        else:
            text += ", jusqu'à l'arrêt"
        return text


@dataclass
class ClickerResult:
    status: str  # "finished", "stopped", "failsafe" ou "error"
    clicks: int = 0
    elapsed: float = 0.0
    message: str = ""


def in_failsafe_corner(pos: Tuple[int, int]) -> bool:
    """Vrai si le curseur est plaqué dans le coin supérieur gauche."""
    x, y = pos
    return 0 <= x <= 1 and 0 <= y <= 1


class AutoClicker:
    def __init__(
        self,
        backend: InputBackend,
        config: ClickerConfig,
        clock: Optional[Clock] = None,
        failsafe: bool = False,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.backend = backend
        self.config = config
        self.clock = clock or RealClock()
        self.failsafe = failsafe
        self.rng = rng or random.Random()
        self.clicks = 0
        self.started_at: Optional[float] = None
        self.waiting_start = False

    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        return max(0.0, self.clock.now() - self.started_at)

    def _target(self, index: int) -> Optional[Tuple[int, int]]:
        cfg = self.config
        if cfg.position == "fixed":
            x, y = cfg.x, cfg.y
        elif cfg.position == "points" and cfg.points:
            x, y = cfg.points[index % len(cfg.points)]
        else:
            return None
        if cfg.jitter_px > 0:
            x += self.rng.randint(-cfg.jitter_px, cfg.jitter_px)
            y += self.rng.randint(-cfg.jitter_px, cfg.jitter_px)
        return x, y

    def _hold(self, stop: threading.Event) -> bool:
        return self.clock.wait(self.config.hold_ms / 1000.0, stop)

    def _perform(self, index: int, stop: threading.Event) -> None:
        cfg = self.config
        target = self._target(index)
        before = self.backend.position() if (target and cfg.restore_cursor) else None
        if target is not None:
            self.backend.move_to(*target)
        try:
            if cfg.mode == "key":
                ref = KeyRef(normalize_key(cfg.key))
                self.backend.key_down(ref)
                try:
                    if cfg.hold_ms > 0:
                        self._hold(stop)
                finally:
                    self.backend.key_up(ref)
            elif cfg.hold_ms > 0:
                for _ in range(cfg.clicks):
                    self.backend.mouse_down(cfg.button)
                    try:
                        self._hold(stop)
                    finally:
                        self.backend.mouse_up(cfg.button)
                    if stop.is_set():
                        break
            else:
                self.backend.click(cfg.button, cfg.clicks)
        finally:
            if before is not None:
                self.backend.move_to(*before)

    def run(self, stop: threading.Event) -> ClickerResult:
        cfg = self.config
        errors = cfg.validate()
        if errors:
            return ClickerResult("error", message=" ".join(errors))
        clock = self.clock
        if cfg.start_delay_s > 0:
            self.waiting_start = True
            if not clock.wait(cfg.start_delay_s, stop):
                self.waiting_start = False
                return ClickerResult("stopped")
            self.waiting_start = False
        start = clock.now()
        self.started_at = start
        next_time = start
        status, message = "finished", ""
        try:
            while True:
                if stop.is_set():
                    status = "stopped"
                    break
                if cfg.repeat == "count" and self.clicks >= cfg.count:
                    break
                if cfg.repeat == "duration" and clock.now() - start >= cfg.duration_s:
                    break
                if self.failsafe and in_failsafe_corner(self.backend.position()):
                    status = "failsafe"
                    break
                self._perform(self.clicks, stop)
                self.clicks += 1
                interval = cfg.interval_ms
                if cfg.random_ms:
                    interval += self.rng.uniform(-cfg.random_ms, cfg.random_ms)
                next_time += max(1.0, interval) / 1000.0
                now = clock.now()
                if next_time < now - 0.05:
                    next_time = now  # trop de retard : on repart sans rafale
                deadline = next_time
                if cfg.repeat == "duration":
                    deadline = min(deadline, start + cfg.duration_s)
                if cfg.repeat == "count" and self.clicks >= cfg.count:
                    break
                if not clock.wait_until(deadline, stop):
                    status = "stopped"
                    break
        except InputError as exc:
            status, message = "error", str(exc)
        finally:
            self.backend.release_all()
        return ClickerResult(status, self.clicks, clock.now() - start, message)
