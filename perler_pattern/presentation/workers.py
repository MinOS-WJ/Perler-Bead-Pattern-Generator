from __future__ import annotations

import traceback
from collections.abc import Callable
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class BackgroundWorker(QRunnable):
    def __init__(self, operation: Callable[[Event, Callable[[int, str], None]], Any]) -> None:
        super().__init__()
        self.operation = operation
        self.cancel_event = Event()
        self.signals = WorkerSignals()

    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation(self.cancel_event, self.signals.progress.emit)
            if self.cancel_event.is_set():
                self.signals.cancelled.emit()
            else:
                self.signals.completed.emit(result)
        except Exception as error:
            if self.cancel_event.is_set():
                self.signals.cancelled.emit()
            else:
                self.signals.failed.emit("".join(traceback.format_exception(error)))
