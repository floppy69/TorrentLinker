"""The Upload tab: Orphans no Candidate matches, made into c411 Drafts (ADR-0011)."""

from __future__ import annotations

import html
import re
import shutil
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import httpx
from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker import net
from torrentlinker.archives import Unpacked, is_archive, unpack, unpacked
from torrentlinker.bbcode import bbcode_to_html
from torrentlinker.disk_rename import RenameApproval
from torrentlinker.domain import ContentKind, ItemState, LocalItem
from torrentlinker.gui.controls import set_role
from torrentlinker.gui.errors import error_text, offer_whole_names
from torrentlinker.gui.library_model import human_size
from torrentlinker.gui.local_drafts import LocalDrafts
from torrentlinker.gui.model_viewer import ModelPanel
from torrentlinker.gui.settings_dialog import kind_label
from torrentlinker.gui.tables import NumberItem, sortable_table
from torrentlinker.gui.tasks import run_in_background, run_with_progress
from torrentlinker.gui.upload_rules import refusal_text, warning_text
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import LibraryEntry
from torrentlinker.matching import IgnoreList
from torrentlinker.options import (
    Chosen,
    OptionType,
    category_options,
    fresh_options,
    options_body,
)
from torrentlinker.qbit import Qbit
from torrentlinker.review import CheckedCandidate
from torrentlinker.scan import scan_item
from torrentlinker.store import Store
from torrentlinker.torrent_details import web_url
from torrentlinker.upload import (
    IMAGE_PLACEHOLDER,
    PROFILES,
    PreparedUpload,
    Problem,
    Refusal,
    UploadFile,
    UploadProfile,
    UploadRequest,
    UploadStopped,
    category_name,
    create_upload,
    default_category,
    find_existing,
    missing_options,
    seed_upload,
    upload_files,
)
from torrentlinker.upload_presentation import assess, extend_template
from torrentlinker.upload_queue import edited_form, save_local, send_local
from torrentlinker.web.uploads import UploadForm

C411_UPLOAD_PAGE = "https://c411.org/upload"
IMAGE_MAX_BYTES = 10_000_000

# Subcategory labels, by c411 id, for every profile.
SUBCATEGORY_LABELS = {
    51: QT_TRANSLATE_NOOP("Subcategory", "Objects"),
    52: QT_TRANSLATE_NOOP("Subcategory", "Characters"),
    53: QT_TRANSLATE_NOOP("Subcategory", "Pack"),
    11: QT_TRANSLATE_NOOP("Subcategory", "Audiobooks"),
    12: QT_TRANSLATE_NOOP("Subcategory", "Comic strips (BD)"),
    13: QT_TRANSLATE_NOOP("Subcategory", "Comics"),
    14: QT_TRANSLATE_NOOP("Subcategory", "Books"),
    15: QT_TRANSLATE_NOOP("Subcategory", "Manga"),
    16: QT_TRANSLATE_NOOP("Subcategory", "Press"),
    59: QT_TRANSLATE_NOOP("Subcategory", "Sheet music & tablature"),
    60: QT_TRANSLATE_NOOP("Subcategory", "Journals & technical manuals"),
    1: QT_TRANSLATE_NOOP("Subcategory", "Animation"),
    2: QT_TRANSLATE_NOOP("Subcategory", "Animated series"),
    3: QT_TRANSLATE_NOOP("Subcategory", "Concert"),
    4: QT_TRANSLATE_NOOP("Subcategory", "Documentary"),
    57: QT_TRANSLATE_NOOP("Subcategory", "Documentary series"),
    5: QT_TRANSLATE_NOOP("Subcategory", "TV programme"),
    6: QT_TRANSLATE_NOOP("Subcategory", "Movie"),
    7: QT_TRANSLATE_NOOP("Subcategory", "TV series"),
    8: QT_TRANSLATE_NOOP("Subcategory", "Stage show"),
    9: QT_TRANSLATE_NOOP("Subcategory", "Sport"),
    10: QT_TRANSLATE_NOOP("Subcategory", "Music videos"),
    54: QT_TRANSLATE_NOOP("Subcategory", "Collection"),
    21: QT_TRANSLATE_NOOP("Subcategory", "Other"),
    22: QT_TRANSLATE_NOOP("Subcategory", "Training"),
    23: QT_TRANSLATE_NOOP("Subcategory", "Linux"),
    24: QT_TRANSLATE_NOOP("Subcategory", "macOS"),
    25: QT_TRANSLATE_NOOP("Subcategory", "Smartphone"),
    26: QT_TRANSLATE_NOOP("Subcategory", "Tablet"),
    27: QT_TRANSLATE_NOOP("Subcategory", "Windows"),
    28: QT_TRANSLATE_NOOP("Subcategory", "Other"),
    29: QT_TRANSLATE_NOOP("Subcategory", "Linux"),
    30: QT_TRANSLATE_NOOP("Subcategory", "macOS"),
    31: QT_TRANSLATE_NOOP("Subcategory", "Microsoft"),
    32: QT_TRANSLATE_NOOP("Subcategory", "Nintendo"),
    33: QT_TRANSLATE_NOOP("Subcategory", "Smartphone"),
    34: QT_TRANSLATE_NOOP("Subcategory", "Sony"),
    35: QT_TRANSLATE_NOOP("Subcategory", "Tablet"),
    36: QT_TRANSLATE_NOOP("Subcategory", "Windows"),
    55: QT_TRANSLATE_NOOP("Subcategory", "VR"),
    39: QT_TRANSLATE_NOOP("Subcategory", "Applications"),
    40: QT_TRANSLATE_NOOP("Subcategory", "Maps"),
    41: QT_TRANSLATE_NOOP("Subcategory", "Miscellaneous"),
    37: QT_TRANSLATE_NOOP("Subcategory", "Emulators"),
    38: QT_TRANSLATE_NOOP("Subcategory", "ROMs / ISOs"),
    17: QT_TRANSLATE_NOOP("Subcategory", "Karaoke"),
    18: QT_TRANSLATE_NOOP("Subcategory", "Music"),
    19: QT_TRANSLATE_NOOP("Subcategory", "Podcasts & radio"),
    20: QT_TRANSLATE_NOOP("Subcategory", "Samples"),
}


class UploadTab(QWidget):
    """Pick an Orphan with no Match, name and describe it by c411's rules, and save it as
    a Draft. An archive is unpacked first, into a new folder, if the user agrees."""

    upload_started = Signal(object)  # Path of the Local Item, now being verified
    unpacked = Signal(object)  # Path of the new folder: the Library needs a Scan

    def __init__(
        self,
        store: Store,
        indexer: Callable[[], Indexer],
        qbit: Callable[[], Qbit],
        ignore: Callable[[], IgnoreList],
        announce: Callable[[], str],
        folder: Path,
        http: httpx.Client | None = None,
        approve_disk_renames: RenameApproval | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.approve_disk_renames = approve_disk_renames
        self.indexer = indexer
        self.qbit = qbit
        self.ignore = ignore
        self.announce = announce
        self.folder = folder  # where the .torrent and .nfo files are kept
        self._http = http  # tests' own; otherwise one per image, through today's proxy
        self._editing_record: dict | None = None
        self.entries: list[LibraryEntry] = []
        self.searched: dict[Path, list[CheckedCandidate]] = {}
        self._refresh_depth = 0
        self._refresh_pending = False
        # While a batch delivers searches one by one, rebuild the list at most once a second.
        self._throttled = False
        self._throttle = QTimer(self, singleShot=True, interval=1000)
        self._throttle.timeout.connect(self._flush_refresh)
        # Orphans whose last search, kept by the Store, found no Candidate at all: known
        # at once after a restart, while the Library still compares the others.
        self._found_nothing: set[Path] = set()
        self.shown: list[LibraryEntry] = []
        self.entry: LibraryEntry | None = None
        self.unpack_target: Unpacked | None = None  # the selected archive, once unpacked
        self._listings: dict[Path, Unpacked | None] = {}  # archives read so far
        self._to_select: tuple[Path, Path] | None = None  # (new folder, its archive)
        self.files: list[UploadFile] = []
        self._picked: dict[Path, int] = {}  # the category the user chose, by Local Item
        self._existing: dict[tuple[Path, int], list[Candidate]] = {}  # searched this session
        self._searching: set[tuple[Path, int]] = set()
        self._edited: set[str] = set()  # name, nfo, description: left alone once edited
        self._stop = threading.Event()
        self._image_url = ""  # the URL whose image the preview shows
        self._description_image_url = ""  # last URL supplied through the image field
        self.option_types: list[OptionType] = []  # the subcategory's, once read
        self._option_widgets: dict[int, QComboBox | QListWidget] = {}
        self._picks: Chosen = {}  # what the user chose, which the profile's suggestion yields to
        self._options_for: int | None = None  # the subcategory whose options are awaited
        self._options_state = ""  # what the Options box says while no selector shows
        self._inspected: set[tuple[Path, int]] = set()  # items a profile has read, by category
        self._inspecting: set[tuple[Path, int]] = set()  # ... being read now

        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel(self.tr("Upload"))
        font = title.font()
        font.setPointSize(font.pointSize() + 5)
        title.setFont(font)
        title.setProperty("role", "heading")
        heading.addWidget(title)
        heading.addStretch()
        self.new_button = QPushButton(self.tr("New draft"))
        set_role(self.new_button, "primary")
        self.new_button.clicked.connect(self.new_draft)
        heading.addWidget(self.new_button)
        layout.addLayout(heading)
        layout.addWidget(QLabel(self.tr("Prepare locally. Review. Send to c411.")))
        navigation = QHBoxLayout()
        self.local_button = QPushButton(self.tr("Local drafts"))
        self.remote_button = QPushButton(self.tr("c411 drafts"))
        for button in (self.local_button, self.remote_button):
            set_role(button, "tab")
            button.setCheckable(True)
            navigation.addWidget(button)
        navigation.addStretch()
        layout.addLayout(navigation)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        # Left: the Orphans
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Filter Local Items…"))
        self.search.setAccessibleName(self.tr("Filter Local Items…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        left_layout.addWidget(self.search)
        filters = QHBoxLayout()
        self.kind_filter = QComboBox()
        self.kind_filter.addItem(self.tr("All kinds"), None)
        for kind in ContentKind:
            self.kind_filter.addItem(kind_label(kind), kind)
        self.kind_filter.currentIndexChanged.connect(self._fill)
        self.show_all = QCheckBox(self.tr("Show all"))
        self.show_all.setToolTip(self.tr("Also show Orphans not searched yet or refused"))
        self.show_all.toggled.connect(self._fill)
        filters.addWidget(self.kind_filter, 1)
        filters.addWidget(self.show_all)
        left_layout.addLayout(filters)
        self.items = QTableWidget(0, 4)
        self.items.setHorizontalHeaderLabels(
            [self.tr("Local Item"), self.tr("Kind"), self.tr("Size"), self.tr("Status")]
        )
        self.items.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.items.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        sortable_table(self.items)
        header = self.items.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 240)
        for c in (1, 2):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, 200)
        self.items.itemSelectionChanged.connect(self._item_selected)
        left_layout.addWidget(self.items)

        # Right: the release
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self._category_picked)
        self.source = QLineEdit()
        self.source.setPlaceholderText(self.tr("Where it comes from; empty for NOTAG"))
        self.source.textChanged.connect(self._regenerate)
        self.subcategory = QComboBox()
        self.subcategory.currentIndexChanged.connect(self._subcategory_changed)
        self.name = QLineEdit()
        self.name.textEdited.connect(lambda: self._edited.add("name"))
        self.name.textChanged.connect(self._name_changed)
        self.image_url = QLineEdit()
        self.image_url.setPlaceholderText(self.tr("https://… an image of it, required by c411"))
        self.image_url.textChanged.connect(self._image_changed)
        form.addRow(self.tr("Category"), self.category)
        form.addRow(self.tr("Source"), self.source)
        form.addRow(self.tr("Subcategory"), self.subcategory)
        form.addRow(self.tr("Upload name"), self.name)
        original_name = QPushButton(self.tr("Use a verified original name…"))
        original_name.clicked.connect(self.use_original_name)
        form.addRow("", original_name)
        image_row = QHBoxLayout()
        image_row.addWidget(self.image_url, 1)
        self.host_image = QPushButton(self.tr("Host image…"))
        self.host_image.setToolTip(
            self.tr("Open Postimages, upload your image, then paste its direct link here.")
        )
        self.host_image.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://postimages.org/"))
        )
        image_row.addWidget(self.host_image)
        form.addRow(self.tr("Image URL"), image_row)
        self.pages = QTabWidget()
        details_page = QWidget()
        details_layout = QVBoxLayout(details_page)
        details_layout.addLayout(form)
        self.pages.addTab(details_page, self.tr("Details"))
        self.options_box = QGroupBox()
        options_layout = QVBoxLayout(self.options_box)
        self.options_toggle = QToolButton()
        set_role(self.options_toggle, "quiet")
        self.options_toggle.setText(self.tr("Options"))
        self.options_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.options_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.options_toggle.setCheckable(True)
        options_layout.addWidget(self.options_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.options_body = QWidget()
        self.options_form = QFormLayout(self.options_body)
        self.options_form.setContentsMargins(0, 0, 0, 0)
        self.options_body.hide()
        self.options_toggle.toggled.connect(self.options_body.setVisible)
        self.options_toggle.toggled.connect(
            lambda expanded: self.options_toggle.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            )
        )
        options_layout.addWidget(self.options_body)
        status_row = QHBoxLayout()
        self.options_status = QLabel()
        self.options_status.setWordWrap(True)
        status_row.addWidget(self.options_status, 1)
        self.options_refresh = QPushButton(self.tr("Refresh options"))
        set_role(self.options_refresh, "quiet")
        self.options_refresh.setToolTip(self.tr("Read this subcategory's options from c411 again"))
        self.options_refresh.clicked.connect(lambda: self._show_options(refresh=True))
        status_row.addWidget(self.options_refresh)
        options_layout.addLayout(status_row)
        details_layout.addWidget(self.options_box)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setProperty("role", "error")
        right_layout.addWidget(self.problems)
        self.warnings = QLabel()  # judgement rules: amber, the Draft can still be saved
        self.warnings.setWordWrap(True)
        self.warnings.setProperty("role", "warning")
        right_layout.addWidget(self.warnings)

        # What c411 already has: information only, collapsible
        self.existing_box = QGroupBox()
        self.existing_box.setCheckable(True)
        self.existing_box.toggled.connect(self._existing_toggled)
        existing_layout = QVBoxLayout(self.existing_box)
        self.existing_body = QWidget()
        body_layout = QVBoxLayout(self.existing_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.existing_status = QLabel()
        self.existing_status.setWordWrap(True)
        self.existing_view = QTextBrowser()
        self.existing_view.setOpenExternalLinks(True)
        self.existing_view.setMaximumHeight(120)
        body_layout.addWidget(self.existing_status)
        body_layout.addWidget(self.existing_view)
        existing_layout.addWidget(self.existing_body)
        details_layout.addWidget(self.existing_box)

        self.file_table = QTableWidget(0, 3)
        self.file_table.setHorizontalHeaderLabels(
            [self.tr("In the torrent"), self.tr("Your file"), self.tr("Size")]
        )
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        sortable_table(self.file_table)
        fh = self.file_table.horizontalHeader()
        fh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        fh.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        fh.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        file_page = QWidget()
        file_layout = QVBoxLayout(file_page)
        file_layout.addWidget(self.file_table, 1)
        self.pages.addTab(file_page, self.tr("Files && NFO"))

        description_page = QWidget()
        dl = QVBoxLayout(description_page)
        dl.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.description = QPlainTextEdit()
        self.description.textChanged.connect(self._description_changed)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        split.addWidget(self.description)
        split.addWidget(self.preview)
        dl.addWidget(split)
        self.presentation_status = QLabel()
        self.presentation_status.setWordWrap(True)
        self.presentation_status.setTextFormat(Qt.TextFormat.PlainText)
        dl.addWidget(self.presentation_status)
        reset_description = QPushButton(self.tr("Reset from the template"))
        set_role(reset_description, "quiet")
        reset_description.clicked.connect(lambda: self._reset("description"))
        dl.addWidget(reset_description, 0, Qt.AlignmentFlag.AlignRight)
        self.pages.addTab(description_page, self.tr("Description"))

        nfo_page = QWidget()
        nl = QVBoxLayout(nfo_page)
        nl.setContentsMargins(0, 0, 0, 0)
        self.nfo = QPlainTextEdit()
        self.nfo.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.nfo.setStyleSheet("font-family: monospace")
        self.nfo.textChanged.connect(lambda: self._edited.add("nfo"))
        self.nfo.textChanged.connect(self._render_description)
        nl.addWidget(self.nfo)
        reset_nfo = QPushButton(self.tr("Reset from the files"))
        set_role(reset_nfo, "quiet")
        reset_nfo.clicked.connect(lambda: self._reset("nfo"))
        nl.addWidget(reset_nfo, 0, Qt.AlignmentFlag.AlignRight)
        file_layout.addWidget(nfo_page, 1)

        image_page = QWidget()
        il = QVBoxLayout(image_page)
        self.image = QLabel(self.tr("Enter the image URL above"))
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(200)
        il.addWidget(self.image, 1)
        self.pages.addTab(image_page, self.tr("Artwork"))
        self.model_panel = ModelPanel(
            folder, lambda: self.name.text().strip(), self.ignore, self._image_is_sheet
        )
        self.model_tab = self.pages.addTab(self.model_panel, self.tr("3D view"))
        right_layout.addWidget(self.pages, 1)

        actions = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.hide()
        actions.addWidget(self.progress, 1)
        self.stop_button = QPushButton(self.tr("Stop"))
        self.stop_button.clicked.connect(self._stop.set)
        self.stop_button.hide()
        actions.addWidget(self.stop_button)
        actions.addStretch()
        self.queue_button = QPushButton(self.tr("Save draft"))
        set_role(self.queue_button, "primary")
        self.queue_button.clicked.connect(self.queue_draft)
        actions.addWidget(self.queue_button)
        self.create_button = QPushButton()
        set_role(self.create_button, "primary")
        self.create_button.clicked.connect(self.create_draft)
        actions.addWidget(self.create_button)

        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(left)
        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        editor_scroll.setWidget(right)
        editor_scroll.setMinimumWidth(420)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(8, 0, 0, 0)
        editor_layout.addWidget(editor_scroll, 1)
        editor_layout.addLayout(actions)
        main.addWidget(editor)
        main.setChildrenCollapsible(False)
        main.setHandleWidth(2)
        main.setSizes([int(str(QSettings().value("upload/prepare_width", 300))), 750])
        main.splitterMoved.connect(
            lambda *_: QSettings().setValue("upload/prepare_width", main.sizes()[0])
        )
        self.workspaces = QStackedWidget()
        self.workspaces.addWidget(main)
        layout.addWidget(self.workspaces, 1)

        self.local_drafts = LocalDrafts(
            store,
            self._edit_local_draft,
            self._send_local_draft,
            self.edit_saved_details,
            lambda sub: category_options(store, self.indexer().category_options, sub),
        )
        self.local_drafts.sent.connect(self._local_draft_sent)
        self.workspaces.addWidget(self.local_drafts)

        drafts_box = QGroupBox(self.tr("Your c411 Drafts"))
        drafts_layout = QVBoxLayout(drafts_box)
        self.drafts = QTableWidget(0, 3)
        self.drafts.setHorizontalHeaderLabels(
            [self.tr("Draft"), self.tr("Category"), self.tr("Modified")]
        )
        self.drafts.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        sortable_table(self.drafts)
        self.drafts.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        drafts_layout.addWidget(self.drafts, 1)
        row = QHBoxLayout()
        self.drafts_status = QLabel()
        row.addWidget(self.drafts_status, 1)
        refresh = QPushButton(self.tr("Refresh"))
        set_role(refresh, "quiet")
        refresh.clicked.connect(self.refresh_drafts)
        row.addWidget(refresh)
        open_page = QPushButton(self.tr("Open c411's upload page"))
        set_role(open_page, "quiet")
        open_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(C411_UPLOAD_PAGE)))
        row.addWidget(open_page)
        drafts_layout.addLayout(row)
        self.workspaces.addWidget(drafts_box)
        self.local_button.clicked.connect(
            lambda: self.workspaces.setCurrentWidget(self.local_drafts)
        )
        self.remote_button.clicked.connect(lambda: self.workspaces.setCurrentWidget(drafts_box))
        self.workspaces.currentChanged.connect(self._workspace_changed)
        self.workspaces.setCurrentWidget(self.local_drafts)

        self._image_timer = QTimer(self)
        self._image_timer.setSingleShot(True)
        self._image_timer.setInterval(600)
        self._image_timer.timeout.connect(self._load_image)
        self._fill()
        self._show_entry()

    def _workspace_changed(self, index: int) -> None:
        self.local_button.setChecked(index != 2)
        self.remote_button.setChecked(index == 2)
        self.notice.setVisible(index == 0)
        self.new_button.setVisible(index != 0)
        if index == 1:
            self.local_drafts.refresh()
        elif index == 2:
            self.refresh_drafts()

    def new_draft(self) -> None:
        self._editing_record = None
        self.items.setEnabled(True)
        self.workspaces.setCurrentIndex(0)
        self.pages.setCurrentIndex(0)

    def edit_saved_details(self, record: dict) -> None:
        self.select(Path(record["path"]))
        if self.entry is None or str(self.entry.item.path) != record["path"]:
            QMessageBox.warning(
                self,
                self.tr("Local drafts"),
                self.tr("Scan the Library containing this Local Draft first."),
            )
            return
        self._editing_record = record
        self.items.setEnabled(False)
        form = record["form"]
        self._picked[self.entry.item.path] = form["category"]
        self._show_entry()
        self._edited.update({"name", "description", "nfo"})
        self.source.setText(form.get("source", ""))
        self.subcategory.setCurrentIndex(
            next(
                (
                    i
                    for i in range(self.subcategory.count())
                    if int(self.subcategory.itemData(i)) == form["subcategory"]
                ),
                -1,
            )
        )
        self._picks = {int(k): v for k, v in form.get("options", {}).items()}
        self.name.setText(form["title"])
        self.image_url.setText(form.get("image", ""))
        self.description.setPlainText(form["description"])
        self.nfo.setPlainText(form["nfo"])
        self._show_options()
        self.pages.setCurrentIndex(0)

    # The Library -----------------------------------------------------------

    def set_entries(self, entries: list[LibraryEntry]) -> None:
        self.entries = entries
        self._found_nothing = {
            e.item.path
            for e in entries
            if e.state is ItemState.ORPHAN and self.store.remembered_candidates(e.item.path) == "[]"
        }
        if self._to_select is not None:
            folder, archive = self._to_select
            if any(e.item.path == folder for e in entries):
                # Searching the archive compared its contents too (ADR-0007).
                if archive in self.searched:
                    self.searched[folder] = self.searched[archive]
                self._to_select = None
                self._fill()
                self.select(folder)
                return
        self._fill()

    @contextmanager
    def defer_refresh(self) -> Iterator[None]:
        """Restore a batch of searches before rebuilding the upload list once."""
        self._refresh_depth += 1
        try:
            yield
        finally:
            self._refresh_depth -= 1
            if self._refresh_depth == 0 and self._refresh_pending:
                self._refresh_pending = False
                self._fill()

    def throttle_refresh(self, on: bool) -> None:
        self._throttled = on
        if not on and self._throttle.isActive():
            self._throttle.stop()
            self._flush_refresh()

    def _flush_refresh(self) -> None:
        if self._refresh_pending:
            self._refresh_pending = False
            self._fill()

    def remember(self, entry: LibraryEntry, checked: list[CheckedCandidate]) -> None:
        """An Orphan's latest search, from the Library."""
        self.searched[entry.item.path] = checked
        self._fill()

    def select(self, path: Path) -> None:
        """Show the Upload form for this Local Item, even if the filters hid it."""
        self.new_draft()
        if all(e.item.path != path for e in self.shown):
            self.search.clear()
            self.kind_filter.setCurrentIndex(0)
            self.show_all.setChecked(True)
        for r in range(self.items.rowCount()):
            selected_cell = self.items.item(r, 0)
            assert selected_cell is not None
            e = selected_cell.data(Qt.ItemDataRole.UserRole)
            if e.item.path == path:
                self.items.selectRow(r)
                return

    def candidates(self) -> list[LibraryEntry]:
        """Every Orphan; only some may become Uploads (see why_not)."""
        return [e for e in self.entries if e.state is ItemState.ORPHAN]

    def needs_unpacking(self, entry: LibraryEntry) -> bool:
        """An archive whose only fault is being one: unpacked, it may become an Upload."""
        profile = self._profile_of(entry)
        if profile is None or not is_archive(entry.item):
            return False
        found = profile.refusals(entry.item, self.ignore(), self._subcategory_of(entry))
        return bool(found) and all(r.problem is not Problem.NO_FILE for r in found)

    def why_not(self, entry: LibraryEntry) -> str | None:
        """Why this Orphan cannot be uploaded now; None when it can, an archive included
        (it is unpacked first)."""
        category = self._category_of(entry)
        if category is None:
            return self.tr("Choose a category")
        profile = PROFILES.get(category)
        if profile is None:
            return self.tr("Uploads to {0} are not supported yet").format(category_name(category))
        checked = self.searched.get(entry.item.path)
        if checked is None and entry.item.path in self._found_nothing:
            checked = []
        if checked is None:
            return self.tr("Search it first: c411 may already have it")
        if any(v.match for v in checked):
            return self.tr("c411 already has it: Reseed it from the Library")
        if self.needs_unpacking(entry):
            return None
        if found := profile.refusals(entry.item, self.ignore(), self._subcategory_of(entry)):
            return "; ".join(refusal_text(r) for r in found)
        return None

    def _subcategory_of(self, entry: LibraryEntry) -> int | None:
        """The subcategory the form shows for the selected item; the list knows none."""
        return self.subcategory.currentData() if entry is self.entry else None

    def _fill(self) -> None:
        if self._refresh_depth or self._throttle.isActive():
            self._refresh_pending = True
            return
        if self._throttled:
            self._throttle.start()
        selected = self.entry.item.path if self.entry else None
        kind = self.kind_filter.currentData()
        everything = self.show_all.isChecked()
        query = self.search.text().strip().casefold()
        rows = []
        for e in self.candidates():
            if kind is not None and e.folder.kind is not kind:
                continue
            if query and query not in e.item.path.name.casefold():
                continue
            reason = self.why_not(e)
            if reason and not everything:
                continue
            rows.append((reason is not None, e.item.path.name.casefold(), e, reason))
        rows.sort(key=lambda r: (r[0], r[1]))
        self.shown = [e for _, _, e, _ in rows]
        self.items.blockSignals(True)
        self.items.setSortingEnabled(False)
        self.items.setRowCount(0)
        self.items.setRowCount(len(rows))
        for r, (_, _, e, reason) in enumerate(rows):
            status = reason or (
                self.tr("Archive: unpack it to upload")
                if self.needs_unpacking(e)
                else self.tr("Ready")
            )
            cells = [e.item.path.name, kind_label(e.folder.kind), human_size(e.item.size), status]
            for c, text in enumerate(cells):
                cell = NumberItem(text, e.item.size) if c == 2 else QTableWidgetItem(text)
                if c == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, e)
                cell.setToolTip(text)
                if reason:
                    cell.setForeground(Qt.GlobalColor.gray)
                self.items.setItem(r, c, cell)
        self.items.setSortingEnabled(True)
        self.items.blockSignals(False)
        if selected is not None and selected not in {e.item.path for e in self.shown}:
            self.entry = None
            self._show_entry()
        for r in range(self.items.rowCount()):
            selected_cell = self.items.item(r, 0)
            assert selected_cell is not None
            e = selected_cell.data(Qt.ItemDataRole.UserRole)
            if e.item.path == selected:
                self.items.selectRow(r)
        hidden = len(self.candidates()) - len(self.shown)
        if not self.announce():
            self.notice.setText(
                self.tr(
                    "An Announce URL is needed only when sending. Set it in Settings → Connections."
                )
            )
        elif not self.shown and query:
            self.notice.setText(self.tr("No Local Items match your search and filters."))
        elif not self.shown and not everything:
            self.notice.setText(
                self.tr(
                    "No Orphan is ready to upload. Search your Orphans in the Library, or "
                    "tick Show all to pick a category and see why the {0} others are not "
                    "ready."
                ).format(hidden)
            )
        else:
            self.notice.setText(
                self.tr(
                    "Choose an Orphan to prepare a local draft. Review it before sending to c411."
                )
            )
        self._update_actions()

    # The release -----------------------------------------------------------

    def _category_of(self, entry: LibraryEntry) -> int | None:
        """The user's pick, else what the Library Folder's Content Kind proposes."""
        return self._picked.get(entry.item.path, default_category(entry.folder.kind))

    def _profile_of(self, entry: LibraryEntry) -> UploadProfile | None:
        category = self._category_of(entry)
        return PROFILES.get(category) if category is not None else None

    def profile(self) -> UploadProfile | None:
        return self._profile_of(self.entry) if self.entry else None

    def _fill_categories(self) -> None:
        """The picker lists every profile; a category proposed but not supported yet
        shows first, so the picker never says otherwise than the status."""
        self.category.blockSignals(True)
        self.category.clear()
        current = self._category_of(self.entry) if self.entry else None
        if current not in PROFILES:
            self.category.addItem(
                category_name(current) if current is not None else self.tr("Choose a category"),
                current,
            )
        for category in PROFILES:
            self.category.addItem(category_name(category), category)
        self.category.setCurrentIndex(self.category.findData(current))
        self.category.blockSignals(False)
        self.category.setEnabled(self.entry is not None)

    def _category_picked(self) -> None:
        """Another category is another profile: its refusals, subcategories and texts."""
        category = self.category.currentData()
        if self.entry is None or category is None:
            return
        self._picked[self.entry.item.path] = category
        self._show_entry()
        self._fill()

    def source_item(self) -> LocalItem | None:
        """What the Upload is made of: the selected item, or the archive as unpacked."""
        if self.entry is None:
            return None
        if self.needs_unpacking(self.entry):
            return self.unpack_target.item if self.unpack_target else None
        return self.entry.item

    def _item_selected(self) -> None:
        rows = self.items.selectionModel().selectedRows()
        cell = self.items.item(rows[0].row(), 0) if rows else None
        entry = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if entry is self.entry:
            return
        self.entry = entry
        self._show_entry()

    def _show_entry(self) -> None:
        self._edited.clear()
        self._picks = {}
        self.unpack_target = None
        entry, profile = self.entry, self.profile()
        if entry is not None and self.needs_unpacking(entry):
            self._read_archive(entry)
        self._fill_categories()
        self.subcategory.blockSignals(True)
        self.subcategory.clear()
        if profile is not None:
            for sub in profile.subcategories:
                label = SUBCATEGORY_LABELS.get(sub.id, sub.label)
                self.subcategory.addItem(
                    QCoreApplication.translate("Subcategory", str(label)), sub.id
                )
        self.subcategory.blockSignals(False)
        self._choose_subcategory()
        for field in (self.source, self.name, self.image_url, self.subcategory):
            field.setEnabled(profile is not None)
        self._show_options()
        self._regenerate()
        self._inspect()
        self._show_existing()
        self._show_model()

    def _inspect(self) -> None:
        """Let the profile read what the files say (tags, MediaInfo) off the GUI thread,
        then redo what depends on it. An archive not yet unpacked has nothing to read."""
        profile, item = self.profile(), self.source_item()
        if profile is None or item is None or not item.path.exists():
            return
        key = (item.path, profile.category)
        if key in self._inspected:
            return
        self._inspected.add(key)
        self._inspecting.add(key)
        ignore = self.ignore()

        def current() -> bool:
            return isValid(self) and self.source_item() is item and self.profile() is profile

        def done(_: object) -> None:
            self._inspecting.discard(key)
            if current():
                self._show_options()
                self._regenerate()
                self._show_existing()  # the profile may now look an item up by ids

        def failed(error: Exception) -> None:
            self._inspected.discard(key)  # selecting the item again retries
            self._inspecting.discard(key)
            if current():
                self._show_existing()

        run_in_background(lambda: profile.inspect(item, ignore), done, failed)

    def _subcategory_changed(self) -> None:
        """Another subcategory has other options, and the old picks do not apply."""
        self._picks = {}
        self._show_options()
        self._regenerate()
        self._show_existing()

    # What c411 already has ---------------------------------------------------

    def _existing_toggled(self, expanded: bool) -> None:
        self.existing_body.setVisible(expanded)

    def _show_existing(self) -> None:
        """List the releases c411 already has of the selected item: one search per item
        and category, off the GUI thread, kept for the session."""
        entry, profile = self.entry, self.profile()
        if entry is None or profile is None:
            self.existing_box.hide()
            return
        self.existing_box.show()
        key = (entry.item.path, profile.category)
        if key in self._existing:
            self._render_existing(self._existing[key])
            return
        self._render_existing(None)
        if key in self._searching or key in self._inspecting:
            return  # an inspection first: its answers may give the search ids
        self._searching.add(key)
        query = profile.existing_query(entry.item, self.ignore())
        indexer = self.indexer()
        search, by_ids = indexer.search, indexer.by_tmdb

        def current() -> bool:
            return (
                self.entry is not None
                and self.entry.item.path == key[0]
                and ((p := self.profile()) is not None and p.category == key[1])
            )

        def done(found: list[Candidate]) -> None:
            self._searching.discard(key)
            self._existing[key] = found
            if isValid(self) and current():
                self._render_existing(found)

        def failed(error: Exception) -> None:
            self._searching.discard(key)  # not kept: selecting the item again retries
            if isValid(self) and current():
                self._render_existing(None, error_text(error))

        run_in_background(lambda: find_existing(search, query, key[1], by_ids), done, failed)

    def _render_existing(self, found: list[Candidate] | None, error: str = "") -> None:
        """`found` None: still searching, or failed with `error`."""
        title = self.tr("Search for existing releases on c411")
        self.existing_view.hide()
        if found is None:
            self.existing_box.setTitle(title)
            self.existing_status.setText(
                self.tr("c411 could not be searched: {0}").format(error)
                if error
                else self.tr("Searching c411…")
            )
            return
        if not found:
            self.existing_box.setTitle(title)
            self.existing_status.setText(
                self.tr(
                    "No release found by this search. These files may still belong to a c411 "
                    "torrent, especially inside a differently named Pack. Rescan the Library "
                    "to check the configured Torrent Client and Path Mappings."
                )
            )
            return
        self.existing_box.setTitle(f"{title} ({len(found)})")
        self.existing_status.setText(
            self.tr("Releases c411 already has, for information: Team Pending refuses duplicates.")
        )
        seeders = self.tr("seeders")
        rows = "".join(
            "<li>"
            + (
                f'<a href="{html.escape(c.details_url, quote=True)}">{html.escape(c.title)}</a>'
                if c.details_url.startswith(("https://", "http://"))
                else html.escape(c.title)
            )
            + f" — {human_size(c.size)}, {c.seeders} {html.escape(seeders)}</li>"
            for c in found
        )
        self.existing_view.setHtml(f"<ul>{rows}</ul>")
        self.existing_view.show()

    def _image_is_sheet(self) -> bool:
        profile = self.profile()
        return profile is not None and profile.image_is_sheet(self.subcategory.currentData())

    def _show_model(self) -> None:
        """The 3D page follows the selection; an archive's models are not on disk yet."""
        profile, entry = self.profile(), self.entry
        shown = profile is not None and profile.renders_models
        self.pages.setTabVisible(self.model_tab, shown)
        usable = entry is not None and shown and not self.needs_unpacking(entry)
        self.model_panel.set_item(entry.item if usable and entry else None)

    def _choose_subcategory(self) -> None:
        profile, item = self.profile(), self.source_item()
        if profile is not None and item is not None:
            default = profile.default_subcategory(item, self.ignore())
            self.subcategory.blockSignals(True)
            self.subcategory.setCurrentIndex(self.subcategory.findData(default))
            self.subcategory.blockSignals(False)

    def _read_archive(self, entry: LibraryEntry) -> None:
        """List the archive off the GUI thread; 7-Zip may take a moment."""
        path = entry.item.path
        if path in self._listings:
            self.unpack_target = self._listings[path]
            return
        self.problems.setText(self.tr("Reading the archive…"))

        def done(target: Unpacked | None) -> None:
            self._listings[path] = target
            if self.entry is not None and self.entry.item.path == path:
                self.unpack_target = target
                self._choose_subcategory()
                self._show_options()  # the profile may suggest from the unpacked files
                self._regenerate()

        run_in_background(lambda: unpacked(entry.item), done, lambda e: done(None))

    # Category Options ------------------------------------------------------

    def chosen_options(self) -> Chosen:
        """The values the selectors show, by option type id."""
        chosen: Chosen = {}
        for option_id, widget in self._option_widgets.items():
            if isinstance(widget, QListWidget):
                chosen[option_id] = [
                    widget.item(r).data(Qt.ItemDataRole.UserRole)
                    for r in range(widget.count())
                    if widget.item(r).checkState() == Qt.CheckState.Checked
                ]
            else:
                value = widget.currentData()
                chosen[option_id] = [] if value is None else [value]
        return chosen

    def missing_options(self) -> list[Refusal]:
        return missing_options(self.option_types, self.chosen_options())

    def _show_options(self, refresh: bool = False) -> None:
        """Show the selectors of the chosen subcategory: from the store when kept for less
        than a week, else read from c411 off the GUI thread."""
        subcategory = self.subcategory.currentData()
        self._options_for = subcategory
        self._clear_options()
        if self.profile() is None or subcategory is None:
            self._set_options_state("")
            return
        if not refresh and (kept := fresh_options(self.store, subcategory)) is not None:
            self._options_read(subcategory, kept)
            return
        self._set_options_state(self.tr("Reading the options…"))
        try:
            fetch = self.indexer().category_options
        except Exception as e:  # noqa: BLE001 - shown where the options would be
            self._options_failed(subcategory, e)
            return
        store = self.store
        run_in_background(
            lambda: category_options(store, fetch, subcategory, refresh=refresh),
            lambda types: self._options_read(subcategory, types),
            lambda e: self._options_failed(subcategory, e),
        )

    def _clear_options(self) -> None:
        self.option_types = []
        self._option_widgets = {}
        while self.options_form.rowCount():
            self.options_form.removeRow(0)

    def _set_options_state(self, text: str) -> None:
        """Say why no selector shows (reading, failed), or hide the box when there are
        none to show."""
        self._options_state = text
        self.options_status.setText(text)
        self.options_status.setVisible(bool(text))
        self.options_refresh.setVisible(bool(text) and text != self.tr("Reading the options…"))
        self.options_box.setVisible(bool(text) or bool(self.option_types))
        self._name_changed()

    def _options_failed(self, subcategory: int, error: Exception) -> None:
        if not isValid(self) or subcategory != self._options_for:
            return
        self._clear_options()
        self._set_options_state(
            self.tr("Could not read the options: {0}").format(error_text(error))
        )

    def _options_read(self, subcategory: int, types: list[OptionType]) -> None:
        if not isValid(self) or subcategory != self._options_for:
            return  # the tab is gone, or another subcategory was chosen meanwhile
        self._clear_options()
        self.option_types = types
        item, profile = self.source_item(), self.profile()
        suggested = (
            profile.suggested_options(item, self.ignore(), types) if profile and item else {}
        )
        wanted = {**suggested, **self._picks}
        for t in types:
            label = f"{t.name} *" if t.required else t.name
            widget: QComboBox | QListWidget
            if t.multiple:
                widget = QListWidget()
                widget.setMaximumHeight(110)
                for v in t.values:
                    entry = QListWidgetItem(v.label)
                    entry.setData(Qt.ItemDataRole.UserRole, v.id)
                    entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    on = v.id in wanted.get(t.id, [])
                    entry.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                    widget.addItem(entry)
                widget.itemChanged.connect(lambda _item, o=t.id: self._option_picked(o))
            else:
                widget = QComboBox()
                widget.addItem("—", None)
                for v in t.values:
                    widget.addItem(v.label, v.id)
                first = next(iter(wanted.get(t.id, [])), None)
                widget.setCurrentIndex(max(widget.findData(first), 0))
                widget.currentIndexChanged.connect(lambda _i, o=t.id: self._option_picked(o))
            if t.required:
                widget.setToolTip(self.tr("c411 requires this one"))
            self._option_widgets[t.id] = widget
            self.options_form.addRow(label, widget)
        self._set_options_state("")

    def _option_picked(self, option_id: int) -> None:
        """The user's choice for this option wins over the profile's suggestion."""
        self._picks[option_id] = self.chosen_options()[option_id]
        self._name_changed()

    def use_original_name(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        from torrentlinker.provenance import Provenance

        item = self.source_item()
        if item is None:
            return
        names = Provenance(self.store.torrent_dir.parent).names(item)
        if not names:
            QMessageBox.information(
                self,
                self.tr("Original names"),
                self.tr("Import and verify an old torrent in Library → Evidence first."),
            )
            return
        name, accepted = QInputDialog.getItem(
            self,
            self.tr("Original names"),
            self.tr("Use this verified release name"),
            names,
            0,
            False,
        )
        if accepted:
            self._edited.add("name")
            self.name.setText(name)

    def _regenerate(self) -> None:
        """Fill what the user has not edited from the profile: name, NFO, description."""
        profile, item = self.profile(), self.source_item()
        if profile is None or item is None:
            if "name" not in self._edited:
                self.name.clear()
            self._name_changed()
            return
        name = profile.suggested_name(
            item, self.ignore(), self.source.text(), self.subcategory.currentData()
        )
        if "name" not in self._edited and name != self.name.text():
            self.name.setText(name)  # which recomputes the rest
        else:
            self._name_changed()

    def _name_changed(self) -> None:
        profile, entry, item = self.profile(), self.entry, self.source_item()
        title = self.name.text().strip()
        problems = [self.why_not(entry)] if entry else []
        if entry is not None and self.needs_unpacking(entry):
            if entry.item.path not in self._listings:
                problems.append(self.tr("Reading the archive…"))
            elif self.unpack_target is None:
                problems.append(self.tr("This archive cannot be read: install 7-Zip to unpack it."))
            else:
                problems.append(
                    self.tr(
                        "c411 refuses archives: it will be unpacked into {0}, next to it."
                    ).format(self.unpack_target.item.path)
                )
        self.files = []
        if profile is not None and item is not None and title:
            if found := profile.refusals(item, self.ignore(), self.subcategory.currentData()):
                problems += [refusal_text(r) for r in found]
            if profile.dotted_names and (" " in title or not title.isascii()):
                problems.append(
                    self.tr("A release name has dots between words, no spaces and no accents.")
                )
            try:
                self.files = upload_files(item, title, self.ignore(), profile.media_extensions)
            except ValueError as e:
                problems.append(str(e))
        if entry is not None and profile is not None:
            if self._options_state:
                problems.append(self._options_state)
            problems += [refusal_text(r) for r in self.missing_options()]
        self.problems.setText("\n".join(p for p in problems if p))
        judged = (
            profile.warnings(item, self.ignore(), self.subcategory.currentData())
            if profile is not None and item is not None and title
            else []
        )
        self.warnings.setText("\n".join(warning_text(w) for w in judged))
        self._show_files()
        self.model_panel.refresh()
        if profile is not None and self.files:
            if "nfo" not in self._edited:
                self._set_text(self.nfo, profile.nfo(title, self.files))
            if "description" not in self._edited:
                self._set_text(self.description, self._template())
        elif not self.files:
            self._set_text(self.nfo, "")
            self._set_text(self.description, "")
        self._update_actions()

    def _template(self) -> str:
        profile = self.profile()
        if profile is None or not self.files:
            return ""
        return extend_template(
            profile.category,
            self.subcategory.currentData(),
            profile.description(
                self.name.text().strip(),
                self.files,
                self.source.text().strip(),
                self.image_url.text().strip(),
            ),
        )

    def _show_files(self) -> None:
        self.file_table.setSortingEnabled(False)
        self.file_table.setRowCount(0)
        self.file_table.setRowCount(len(self.files))
        for r, f in enumerate(self.files):
            for c, text in enumerate([f.torrent_path, f.local_path, human_size(f.size)]):
                cell = NumberItem(text, f.size) if c == 2 else QTableWidgetItem(text)
                self.file_table.setItem(r, c, cell)
        self.file_table.setSortingEnabled(True)

    def _set_text(self, editor: QPlainTextEdit, text: str) -> None:
        editor.blockSignals(True)
        editor.setPlainText(text)
        editor.blockSignals(False)
        if editor is self.description:
            self._render_description()

    def _description_changed(self) -> None:
        self._edited.add("description")
        self._render_description()

    def _render_description(self) -> None:
        self.preview.setHtml(bbcode_to_html(self.description.toPlainText()))
        profile = self.profile()
        if profile is not None:
            check = assess(
                dict(
                    category=profile.category,
                    subcategory=self.subcategory.currentData(),
                    title=self.name.text(),
                    nfo=self.nfo.toPlainText(),
                    description=self.description.toPlainText(),
                )
            )
            self.presentation_status.setText(
                self.tr("Missing fields: ")
                + ", ".join(row["field"] for row in check["missing_fields"])
                if check["missing_fields"]
                else ""
            )
            self.presentation_status.setToolTip(
                "\n".join(row["message"] for row in check["missing_fields"])
            )
        else:
            self.presentation_status.clear()

    def _reset(self, what: str) -> None:
        self._edited.discard(what)
        self._name_changed()

    # The image -------------------------------------------------------------

    def _image_changed(self) -> None:
        if "description" not in self._edited:
            self._set_text(self.description, self._template())
        else:
            self._sync_description_image()
        self._description_image_url = self.image_url.text().strip()
        self._image_timer.start()

    def _sync_description_image(self) -> None:
        """Update just the presentation image, preserving the user's description."""
        url = self.image_url.text().strip()
        text = self.description.toPlainText()
        images = list(re.finditer(r"\[img\](.*?)\[/img\]", text, re.IGNORECASE | re.DOTALL))
        if url and any(m.group(1).strip() == url for m in images):
            return
        replacement = f"[img]{url or IMAGE_PLACEHOLDER}[/img]"
        for match in images:
            if match.group(1).strip() in {self._description_image_url, IMAGE_PLACEHOLDER, ""}:
                text = text[: match.start()] + replacement + text[match.end() :]
                break
        else:
            if not url:
                return
            text = f"[center]{replacement}[/center]\n\n{text}"
        self._set_text(self.description, text)

    def _load_image(self) -> None:
        url = self.image_url.text().strip()
        self._image_url = url
        if not url.startswith(("https://", "http://")):
            self.image.setPixmap(QPixmap())
            self.image.setText(self.tr("Enter the image URL above") if not url else url)
            return
        self.image.setText(self.tr("Loading the image…"))
        http = self._http or net.client(timeout=20, follow_redirects=True)

        def fetch() -> bytes:
            with http.stream("GET", url) as r:
                r.raise_for_status()
                data = b""
                for chunk in r.iter_bytes():
                    data += chunk
                    if len(data) > IMAGE_MAX_BYTES:
                        raise ValueError("image larger than 10 Mo")
                return data

        run_in_background(
            fetch, lambda data: self._image_loaded(url, data), lambda e: self._image_failed(url, e)
        )

    def _image_loaded(self, url: str, data: bytes) -> None:
        if not isValid(self) or url != self._image_url:
            return
        image = QImage.fromData(data)
        if image.isNull():
            self._image_failed(url, ValueError(self.tr("not an image")))
            return
        self.image.setPixmap(
            QPixmap.fromImage(image).scaled(
                480,
                360,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.preview.document().addResource(
            QTextDocument.ResourceType.ImageResource, QUrl(url), image
        )
        self._render_description()

    def _image_failed(self, url: str, error: Exception) -> None:
        if isValid(self) and url == self._image_url:
            self.image.setPixmap(QPixmap())
            self.image.setText(self.tr("Could not load the image: {0}").format(error_text(error)))

    # Making the Upload -----------------------------------------------------

    def _update_actions(self) -> None:
        entry, profile = self.entry, self.profile()
        archive = entry is not None and self.needs_unpacking(entry)
        self.create_button.setVisible(archive)
        self.create_button.setText(self.tr("Unpack…"))
        self.create_button.setToolTip(
            self.tr("Unpack the archive into a new folder next to it, then prepare its Upload")
            if archive
            else self.tr(
                "Make the torrent, save it with the NFO and description as a Draft on c411, "
                "then seed from your files. You publish it on c411."
            )
        )
        title = self.name.text().strip()
        self.queue_button.setEnabled(
            entry is not None
            and bool(self.files)
            and not archive
            and bool(title)
            and not self.progress.isVisible()
        )
        ready = (
            entry is not None
            and self.why_not(entry) is None
            and bool(self.files)
            and (
                profile is None
                or not profile.dotted_names
                or (" " not in title and title.isascii())
            )
            and bool(self.nfo.toPlainText().strip())
            and bool(self.announce())
            and not self._options_state
            and not self.missing_options()
            and not self.progress.isVisible()
        )
        self.create_button.setEnabled(ready)

    def queue_draft(self) -> None:
        entry, profile = self.entry, self.profile()
        if entry is None or profile is None or not self.files:
            return
        self._sync_description_image()
        form = UploadForm(
            category=profile.category,
            subcategory=self.subcategory.currentData(),
            source=self.source.text(),
            image=self.image_url.text().strip(),
            title=self.name.text().strip(),
            description=self.description.toPlainText(),
            nfo=self.nfo.toPlainText(),
            nfo_origin="original" if "nfo" in self._edited else "generated",
            options=self.chosen_options(),
        ).model_dump()
        record = self._editing_record or {
            "path": str(entry.item.path),
            "form": form,
            "id": "",
            "revision": 0,
        }
        if self._editing_record:
            form = {
                **record["form"],
                **form,
                "assets": self.model_panel.asset_ids or record["form"].get("assets", []),
                "field_provenance": record["form"].get("field_provenance", {}),
            }
        self.queue_button.setEnabled(False)

        def saved(value):
            self._editing_record = None
            self.items.setEnabled(True)
            self.local_drafts.record = value
            self.local_drafts.load()
            self.local_drafts.refresh()
            self.workspaces.setCurrentWidget(self.local_drafts)
            self.local_drafts.status.setText(self.tr("Saved locally. Nothing sent to c411."))
            self._update_actions()

        def failed(error):
            self._update_actions()
            QMessageBox.warning(self, self.tr("Local draft queue"), error_text(error))

        run_in_background(lambda: self._edit_local_draft(record, form), saved, failed)

    def _local_request(
        self, record: dict, form: dict, *, sending=False
    ) -> tuple[UploadRequest, list]:
        values = UploadForm.model_validate(form)
        if not any(str(e.item.path) == record["path"] for e in self.entries):
            raise ValueError("Scan the Library containing this Local Draft first.")
        item = scan_item(Path(record["path"]))
        profile = PROFILES.get(values.category) if values.category is not None else None
        if profile is None or values.subcategory not in {s.id for s in profile.subcategories}:
            raise ValueError("Choose a supported Upload Category and subcategory.")
        title = values.title
        if not title or title in {".", ".."} or any(c in title for c in "/\\\x00"):
            raise ValueError("Use a release name without directory separators.")
        if values.image and not web_url(values.image):
            raise ValueError("Use a direct HTTP(S) image link.")
        ignore = self.ignore()
        profile.inspect(item, ignore)
        files = upload_files(item, title, ignore, profile.media_extensions)
        types = (
            category_options(self.store, self.indexer().category_options, values.subcategory)
            if sending
            else []
        )
        for kind in types:
            selected = values.options.get(kind.id, [])
            if len(selected) > (100 if kind.multiple else 1) or not set(selected).issubset(
                {v.id for v in kind.values}
            ):
                raise ValueError("Invalid category option.")
        description = values.description
        if values.image and values.image not in description:
            description = f"[center][img]{values.image}[/img][/center]\n" + description
        request = UploadRequest(
            item,
            title,
            files,
            values.nfo,
            description,
            profile.category,
            values.subcategory,
            options_body(types, values.options),
            profile.draft_fields(item, ignore, files),
        )
        refusals = profile.refusals(item, ignore, values.subcategory) + missing_options(
            types, values.options
        )
        return request, refusals

    def _edit_local_draft(self, record: dict, form: dict) -> dict:
        form = edited_form(record.get("form", {}), form)
        request, refusals = self._local_request(record, form)
        profile = PROFILES[request.category]
        if self.model_panel.item and self.model_panel.item.path == request.item.path:
            form = {**form, "assets": self.model_panel.asset_ids or form.get("assets", [])}
        return save_local(
            self.store,
            request,
            {**form, "description": request.description},
            identifier=record["id"],
            revision=record["revision"],
            review={
                "refusals": [f"{r.problem.value}: {r.detail}" for r in refusals],
                "warnings": [
                    f"{w.judgement.value}: {w.detail}"
                    for w in profile.warnings(request.item, self.ignore(), request.subcategory)
                ],
            },
        )

    def _send_local_draft(self, record: dict) -> PreparedUpload:
        # Use the persisted revision, never an editor's unsaved text or agent-supplied form.
        current = self.store.local_draft(record["id"])
        request, refusals = self._local_request(current, current["form"], sending=True)
        request = replace(request, extra=current.get("extra", request.extra))
        if (
            refusals
            or not web_url(current["form"].get("image", ""))
            or not request.description.strip()
            or not request.nfo.strip()
        ):
            raise ValueError("Resolve the Upload refusals and add a hosted image before sending.")
        announce, indexer = self.announce(), self.indexer()
        if not announce:
            raise ValueError("Set your Announce URL before sending to c411.")
        return send_local(
            self.store,
            record["id"],
            record["revision"],
            request,
            lambda: create_upload(request, announce, self.folder, indexer.save_draft, self.store),
        )

    def _local_draft_sent(self, prepared: PreparedUpload) -> None:
        self.local_drafts.refresh()
        entry = next((e for e in self.entries if e.item.path == prepared.saved.item_path), None)
        if entry is not None:
            self._start_progress()
            self._drafted(entry, prepared)

    def create_draft(self) -> None:
        entry, profile = self.entry, self.profile()
        if entry is None or profile is None or not self.files:
            return
        if self.needs_unpacking(entry):
            self._unpack(entry)
            return
        # Manual preparation always enters local review; only saved revisions can be sent.
        self.queue_draft()

    def _start_progress(self) -> None:
        self._stop.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self.stop_button.show()
        self._update_actions()

    def _progressed(self, value: tuple[int, int]) -> None:
        done, total = value
        self.progress.setValue(int(100 * done / total) if total else 100)

    # Archives --------------------------------------------------------------

    def _unpack(self, entry: LibraryEntry) -> None:
        target = self.unpack_target
        if target is None:
            return
        folder = target.item.path
        if folder.exists():
            QMessageBox.information(
                self,
                self.tr("Unpack"),
                self.tr(
                    "{0} already exists. If it holds this archive unpacked, scan the Library "
                    "and pick that folder."
                ).format(folder),
            )
            return
        free = shutil.disk_usage(target.archive.parent).free
        if free < target.size:
            QMessageBox.warning(
                self,
                self.tr("Unpack"),
                self.tr("Unpacking needs {0}, but only {1} is free on that disk.").format(
                    human_size(target.size), human_size(free)
                ),
            )
            return
        answer = QMessageBox.question(
            self,
            self.tr("Unpack"),
            self.tr(
                "c411 refuses archives. Unpack {0} into the new folder\n{1}?\n\n"
                "It writes {2} in {3} files; {4} is free on that disk. Nothing is "
                "overwritten. The Upload is then made from the unpacked files; once it seeds, "
                "you are offered to move the archive to the trash."
            ).format(
                target.archive.name,
                folder,
                human_size(target.size),
                len(target.item.files),
                human_size(free),
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_progress()
        self.stop_button.hide()  # unpacking runs to the end, or undoes itself on failure
        store = self.store

        def work(report: Callable[[object], None]) -> Path:
            unpack(target, lambda done, total: report((done, total)))
            store.remember_unpacked(folder, target.archive)
            return folder

        run_with_progress(
            work, self._progressed, lambda f: self._unpacked(f, entry.item.path), self._failed
        )

    def _unpacked(self, folder: Path, archive: Path) -> None:
        self._done()
        self._to_select = (folder, archive)
        self.unpacked.emit(folder)

    # Seeding ---------------------------------------------------------------

    def _drafted(self, entry: LibraryEntry, prepared: PreparedUpload) -> None:
        self.progress.setRange(0, 0)
        self.stop_button.hide()
        self.refresh_drafts()
        self._seed(entry, prepared)

    def _seed(self, entry: LibraryEntry, prepared: PreparedUpload) -> None:
        qbit, store = self.qbit(), self.store
        run_in_background(
            lambda: seed_upload(
                qbit,
                store,
                entry.item,
                prepared,
                approve_disk_renames=self.approve_disk_renames,
            ),
            lambda _hash: self._seeding(entry, prepared),
            lambda e: self._seed_failed(entry, prepared, e),
        )

    def _seeding(self, entry: LibraryEntry, prepared: PreparedUpload) -> None:
        if not isValid(self):
            return
        self._done()
        self.upload_started.emit(entry.item.path)
        QMessageBox.information(
            self,
            self.tr("Draft saved"),
            self.tr(
                "{0} is saved as a Draft on c411 and is being verified in your torrent "
                "client. Once it seeds, open c411's upload page, load the Draft, check it and "
                "publish it."
            ).format(prepared.saved.title),
        )

    def _seed_failed(self, entry: LibraryEntry, prepared: PreparedUpload, error: Exception) -> None:
        self._done()
        if offer_whole_names(self, error, then=lambda: self._seed(entry, prepared)):
            return
        QMessageBox.warning(
            self,
            self.tr("Not seeding"),
            self.tr(
                "The Draft is saved on c411, but its torrent could not be added to your "
                "torrent client: {0}\n\nc411 refuses an upload whose uploader is not "
                "seeding: do not publish it before it seeds."
            ).format(error_text(error)),
        )

    def _failed(self, error: Exception) -> None:
        self._done()
        if isinstance(error, UploadStopped):
            return
        QMessageBox.warning(self, self.tr("Upload failed"), error_text(error))

    def _done(self) -> None:
        if not isValid(self):
            return
        self.progress.hide()
        self.stop_button.hide()
        self._update_actions()

    # Drafts ----------------------------------------------------------------

    def refresh_drafts(self) -> None:
        self.drafts_status.setText(self.tr("Reading your Drafts…"))
        run_in_background(lambda: self.indexer().drafts(), self._show_drafts, self._drafts_failed)

    def _show_drafts(self, drafts: list[dict[str, object]]) -> None:
        self.drafts.setSortingEnabled(False)
        self.drafts.setRowCount(0)
        self.drafts.setRowCount(len(drafts))
        for r, d in enumerate(drafts):
            category = d.get("subcategory") or d.get("category") or ""
            if isinstance(category, dict):
                category = category.get("name", "")
            modified = str(d.get("updatedAt") or "")[:16].replace("T", " ")
            for c, text in enumerate([str(d.get("name") or ""), str(category), modified]):
                self.drafts.setItem(r, c, QTableWidgetItem(text))
        self.drafts.setSortingEnabled(True)
        self.drafts_status.setText(self.tr("{0}/15 Drafts on c411").format(len(drafts)))

    def _drafts_failed(self, error: Exception) -> None:
        self.drafts_status.setText(error_text(error))
