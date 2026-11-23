"""Run blocking work off the GUI thread."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QRunnable, QThreadPool, Signal

from torrentlinker.agent.coordination import coordinator


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any], coordinate: bool = True) -> None:
        super().__init__()
        self.fn = fn
        self.coordinate = coordinate
        self.signals = _Signals()

    def run(self) -> None:
        try:
            with coordinator.desktop() if self.coordinate else nullcontext():
                result = self.fn()
        except Exception as e:  # noqa: BLE001 - surfaced to the GUI
            self.signals.failed.emit(e)
        else:
            self.signals.done.emit(result)


_alive: set[_Job] = set()
_closing = False


def shutdown() -> None:
    """Finish running work while its signals and GUI callbacks are still alive."""
    global _closing
    _closing = True
    pool = QThreadPool.globalInstance()
    for job in tuple(_alive):
        if pool.tryTake(job):
            _alive.discard(job)
    # Completion callbacks may save results. Deliver them on the GUI thread, but
    # refuse follow-up work once exit has begun. A plain waitForDone() would leave
    # those callbacks queued until after their widgets or databases are destroyed.
    while not pool.waitForDone(10):
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    QCoreApplication.sendPostedEvents()
    _alive.clear()


def run_in_background(
    fn: Callable[[], Any],
    on_done: Callable[[Any], object],
    on_error: Callable[[Exception], object],
    *,
    coordinate: bool = True,
) -> None:
    if _closing:
        return
    job = _Job(fn, coordinate)
    job.setAutoDelete(False)
    _alive.add(job)

    def finish(cb: Callable[[Any], object]) -> Callable[[Any], None]:
        def handler(value: Any) -> None:
            _alive.discard(job)
            cb(value)
            if cb is on_error:
                from torrentlinker.crash_reports import unexpected

                if not _closing and unexpected(value):
                    from torrentlinker.gui.crash_reports import offer_report

                    offer_report(value, modal=False)

        return handler

    job.signals.done.connect(finish(on_done))
    job.signals.failed.connect(finish(on_error))
    QThreadPool.globalInstance().start(job)


def run_with_progress(
    fn: Callable[[Callable[[object], None]], Any],
    on_progress: Callable[[Any], object],
    on_done: Callable[[Any], object],
    on_error: Callable[[Exception], object],
) -> None:
    """Like run_in_background; `fn(report)` may report progress, shown by `on_progress`."""
    if _closing:
        return
    signals: list[_Signals] = []

    def work() -> Any:
        return fn(lambda value: signals[0].progress.emit(value))

    job = _Job(work)
    signals.append(job.signals)
    job.signals.progress.connect(on_progress)
    job.setAutoDelete(False)
    _alive.add(job)

    def finish(cb: Callable[[Any], object]) -> Callable[[Any], None]:
        def handler(value: Any) -> None:
            _alive.discard(job)
            cb(value)
            if cb is on_error:
                from torrentlinker.crash_reports import unexpected

                if not _closing and unexpected(value):
                    from torrentlinker.gui.crash_reports import offer_report

                    offer_report(value, modal=False)

        return handler

    job.signals.done.connect(finish(on_done))
    job.signals.failed.connect(finish(on_error))
    QThreadPool.globalInstance().start(job)
