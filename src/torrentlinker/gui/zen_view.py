"""The Zen tab: the Seeding view and, later, the Plan."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker.gui.controls import ScrollDoubleSpinBox as QDoubleSpinBox
from torrentlinker.gui.controls import ScrollSpinBox as QSpinBox
from torrentlinker.gui.controls import icon_button, set_role
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.profile_view import ProfileView
from torrentlinker.gui.seeding_tree import SeedingTree
from torrentlinker.gui.tables import EmptyState, NumberItem, sortable_table
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.plan import Plan, PlanGoal, PlanOptions
from torrentlinker.plan_diagnostics import PlanIssue, issue_text
from torrentlinker.profile import ProfileError, ProfileProblem, UserProfile
from torrentlinker.seeding import Seeding
from torrentlinker.send import SendProgress
from torrentlinker.zen import GB, ZenClass, ZenProfile, compare_classes

CLASS_LABELS = {
    ZenClass.TANKER: QT_TRANSLATE_NOOP("ZenClass", "Tanker"),
    ZenClass.SWARM_KEEPER: QT_TRANSLATE_NOOP("ZenClass", "Swarm Keeper"),
    ZenClass.REUPLOADER: QT_TRANSLATE_NOOP("ZenClass", "Reuploader"),
}


def class_label(zen_class: ZenClass) -> str:
    return QCoreApplication.translate("ZenClass", str(CLASS_LABELS[zen_class]))


def zen_text(value: float) -> str:
    return f"≈ {value:.2f}"


def readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    sortable_table(table)
    return table


def clear_rows(table: QTableWidget, rows: int) -> None:
    """Empty the table, then size it for `rows` new rows.

    Replacing the items of a filled table resizes its columns to their contents after
    every cell: about 100 s for 1,300 rows. Filling empty rows takes a fraction of a
    second.
    """
    table.setSortingEnabled(False)
    table.setRowCount(0)
    table.setRowCount(rows)


class SeedingView(QWidget):
    """The user's Indexer torrents in qBittorrent, with a Zen Estimate each."""

    updated = Signal(object)  # Seeding
    unavailable = Signal()

    def __init__(self, load: Callable[[], Callable[[], Seeding]]) -> None:
        super().__init__()
        self.load = load
        self.seeding: Seeding | None = None
        self._quiet = False
        # The tree is costly to rebuild. While the main window says it is out of sight, the
        # newest data waits here and the tree is rebuilt when the page is shown again.
        self.defer_tree: Callable[[], bool] = lambda: False
        self._tree_dirty = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.title = QLabel(self.tr("<b>Seeding</b>"))
        top.addWidget(self.title)
        top.addStretch()
        self.refresh_button = QPushButton(self.tr("Refresh"))
        set_role(self.refresh_button, "quiet")
        self.refresh_button.setToolTip(self.tr("Read your torrents from your torrent client again"))
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)
        self.search = QLineEdit()
        self.search.setAccessibleName(self.tr("Filter torrents or categories"))
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.table = SeedingTree()
        self.search.textChanged.connect(self.table.filter)
        self.search.setPlaceholderText(self.tr("Filter torrents or categories…"))
        self.expand_button = QPushButton(self.tr("Expand all"))
        set_role(self.expand_button, "quiet")
        self.expand_button.clicked.connect(self.table.expandAll)
        self.collapse_button = QPushButton(self.tr("Collapse all"))
        set_role(self.collapse_button, "quiet")
        self.collapse_button.clicked.connect(self.table.collapseAll)
        top.insertWidget(1, self.expand_button)
        top.insertWidget(2, self.collapse_button)
        layout.addWidget(self.table)
        self.total = QLabel()
        layout.addWidget(self.total)
        self.tag_status = QLabel()
        self.tag_status.setWordWrap(True)
        self.tag_status.setProperty("role", "muted")
        layout.addWidget(self.tag_status)
        self._show_total()

    def refresh(self, *, quiet: bool = False) -> None:
        if not self.refresh_button.isEnabled():
            return
        self._quiet = quiet
        self.refresh_button.setEnabled(False)
        if not quiet:
            self.total.setText(self.tr("Reading your torrent client…"))
        run_in_background(self.load(), self.show_seeding, self._failed)

    def show_seeding(self, view: Seeding) -> None:
        self.refresh_button.setEnabled(True)
        self.seeding = view
        if self.defer_tree():
            self._tree_dirty = True
        else:
            self._tree_dirty = False
            self.table.show_seeding(view)
        report = view.tag_sync
        self.tag_status.setToolTip("")
        if report is None:
            self.tag_status.clear()
        elif not report.supported:
            self.tag_status.setText(
                self.tr(
                    "Category tags: Deluge's single label is kept for Verification. "
                    "The category tree is available here."
                )
            )
        elif report.failed:
            self.tag_status.setText(
                self.tr("Category tags: {0} updated, {1} failed; the next refresh retries.").format(
                    report.updated, report.failed
                )
            )
            self.tag_status.setToolTip("\n".join(report.errors))
        else:
            self.tag_status.setText(
                self.tr(
                    "Category tags: {0} updated, {1} already set, {2} without a known category."
                ).format(report.updated, report.unchanged, report.unknown)
            )
            self.tag_status.setToolTip("")
        self._show_total()
        self.updated.emit(view)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._tree_dirty:
            # Let the page appear first; the rebuild follows on the next turn of the event loop.
            QTimer.singleShot(0, self._rebuild_tree)

    def _rebuild_tree(self) -> None:
        if self._tree_dirty and self.seeding is not None and self.isVisible():
            self._tree_dirty = False
            self.table.show_seeding(self.seeding)

    def _show_total(self) -> None:
        view = self.seeding
        if view is None:
            self.total.setText(
                self.tr("Refresh to read your c411 torrents from your torrent client.")
            )
            return
        self.total.setText(
            self.tr("{0} torrents seeding · {1} Zen/day (paid ≈ {2}) · estimates").format(
                view.count, zen_text(view.day.total), view.day.paid
            )
        )

    def _failed(self, error: Exception) -> None:
        self.unavailable.emit()
        self.refresh_button.setEnabled(True)
        self._show_total()
        if not self._quiet:
            QMessageBox.warning(self, self.tr("Torrent client"), str(error) or type(error).__name__)


class ClassComparison(QGroupBox):
    """Current seeding estimated in every Class, to help choose during c411's window."""

    uploads_changed = Signal(int)

    def __init__(self, profile: Callable[[], ZenProfile], uploads: int) -> None:
        super().__init__(self.tr("Class comparison"))
        self.profile = profile
        self.seeding: Seeding | None = None
        # The estimate for every Class takes about a second on a large library. Like the
        # seeding tree it waits while out of sight, and the page computes it off the GUI thread.
        self.defer: Callable[[], bool] = lambda: False
        self.background = False
        self._dirty = False
        self._generation = 0
        layout = QHBoxLayout(self)
        self.labels: dict[ZenClass, QLabel] = {}
        for c in ZenClass:
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.RichText)
            self.labels[c] = label
            layout.addWidget(label)
            layout.addSpacing(24)
        self.labels[ZenClass.REUPLOADER].setToolTip(
            self.tr(
                "Rough: a Reuploader is paid per upload, counted here at the guide's "
                "upper figure of about 0.43 Zen per upload a day."
            )
        )
        layout.addStretch()
        layout.addWidget(QLabel(self.tr("Your uploads")))
        self.uploads = QSpinBox()
        self.uploads.setRange(0, 100_000)
        self.uploads.setValue(uploads)
        self.uploads.valueChanged.connect(self._uploads_edited)
        layout.addWidget(self.uploads)
        self.show_seeding(None)

    def _uploads_edited(self, value: int) -> None:
        self.uploads_changed.emit(value)
        self.show_seeding(self.seeding)

    def show_seeding(self, view: Seeding | None) -> None:
        self.seeding = view
        if self.defer():
            self._dirty = True
            return
        self._compute()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._dirty:
            QTimer.singleShot(0, self._compute)

    def _compute(self) -> None:
        if not isValid(self):
            return
        self._dirty = False
        profile = self.profile()
        active = self.seeding.active if self.seeding else []
        uploads = self.uploads.value()
        if not self.background:
            self._show_days(profile, compare_classes(profile, active, uploads))
            return
        self._generation += 1
        generation = self._generation

        def done(days) -> None:
            if isValid(self) and generation == self._generation:
                self._show_days(profile, days)

        run_in_background(lambda: compare_classes(profile, active, uploads), done, lambda _e: None)

    def _show_days(self, profile: ZenProfile, days) -> None:
        for c, label in self.labels.items():
            text = self.tr("{0}: {1} Zen/day").format(class_label(c), zen_text(days[c].total))
            if c is ZenClass.REUPLOADER:
                text += " " + self.tr("(rough)")
            if c is profile.zen_class:
                text = "<b>" + text + "</b> " + self.tr("← your Class")
            label.setText(text)


@dataclass(frozen=True)
class CategoryCard:
    """One c411 category in the Catalogue panel."""

    root: int
    name: str
    ours: int
    site: int | None  # None: c411's listing does not show it (XXX)
    state: str  # done | never | waiting | running | year | prune | paused | cache
    note: str = ""
    fetchable: bool = True  # False for XXX, which c411's listing never returns


CHIPS = {
    "done": QT_TRANSLATE_NOOP("CatalogueBox", "Up to date"),
    "never": QT_TRANSLATE_NOOP("CatalogueBox", "Not read yet"),
    "waiting": QT_TRANSLATE_NOOP("CatalogueBox", "Waiting"),
    "running": QT_TRANSLATE_NOOP("CatalogueBox", "Reading"),
    "year": QT_TRANSLATE_NOOP("CatalogueBox", "By year"),
    "prune": QT_TRANSLATE_NOOP("CatalogueBox", "Checking"),
    "paused": QT_TRANSLATE_NOOP("CatalogueBox", "Paused"),
    "cache": QT_TRANSLATE_NOOP("CatalogueBox", "Cache only"),
}
ACTIVE = {"running", "year", "prune"}


class CategoryTile(QFrame):
    """A category: how much of it the Catalogue holds against c411, and a button to
    fetch it alone. Highlighted, with each page's gain, while it is being fetched."""

    fetch_requested = Signal(int)

    def __init__(self, card: CategoryCard) -> None:
        super().__init__()
        self.setObjectName("catalogueCard")
        self.root = card.root
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.name = QLabel(card.name)
        self.name.setProperty("role", "cardTitle")
        self.name.setMinimumWidth(0)
        header.addWidget(self.name, 1)
        self.fetch_button = icon_button("⟳", self.tr("Fetch only {0}").format(card.name))
        self.fetch_button.clicked.connect(lambda: self.fetch_requested.emit(self.root))
        header.addWidget(self.fetch_button)
        layout.addLayout(header)
        counts = QHBoxLayout()
        self.number = QLabel()
        self.number.setProperty("role", "cardNumber")
        counts.addWidget(self.number)
        self.of_site = QLabel()
        self.of_site.setProperty("role", "muted")
        counts.addWidget(self.of_site)
        self.gain = QLabel()
        self.gain.setProperty("role", "gain")
        counts.addWidget(self.gain)
        counts.addStretch()
        layout.addLayout(counts)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, 1000)
        layout.addWidget(self.bar)
        footer = QHBoxLayout()
        self.note = QLabel()
        self.note.setProperty("role", "muted")
        self.note.setMinimumWidth(0)
        footer.addWidget(self.note, 1)
        self.chip = QLabel()
        footer.addWidget(self.chip)
        layout.addLayout(footer)
        self._gain_timer = QTimer(self)
        self._gain_timer.setSingleShot(True)
        self._gain_timer.timeout.connect(self.gain.clear)
        self.show_card(card)

    def show_card(self, card: CategoryCard) -> None:
        self.fetch_button.setVisible(card.fetchable)
        self.number.setText(f"{card.ours:,}".replace(",", "\u202f"))
        if not card.fetchable:
            self.of_site.setText(self.tr("c411's listing does not show it"))
            self.bar.setValue(1000)
        elif card.site is None:
            self.of_site.setText("")
            self.bar.setValue(0)
        else:
            self.of_site.setText(
                self.tr("/ {0} on c411").format(f"{card.site:,}".replace(",", "\u202f"))
            )
            self.bar.setValue(round(1000 * min(1.0, card.ours / card.site)) if card.site else 0)
        self.note.setText(card.note)
        self.note.setToolTip(card.note)
        self.chip.setText(QCoreApplication.translate("CatalogueBox", str(CHIPS[card.state])))
        self._restyle(self.chip, "chip", card.state)
        self._restyle(self, "active", "true" if card.state in ACTIVE else "false")

    def show_gain(self, added: int) -> None:
        if added > 0:
            self.gain.setText(f"+{added:,}".replace(",", "\u202f"))
            self._gain_timer.start(1500)

    @staticmethod
    def _restyle(widget: QWidget, name: str, value: str) -> None:
        if widget.property(name) != value:
            widget.setProperty(name, value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class CatalogueBox(QGroupBox):
    """The Catalogue, one card per c411 category: fetch all of them, or one, to parity
    with the site, with progress, pause and resume."""

    start_requested = Signal()
    pause_requested = Signal()
    category_requested = Signal(int)

    COLUMNS = 3

    def __init__(self) -> None:
        super().__init__(self.tr("Catalogue"))
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        header.addWidget(self.status, 1)
        self.fetch_button = QPushButton()
        self.fetch_button.setToolTip(
            self.tr(
                "Fetch every category to parity with c411: every page again, the big "
                "categories year by year, then the torrents c411 deleted are removed. "
                "You can pause and resume after closing the app."
            )
        )
        self.fetch_button.clicked.connect(self._clicked)
        header.addWidget(self.fetch_button)
        layout.addLayout(header)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setRange(0, 1000)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.phase = QLabel()
        self.phase.setProperty("role", "muted")
        self.phase.setWordWrap(True)
        layout.addWidget(self.phase)
        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        layout.addLayout(self.grid)
        self.tiles: dict[int, CategoryTile] = {}
        self.running = False
        self.set_state(False, False)

    def _clicked(self) -> None:
        (self.pause_requested if self.running else self.start_requested).emit()

    def set_state(self, running: bool, paused: bool) -> None:
        self.running = running
        if running:
            self.fetch_button.setText(self.tr("Pause"))
        elif paused:
            self.fetch_button.setText(self.tr("Resume fetching all categories"))
        else:
            self.fetch_button.setText(self.tr("Fetch all categories"))
        self.progress.setVisible(running)
        for tile in self.tiles.values():
            tile.fetch_button.setEnabled(not running)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_phase(self, text: str, fraction: float | None = None) -> None:
        self.phase.setText(text)
        if fraction is not None:
            self.progress.setValue(round(1000 * max(0.0, min(1.0, fraction))))

    def set_cards(self, cards: list[CategoryCard]) -> None:
        for i, card in enumerate(cards):
            tile = self.tiles.get(card.root)
            if tile is None:
                tile = CategoryTile(card)
                tile.fetch_requested.connect(self.category_requested)
                tile.fetch_button.setEnabled(not self.running)
                self.tiles[card.root] = tile
                self.grid.addWidget(tile, i // self.COLUMNS, i % self.COLUMNS)
            else:
                tile.show_card(card)

    def show_gain(self, root: int, added: int) -> None:
        if (tile := self.tiles.get(root)) is not None:
            tile.show_gain(added)


class PlanView(QGroupBox):
    """The Plan: what to download and seed next for the most Zen."""

    make_requested = Signal()
    send_requested = Signal()
    categories_changed = Signal(object)  # set[int] | None
    stop_fetch_requested = Signal()
    stop_send_requested = Signal()
    speed_test_requested = Signal()
    options_changed = Signal(object)  # PlanOptions

    def __init__(self) -> None:
        super().__init__(self.tr("Plan"))
        self.plan: Plan | None = None
        layout = QVBoxLayout(self)
        self._busy = False
        self.summary = QLabel(
            self.tr(
                "Choose whether to prioritize Zen/day or torrent notes, within your "
                "download limit and available disk space."
            )
        )
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.catalogue_notice = QLabel()
        self.catalogue_notice.setProperty("role", "muted")
        self.catalogue_notice.setWordWrap(True)
        self.catalogue_notice.hide()
        layout.addWidget(self.catalogue_notice)
        self.speed: float | None = None  # bytes/s
        self.keys = 1  # API keys a Plan's downloads spread over
        self.speed_tested: str | None = None
        times = QHBoxLayout()
        self.times = QLabel()
        self.times.setWordWrap(True)
        self.times.setToolTip(
            self.tr(
                "Sending: c411 allows each API key 30 .torrent files a minute, and about "
                "280 in 20 minutes; more keys send faster. Downloading: at the speed of your "
                "last speed test, so at best; a torrent with few seeders is slower than your "
                "connection."
            )
        )
        times.addWidget(self.times, 1)
        self.speed_button = QPushButton(self.tr("Test speed"))
        self.speed_button.setToolTip(
            self.tr(
                "Measure your download speed for about 8 seconds with Cloudflare's public "
                "speed test (anonymous). Run it while your torrent client is not downloading."
            )
        )
        self.speed_button.clicked.connect(self.speed_test_requested)
        times.addWidget(self.speed_button)
        layout.addLayout(times)
        self._show_times()
        options = QHBoxLayout()
        self.goal = QComboBox()
        self.goal.addItem(self.tr("Note"), PlanGoal.NOTE.value)
        self.goal.addItem(self.tr("Zen/day"), PlanGoal.ZEN.value)
        self.goal.setToolTip(
            self.tr(
                "Zen/day maximizes estimated earnings. "
                "Note prioritizes each torrent's initial score, without a seed-age bonus. "
                "Equal scores prefer smaller downloads."
            )
        )
        label = QLabel(self.tr("Optimize for"))
        label.setBuddy(self.goal)
        options.addWidget(label)
        options.addWidget(self.goal)
        self.download_limit = QDoubleSpinBox()
        self.download_limit.setRange(0, 1_000_000)
        self.download_limit.setDecimals(2)
        self.download_limit.setSuffix(self.tr(" GB"))
        self.download_limit.setSpecialValueText(self.tr("No limit"))
        self.download_limit.setToolTip(
            self.tr(
                "Maximum total download size for this Plan. 1 GB = 1,000,000,000 bytes. "
                "Reseeds use no download budget."
            )
        )
        label = QLabel(self.tr("Download limit"))
        label.setBuddy(self.download_limit)
        options.addWidget(label)
        options.addWidget(self.download_limit)
        options.addStretch()
        layout.addLayout(options)
        limits = QHBoxLayout()
        self.limit_torrents = QCheckBox(self.tr("Limit torrents"))
        self.torrent_limit = QSpinBox()
        self.torrent_limit.setRange(1, 1_000_000)
        self.torrent_limit.setValue(100)
        self.torrent_limit.setToolTip(
            self.tr(
                "Maximum torrents added by this Plan, including Reseeds. "
                "Your overall torrent cap still applies."
            )
        )
        self.torrent_limit.setEnabled(False)
        limits.addWidget(self.limit_torrents)
        limits.addWidget(self.torrent_limit)
        limits.addSpacing(16)
        self.low_seeders = QCheckBox(self.tr("Low seeders only"))
        self.seeder_limit = QSpinBox()
        self.seeder_limit.setRange(1, 1_000_000)
        self.seeder_limit.setValue(10)
        self.seeder_limit.setSuffix(self.tr(" seeders max."))
        tooltip = self.tr(
            "Only include torrents with at most this many current seeders, before you join. "
            "Applies to downloads and Reseeds, in both Note and Zen/day modes."
        )
        self.low_seeders.setToolTip(tooltip)
        self.seeder_limit.setToolTip(tooltip)
        self.seeder_limit.setEnabled(False)
        limits.addWidget(self.low_seeders)
        limits.addWidget(self.seeder_limit)
        limits.addStretch()
        layout.addLayout(limits)
        sizes = QHBoxLayout()
        tooltip = self.tr(
            "Only include torrents of at least / at most this size each, in decimal GB. "
            "Applies to downloads and Reseeds."
        )
        self.min_size = self._size_box(self.tr("No minimum"), tooltip)
        self.max_size = self._size_box(self.tr("No maximum"), tooltip)
        label = QLabel(self.tr("Torrent size from"))
        label.setBuddy(self.min_size)
        sizes.addWidget(label)
        sizes.addWidget(self.min_size)
        label = QLabel(self.tr("to"))
        label.setBuddy(self.max_size)
        sizes.addWidget(label)
        sizes.addWidget(self.max_size)
        sizes.addStretch()
        layout.addLayout(sizes)
        top = QHBoxLayout()
        self.categories_button = QToolButton()
        self.categories_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.categories_button.setToolTip(self.tr("Categories this Plan draws from"))
        self.categories_menu = QMenu(self.categories_button)
        self.categories_button.setMenu(self.categories_menu)
        self.category_options: list[tuple[int, str, bool]] = []
        self.chosen_categories: set[int] | None = None
        self.without_folder: set[int] = set()
        top.addWidget(self.categories_button)
        self._refresh_categories_label()
        self.make_button = QPushButton(self.tr("Make a Plan"))
        set_role(self.make_button, "primary")
        self.make_button.clicked.connect(self.make_requested)
        top.addWidget(self.make_button)
        self.stop_fetch_button = QPushButton(self.tr("Stop fetching and plan now"))
        self.stop_fetch_button.setToolTip(
            self.tr("Make the Plan from the Catalogue fetched so far; the fetch resumes next time")
        )
        self.stop_fetch_button.clicked.connect(self.stop_fetch_requested)
        self.stop_fetch_button.hide()
        top.addWidget(self.stop_fetch_button)
        self.send_button = QPushButton(self.tr("Send to the torrent client…"))
        self.send_button.setToolTip(
            self.tr(
                "Download each .torrent directly from c411 and add it to its Download "
                "Folder. A torrent whose files already exist there is refused."
            )
        )
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_requested)
        top.addWidget(self.send_button)
        self.stop_send_button = QPushButton(self.tr("Stop sending"))
        self.stop_send_button.setToolTip(
            self.tr(
                "Stop after the current torrent. Torrents already sent stay in your torrent "
                "client; a new Plan leaves them out."
            )
        )
        self.stop_send_button.clicked.connect(self._stop_send)
        self.stop_send_button.hide()
        top.addWidget(self.stop_send_button)
        self.action_row = top
        top.addStretch()
        layout.addLayout(top)
        self.send_progress = QProgressBar()
        self.send_progress.setFormat(self.tr("%v of %m torrents"))
        self.send_progress.hide()
        layout.addWidget(self.send_progress)
        self._send_started: float | None = None
        self.space_table = readonly_table(
            [
                self.tr("Disk / Download Folder"),
                self.tr("Free now"),
                self.tr("Reserved"),
                self.tr("Plan downloads"),
                self.tr("Free after Plan"),
            ]
        )
        self.space_table.setToolTip(
            self.tr(
                "Free after Plan includes the reserved disk-space margin. "
                "Download Folders on the same disk are counted once."
            )
        )
        self.space_table.setMaximumHeight(150)
        self.space_table.hide()
        layout.addWidget(self.space_table)
        self.table = readonly_table(
            [
                self.tr("Torrent"),
                self.tr("Size"),
                self.tr("Seeders"),
                self.tr("Note"),
                self.tr("≈ Zen/day"),
                self.tr("Download Folder"),
            ]
        )
        self.client_names: dict[str, str] = {}
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderItem(6, QTableWidgetItem(self.tr("Client")))
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.empty_state = EmptyState(
            self.table, self.tr("Make a Plan to see suggested torrents here.")
        )
        # Plan order first: Reseeds, then downloads; a header click sorts.
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)
        self.goal.currentIndexChanged.connect(self._options_changed)
        self.download_limit.valueChanged.connect(self._options_changed)
        self.limit_torrents.toggled.connect(self._options_changed)
        self.torrent_limit.valueChanged.connect(self._options_changed)
        self.low_seeders.toggled.connect(self._options_changed)
        self.seeder_limit.valueChanged.connect(self._options_changed)
        self.min_size.valueChanged.connect(self._min_size_changed)
        self.max_size.valueChanged.connect(self._max_size_changed)

    def _size_box(self, unset: str, tooltip: str) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(0, 1_000_000)
        box.setDecimals(3)  # 1 MB steps, for ebooks
        box.setSuffix(self.tr(" GB"))
        box.setSpecialValueText(unset)
        box.setToolTip(tooltip)
        return box

    def _min_size_changed(self) -> None:
        if self.max_size.value() and self.min_size.value() > self.max_size.value():
            self.max_size.blockSignals(True)
            self.max_size.setValue(self.min_size.value())
            self.max_size.blockSignals(False)
        self._options_changed()

    def _max_size_changed(self) -> None:
        if self.max_size.value() and self.min_size.value() > self.max_size.value():
            self.min_size.blockSignals(True)
            self.min_size.setValue(self.max_size.value())
            self.min_size.blockSignals(False)
        self._options_changed()

    def set_options(self, value: PlanOptions) -> None:
        controls = [
            self.goal,
            self.download_limit,
            self.limit_torrents,
            self.torrent_limit,
            self.low_seeders,
            self.seeder_limit,
            self.min_size,
            self.max_size,
        ]
        for control in controls:
            control.blockSignals(True)
        try:
            self.goal.setCurrentIndex(self.goal.findData(value.goal.value))
            self.download_limit.setValue(value.max_download_bytes / GB)
            self.limit_torrents.setChecked(value.max_torrents is not None)
            self.torrent_limit.setValue(value.max_torrents or 100)
            self.torrent_limit.setEnabled(not self._busy and value.max_torrents is not None)
            self.low_seeders.setChecked(value.max_seeders is not None)
            self.seeder_limit.setValue(value.max_seeders if value.max_seeders is not None else 10)
            self.seeder_limit.setEnabled(not self._busy and value.max_seeders is not None)
            self.min_size.setValue(value.min_size / GB)
            self.max_size.setValue(value.max_size / GB)
        finally:
            for control in controls:
                control.blockSignals(False)

    def _options_changed(self) -> None:
        self.torrent_limit.setEnabled(not self._busy and self.limit_torrents.isChecked())
        self.seeder_limit.setEnabled(not self._busy and self.low_seeders.isChecked())
        self.options_changed.emit(
            PlanOptions(
                PlanGoal(self.goal.currentData()),
                round(self.download_limit.value() * GB),
                self.torrent_limit.value() if self.limit_torrents.isChecked() else None,
                self.seeder_limit.value() if self.low_seeders.isChecked() else None,
                round(self.min_size.value() * GB),
                round(self.max_size.value() * GB),
            )
        )

    def invalidate(self) -> None:
        # Editing must not disable the focused input: Qt advances focus and scrolls
        # to the next enabled control when a spin box is disabled mid-keystroke.
        self._clear_result()
        self.busy(False)
        self.summary.setText(self.tr("Plan options changed. Make a new Plan to apply them."))

    # Categories ------------------------------------------------------------

    def set_category_options(
        self,
        options: list[tuple[int, str, bool]],
        chosen: set[int] | None,
        without_folder: set[int] | None = None,
    ) -> None:
        """Offer these (id, name, is_subcategory) categories; `chosen` None means all.

        Categories in `without_folder` are marked: choosing one asks for its folder.
        """
        self.category_options = options
        self.chosen_categories = chosen
        if without_folder is not None:
            self.without_folder = without_folder
        self.categories_menu.clear()
        everything = self.categories_menu.addAction(self.tr("All categories"))
        everything.setCheckable(True)
        everything.setChecked(chosen is None)
        everything.triggered.connect(lambda: self._choose(None))
        self.categories_menu.addSeparator()
        for cid, name, sub in options:
            label = ("    " if sub else "") + name
            if cid in self.without_folder:
                label += "  —  " + self.tr("no Download Folder")
            action = self.categories_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(chosen is not None and cid in chosen)
            action.toggled.connect(lambda on, cid=cid: self._toggle(cid, on))
        self._refresh_categories_label()

    def _toggle(self, cid: int, on: bool) -> None:
        chosen = set(self.chosen_categories or ())
        chosen.add(cid) if on else chosen.discard(cid)
        self._choose(chosen or None)

    def _choose(self, chosen: set[int] | None) -> None:
        self.set_category_options(self.category_options, chosen)
        self.categories_changed.emit(chosen)

    def _refresh_categories_label(self) -> None:
        chosen = self.chosen_categories
        if chosen is None:
            text = self.tr("All categories")
        else:
            names = [name for cid, name, _sub in self.category_options if cid in chosen]
            text = (
                ", ".join(names)
                if len(names) <= 2
                else self.tr("{0} categories").format(len(names))
            )
        self.categories_button.setText(text + " ▾")

    def fetching(self, fetching: bool) -> None:
        """While the Plan's categories are fetched, offer to stop and plan right away."""
        self.stop_fetch_button.setVisible(fetching)
        self.stop_fetch_button.setEnabled(fetching)

    def begin(self) -> None:
        """Clear the previous result while a new Plan is being prepared."""
        self._clear_result()
        self.empty_state.label.setText(self.tr("Making a Plan…"))
        self.busy(True)

    def _clear_result(self) -> None:
        self.plan = None
        self.empty_state.label.setText(self.tr("Make a Plan to see suggested torrents here."))
        self.catalogue_notice.clear()
        self.catalogue_notice.hide()
        self._show_times()
        self.table.setRowCount(0)
        self.space_table.setRowCount(0)
        self.space_table.hide()

    def busy(self, busy: bool, text: str | None = None) -> None:
        self._busy = busy
        self.make_button.setEnabled(not busy)
        self.goal.setEnabled(not busy)
        self.download_limit.setEnabled(not busy)
        self.limit_torrents.setEnabled(not busy)
        self.torrent_limit.setEnabled(not busy and self.limit_torrents.isChecked())
        self.low_seeders.setEnabled(not busy)
        self.seeder_limit.setEnabled(not busy and self.low_seeders.isChecked())
        self.min_size.setEnabled(not busy)
        self.max_size.setEnabled(not busy)
        self.categories_button.setEnabled(not busy)
        self.send_button.setEnabled(not busy and bool(self.plan and self.plan.items))
        if busy:
            self.summary.setText(text or self.tr("Making a Plan…"))

    def show_plan(self, plan: Plan) -> None:
        self.plan = plan
        self.catalogue_notice.clear()
        self.catalogue_notice.hide()
        self.summary.setToolTip("")
        self.busy(False)
        self._show_times()
        clear_rows(self.table, len(plan.items))
        for r, item in enumerate(plan.items):
            c = item.candidate
            size_text = self.tr("Reseed (0 Go)") if c.reseed else human_size(c.size)
            self.table.setItem(r, 0, QTableWidgetItem(c.title))
            self.table.setItem(
                r, 6, QTableWidgetItem(self.client_names.get(c.client_id, c.client_id))
            )
            self.table.setItem(r, 1, NumberItem(size_text, c.download_size))
            self.table.setItem(r, 2, NumberItem(str(c.seeders), c.seeders))
            self.table.setItem(
                r,
                3,
                NumberItem(f"{item.note:.2f}" if item.note is not None else "–", item.note or 0),
            )
            self.table.setItem(r, 4, NumberItem(zen_text(item.zen), item.zen))
            self.table.setItem(r, 5, QTableWidgetItem(str(c.folder) if c.folder else ""))
        self.table.setSortingEnabled(True)
        clear_rows(self.space_table, len(plan.disk_spaces))
        for row, space in enumerate(plan.disk_spaces):
            self.space_table.setItem(row, 0, QTableWidgetItem(str(space.folder)))
            for col, amount in enumerate(
                (space.free, space.reserved, space.download, space.after_plan), 1
            ):
                self.space_table.setItem(row, col, NumberItem(human_size(amount), amount))
        self.space_table.setSortingEnabled(True)
        self.space_table.setVisible(bool(plan.disk_spaces))
        self.space_table.setFixedHeight(
            min(
                150,
                self.space_table.horizontalHeader().height()
                + sum(self.space_table.rowHeight(i) for i in range(len(plan.disk_spaces)))
                + 2,
            )
        )
        if not plan.items:
            self.empty_state.label.setText(self.tr("No torrents selected. See the reason above."))
            self.summary.setText(
                "\n".join(
                    issue_text(
                        issue, lambda text: QCoreApplication.translate("PlanDiagnostics", text)
                    )
                    for issue in plan.issues or (PlanIssue("no_candidates"),)
                )
            )
            return
        text = self.plan_text(plan)
        self.summary.setToolTip("")
        if plan.on_disk:
            text += "\n" + self.tr(
                "{0} torrents left out: they seem to be on disk already. Search them in the "
                "Library to Reseed them instead."
            ).format(len(plan.on_disk))
            shown = [f"{d.title} ← {d.path}" for d in plan.on_disk[:30]]
            if len(plan.on_disk) > 30:
                shown.append(self.tr("… and {0} more").format(len(plan.on_disk) - 30))
            self.summary.setToolTip("\n".join(shown))
        self.summary.setText(text)

    def plan_text(self, plan: Plan) -> str:
        payback = plan.payback_days
        return self.tr(
            "{0} torrents · ≈ +{1} Zen/day · {2} Go to download · paid back in ≈ {3} days"
        ).format(
            len(plan.items),
            f"{plan.zen_added:.2f}",
            f"{plan.download_size / 1e9:.1f}",
            f"{payback:.0f}" if payback is not None else "–",
        ) + (
            self.tr(" · average note {0}").format(f"{plan.average_note:.2f}")
            if plan.average_note is not None
            else ""
        )

    def failed(self, error: Exception) -> None:
        self.busy(False)
        self.summary.setText(self.tr("Could not make a Plan: {0}").format(error_text(error)))

    # Estimated times -------------------------------------------------------

    def set_speed(self, speed: float | None, tested: str | None) -> None:
        self.speed, self.speed_tested = speed, tested
        self.speed_button.setEnabled(True)
        self.speed_button.setText(self.tr("Test speed"))
        self._show_times()

    def speed_testing(self) -> None:
        self.speed_button.setEnabled(False)
        self.speed_button.setText(self.tr("Testing speed…"))

    def _show_times(self) -> None:
        plan = self.plan
        lines = [self.speed_text()]
        if plan is not None and plan.items:
            lines.insert(
                0,
                self.tr("Sending to the torrent client: ≈ {0}").format(
                    duration_text(plan.sending_seconds(self.keys))
                )
                + " · "
                + (
                    self.tr("Downloading the data: ≈ {0} at best").format(
                        duration_text(plan.download_seconds(self.speed))
                    )
                    if self.speed
                    else self.tr("Downloading the data: test your speed to estimate it")
                ),
            )
        self.times.setText("\n".join(lines))

    def speed_text(self) -> str:
        if not self.speed:
            return self.tr("Download speed: not tested")
        text = self.tr("Download speed: {0} Mbit/s ({1}/s)").format(
            f"{self.speed * 8 / 1e6:.0f}", human_size(round(self.speed))
        )
        if self.speed_tested:
            text += " · " + self.tr("tested {0}").format(self.speed_tested[:16].replace("T", " "))
        return text

    # Sending ---------------------------------------------------------------

    def sending(self, progress: SendProgress | None) -> None:
        """Show how far sending the Plan has gone; None when it has ended."""
        if progress is None:
            self._send_started = None
            self.send_progress.hide()
            self.stop_send_button.hide()
            self.make_button.setToolTip("")
            return
        # A new Plan would replace the one being sent, and its progress.
        self.make_button.setToolTip(
            self.tr("Wait for the Plan being sent to finish, or stop it, to make a new one.")
        )
        if self._send_started is None:
            self._send_started = time.monotonic()
            self.stop_send_button.setEnabled(True)
        self.send_progress.setRange(0, max(progress.total, 1))
        self.send_progress.setValue(progress.done)
        self.send_progress.show()
        self.stop_send_button.show()
        stopping = not self.stop_send_button.isEnabled()
        self.busy(
            True,
            self.tr("Stopping after the current torrent…")
            if stopping
            else self.send_text(progress),
        )

    def send_text(self, p: SendProgress) -> str:
        lines = [self.plan_text(self.plan)] if self.plan and self.plan.items else []
        lines.append(
            self.tr("Sending the Plan: {0} of {1} · {2} added · {3} refused · {4} failed").format(
                p.done, p.total, p.added, p.refused, p.failed
            )
            + " · "
            + self.tr("≈ +{0} Zen/day sent").format(f"{p.zen_added:.2f}")
        )
        if p.retry_at is not None:
            lines.append(
                self.tr(
                    "c411 is limiting downloads. Next try at {0}; sending continues by itself."
                ).format(time.strftime("%H:%M", time.localtime(p.retry_at)))
            )
        elif p.title:
            lines.append(self.tr("Now: {0}").format(p.title))
        elapsed = time.monotonic() - self._send_started if self._send_started else 0.0
        if p.done and p.done < p.total and elapsed > 0:
            left = elapsed / p.done * (p.total - p.done)
            lines.append(self.tr("About {0} left").format(duration_text(left)))
        return "\n".join(lines)

    def _stop_send(self) -> None:
        self.stop_send_button.setEnabled(False)
        self.summary.setText(self.tr("Stopping after the current torrent…"))
        self.stop_send_requested.emit()


def duration_text(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes >= 48 * 60:
        return QCoreApplication.translate("PlanView", "{0} days").format(f"{minutes / 1440:.1f}")
    if minutes < 60:
        return QCoreApplication.translate("PlanView", "{0} min").format(max(minutes, 1))
    return QCoreApplication.translate("PlanView", "{0} h {1:02d}").format(
        minutes // 60, minutes % 60
    )


class ZenTab(QWidget):
    """Everything about Zen: what the user's seeding earns, and what to seed next."""

    def defer_while_hidden(self, hidden: Callable[[], bool]) -> None:
        """Hold back the costly seeding views while `hidden()` says the page is out of sight."""
        self.seeding_view.defer_tree = hidden
        self.comparison.defer = hidden

    def __init__(
        self,
        load_seeding: Callable[[], Callable[[], Seeding]],
        profile: Callable[[], ZenProfile],
        uploads: int = 0,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.seeding_view = SeedingView(load_seeding)
        self.comparison = ClassComparison(profile, uploads)
        self.seeding_view.updated.connect(self.comparison.show_seeding)
        self.comparison.background = True
        self.catalogue = CatalogueBox()
        self.plan_view = PlanView()
        layout.setContentsMargins(0, 0, 0, 0)
        from torrentlinker.gui.workspace_tabs import WorkspaceTabs

        self.pages = WorkspaceTabs()
        self.profile_view = ProfileView()
        self.pages.addTab(self.profile_view, self.tr("Profile"))
        seeding_page = QWidget()
        seeding_layout = QVBoxLayout(seeding_page)
        seeding_layout.setContentsMargins(0, 0, 0, 0)
        seeding_layout.addWidget(self.seeding_view, 1)
        seeding_layout.addWidget(self.comparison)
        catalogue_page = self.catalogue_page = QWidget()
        catalogue_layout = QVBoxLayout(catalogue_page)
        catalogue_layout.setContentsMargins(0, 0, 0, 0)
        catalogue_layout.addWidget(self.catalogue)
        catalogue_layout.addStretch()
        self.pages.addTab(seeding_page, self.tr("Seeding"))
        plan_scroll = QScrollArea()
        plan_scroll.setWidgetResizable(True)
        plan_scroll.setFrameShape(QFrame.Shape.NoFrame)
        plan_scroll.setWidget(self.plan_view)
        self.pages.addTab(plan_scroll, self.tr("Plan"))
        self.pages.addTab(catalogue_page, self.tr("Catalogue"))
        layout.addWidget(self.pages)


KEYS_URL = "https://c411.org/user/integrations"
WARNING = QColor("#c62828")


class ZenBand(QFrame):
    """In the window's footer, on the right: Zen Balance, what seeding earns, Plan and
    Catalogue. `message`, for profile problems, goes above the workspace instead."""

    refresh_requested = Signal()
    catalogue_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("zenBand")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 4, 0)
        row.setSpacing(6)
        self.balance = QLabel()
        self.seeding = QLabel()
        self.plan = QLabel()
        self.catalogue = QLabel()
        for i, label in enumerate((self.balance, self.seeding, self.plan, self.catalogue)):
            if i:
                row.addWidget(QLabel("·"))
            row.addWidget(label)
        self.refresh_button = icon_button("⟳", self.tr("Refresh profile"))
        self.refresh_button.setToolTip(self.tr("Read your Zen Balance and Class from c411"))
        self.refresh_button.clicked.connect(self.refresh_requested)
        row.addWidget(self.refresh_button)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setOpenExternalLinks(True)
        self.message.setProperty("role", "error")
        self.message.hide()
        self.set_balance(None)
        self.set_seeding(None)
        self.set_plan(None)
        self.set_catalogue(None)

    def set_balance(self, balance: float | None) -> None:
        value = f"{balance:.1f}" if balance is not None else "–"
        self.balance.setText(self.tr("Zen Balance: <b>{0}</b>").format(value))

    def set_seeding(self, view: Seeding | None) -> None:
        value = zen_text(view.day.total) if view is not None else "–"
        self.seeding.setText(self.tr("Seeding: <b>{0}</b> Zen/day").format(value))

    def set_plan(self, added: float | None) -> None:
        value = f"+{added:.2f}" if added is not None else "–"
        self.plan.setText(self.tr("with Plan: {0}").format(value))

    def set_sending(self, progress: SendProgress | None, added: float | None = None) -> None:
        """Sending progress after the Plan's Zen; with None, the Plan's Zen alone."""
        self.set_plan(added)
        if progress is None:
            return
        self.plan.setText(
            self.plan.text()
            + " · "
            + self.tr("Sending the Plan: <b>{0}/{1}</b>").format(progress.done, progress.total)
            + (" " + self.tr("(c411 limit, waiting)") if progress.retry_at is not None else "")
        )

    def set_catalogue(self, text: str | None) -> None:
        self.catalogue.setText(self.tr("Catalogue: {0}").format(text or "–"))
        self.catalogue_changed.emit(self.catalogue.text())

    def busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)

    def show_profile(self, profile: UserProfile) -> None:
        self.busy(False)
        self.set_balance(profile.balance)
        notes = []
        if not profile.download_allowed:
            if profile.blocked_reason == "insufficient_balance":
                notes.append(self.tr("Downloads are blocked on c411: not enough Zen."))
            else:
                notes.append(
                    self.tr("Downloads are blocked on c411 ({0}).").format(
                        profile.blocked_reason or "?"
                    )
                )
        if profile.zen_class is None:
            notes.append(
                self.tr(
                    "c411 Class “{0}” is not known here: enter your Zen Profile in Settings → Zen."
                ).format(profile.class_slug or self.tr("none"))
            )
        self._message(" ".join(notes))

    def show_profile_error(self, error: Exception) -> None:
        self.busy(False)
        problem = error.problem if isinstance(error, ProfileError) else ProfileProblem.FAILED
        texts = {
            ProfileProblem.NO_KEY: self.tr(
                "Enter your c411 key in Settings → Connections to see your Zen Balance."
            ),
            ProfileProblem.UNAUTHORIZED: self.tr(
                "c411 refused the key: check it in Settings → Connections."
            ),
            ProfileProblem.MISSING_SCOPE: self.tr(
                'Your c411 key cannot read your profile: create one with the "Profil '
                '(lecture)" scope at <a href="{0}">{0}</a>. Until then, enter your Zen '
                "Profile in Settings → Zen."
            ).format(KEYS_URL),
            ProfileProblem.RATE_LIMITED: self.tr(
                "c411 is limiting requests: refresh your profile in a minute."
            ),
        }
        self._message(
            texts.get(problem) or self.tr("Could not read your c411 profile: {0}").format(error)
        )

    def _message(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text) and not self.isHidden())  # hidden with the band
