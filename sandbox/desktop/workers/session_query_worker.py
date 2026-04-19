from __future__ import annotations

from collections.abc import Callable
from threading import Lock, Thread

from PySide6.QtCore import QObject, Signal


class SessionQueryWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        task: Callable[[], object],
    ) -> None:
        super().__init__()
        self.task = task
        self._thread: Thread | None = None
        self._lock = Lock()
        self._is_running = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def start(self) -> None:
        with self._lock:
            if self._is_running:
                return
            self._is_running = True

        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            result = self.task()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result)
        finally:
            with self._lock:
                self._is_running = False
