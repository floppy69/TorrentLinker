from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.disk_rename import RenameApproval
from torrentlinker.domain import ContentKind, ItemState, LocalItem
from torrentlinker.gui.controls import set_role
from torrentlinker.gui.errors import error_text, offer_whole_names
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.rename_dialog import RenameDialog
from torrentlinker.gui.tables import EmptyState, NumberItem, sortable_table
from torrentlinker.gui.tasks import run_in_background, run_with_progress
from torrentlinker.gui.torrent_details import DescriptionBrowser
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import LibraryEntry
from torrentlinker.matching import MatchRules
from torrentlinker.qbit import AlreadyInClient, Qbit
from torrentlinker.reseed import start_reseed
from torrentlinker.review import (
    CheckedCandidate,
    candidate_key,
    check_candidate,
    find_candidates,
    remember_candidates,
    unpack_and_reseed,
)
from torrentlinker.store import Store
from torrentlinker.torrent_details import parse_details, preview_html, website_url
from torrentlinker.transmission import PartialNamesOn

Searcher = Callable[[LibraryEntry, str | None], list[Candidate]]
"""Searches an Indexer for a Local Item, optionally with a user-edited query."""

GREEN, ORANGE, RED = QColor("#2e7d32"), QColor("#ef6c00"), QColor("#c62828")


def _readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    sortable_table(table)
    return table


class ReviewPanel(QWidget):
    """Candidates for the selected Orphan, and how a Candidate's files line up locally."""

    reseed_started = Signal(object)  # Path of the Local Item
    unpacked = Signal(object)  # Path of the new folder: the Library needs a Scan
    candidates_checked = Signal(object, object)  # LibraryEntry, list[CheckedCandidate]
    upload_requested = Signal(object)  # LibraryEntry to make an Upload of

    def __init__(
        self,
        store: Store,
        indexer: Callable[[], Indexer],
        qbit: Callable[[], Qbit],
        rules: Callable[[], MatchRules],
        searcher: Callable[[], Searcher],
        default_query: Callable[[LibraryEntry], str],
        approve_disk_renames: RenameApproval | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.indexer = indexer
        self.qbit = qbit
        self.rules = rules
        self.searcher = searcher
        self.default_query = default_query
        self.approve_disk_renames = approve_disk_renames
        # Why the entry cannot be an Upload, None when it can; set by the window.
        self.upload_blocker: Callable[[LibraryEntry], str | None] = lambda e: ""
        self.entry: LibraryEntry | None = None
        self.checked: list[CheckedCandidate] = []
        self.cache: dict[
            Path, list[CheckedCandidate]
        ] = {}  # last Candidates checked per Local Item

        layout = QVBoxLayout(self)
        self._review_generation = 0
        self._details_loaded = ""
        self._selected_keys: dict[Path, str] = {}
        heading = QHBoxLayout()
        label = QLabel(self.tr("Candidate review"))
        label.setStyleSheet("font-size: 16px; font-weight: 600")
        heading.addWidget(label, 1)
        self.expand_button = QPushButton(self.tr("Expand review"))
        self.expand_button.setObjectName("expandCandidateReview")
        heading.addWidget(self.expand_button)
        layout.addLayout(heading)
        self.title = QLabel()
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(self.tr("Search query"))
        self.query.returnPressed.connect(self.search)
        self.search_button = QPushButton(self.tr("Search"))
        self.search_button.clicked.connect(self.search)
        row.addWidget(self.query)
        row.addWidget(self.search_button)
        self.compatible_button = QPushButton(self.tr("Find compatible torrents"))
        self.compatible_button.setObjectName("findCompatibleTorrents")
        self.compatible_button.setToolTip(
            self.tr(
                "Search up to 30 pages across series, seasons and episodes, including seeded items."
            )
        )
        self.compatible_button.clicked.connect(self.find_compatible)
        self.compatible_categories: Callable[[ContentKind], tuple[int, ...]] = lambda kind: ()
        row.addWidget(self.compatible_button)
        layout.addLayout(row)

        self.candidates = _readonly_table(
            [self.tr("Candidate"), self.tr("Size"), self.tr("Seeders"), self.tr("Match")]
        )
        self.empty_state = EmptyState(
            self.candidates, self.tr("Select a Local Item and search for Candidates.")
        )
        self.candidates.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.candidates.itemSelectionChanged.connect(self._candidate_selected)
        self.files = _readonly_table([self.tr("Torrent file"), self.tr("Local file"), ""])
        self.files.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)

        actions = QHBoxLayout()
        self.check_button = QPushButton(self.tr("Check Candidate"))
        self.check_button.setToolTip(
            self.tr(
                "Download this Candidate's .torrent and compare. Needed for Candidates "
                "outside the size tolerance, e.g. a season pack you only partly have."
            )
        )
        self.check_button.clicked.connect(self._check_selected)
        actions.addWidget(self.check_button)
        self.reject_button = QPushButton(self.tr("Reject"))
        set_role(self.reject_button, "quiet")
        self.reject_button.setToolTip(self.tr("Not this Local Item: never propose it again"))
        self.reject_button.clicked.connect(self._reject_selected)
        actions.addWidget(self.reject_button)
        self.upload_button = QPushButton(self.tr("Upload…"))
        self.upload_button.clicked.connect(
            lambda: self.entry is not None and self.upload_requested.emit(self.entry)
        )
        actions.addWidget(self.upload_button)
        self.repair_button = QPushButton(self.tr("Diagnose repair…"))
        self.repair_button.clicked.connect(self.diagnose_repair)
        self.repair_supported = lambda: True
        actions.addWidget(self.repair_button)
        history = QPushButton(self.tr("Repair history…"))
        history.clicked.connect(lambda: self.open_repair())
        actions.addWidget(history)
        actions.addStretch()
        self.reseed_button = QPushButton(self.tr("Reseed"))
        self.reseed_button.setToolTip(
            self.tr("Add to your torrent client against your files, verify, then seed")
        )
        set_role(self.reseed_button, "primary")
        self.reseed_button.clicked.connect(self._reseed_selected)
        actions.addWidget(self.reseed_button)
        self.website_button = QPushButton(self.tr("Open on website"))
        self.website_button.clicked.connect(self._open_website)
        actions.addWidget(self.website_button)
        self.action_row = actions
        self.unpack_progress = QProgressBar()
        self.unpack_progress.hide()

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        self.details_tabs = QTabWidget()
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.summary.setMargin(12)
        self.description = DescriptionBrowser()
        self.description.setOpenLinks(False)
        self.description.anchorClicked.connect(self._open_link)
        self.nfo = QPlainTextEdit()
        self.nfo.setReadOnly(True)
        for widget, title in (
            (self.summary, self.tr("Summary")),
            (self.files, self.tr("Files")),
            (self.description, self.tr("Description")),
            (self.nfo, self.tr("NFO")),
        ):
            self.details_tabs.addTab(widget, title)
        from torrentlinker.gui.library_evidence import EvidencePanel

        self.evidence = EvidencePanel(store.torrent_dir.parent)
        self.details_tabs.addTab(self.evidence, self.tr("Evidence"))
        self.details_tabs.currentChanged.connect(self._load_details)
        lower_layout.addWidget(self.details_tabs)
        lower_layout.addWidget(self.unpack_progress)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.candidates)
        split.addWidget(lower)
        layout.addWidget(split, 1)
        layout.addLayout(actions)
        self.candidates.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 85), (2, 65), (3, 150)):
            self.candidates.setColumnWidth(column, width)
        self.files.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.files.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.files.setColumnWidth(2, 130)
        self.set_entry(None)

    def hasHeightForWidth(self) -> bool:
        # A vertical layout treats a height-for-width child's preferred height as
        # its minimum, which crushes the Local Items above the review.
        return False

    # Selection -------------------------------------------------------------

    def set_entry(self, entry: LibraryEntry | None) -> None:
        self._review_generation += 1
        self.entry = entry
        self.evidence.set_entry(entry)
        self.checked = []
        self.candidates.setRowCount(0)
        self.files.setRowCount(0)
        self.compatible_button.setEnabled(entry is not None)
        searchable = entry is not None and entry.state is not ItemState.SEEDED
        self.query.setEnabled(searchable)
        self.search_button.setEnabled(searchable)
        partial = entry is not None and entry.state is ItemState.PARTIALLY_SEEDED
        self.search_button.setText(self.tr("Force search") if partial else self.tr("Search"))
        self._update_actions()
        if entry is None:
            self.title.setText(self.tr("Select a Local Item"))
            self.query.clear()
            return
        title = f"<b>{entry.item.path.name}</b> — {human_size(entry.item.size)}"
        if entry.state is ItemState.SEEDED:
            title += "<br>" + self.tr("Already seeded for c411 by your torrent client.")
        elif partial:
            title += "<br>" + self.tr(
                "Some of these files are already seeded: a Match would overlap that torrent."
            )
        self.title.setText(title)
        self.query.setText(self.store.item_query(entry.item.path) or self.default_query(entry))
        if entry.item.path in self.cache:
            self._show(entry, self.cache[entry.item.path])

    def selected(self) -> CheckedCandidate | None:
        """The Candidate whose files are shown: the current one among the selection."""
        rows = self.selected_all()
        current = self.candidates.currentRow()
        cell = self.candidates.item(current, 0)
        candidate = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if candidate in rows:
            return candidate
        return rows[0] if rows else None

    def selected_all(self) -> list[CheckedCandidate]:
        rows = sorted(i.row() for i in self.candidates.selectionModel().selectedRows())
        return [
            cell.data(Qt.ItemDataRole.UserRole)
            for r in rows
            if (cell := self.candidates.item(r, 0)) is not None
        ]

    # Search ----------------------------------------------------------------

    def open_repair(self, diagnose=None) -> None:
        from torrentlinker.gui.repair_dialog import RepairDialog
        from torrentlinker.repair import Repairs

        if not self.repair_supported():
            QMessageBox.information(
                self,
                self.tr("Repair"),
                self.tr("Experimental repair currently requires qBittorrent."),
            )
            return
        dialog = RepairDialog(
            self,
            Repairs(self.store.torrent_dir.parent, self.store.client_id),
            self.qbit(),
            diagnose=diagnose,
        )
        dialog.exec()

    def diagnose_repair(self) -> None:
        from torrentlinker.repair import Repairs

        selected, entry = self.selected(), self.entry
        if selected is None or entry is None:
            return
        indexer = self.indexer()
        repository = Repairs(self.store.torrent_dir.parent, self.store.client_id)
        self.open_repair(
            lambda stop: repository.diagnose(
                entry.item,
                selected.candidate,
                indexer.fetch_torrent(selected.candidate),
                stop,
            )
        )

    def find_compatible(self) -> None:
        import threading

        from torrentlinker.compatible import discover

        if self.entry is None:
            return
        entry, indexer, rules = self.entry, self.indexer(), self.rules()
        self.compatible_button.setEnabled(False)
        categories = self.compatible_categories(entry.folder.kind)

        def work():
            return discover(
                indexer,
                self.store,
                entry.item,
                entry.folder.kind,
                categories,
                rules,
                threading.Event(),
                lambda value: None,
            )

        def done(checked):
            self.compatible_button.setEnabled(self.entry is not None)
            self._show(entry, checked)

        def failed(error):
            self.compatible_button.setEnabled(self.entry is not None)
            self._failed(error)

        run_in_background(work, done, failed)

    def search(self) -> None:
        if self.entry is None:
            return
        entry = self.entry
        q = self.query.text().strip()
        override = q if q and q != self.default_query(entry) else None
        if override:
            self.store.set_item_query(entry.item.path, override)
        self.search_button.setEnabled(False)
        indexer, rules, searcher = self.indexer(), self.rules(), self.searcher()
        store = self.store
        rejections = store.rejections(entry.item.path)

        def work() -> list[CheckedCandidate]:
            found, checked = find_candidates(
                store,
                indexer,
                entry.item,
                lambda: searcher(entry, override),
                rules,
                rejections,
                use_catalogue=override is None,
            )
            remember_candidates(store, indexer, entry.item.path, found)
            return checked

        run_in_background(work, lambda checked: self._show(entry, checked), self._failed)

    def remember(self, entry: LibraryEntry, checked: list[CheckedCandidate]) -> None:
        """Keep Candidates checked elsewhere (batch search) for when the item is selected."""
        self.cache[entry.item.path] = checked
        self.candidates_checked.emit(entry, checked)
        if self.entry is not None and self.entry.item.path == entry.item.path:
            self._show(self.entry, checked)

    def _show(self, entry: LibraryEntry, checked: list[CheckedCandidate]) -> None:
        self.search_button.setEnabled(self.entry is not None)
        self.cache[entry.item.path] = checked
        self.candidates_checked.emit(entry, checked)
        if entry is not self.entry:
            return
        self.checked = sorted(
            checked, key=lambda v: (v.match is None, not v.compared, -v.candidate.seeders)
        )
        self._fill_candidates()
        self._update_actions()
        if not checked:
            self.title.setText(self.title.text() + "<br>" + self.tr("No Candidates found"))
        else:
            saved = self._selected_keys.get(entry.item.path)
            self._select_candidate(
                next(
                    (c for c in self.checked if candidate_key(c.candidate) == saved),
                    self.checked[0],
                )
            )

    def _select_candidate(self, candidate: CheckedCandidate) -> None:
        for row in range(self.candidates.rowCount()):
            cell = self.candidates.item(row, 0)
            if cell is not None and cell.data(Qt.ItemDataRole.UserRole) is candidate:
                self.candidates.selectRow(row)
                return

    def _fill_candidates(self) -> None:
        with QSignalBlocker(self.candidates):
            self.candidates.setSortingEnabled(False)
            self.candidates.setRowCount(0)
            self.candidates.setRowCount(len(self.checked))
            for r, v in enumerate(self.checked):
                c = v.candidate
                title = QTableWidgetItem(c.title)
                title.setData(Qt.ItemDataRole.UserRole, v)
                title.setToolTip(c.title)
                self.candidates.setItem(r, 0, title)
                self.candidates.setItem(r, 1, NumberItem(human_size(c.size), c.size))
                self.candidates.setItem(r, 2, NumberItem(str(c.seeders), c.seeders))
                label, color = self._match_label(v)
                cell = QTableWidgetItem(label)
                if color:
                    cell.setForeground(color)
                self.candidates.setItem(r, 3, cell)
            self.candidates.setSortingEnabled(True)
        self._candidate_selected()

    def _match_label(self, v: CheckedCandidate) -> tuple[str, QColor | None]:
        if not v.compared:
            return self.tr("Not checked"), None
        if v.match is not None and v.unpack is not None:
            if v.match.is_full:
                return self.tr("Full match inside the archive"), GREEN
            return self.tr("Partial match inside the archive ({0})").format(
                f"{v.match.coverage:.0%}"
            ), ORANGE
        if v.match is not None and v.match.is_full:
            return self.tr("Full match"), GREEN
        if v.match is not None:
            return self.tr("Partial match ({0})").format(f"{v.match.coverage:.0%}"), ORANGE
        return self.tr("No match"), RED

    def _failed(self, error: Exception) -> None:
        self.search_button.setEnabled(True)
        self.check_button.setEnabled(True)
        QMessageBox.warning(self, self.tr("Search failed"), error_text(error))

    # Candidate details -----------------------------------------------------

    def _candidate_selected(self) -> None:
        self.files.setRowCount(0)
        v = self.selected()
        self._review_generation += 1
        self._details_loaded = ""
        self.description.setPlainText(
            self.tr("Select Description to load the torrent presentation.")
        )
        self.nfo.setPlainText(self.tr("Select NFO to load its contents."))
        self.summary.setText(self.tr("Select a Candidate to compare it with your Local Item."))
        if v is not None and self.entry is not None:
            self._selected_keys[self.entry.item.path] = candidate_key(v.candidate)
            self.summary.setText(
                f"{v.candidate.title}\n\n{self._match_label(v)[0]} · "
                f"{human_size(v.candidate.size)} · {v.candidate.seeders} seeders\n\n"
                + self.tr("Local folder: ")
                + str(self.entry.item.path.parent)
                + "\n\n"
                + self.tr(
                    "A Match compares file names and sizes. Your Torrent Client must "
                    "verify the hashes before seeding."
                )
            )
        if v is not None and v.candidate.metadata.get("discovery") == "catalogue":
            self.summary.setText(
                self.summary.text()
                + "\n\n"
                + self.tr(
                    "Found in the local Catalogue by its exact size, without spending a search."
                )
            )
        if v is not None and v.candidate.metadata.get("discovery") == "layout":
            self.summary.setText(
                self.summary.text()
                + "\n\n"
                + self.tr(
                    "Found among the torrents already downloaded, by the sizes of your files, "
                    "without spending a search."
                )
            )
        if v is not None and v.candidate.metadata.get("discovery") == "compatible":
            self.summary.setText(
                self.summary.text()
                + "\n\n"
                + self.tr("Discovery scope: ")
                + str(v.candidate.metadata.get("scope", ""))
            )
            if v.candidate.metadata.get("limited") == "true":
                self.summary.setText(
                    self.summary.text()
                    + "\n"
                    + self.tr("Search limit reached; results are incomplete.")
                )
        self._load_details()
        self._update_actions()
        if v is None or v.comparison is None:
            return
        cmp = v.comparison
        rows: list[tuple[str, str | None]] = list(cmp.pairs.items())
        rows += [(t, None) for t in cmp.unwanted]
        self.files.setSortingEnabled(False)
        self.files.setRowCount(len(rows))
        for r, (t_path, local) in enumerate(sorted(rows)):
            self.files.setItem(r, 0, QTableWidgetItem(t_path))
            self.files.setItem(r, 1, QTableWidgetItem(local or ""))
            if local is None and t_path in cmp.skipped:
                status, color = self.tr("– ignored, not downloaded"), ORANGE
            elif local is None:
                status, color = self.tr("✗ absent, not downloaded"), RED
            elif v.unpack is not None:
                status, color = self.tr("✓ in the archive"), GREEN
            elif local != t_path:
                status, color = self.tr("✓ renamed"), ORANGE
            else:
                status, color = self.tr("✓"), GREEN
            cell = QTableWidgetItem(status)
            cell.setForeground(color)
            self.files.setItem(r, 2, cell)
        self.files.setSortingEnabled(True)

    @staticmethod
    def _open_link(url: QUrl) -> None:
        from torrentlinker.torrent_details import web_url

        if value := web_url(url.toString()):
            QDesktopServices.openUrl(QUrl(value))

    def _open_website(self) -> None:
        if selected := self.selected():
            self._open_link(QUrl(website_url(selected.candidate, self.indexer())))

    def _load_details(self, *_: object) -> None:
        if self.details_tabs.currentIndex() not in (2, 3):
            return
        selected = self.selected()
        if selected is None:
            return
        key = candidate_key(selected.candidate)
        if self._details_loaded == key:
            return
        indexer = self.indexer()
        if not indexer.is_c411 or not selected.candidate.infohash:
            self.description.setPlainText(self.tr("Open this Candidate on its Indexer website."))
            self.nfo.setPlainText(self.tr("NFO unavailable for this Indexer."))
            return
        self._details_loaded = key
        generation = self._review_generation
        self.description.setPlainText(self.tr("Loading…"))
        self.nfo.setPlainText(self.tr("Loading…"))

        def loaded(details) -> None:
            if generation != self._review_generation:
                return
            markup, _images = preview_html(details.description)
            self.description.setHtml(markup or self.tr("No description supplied."))
            self.nfo.setPlainText(details.nfo or self.tr("No NFO supplied."))

        def failed(error: Exception) -> None:
            if generation == self._review_generation:
                self._details_loaded = ""
                self.description.setPlainText(error_text(error))
                self.nfo.setPlainText(error_text(error))

        run_in_background(
            lambda: parse_details(indexer.torrent_json(selected.candidate.infohash or "")),
            loaded,
            failed,
        )

    def _update_actions(self) -> None:
        v, chosen = self.selected(), self.selected_all()
        self.repair_button.setEnabled(
            v is not None and self.entry is not None and self.entry.item.path.is_file()
        )
        self.website_button.setEnabled(v is not None)
        self.check_button.setEnabled(v is not None and not v.compared)
        self.reject_button.setEnabled(bool(chosen))
        archive = any(c.unpack for c in chosen)
        blocker = self.upload_blocker(self.entry) if self.entry is not None else ""
        self.upload_button.setVisible(
            self.entry is not None and self.entry.folder.kind is ContentKind.MODEL_3D
        )
        self.upload_button.setEnabled(blocker is None)
        self.upload_button.setToolTip(
            blocker or self.tr("c411 does not have it: make it a c411 Draft in the Upload tab")
        )
        self.reseed_button.setEnabled(
            bool(chosen)
            and all(c.match for c in chosen)
            and not (archive and len(chosen) > 1)
            and self.unpack_progress.isHidden()
        )
        if archive:
            self.reseed_button.setText(self.tr("Unpack and Reseed…"))
        else:
            self.reseed_button.setText(
                self.tr("Reseed {0} Matches").format(len(chosen))
                if len(chosen) > 1
                else self.tr("Verify && reseed")
            )

    def _reject_selected(self) -> None:
        if self.entry is None:
            return
        for v in self.selected_all():
            self.store.reject(self.entry.item.path, candidate_key(v.candidate), "Rejected by user")
            self.checked.remove(v)
        self.cache[self.entry.item.path] = list(self.checked)
        self.candidates_checked.emit(self.entry, self.checked)
        self.candidates.clearSelection()
        self._fill_candidates()

    def _check_selected(self) -> None:
        v, entry = self.selected(), self.entry
        if v is None or entry is None:
            return
        self.check_button.setEnabled(False)
        indexer, rules = self.indexer(), self.rules()
        run_in_background(
            lambda: check_candidate(indexer, entry.item, v.candidate, rules),
            lambda checked: self._replace(entry, v, checked),
            self._failed,
        )

    def _replace(self, entry: LibraryEntry, old: CheckedCandidate, new: CheckedCandidate) -> None:
        if entry is not self.entry or old not in self.checked:
            return
        i = self.checked.index(old)
        self.checked[i] = new
        self.cache[entry.item.path] = list(self.checked)
        self.candidates_checked.emit(entry, self.checked)
        self._fill_candidates()
        self._select_candidate(new)

    def reseed_archive(self, entry: LibraryEntry, checked: CheckedCandidate) -> None:
        """Review a batch's archive Match through the normal unpack confirmation."""
        self.set_entry(entry)
        self._select_candidate(checked)
        self._reseed_selected()

    def _reseed_selected(self) -> None:
        entry = self.entry
        chosen = [v for v in self.selected_all() if v.meta is not None and v.match is not None]
        if entry is None or not chosen:
            return
        if len(chosen) == 1 and chosen[0].unpack is not None:
            self._unpack_and_reseed(entry, chosen[0])
            return
        qbit, store = self.qbit(), self.store
        for v in chosen:
            assert v.match is not None
            if v.match.is_full:
                continue
            if not getattr(qbit, "supports_partial_reseeds", True):
                self._refuse_partial(getattr(qbit, "client_name", "") or "")
                return
            if not self._confirm_partial(len(v.match.absent), v.match.coverage):
                return
        renames = {k: n for v in chosen if v.match for k, n in v.match.renames.items()}
        if (
            renames
            and not getattr(qbit, "requires_disk_renames", False)
            and not self._confirm_renames(renames)
        ):
            return
        self.reseed_button.setEnabled(False)

        def work() -> tuple[list[str], list[str], Exception | None, list[str]]:
            """Reseed each Match; one failing must not hide the ones already added."""
            hashes: list[str] = []
            errors: list[str] = []
            present: list[str] = []
            for v in chosen:
                assert v.meta is not None and v.match is not None
                key = candidate_key(v.candidate)
                try:
                    hashes.append(
                        start_reseed(
                            qbit,
                            store,
                            entry.item,
                            v.meta,
                            v.match,
                            key,
                            approve_disk_renames=self.approve_disk_renames,
                        )
                    )
                except PartialNamesOn as e:
                    return hashes, errors, e, present  # may retry after changing Transmission
                except AlreadyInClient as e:
                    present.append(f"{v.candidate.title}: {error_text(e)}")
                except Exception as e:  # noqa: BLE001 - reported to the user below
                    errors.append(f"{v.candidate.title}: {error_text(e)}")
            return hashes, errors, None, present

        run_in_background(work, lambda done: self._reseeded(entry, *done), self._reseed_failed)

    def _reseeded(
        self,
        entry: LibraryEntry,
        hashes: list[str],
        errors: list[str],
        refused: Exception | None = None,
        present: list[str] | None = None,
    ) -> None:
        self._update_actions()
        if hashes:
            self.reseed_started.emit(entry.item.path)
        if present:
            QMessageBox.information(self, self.tr("Torrent already present"), "\n\n".join(present))
        if refused is not None:
            if offer_whole_names(self, refused, then=self._reseed_selected):
                return
        if errors:
            self._reseed_failed(RuntimeError("\n".join(errors)))

    # Archives --------------------------------------------------------------

    def _unpack_and_reseed(self, entry: LibraryEntry, v: CheckedCandidate) -> None:
        u = v.unpack
        assert u is not None and v.match is not None
        folder = u.item.path
        if folder.exists():
            QMessageBox.information(
                self,
                self.tr("Unpack and Reseed"),
                self.tr(
                    "{0} already exists. If it holds this archive unpacked, scan the Library "
                    "and search that folder to Reseed it."
                ).format(folder),
            )
            return
        free = shutil.disk_usage(u.archive.parent).free
        if free < u.size:
            QMessageBox.warning(
                self,
                self.tr("Unpack and Reseed"),
                self.tr("Unpacking needs {0}, but only {1} is free on that disk.").format(
                    human_size(u.size), human_size(free)
                ),
            )
            return
        if not v.match.is_full and not self._confirm_partial(len(v.match.absent), v.match.coverage):
            return
        answer = QMessageBox.question(
            self,
            self.tr("Unpack and Reseed"),
            self.tr(
                "Unpack {0} into the new folder\n{1}?\n\n"
                "It writes {2} in {3} files; {4} is free on that disk. Nothing is "
                "overwritten.\n\nThe torrent is then added to your torrent client against the "
                "unpacked files, and verified before it seeds. Once it is verified, you are "
                "offered to move the archive to the trash."
            ).format(
                u.archive.name,
                folder,
                human_size(u.size),
                len(u.item.files),
                human_size(free),
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        qbit, store, rules = self.qbit(), self.store, self.rules()
        self.unpack_progress.setRange(0, 1000)
        self.unpack_progress.setValue(0)
        self.unpack_progress.setFormat(self.tr("Unpacking %p%"))
        self.unpack_progress.show()
        self._update_actions()

        def work(report: Callable[[object], None]) -> tuple[str, LocalItem]:
            return unpack_and_reseed(
                qbit,
                store,
                v,
                rules,
                lambda done, total: report((done, total)),
                approve_disk_renames=self.approve_disk_renames,
            )

        run_with_progress(
            work,
            self._unpack_progress,
            lambda result: self._unpacked(entry, result[1].path),
            self._unpack_failed,
        )

    def _unpack_progress(self, value: tuple[int, int]) -> None:
        done, total = value
        self.unpack_progress.setValue(round(1000 * done / total) if total else 0)
        self.unpack_progress.setFormat(
            self.tr("Unpacking: {0} of {1}").format(human_size(done), human_size(total))
        )

    def _unpacked(self, entry: LibraryEntry, folder: Path) -> None:
        self.unpack_progress.hide()
        self._update_actions()
        self.unpacked.emit(folder)
        self.reseed_started.emit(folder)

    def _unpack_failed(self, error: Exception) -> None:
        self.unpack_progress.hide()
        self._update_actions()
        QMessageBox.warning(
            self,
            self.tr("Unpack and Reseed"),
            self.tr("Could not unpack and Reseed: {0}").format(error_text(error)),
        )

    def _refuse_partial(self, client: str) -> None:
        QMessageBox.information(
            self,
            self.tr("Partial Match"),
            self.tr(
                "{0} cannot reseed a Partial Match: it cannot check only the files you have "
                "without touching the missing ones. Choose a Full Match, or reseed this one "
                "with qBittorrent, Transmission or Deluge."
            ).format(client or self.tr("Your torrent client")),
        )

    def _confirm_partial(self, missing: int, coverage: float) -> bool:
        answer = QMessageBox.question(
            self,
            self.tr("Partial Match"),
            self.tr(
                "You have {0} of this torrent. The {1} absent files will not be downloaded. "
                "After Verification it seeds the pieces you have, with every file skipped so "
                "that nothing is ever downloaded into your files. Reseed?"
            ).format(f"{coverage:.0%}", missing),
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_renames(self, renames: dict[str, str]) -> bool:
        dialog = RenameDialog(renames, self)
        try:
            return dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            dialog.deleteLater()

    def _reseed_failed(self, error: Exception) -> None:
        self._update_actions()
        QMessageBox.warning(self, self.tr("Reseed failed"), error_text(error))
