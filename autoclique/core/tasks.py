"""Exécution d'une tâche (auto-clic, lecture…) dans un thread arrêtable."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

log = logging.getLogger("autoclique")


class BackgroundTask:
    """Lance ``target(stop_event)`` dans un thread.

    ``on_done(task)`` est appelé depuis ce thread quand la tâche se termine,
    normalement ou sur erreur (``task.error`` contient alors l'exception).
    """

    def __init__(
        self,
        target: Callable[[threading.Event], Any],
        name: str = "tâche",
        on_done: Optional[Callable[["BackgroundTask"], None]] = None,
    ) -> None:
        self.target = target
        self.name = name
        self.on_done = on_done
        self.stop_event = threading.Event()
        self.result: Any = None
        self.error: Optional[BaseException] = None
        self._thread = threading.Thread(target=self._run, name=f"autoclique-{name}", daemon=True)

    def _run(self) -> None:
        try:
            self.result = self.target(self.stop_event)
        except BaseException as exc:  # noqa: BLE001 - on remonte tout à l'interface
            self.error = exc
            log.exception("Erreur dans la tâche %s", self.name)
        finally:
            if self.on_done is not None:
                try:
                    self.on_done(self)
                except Exception:
                    log.exception("Erreur dans le rappel de fin de %s", self.name)

    def start(self) -> "BackgroundTask":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.stop_event.set()

    def join(self, timeout: Optional[float] = None) -> None:
        self._thread.join(timeout)

    @property
    def running(self) -> bool:
        return self._thread.is_alive()
