"""Running blocking work off the GUI thread.

``TaskRunner.run`` executes a callable on a pool thread and delivers the result (or exception)
back on the GUI thread. Tasks that mutate the session go through the serial pool so they can
never overlap; read-only/network work may use the parallel pool.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThread, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(object)
    progress = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], with_progress: bool) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.with_progress = with_progress
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn(self.signals.progress.emit) if self.with_progress else self.fn()
        except BaseException as exc:
            log.debug("Background task raised %s", type(exc).__name__, exc_info=True)
            self.signals.failed.emit(exc)
        else:
            self.signals.finished.emit(result)


class TaskRunner(QObject):
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._serial = QThreadPool(self)
        self._serial.setMaxThreadCount(1)
        self._parallel = QThreadPool(self)
        self._parallel.setMaxThreadCount(4)
        self._active: set[_Task] = set()
        self._serial_pending = 0

    @property
    def busy(self) -> bool:
        return self._serial_pending > 0

    def run(
        self,
        fn: Callable[..., Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_progress: Callable[[Any], None] | None = None,
        *,
        serial: bool = True,
    ) -> None:
        task = _Task(fn, on_progress is not None)
        self._active.add(task)
        if serial:
            self._serial_pending += 1
            if self._serial_pending == 1:
                self.busy_changed.emit(True)

        def finish() -> None:
            self._active.discard(task)
            if serial:
                self._serial_pending -= 1
                if self._serial_pending == 0:
                    self.busy_changed.emit(False)

        def done(result: object) -> None:
            finish()
            if on_done is not None:
                on_done(result)

        def failed(exc: BaseException) -> None:
            finish()
            if on_error is not None:
                on_error(exc)
            else:
                log.error("Unhandled background error: %s", exc, exc_info=exc)

        task.signals.finished.connect(done, Qt.ConnectionType.QueuedConnection)
        task.signals.failed.connect(failed, Qt.ConnectionType.QueuedConnection)
        if on_progress is not None:
            task.signals.progress.connect(on_progress, Qt.ConnectionType.QueuedConnection)
        (self._serial if serial else self._parallel).start(task)

    def wait(self, timeout_ms: int = 30000) -> bool:
        ok = self._serial.waitForDone(timeout_ms) and self._parallel.waitForDone(timeout_ms)
        QApplication.processEvents()
        return ok


class GuiInvoker(QObject):
    """Run a callable on the GUI thread and block the calling worker until it returns."""

    _request = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request.connect(self._execute, Qt.ConnectionType.BlockingQueuedConnection)

    @Slot(object)
    def _execute(self, box: list[Any]) -> None:
        fn = box[0]
        try:
            box.append(fn())
        except BaseException as exc:
            box.append(exc)

    def call(self, fn: Callable[[], Any]) -> Any:
        if QThread.currentThread() is self.thread():
            return fn()
        box: list[Any] = [fn]
        self._request.emit(box)
        result = box[1]
        if isinstance(result, BaseException):
            raise result
        return result
