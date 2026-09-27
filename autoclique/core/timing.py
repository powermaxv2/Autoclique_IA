"""Horloges : attentes précises et interruptibles.

Les moteurs (auto-clic, lecteur de macros) ne dorment jamais avec
``time.sleep`` directement : ils passent par une horloge qui s'arrête dès que
l'événement d'arrêt est levé. Les tests utilisent :class:`FakeClock`, dont le
temps avance instantanément.
"""

from __future__ import annotations

import sys
import threading
import time


class Clock:
    """Interface d'horloge."""

    def now(self) -> float:
        raise NotImplementedError

    def wait_until(self, deadline: float, stop: threading.Event) -> bool:
        """Attend jusqu'à ``deadline``. Renvoie ``False`` si ``stop`` a été levé."""
        raise NotImplementedError

    def wait(self, seconds: float, stop: threading.Event) -> bool:
        return self.wait_until(self.now() + max(0.0, seconds), stop)


class RealClock(Clock):
    """Horloge réelle, précise à la milliseconde environ.

    Les longues attentes passent par ``Event.wait`` (réveil immédiat en cas
    d'arrêt) ; les dernières millisecondes sont attendues finement pour ne pas
    dépendre de la granularité de l'ordonnanceur du système.
    """

    def now(self) -> float:
        return time.perf_counter()

    def wait_until(self, deadline: float, stop: threading.Event) -> bool:
        while True:
            if stop.is_set():
                return False
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return True
            if remaining > 0.03:
                stop.wait(min(remaining - 0.02, 0.25))
            elif remaining > 0.002:
                time.sleep(0.001)
            else:
                time.sleep(0)


class FakeClock(Clock):
    """Horloge virtuelle pour les tests : le temps avance sans attendre."""

    def __init__(self, start: float = 1000.0):
        self.t = start
        self.waits = []

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds

    def wait_until(self, deadline: float, stop: threading.Event) -> bool:
        if stop.is_set():
            return False
        if deadline > self.t:
            self.waits.append(deadline - self.t)
            self.t = deadline
        return not stop.is_set()


_timer_resolution_set = False


def enable_high_resolution_timer() -> None:
    """Sous Windows, demande une résolution de minuterie de 1 ms.

    Sans cela, les attentes courtes peuvent durer jusqu'à ~15,6 ms, ce qui
    limite la cadence de l'auto-clic.
    """
    global _timer_resolution_set
    if _timer_resolution_set or not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.winmm.timeBeginPeriod(1)
        _timer_resolution_set = True
    except Exception:
        pass
