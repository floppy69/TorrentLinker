"""Run a batch search off the GUI thread, reporting each Local Item as it is done."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from torrentlinker.agent.coordination import desktop_worker
from torrentlinker.batch import run_batch
from torrentlinker.library import LibraryEntry
from torrentlinker.review import CheckedCandidate


class BatchSignals(QObject):
    started = Signal(int, int, object)  # index, total, entry: before its search begins
    searched = Signal(int, int, object, object)  # index, total, entry, checked Candidates
    error = Signal(object, object)  # entry, exception
    waiting = Signal(object, float)  # entry, seconds c411 asks to wait before its retry
    already_present = Signal(object, str)  # entry, torrent hash
    finished = Signal(int)


class BatchRunner(QRunnable):
    def __init__(
        self,
        entries: list[LibraryEntry],
        search: Callable[[LibraryEntry], list[CheckedCandidate]],
        *,
        orphans_only: bool = True,
    ) -> None:
        super().__init__()
        self.entries = entries
        self.search = search
        self.orphans_only = orphans_only
        self.signals = BatchSignals()
        self._cancelled = False
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self._cancelled = True

    def cancelled(self) -> bool:
        return self._cancelled

    def start(self) -> None:
        QThreadPool.globalInstance().start(self)

    @desktop_worker
    def run(self) -> None:
        done = run_batch(
            self.entries,
            self.search,
            lambda i, n, e, r: self.signals.searched.emit(i, n, e, r),
            lambda: self._cancelled,
            lambda e, err: self.signals.error.emit(e, err),
            orphans_only=self.orphans_only,
            on_wait=lambda e, seconds: self.signals.waiting.emit(e, seconds),
            on_start=lambda i, n, e: self.signals.started.emit(i, n, e),
        )
        self.signals.finished.emit(done)
