from __future__ import annotations

import errno
import logging
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QFile, QItemSelection, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker import i18n, net
from torrentlinker.agent.desktop import agent_settings_change
from torrentlinker.catalogue import (
    STARTUP_PAGES,
    CrawlProgress,
    Progress,
    age,
    candidate,
    crawl_categories,
    plan_categories,
    startup_categories,
)
from torrentlinker.catalogue_sync import SNAPSHOT_NAME, sync_catalogue
from torrentlinker.category_tags import sync_category_tags
from torrentlinker.clients import connect
from torrentlinker.config import Settings
from torrentlinker.credentials import get_secret
from torrentlinker.domain import ContentKind, ItemState, LibraryFolder, TorrentClient
from torrentlinker.downloads import IndexerCategory
from torrentlinker.ebooks import UNLOCK_COUNT, book_categories, book_roots, seeded_ebooks
from torrentlinker.gui.batch_runner import BatchRunner
from torrentlinker.gui.catalogue_runner import CatalogueRunner
from torrentlinker.gui.controls import set_role
from torrentlinker.gui.documentation import DocumentationTab
from torrentlinker.gui.ebook_reader import ReadingRoom
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.library_folder_dialog import LibraryFolderDialog
from torrentlinker.gui.library_model import LibraryFilter, LibraryModel, human_size, state_label
from torrentlinker.gui.library_workspace import LibraryWorkspace
from torrentlinker.gui.reseed_consent import ReseedConsent
from torrentlinker.gui.reseed_dialog import ReseedDialog
from torrentlinker.gui.review_panel import ReviewPanel, Searcher
from torrentlinker.gui.search_view import SearchTab
from torrentlinker.gui.send_runner import SendRunner
from torrentlinker.gui.settings_dialog import (
    ANNOUNCE_URL,
    DELUGE_PASSWORD,
    INDEXER_API_KEY,
    PROXY_PASSWORD,
    QBIT_API_KEY,
    QBIT_PASSWORD,
    TMDB_API_KEY,
    TRANSMISSION_PASSWORD,
    UTORRENT_PASSWORD,
    SettingsDialog,
    choose_directory,
    extra_indexer_keys,
)
from torrentlinker.gui.tables import EmptyState, style_table
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.theme import set_theme
from torrentlinker.gui.torrents_view import TorrentsTab
from torrentlinker.gui.update_notice import UpdateNotice
from torrentlinker.gui.upload_view import UploadTab
from torrentlinker.gui.zen_view import ZenBand, ZenTab
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import (
    LibraryEntry,
    auto_searchable,
    build_library,
    indexer_contents,
)
from torrentlinker.matching import MatchRules
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.plan import (
    Plan,
    PlanCandidate,
    PlanOptions,
    ReseedSource,
    catalogue_candidates,
    disk_of,
    disk_space,
    explain_inputs,
    make_plan,
    on_disk,
    reseed_candidates,
    restore_plan,
    saved_items,
)
from torrentlinker.plan_diagnostics import PlanIssue
from torrentlinker.profile import UserProfile
from torrentlinker.qbit import AlreadyInClient, ClientApi
from torrentlinker.queries import build_queries, find_ids
from torrentlinker.reseed import (
    Outcome,
    check_verifications,
    pending_verifications,
    start_reseed,
)
from torrentlinker.review import (
    CheckedCandidate,
    candidate_key,
    check_candidate,
    check_candidates,
    match_zen,
    remember_candidates,
    remembered_candidates,
    restore_checked,
    search_candidates,
)
from torrentlinker.scan import scan
from torrentlinker.seeding import Seeding, indexer_torrents, observe_swarm, seeding
from torrentlinker.send import SendProgress, SendReport, send_plan
from torrentlinker.speedtest import measure_download_speed
from torrentlinker.store import CatalogueRow, Store
from torrentlinker.tmdb import Tmdb
from torrentlinker.updates import check_for_update, installed_version

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, settings_path: Path, store: Store) -> None:
        super().__init__()
        settings.ensure_profiles()
        store = store.for_client(settings.active_client_id)
        self.settings = settings
        self.settings_path = settings_path
        from torrentlinker.companion import CompanionReceiver
        from torrentlinker.profile_workspace import ProfileWorkspace

        self.account_workspace = ProfileWorkspace(settings_path.parent)
        self.companion_receiver: CompanionReceiver | None = None
        self._profile_refreshing = False
        self._receiver_retry_at = 0.0
        self.agent_runtime: Any = None
        self.agent_settings_timer = QTimer(self)
        self.agent_settings_timer.setInterval(1000)
        self.agent_settings_timer.timeout.connect(self._sync_agent_settings)
        self.agent_settings_timer.start()
        self.store = store
        from torrentlinker.client_profiles import Connections

        self._connections = Connections(get_secret)
        self._indexer: Indexer | None = None
        # Kept connections, with what they were made for, the proxy in use included.
        self._qbit: tuple[tuple[str, ...], ClientApi, tuple[str | None, str | None]] | None = None
        self.apply_proxy()
        self._indexer_proxy = net.current()  # what the Indexer, once made, goes through
        self.running_version = installed_version()
        self.setWindowTitle(f"TorrentLinker {self.running_version}")
        available = self.screen().availableGeometry()
        self.resize(min(1280, available.width() - 40), min(800, available.height() - 60))

        toolbar = QToolBar(self.tr("Library"), self)
        toolbar.setMovable(False)
        self.add_folder_action = QAction(self.tr("Add folder…"), self)
        self.add_folder_action.triggered.connect(self.add_library_folder)
        self.scan_action = QAction(self.tr("Scan"), self)
        self.scan_action.triggered.connect(lambda: self.scan())
        self.rescan_action = QAction(self.tr("Rescan everything"), self)
        self.rescan_action.setToolTip(
            self.tr("Walk every file again, ignoring the scan cache (slower)")
        )
        self.rescan_action.triggered.connect(lambda: self.scan(refresh=True))
        settings_action = QAction(self.tr("Settings"), self)
        settings_action.triggered.connect(self.open_settings)
        self.batch_selected_action = QAction(self.tr("Search selected"), self)
        self.batch_selected_action.triggered.connect(lambda: self.start_batch(selected_only=True))
        self.batch_all_action = QAction(self.tr("Search all Orphans"), self)
        self.batch_all_action.triggered.connect(lambda: self.start_batch(selected_only=False))
        self.check_all_action = QAction(self.tr("Check all Candidates"), self)
        self.check_all_action.setToolTip(
            self.tr("Check every untested Candidate across the Library, including filtered items")
        )
        self.check_all_action.triggered.connect(lambda: self.start_library_batch("check"))
        self.reseed_all_action = QAction(self.tr("Reseed all Full Matches"), self)
        self.reseed_all_action.setToolTip(
            self.tr(
                "Reseed confirmed Full Matches across the Library; "
                "archives need individual unpacking"
            )
        )
        self.reseed_all_action.triggered.connect(lambda: self.start_library_batch("reseed"))
        self.cancel_action = QAction(self.tr("Cancel search"), self)
        self.cancel_action.triggered.connect(self.cancel_batch)
        self.cancel_action.setEnabled(False)
        scan_button = QToolButton()
        scan_button.setDefaultAction(self.scan_action)
        scan_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        scan_menu = QMenu(scan_button)
        scan_menu.addAction(self.rescan_action)
        scan_button.setMenu(scan_menu)
        toolbar.addWidget(scan_button)
        toolbar.addAction(self.add_folder_action)
        toolbar.addSeparator()
        toolbar.addAction(self.batch_selected_action)
        toolbar.addAction(self.batch_all_action)
        toolbar.addAction(self.cancel_action)
        match_toolbar = QToolBar(self.tr("Matches"), self)
        match_toolbar.setMovable(False)
        match_toolbar.addAction(self.check_all_action)
        match_toolbar.addAction(self.reseed_all_action)
        manage_action = QAction(self.tr("Open in Torrents"), self)
        manage_action.triggered.connect(lambda: self.open_torrents())
        match_toolbar.addAction(manage_action)

        self.batch: BatchRunner | None = None
        self._batch_mode = "search"
        self._batch_errors: list[str] = []
        self._batch_reseeded = 0
        self.batch_text = ""
        self.countdown = QTimer(self)
        self.countdown.setInterval(250)
        self.countdown.timeout.connect(self._show_batch_progress)

        self.library_model = LibraryModel()
        self.library_proxy = LibraryFilter()
        self.library_proxy.setSourceModel(self.library_model)
        self.library_view = QTableView()
        self.library_view.setModel(self.library_proxy)
        style_table(self.library_view)
        self.library_view.setAccessibleName(self.tr("Library"))
        self.library_empty = EmptyState(
            self.library_view,
            self.tr("No Local Items to show. Adjust the filters or scan your Library Folders."),
        )
        self.library_view.setSortingEnabled(True)
        self.library_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.library_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.library_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.library_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, 160)
        self.library_view.selectionModel().selectionChanged.connect(self._selection_changed)

        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText(self.tr("Filter Local Items…"))
        self.library_search.setAccessibleName(self.tr("Filter Local Items"))
        self.library_search.setClearButtonEnabled(True)
        self.library_search.textChanged.connect(self._apply_filters)
        filters = QHBoxLayout()
        self.state_filter = QComboBox()
        self.state_filter.addItem(self.tr("All states"), None)
        for state in ItemState:
            self.state_filter.addItem(state_label(state), state)
        self.folder_filter = QComboBox()
        self.state_filter.currentIndexChanged.connect(self._apply_filters)
        self.folder_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.library_search, 2)
        filters.addWidget(self.state_filter)
        filters.addWidget(self.folder_filter, 1)
        library_pane = QWidget()
        library_layout = QVBoxLayout(library_pane)
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.addLayout(filters)
        library_layout.addWidget(self.library_view)
        self._fill_folder_filter()

        self.reseed_consent = ReseedConsent(self)
        self.review = ReviewPanel(
            store,
            self.indexer,
            self.qbit,
            self.match_rules,
            self.searcher,
            self.default_query,
            approve_disk_renames=self.reseed_consent.approve,
        )
        self.review.compatible_categories = lambda kind: self.settings.categories(kind)
        self.review.repair_supported = lambda: self.settings.client is TorrentClient.QBITTORRENT
        self.review.reseed_started.connect(self._reseed_started)
        self.review.unpacked.connect(lambda _folder: self.scan())  # show the new folder
        self.review.candidates_checked.connect(self._show_match_zen)
        self.zen_tab = ZenTab(self.seeding_loader, lambda: self.settings.zen, settings.uploads)
        self.zen_tab.profile_view.refresh_requested.connect(self.refresh_profile)
        self.companion_panel = None  # only while Settings is open
        self.profile_timer = QTimer(self)
        self.profile_timer.setInterval(3000)
        self.profile_timer.timeout.connect(self._poll_account_profile)
        self.profile_timer.start()
        self.show_account_profile()
        self.zen_tab.comparison.uploads_changed.connect(self._uploads_changed)
        self.zen_tab.defer_while_hidden(
            lambda: self.isVisible() and not self.zen_tab.seeding_view.table.isVisible()
        )
        self.tabs = QTabWidget()
        self.tabs.addTab(self.zen_tab, self.tr("Zen"))
        self.library_workspace = LibraryWorkspace(self, library_pane, toolbar, match_toolbar)
        self.tabs.addTab(self.library_workspace, self.tr("Library"))
        self.upload_tab = UploadTab(
            store,
            self.indexer,
            self.qbit,
            lambda: self.settings.matching.ignore,
            lambda: get_secret(ANNOUNCE_URL),
            store.torrent_dir.parent / "uploads",
            approve_disk_renames=self.reseed_consent.approve,
        )
        self.review.candidates_checked.connect(self.upload_tab.remember)
        self.review.upload_blocker = self.upload_tab.why_not
        self.review.upload_requested.connect(self._open_upload)
        self.upload_tab.upload_started.connect(self._reseed_started)
        self.upload_tab.unpacked.connect(lambda _folder: self.scan())  # show the new folder
        self.tabs.addTab(self.upload_tab, self.tr("Upload"))
        self.search_tab = SearchTab(store, settings, self.indexer, self.qbit)
        self.tabs.addTab(self.search_tab, self.tr("Search"))
        from torrentlinker.gui.feeds import FeedsTab

        self.feeds_tab = FeedsTab(lambda: self.assistant_service().agent.feed_control)
        self.tabs.addTab(self.feeds_tab, self.tr("RSS"))
        self.search_tab.subscribe_requested.connect(lambda query: self.feeds_tab.edit(query=query))
        self.torrents_tab = TorrentsTab(self.qbit)
        from torrentlinker.gui.client_overview import ClientOverview

        self.client_overview = ClientOverview(settings, store)
        torrents_page = QWidget()
        torrents_layout = QVBoxLayout(torrents_page)
        torrents_layout.setContentsMargins(0, 0, 0, 0)
        self.all_clients = QCheckBox(self.tr("All clients"))
        torrents_layout.addWidget(self.all_clients)
        self.torrent_stack = QStackedWidget()
        self.torrent_stack.addWidget(self.torrents_tab)
        self.torrent_stack.addWidget(self.client_overview)
        torrents_layout.addWidget(self.torrent_stack)
        self.all_clients.toggled.connect(self._show_all_clients)
        self.tabs.addTab(torrents_page, self.tr("Torrents"))
        from torrentlinker.gui.assistant import AssistantTab

        self.assistant_tab = AssistantTab(self.assistant_service)
        self.assistant_tab.connectionsRequested.connect(self.open_assistant_connections)
        self.tabs.addTab(self.assistant_tab, self.tr("Assistant"))
        from torrentlinker.gui.media import MediaTab

        self.media_tab = MediaTab(
            self.assistant_service,
            lambda: self.settings.active_client_id,
            self.add_library_folder,
        )
        self.media_tab.set_media_layout(settings.media_layout)
        self.media_tab.refresh_on_first_open = True
        self.media_tab.layout_changed.connect(self._save_media_layout)
        self.media_tab.center_mode_requested.connect(self.set_media_center)
        self.media_tab.connections_requested.connect(self.open_assistant_connections)
        self.tabs.addTab(self.media_tab, self.tr("Media"))
        self.search_tab.manage_requested.connect(self.open_torrents)
        self.band = ZenBand()
        self.band.refresh_requested.connect(self.refresh_profile)
        self.zen_tab.seeding_view.updated.connect(self.band.set_seeding)
        self.zen_tab.seeding_view.updated.connect(self.search_tab.set_seeding)
        self.zen_tab.seeding_view.updated.connect(self.torrents_tab.set_seeding)
        self.zen_tab.seeding_view.updated.connect(self.library_model.set_seeding)
        self.zen_tab.seeding_view.unavailable.connect(lambda: self.library_model.set_seeding(None))
        self.zen_tab.seeding_view.updated.connect(self._update_reading_room)
        self.zen_tab.seeding_view.unavailable.connect(self._lock_reading_room)
        self.reading_room: ReadingRoom | None = None
        self._reader_view: Seeding | None = None
        self._reader_unlocked = False
        self.tabs.tabBar().hide()
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setAccessibleName(self.tr("Workspaces"))
        self.navigation.addItems(
            [
                self.tr("Zen"),
                self.tr("Library"),
                self.tr("Upload"),
                self.tr("Search"),
                self.tr("RSS"),
                self.tr("Torrents"),
                self.tr("Assistant"),
                self.tr("Media"),
            ]
        )
        self.navigation.setCurrentRow(0)
        self.navigation.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.navigation.itemClicked.connect(
            lambda item: self.tabs.setCurrentIndex(self.navigation.row(item))
        )
        self.tabs.currentChanged.connect(self._sync_navigation)
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(172)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 24, 16, 16)
        brand = QLabel("TorrentLinker")
        brand.setProperty("role", "brand")
        side.addWidget(brand)
        side.addSpacing(24)
        side.addWidget(self.navigation, 1)
        self.reader_button = QPushButton(self.tr("Reading room"))
        set_role(self.reader_button, "quiet")
        self.reader_button.setCheckable(True)
        self.reader_button.setObjectName("readingRoomButton")
        self.reader_button.hide()
        self.reader_button.clicked.connect(self._open_reading_room)
        side.addWidget(self.reader_button)
        self.documentation_tab: DocumentationTab | None = None
        self.documentation_button = QPushButton(self.tr("Documentation"))
        set_role(self.documentation_button, "quiet")
        self.documentation_button.setCheckable(True)
        self.documentation_button.clicked.connect(self._open_documentation)
        side.addWidget(self.documentation_button)
        settings_button = QPushButton(self.tr("Settings"))
        set_role(settings_button, "quiet")
        settings_button.clicked.connect(self.open_settings)
        side.addWidget(settings_button)
        central = QWidget()
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(sidebar)
        content = QWidget()
        central_layout = QVBoxLayout(content)
        self.content_layout = central_layout
        central_layout.setContentsMargins(24, 20, 24, 12)
        central_layout.setSpacing(16)
        self.app_header = QWidget()
        header_layout = QVBoxLayout(self.app_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(16)
        central_layout.addWidget(self.app_header)
        self.page_title = QLabel()
        self.page_title.setProperty("role", "heading")
        self.page_description = QLabel()
        self.page_description.setProperty("role", "muted")
        self.page_description.setWordWrap(True)
        self.client_selector = QComboBox()
        self.client_selector.setAccessibleName(self.tr("Target client"))
        for profile in settings.client_profiles:
            if profile.enabled:
                self.client_selector.addItem(profile.name, profile.id)
        self.client_selector.setCurrentIndex(
            self.client_selector.findData(settings.active_client_id)
        )
        self.client_selector.currentIndexChanged.connect(self._select_client)
        title_row = QHBoxLayout()
        title_row.addWidget(self.page_title, 1)
        title_row.addWidget(QLabel(self.tr("Target client")))
        title_row.addWidget(self.client_selector)
        clients_button = QPushButton(self.tr("Clients…"))
        clients_button.clicked.connect(self.open_client_profiles)
        title_row.addWidget(clients_button)
        header_layout.addLayout(title_row)
        header_layout.addWidget(self.page_description)
        self.update_notice = UpdateNotice()
        header_layout.addWidget(self.update_notice)
        self.setup_notice = QLabel(
            self.tr('Add your Indexer API key to get started. <a href="settings">Open settings</a>')
        )
        self.setup_notice.setWordWrap(True)
        self.setup_notice.linkActivated.connect(lambda _link: self.open_settings())
        self.setup_notice.hide()
        header_layout.addWidget(self.setup_notice)
        header_layout.addWidget(self.band)
        # A wide workspace must not impose its minimum size on the desktop window.
        # Keep navigation and the status band visible; scroll only the workspace.
        self.workspace_scroll = QScrollArea()
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.workspace_scroll.setWidget(self.tabs)
        central_layout.addWidget(self.workspace_scroll, 1)
        shell.addWidget(content, 1)
        self.tabs.currentChanged.connect(self._workspace_changed)
        self._workspace_changed(0)
        self.setCentralWidget(central)
        self.media_center_active = False
        settings_action.setShortcut("Ctrl+,")
        self.addAction(settings_action)
        for index in range(self.tabs.count()):
            action = QAction(self.tabs.tabText(index), self)
            action.setShortcut(f"Ctrl+{index + 1}")
            action.triggered.connect(lambda checked=False, i=index: self.tabs.setCurrentIndex(i))
            self.addAction(action)
        find = QAction(self.tr("Filter Local Items"), self)
        find.setShortcut("Ctrl+F")
        find.triggered.connect(self._focus_search)
        self.addAction(find)
        self.statusBar().showMessage(self.tr("Ready"))

        self._checking = False
        self.catalogue_runner: CatalogueRunner | None = None
        self.send_runner: SendRunner | None = None
        self._crawl_position = [0, 0]  # category being crawled, of how many (worker writes)
        self._plan_destinations = {settings.active_client_id: 0}
        self.zen_tab.plan_view.client_names = {p.id: p.name for p in settings.client_profiles}
        self.zen_tab.plan_view.client_names[""] = settings.profile().name
        self.plan_targets_button = QPushButton(self.tr("Plan destinations…"))
        self.plan_targets_button.clicked.connect(self._choose_plan_clients)
        plan_layout = self.zen_tab.plan_view.layout()
        assert isinstance(plan_layout, QVBoxLayout)
        plan_layout.insertWidget(0, self.plan_targets_button)
        self.zen_tab.plan_view.make_requested.connect(self.make_plan)
        self.zen_tab.plan_view.categories_changed.connect(self._plan_categories_changed)
        self.zen_tab.plan_view.set_options(self.settings.plan_options)
        self.zen_tab.plan_view.options_changed.connect(self._plan_options_changed)
        self.zen_tab.plan_view.stop_fetch_requested.connect(self._stop_plan_fetch)
        self.offer_plan_categories()
        self.zen_tab.plan_view.send_requested.connect(self.confirm_send)
        self.zen_tab.plan_view.stop_send_requested.connect(self.stop_sending)
        self.zen_tab.plan_view.speed_test_requested.connect(self.test_speed)
        self.zen_tab.plan_view.set_speed(settings.download_speed, settings.download_speed_tested)
        self.zen_tab.plan_view.keys = 1 + len(extra_indexer_keys())
        self._after_catalogue: Callable[[], None] | None = None
        self._after_catalogue_always: Callable[[], None] | None = None
        self._pending_plan: Callable[[], None] | None = None
        self._last_crawl_progress: CrawlProgress | None = None
        self.crawl_ticker = QTimer(self)
        self.crawl_ticker.setInterval(500)
        self.crawl_ticker.timeout.connect(self._show_crawl_progress)
        self._planning = False
        self.zen_tab.catalogue.start_requested.connect(self.crawl_catalogue)
        self.zen_tab.catalogue.pause_requested.connect(self.pause_catalogue)
        self._show_catalogue_age()
        self.verify_timer = QTimer(self)
        self.verify_timer.setInterval(3000)
        self.verify_timer.timeout.connect(self.check_verifications)
        self.seeding_timer = QTimer(self)
        self.seeding_timer.setInterval(30_000)
        self.seeding_timer.timeout.connect(lambda: self.zen_tab.seeding_view.refresh(quiet=True))
        self._startup_complete = False
        self.show_saved_plan(interrupted=bool((saved := store.saved_plan()) and saved.sending))

    def assistant_service(self):
        from PySide6.QtWidgets import QApplication

        from torrentlinker.agent.desktop import DesktopServer

        if self.agent_runtime is None:
            self.agent_runtime = DesktopServer(
                self.settings, self.settings_path, self.store, workspace=self.account_workspace
            )
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.agent_runtime.close)
        try:
            self.agent_runtime.start()
        except OSError as error:
            if error.errno == errno.EADDRINUSE or getattr(error, "winerror", None) == 10048:
                raise ValueError(
                    self.tr(
                        "The Assistant cannot start because local port {0} is already in use. "
                        "Close the other TorrentLinker instance or application using this port, "
                        "then reopen the Assistant tab to retry."
                    ).format(self.agent_runtime.port)
                ) from error
            raise
        return self.agent_runtime.app.state.assistant

    def open_agent_access(self) -> None:
        self.open_settings(agents=True)

    def agent_access_widget(self, parent=None):
        try:
            from PySide6.QtWidgets import QApplication

            from torrentlinker.agent.desktop import DesktopServer
            from torrentlinker.gui.agent_access import AgentAccess

            if self.agent_runtime is None:
                self.agent_runtime = DesktopServer(
                    self.settings, self.settings_path, self.store, workspace=self.account_workspace
                )
                app = QApplication.instance()
                if app is not None:
                    app.aboutToQuit.connect(self.agent_runtime.close)
            self.agent_runtime.start()
            stack = getattr(self, "_settings_stack", None)
            if stack is not None and not self.agent_runtime.settings_edit_depth:
                stack.enter_context(self.agent_runtime.editing_settings())
            return AgentAccess(self.agent_runtime.service, self.agent_runtime.url, parent)
        except Exception as error:
            from torrentlinker.torrent_management import safe_error

            port = self.agent_runtime.port if self.agent_runtime else 8790
            detail = (
                self.agent_runtime.setup.secrets.redact(str(error))
                if self.agent_runtime
                else safe_error(error)
            ) or type(error).__name__
            log.error("Agent access startup failed (%s): %s", type(error).__name__, detail)
            if self.agent_runtime is not None and self.agent_runtime.app is None:
                self.agent_runtime.close()
                self.agent_runtime = None
            if isinstance(error, OSError) and (
                error.errno == errno.EADDRINUSE or getattr(error, "winerror", None) == 10048
            ):
                message = self.tr(
                    "Cannot start the local MCP server on port {0}. Check whether another "
                    "TorrentLinker instance or another application is using it."
                ).format(port)
            else:
                message = self.tr("Cannot open Agent access. See torrentlinker.log for details.")
            QMessageBox.warning(
                self,
                self.tr("Agent access"),
                message + "\n" + detail,
            )

    def start_saved_agent_access(self) -> None:
        if not (self.settings_path.parent / "agents.sqlite").exists():
            return
        from torrentlinker.agent.access import Access

        access = Access(self.settings_path.parent)
        enabled = access.enabled or (self.settings_path.parent / "assistant.sqlite").exists()
        access.db.close()
        if enabled:
            try:
                # RSS or an early visit to Assistant may already own the listener.
                # Reuse it instead of losing its reference and binding the same port.
                self.assistant_service()
            except Exception:
                if self.agent_runtime is not None:
                    self.agent_runtime.close()
                    self.agent_runtime = None
                self.statusBar().showMessage(
                    self.tr("Agent access could not start. Open Settings → Agent access to retry.")
                )

    def _has_indexer_key(self) -> bool:
        return bool(self.settings.indexer.url.strip() and get_secret(INDEXER_API_KEY).strip())

    def _await_setup(self) -> None:
        self.setup_notice.show()
        self.tabs.setEnabled(True)
        for index in range(self.tabs.count()):
            self.tabs.setTabEnabled(index, self.tabs.widget(index) is self.media_tab)
        self.band.setEnabled(False)
        self.seeding_timer.stop()
        self._startup_complete = False
        self.statusBar().showMessage(self.tr("Finish connection setup in Settings to get started."))

    def startup(self) -> None:
        """Start only after configuration; constructing a window never contacts services."""
        if self._startup_complete:
            return
        if not self.settings_path.exists() or not self._has_indexer_key():
            self._await_setup()
            QMessageBox.information(
                self,
                self.tr("Welcome to TorrentLinker"),
                self.tr(
                    "Let's set up your connection first. In Settings → Connections, enter "
                    "your Indexer API key and configure your torrent client, then save. "
                    "TorrentLinker will load your data when setup is complete."
                ),
            )
            self.open_settings()
            return
        self._start_services()

    def _start_services(self) -> None:
        if self._startup_complete or not self._has_indexer_key():
            return
        self._startup_complete = True
        if (self.settings_path.parent / "feeds.sqlite").exists():
            QTimer.singleShot(0, self.assistant_service)
        self.setup_notice.hide()
        self.tabs.setEnabled(True)
        for index in range(self.tabs.count()):
            self.tabs.setTabEnabled(index, True)
        self.band.setEnabled(True)
        self.statusBar().showMessage(self.tr("Ready"))
        self.seeding_timer.start()
        QTimer.singleShot(0, self.check_verifications)
        QTimer.singleShot(0, self.zen_tab.seeding_view.refresh)
        QTimer.singleShot(0, self.refresh_profile)
        QTimer.singleShot(0, self.upload_tab.refresh_drafts)
        QTimer.singleShot(0, lambda: self.refresh_categories(then=self.update_catalogue))
        if self.settings.library_folders:
            QTimer.singleShot(0, self.scan)

    def check_for_updates(self) -> None:
        cache = self.settings_path.parent / "release-check.json"
        run_in_background(
            lambda: check_for_update(cache, current=self.running_version),
            self.update_notice.show_release,
            lambda error: log.debug("release check unavailable: %s", error),
        )

    def _show_all_clients(self, checked: bool) -> None:
        self.torrent_stack.setCurrentIndex(int(checked))
        if checked:
            self.client_overview.refresh()

    def open_torrents(self, hash: str = "") -> None:
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.feeds_tab) + 1)
        self.torrents_tab.focus_torrent(hash)

    def _workspace_changed(self, index: int) -> None:
        if (
            getattr(self, "media_center_active", False)
            and self.tabs.widget(index) is not self.media_tab
        ):
            self.set_media_center(False)
        self.workspace_scroll.horizontalScrollBar().setValue(0)
        self.workspace_scroll.verticalScrollBar().setValue(0)
        self.page_title.setText(self.tabs.tabText(index))
        descriptions = [
            self.tr("Track your earnings and plan what to seed next."),
            self.tr("Find Orphans, compare Candidates and Reseed your files."),
            self.tr("Prepare an Upload, then review and publish its Draft on c411."),
            self.tr("Search torrents and queue the ones you want to download."),
            self.tr("Review RSS releases and manage subscription rules."),
            self.tr("Manage downloads and seeds in your Torrent Client."),
            self.tr("Discuss tasks, review proposals and schedule automations."),
            self.tr("Play videos and music from your Library Folders."),
            self.tr("Ten thousand books kept alive. Take a moment to read one."),
        ]
        if 0 <= index < len(descriptions):
            self.page_description.setText(descriptions[index])
        self.band.setVisible(index < self.navigation.count() and index not in {5, 6, 7})
        self.page_title.setVisible(index < self.navigation.count())
        self.page_description.setVisible(
            index < self.navigation.count() and self.tabs.currentWidget() is not self.media_tab
        )
        policy = (
            QSizePolicy.Policy.Ignored
            if index >= self.navigation.count() or index in {5, 6, 7}
            else QSizePolicy.Policy.Preferred
        )
        self.tabs.setSizePolicy(policy, policy)
        if self.tabs.currentWidget() is self.assistant_tab:
            self.assistant_tab.activate()
        if self.tabs.currentWidget() is self.media_tab:
            self.media_tab.activate()
        if self.reading_room is not None and self.tabs.currentWidget() is self.reading_room:
            self.reading_room.activate()

    def _sync_navigation(self, index: int) -> None:
        with QSignalBlocker(self.navigation):
            if index < self.navigation.count():
                self.navigation.setCurrentRow(index)
            else:
                # Keep the current row so Qt doesn't select row zero on focus
                # and unexpectedly navigate away from the reading room.
                self.navigation.clearSelection()
        current = self.tabs.currentWidget()
        self.reader_button.setChecked(
            self.reading_room is not None and current is self.reading_room
        )
        self.documentation_button.setChecked(
            self.documentation_tab is not None and current is self.documentation_tab
        )

    def _update_reading_room(self, view: Seeding) -> None:
        if seeded_ebooks(view) < UNLOCK_COUNT:
            self._lock_reading_room()
            return
        self._reader_unlocked = True
        self._reader_view = view
        self.reader_button.show()
        if self.reading_room is not None:
            self.reading_room.set_roots(
                book_roots(self.settings, view), book_categories(self.settings, view)
            )

    def _lock_reading_room(self) -> None:
        self._reader_unlocked = False
        self._reader_view = None
        self.reader_button.hide()
        if self.reading_room is not None:
            index = self.tabs.indexOf(self.reading_room)
            if index >= 0:
                if self.tabs.currentIndex() == index:
                    self.tabs.setCurrentIndex(0)
                self.tabs.removeTab(index)
            self.reading_room.hide()
            self.reading_room.stop()

    def _open_documentation(self) -> None:
        if self.documentation_tab is None:
            self.documentation_tab = DocumentationTab(i18n.pick_language(self.settings.language))
            self.tabs.addTab(self.documentation_tab, self.tr("Documentation"))
        self.tabs.setCurrentWidget(self.documentation_tab)

    def _open_reading_room(self) -> None:
        if not self._reader_unlocked or self._reader_view is None:
            return
        if self.reading_room is None:
            self.reading_room = ReadingRoom(self.settings_path.parent / "reading-progress.json")
            self.reading_room.settings_requested.connect(self.open_settings)
        self.reading_room.set_roots(
            book_roots(self.settings, self._reader_view),
            book_categories(self.settings, self._reader_view),
        )
        index = self.tabs.indexOf(self.reading_room)
        if index < 0:
            index = self.tabs.addTab(self.reading_room, self.tr("Reading room"))
        self.tabs.setCurrentIndex(index)

    def _focus_search(self) -> None:
        if self.tabs.currentWidget() is self.assistant_tab:
            self.assistant_tab.prompt.setFocus()
            return
        if self.reading_room is not None and self.tabs.currentWidget() is self.reading_room:
            self.reading_room.filter.setFocus()
            return
        if self.tabs.currentWidget() is self.search_tab:
            self.search_tab.focus_search()
            return
        self.tabs.setCurrentIndex(1)
        self.library_search.setFocus()
        self.library_search.selectAll()

    def apply_proxy(self) -> None:
        """Make every connection from now on go through the proxy set in Settings."""
        p = self.settings.proxy
        try:
            proxy = net.proxy_url(p.address, p.username, get_secret(PROXY_PASSWORD))
        except ValueError as e:
            log.warning("proxy ignored: %s", e)
            proxy = None
        net.configure(proxy, p.torrent_client)
        log.info("proxy: %s", net.redacted(proxy) or "none")

    def qbit(self) -> MappedQbit:
        """The Torrent Client the user chose, through Path Mappings."""
        s = self.settings
        if s.client is TorrentClient.DELUGE:
            key: tuple[str, ...] = (
                s.client,
                s.deluge.host,
                "",
                get_secret(s.secret_name(DELUGE_PASSWORD)),
            )
        elif s.client is TorrentClient.TRANSMISSION:
            t = s.transmission
            key = (s.client, t.host, t.username, get_secret(s.secret_name(TRANSMISSION_PASSWORD)))
        elif s.client in {TorrentClient.UTORRENT, TorrentClient.BITTORRENT}:
            u = s.utorrent
            key = (s.client, u.host, u.username, get_secret(s.secret_name(UTORRENT_PASSWORD)))
        else:
            q = s.qbit
            key = (s.client, q.host, q.username, get_secret(s.secret_name(QBIT_PASSWORD)))
            key += (get_secret(s.secret_name(QBIT_API_KEY)),)
        if self._qbit is None or self._qbit[2] != net.current() or self._qbit[0] != key:
            self._qbit = (key, connect(s.client, *key[1:]), net.current())
        return MappedQbit(self._qbit[1], PathMapper(s.path_mappings))

    def indexer(self) -> Indexer:
        """One Indexer instance, so every search shares the same rate limiter.

        Only call on the GUI thread; workers get the instance passed in.
        """
        url, key = self.settings.indexer.url, get_secret(INDEXER_API_KEY)
        extra = tuple(extra_indexer_keys())
        current = self._indexer
        if (
            current is None
            or self._indexer_proxy != net.current()
            or (
                current.url,
                current.api_key,
                tuple(getattr(current, "extra_keys", ())),  # test stubs have none
            )
            != (url, key, extra)
        ):
            current = self._indexer = Indexer(url, key, cache=self.store, extra_keys=extra)
            current.session = self.account_workspace
            self._indexer_proxy = net.current()
        return current

    def _sync_agent_settings(self) -> None:
        if self.agent_runtime is not None:
            self.agent_runtime.sync(self.settings)

    def refresh_profile(self) -> None:
        """Refresh automatically, with at most one desktop request in flight."""
        if not isValid(self) or self._profile_refreshing:
            return
        self._profile_refreshing = True
        self.band.busy(True)
        self.zen_tab.profile_view.refresh_button.setEnabled(False)
        credentials = (self.settings.indexer.url, get_secret(INDEXER_API_KEY))
        run_in_background(
            lambda: self.account_workspace.refresh(*credentials),
            self._profile_read,
            self._profile_failed,
        )

    def show_account_profile(self) -> None:
        self.account_workspace.bind(self.settings.indexer.url, get_secret(INDEXER_API_KEY))
        state = self.account_workspace.state()
        self.zen_tab.profile_view.show_state(state)
        if self.companion_panel is not None:
            self.companion_panel.show_state(state)
        if state["paired"] and self.companion_receiver is None:
            if time.monotonic() >= self._receiver_retry_at:
                self._receiver_retry_at = time.monotonic() + 30
                try:
                    self._start_companion_receiver()
                except OSError:
                    self.zen_tab.profile_view.advanced_status.setText(
                        self.tr(
                            "Browser connection unavailable. "
                            "Close the other TorrentLinker instance; retrying automatically."
                        )
                    )

    def _poll_account_profile(self) -> None:
        self.show_account_profile()
        if time.time() >= self.account_workspace.state()["refresh_after"]:
            self.refresh_profile()

    def _start_companion_receiver(self) -> None:
        from torrentlinker.companion import CompanionReceiver

        if self.companion_receiver is None:
            self.companion_receiver = CompanionReceiver(
                self.account_workspace,
                lambda: (self.settings.indexer.url, get_secret(INDEXER_API_KEY)),
                port=self.account_workspace.receiver_port(),
            )

    def pair_companion(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from torrentlinker.companion import connection_url

        try:
            self.show_account_profile()
            pairing = self.account_workspace.pairing()
            self._start_companion_receiver()
            assert self.companion_receiver is not None
            self.account_workspace.remember_receiver(self.companion_receiver.server.server_port)
            address = self.companion_receiver.address
            account_id = self.account_workspace.state()["api"]["account_id"]
            if self.companion_panel is not None:
                self.companion_panel.show_pairing()
            QDesktopServices.openUrl(QUrl(connection_url(address, pairing["code"], account_id)))
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, self.tr("Browser companion"), str(error))

    def companion_panel_widget(self, parent=None):
        from torrentlinker.gui.companion_panel import CompanionPanel

        panel = self.companion_panel = CompanionPanel(parent)
        panel.pair_requested.connect(self.pair_companion)
        panel.disconnect_requested.connect(self.disconnect_companion)
        panel.extension_requested.connect(self.save_companion_extension)
        panel.session_downloads_toggled.connect(self.set_session_downloads)
        panel.destroyed.connect(lambda: setattr(self, "companion_panel", None))
        panel.show_state(self.account_workspace.state())
        return panel

    def set_session_downloads(self, enabled: bool) -> None:
        try:
            self.account_workspace.set_session_downloads(enabled)
        except ValueError as error:
            QMessageBox.warning(self, self.tr("Browser companion"), str(error))
        if self.companion_panel is not None:
            self.companion_panel.show_state(self.account_workspace.state())

    def disconnect_companion(self) -> None:
        self.account_workspace.disconnect()
        if self.companion_panel is not None:
            self.companion_panel.pairing_box.hide()
        if self.companion_receiver is not None:
            self.companion_receiver.stop()
            self.companion_receiver = None
        self.show_account_profile()

    def save_companion_extension(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from torrentlinker.companion import extension_zip

        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save browser companion"), "torrentlinker-companion.zip", "ZIP (*.zip)"
        )
        if path:
            try:
                Path(path).write_bytes(extension_zip())
            except OSError:
                QMessageBox.warning(
                    self,
                    self.tr("Browser companion"),
                    self.tr("Could not save the extension. Choose a writable folder."),
                )

    def _profile_read(self, profile: UserProfile) -> None:
        self._profile_refreshing = False
        if not isValid(self):
            return
        self.zen_tab.profile_view.refresh_button.setEnabled(True)
        self.show_account_profile()
        self.band.show_profile(profile)
        filled = profile.apply(self.settings.zen)
        if filled != self.settings.zen:
            self.settings.zen = filled
            self.settings.save(self.settings_path)
            log.info("Zen Profile filled from c411: %s", filled)
            self.zen_tab.seeding_view.refresh()

    def _profile_failed(self, error: Exception) -> None:
        self._profile_refreshing = False
        if not isValid(self):
            return
        self.zen_tab.profile_view.refresh_button.setEnabled(True)
        self.show_account_profile()
        log.info("c411 profile not read: %s", error)
        self.band.show_profile_error(error)

    # Plan ------------------------------------------------------------------

    def make_plan(self, then: Callable[[], None] | None = None) -> None:
        """Refresh new torrents in the Plan's categories, then make the Plan."""
        if not self._ensure_plan_download_folders():
            return
        self._use_cached_plan = False
        self._plan_refresh_failed = False
        self.store.clear_plan()
        self.zen_tab.plan_view.begin()
        self.band.set_plan(None)
        if self.catalogue_runner is not None:

            def resume() -> None:
                if self._use_cached_plan:
                    self._build_plan(then)
                else:
                    self.make_plan(then)

            self._pending_plan = resume
            self._planning = True
            self.zen_tab.plan_view.busy(
                True, self.tr("Waiting for the Catalogue refresh to finish…")
            )
            self.zen_tab.plan_view.fetching(True)
            return
        s = self.settings
        chosen = set(s.plan_categories) if s.plan_categories is not None else None
        targets = plan_categories(chosen, s.download_folders, s.indexer_categories)
        if not targets or not get_secret(INDEXER_API_KEY):
            self._build_plan(then)
            return
        indexer, store, categories = self.indexer(), self.store, dict(s.indexer_categories)

        def work(stop: Callable[[], bool], progress: Progress) -> None:
            log.info("Fetching Catalogue categories for the Plan: %s", targets)
            sync_catalogue(
                indexer,
                store,
                targets,
                full=False,
                bootstrap=True,
                stop=stop,
                progress=progress,
                categories=categories,
            )

        self._planning = True
        self.zen_tab.plan_view.busy(True, self.tr("Fetching the Catalogue for the Plan…"))
        self.zen_tab.plan_view.fetching(True)

        def after_fetch() -> None:
            if self._catalogue_error is not None and not self._use_cached_plan:
                if self.store.catalogue_size() == 0:
                    self._planning = False
                    self.zen_tab.plan_view.fetching(False)
                    self.zen_tab.plan_view.failed(self._catalogue_error)
                    return
                self._plan_refresh_failed = True
                log.info("Planning from cached metadata after Catalogue refresh failure")
            self._build_plan(then)

        self._after_catalogue_always = after_fetch
        self._run_catalogue(work)

    def _ensure_plan_download_folders(self) -> bool:
        """Offer category-scoped destinations before starting an otherwise empty Plan."""
        from torrentlinker.category_tags import category_path

        s = self.settings
        cats = s.indexer_categories
        for identifier in self._plan_destinations:
            profile = s.profile(identifier)
            folders = (
                s.download_folders if identifier == s.active_client_id else profile.download_folders
            )
            chosen = s.plan_categories
            if chosen is None:
                if folders.default.strip() or plan_categories(None, folders, cats):
                    continue
                if not cats:
                    QMessageBox.information(
                        self,
                        self.tr("Download Folder"),
                        self.tr(
                            "Fetch the Indexer categories in Settings before choosing "
                            "a Download Folder."
                        ),
                    )
                    return False
                choices = sorted(cats, key=lambda cid: category_path(cid, cats))
                labels = [
                    " / ".join(cats[c].name for c in category_path(cid, cats) if c in cats)
                    for cid in choices
                ]
                label, accepted = QInputDialog.getItem(
                    self,
                    self.tr("Download Folder"),
                    self.tr(
                        "No Download Folder is set for {0}. Choose the category to configure."
                    ).format(profile.name),
                    labels,
                    0,
                    False,
                )
                if not accepted:
                    return False
                missing = [choices[labels.index(label)]]
            else:
                missing = [cid for cid in chosen if not plan_categories([cid], folders, cats)]
            for cid in missing:
                name = " / ".join(
                    cats[c].name for c in category_path(cid, cats) if c in cats
                ) or str(cid)
                if (
                    chosen is not None
                    and QMessageBox.question(
                        self,
                        self.tr("Download Folder"),
                        self.tr(
                            "No Download Folder is set for {0} on {1}. "
                            "Set one now to make the Plan?"
                        ).format(name, profile.name),
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    return False
                path = choose_directory(self, self.tr("Download Folder for {0}").format(name))
                if not path:
                    return False
                folders.by_category[cid] = path
                s.save(self.settings_path)
                self.offer_plan_categories()
        return True

    def _stop_plan_fetch(self) -> None:
        self._use_cached_plan = True
        if self.catalogue_runner is not None:
            self.catalogue_runner.stop()
        self.zen_tab.plan_view.fetching(False)

    def _build_plan(self, then: Callable[[], None] | None = None) -> None:
        self._planning = False
        self.zen_tab.plan_view.fetching(False)
        self.zen_tab.plan_view.busy(True)

        def done(plan: Plan) -> None:
            self._planning = False
            self.zen_tab.plan_view.fetching(False)
            self._plan_made(plan)
            if then is not None and plan.items:
                then()

        run_in_background(self.plan_maker(), done, self.zen_tab.plan_view.failed)

    def offer_plan_categories(self) -> None:
        """Offer every category and subcategory, marking those without a Download Folder."""
        s = self.settings
        cats, folders = s.indexer_categories, s.download_folders
        options = []
        for cid, cat in sorted(cats.items()):
            if cat.parent is None:
                options.append((cid, cat.name, False))
                options += [
                    (sid, sub.name, True) for sid, sub in sorted(cats.items()) if sub.parent == cid
                ]
        without = {cid for cid, _name, _sub in options if folders.resolve(cid, cats) is None}
        chosen = set(s.plan_categories) if s.plan_categories is not None else None
        self.zen_tab.plan_view.set_category_options(options, chosen, without)

    def _plan_categories_changed(self, chosen: set[int] | None) -> None:
        before = set(self.settings.plan_categories or ())
        added = sorted(chosen - before) if chosen is not None else []
        if added:
            self.prefetch_categories(added)  # fetched while the user picks folders
        refused = {cid for cid in added if not self.ensure_download_folder(cid)}
        if chosen is not None and refused:
            chosen = (chosen - refused) or None
        self.settings.plan_categories = sorted(chosen) if chosen is not None else None
        self.settings.save(self.settings_path)
        self.offer_plan_categories()

    def ensure_download_folder(self, cid: int) -> bool:
        """Whether the Plan can draw from `cid`; asks for its Download Folder if needed."""
        s = self.settings
        cats, folders = s.indexer_categories, s.download_folders
        if folders.resolve(cid, cats) is not None:
            return True
        name = cats[cid].name if cid in cats else str(cid)
        covered = [
            c.name
            for sid, c in sorted(cats.items())
            if c.parent == cid and folders.resolve(sid, cats) is not None
        ]
        if covered:
            answer = QMessageBox.question(
                self,
                self.tr("Download Folder"),
                self.tr(
                    "{0} has no Download Folder, but {1} have theirs. Choose a folder for "
                    "its other subcategories? Otherwise the Plan draws only from those."
                ).format(name, ", ".join(covered)),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return True
        path = choose_directory(self, self.tr("Download Folder for {0}").format(name))
        if not path:
            return bool(covered)
        folders.by_category[cid] = path
        s.save(self.settings_path)
        log.info("Download Folder of category %s set to %s", cid, path)
        return True

    def prefetch_categories(self, categories: list[int]) -> None:
        """Start fetching the Catalogue of newly chosen categories, in the background."""
        if self.catalogue_runner is not None or not get_secret(INDEXER_API_KEY):
            return  # the update under way, or the next Plan, fetches them
        indexer, store, known = self.indexer(), self.store, dict(self.settings.indexer_categories)

        def work(stop: Callable[[], bool], progress: Progress) -> None:
            log.info("Fetching the Catalogue of newly chosen categories: %s", categories)
            sync_catalogue(
                indexer,
                store,
                categories,
                full=False,
                bootstrap=True,
                stop=stop,
                progress=progress,
                categories=known,
            )

        self._run_catalogue(work)

    def _plan_options_changed(self, options: PlanOptions) -> None:
        self.settings.plan_options = options
        self.settings.save(self.settings_path)
        self.store.clear_plan()
        self.zen_tab.plan_view.invalidate()
        self.band.set_plan(None)

    def _choose_plan_clients(self) -> None:
        from torrentlinker.gui.plan_clients import PlanClientsDialog

        dialog = PlanClientsDialog(self.settings, self._plan_destinations, self)
        if dialog.exec() and dialog.selected():
            self._plan_destinations = dialog.selected()
            names = [self.settings.profile(i).name for i in self._plan_destinations]
            self.plan_targets_button.setText(self.tr("Plan destinations: ") + ", ".join(names))
            self.zen_tab.plan_view.invalidate()

    def plan_maker(self) -> Callable[[], Plan]:
        """Build on the GUI thread the work that makes a Plan (no Indexer request)."""
        s = self.settings
        if self._plan_destinations != {s.active_client_id: 0}:
            from torrentlinker.client_profiles import Connections
            from torrentlinker.multi_plan import distributed_plan

            connections = Connections(get_secret)
            clients = {i: connections.client(s, i) for i in self._plan_destinations}
            budgets = dict(self._plan_destinations)
            return lambda: distributed_plan(s, self.store, clients, budgets)
        qbit, store, profile, url = self.qbit(), self.store, s.zen, s.indexer.url
        folders, categories, margin = (
            s.download_folders,
            dict(s.indexer_categories),
            s.free_space_margin,
        )
        only = set(s.plan_categories) if s.plan_categories is not None else None
        options = s.plan_options
        planned_folders = {
            folder
            for c in plan_categories(only, folders, categories)
            if (folder := folders.resolve(c, categories)) is not None
        }
        if only is None and folders.default.strip():
            planned_folders.add(Path(folders.default))
        # Orphans whose Matches searches found, for Reseed rows (read on the GUI thread)
        found = [
            (e, list(self.review.cache[e.item.path]))
            for e in self.library_model.entries
            if e.state is ItemState.ORPHAN and e.item.path in self.review.cache
        ]
        local_items = [e.item for e in self.library_model.entries]
        # Download Folders hold books too, maybe from torrents removed from qBittorrent.
        libraries = [f.path for f in s.library_folders]
        unlisted = sorted(
            f for f in planned_folders if not any(f.is_relative_to(r) for r in libraries)
        )

        def work() -> Plan:
            torrents = qbit.torrents(with_files=False)
            cached = observe_swarm(store, torrents, url)
            view = seeding(profile, torrents, url, catalogue=cached)
            in_client = {t.hash.lower() for t in torrents}
            candidates = reseed_candidates(
                profile,
                found,
                in_client,
                view.active,
                options=options,
            )
            issues: list[PlanIssue] = []
            downloads = catalogue_candidates(
                store.catalogue(),
                folders,
                categories,
                in_client,
                disk_of,
                only,
                s.plan_exclusions,
                issues=issues,
            )
            on_disk_items = list(local_items)
            for folder in unlisted:
                try:
                    on_disk_items += scan(LibraryFolder(folder), store).require_complete()
                except OSError as e:
                    log.info("Download Folder not scanned for books on disk: %s", e)
            already = on_disk(downloads, on_disk_items)
            left_out = {d.infohash for d in already}
            candidates += [c for c in downloads if c.infohash not in left_out]
            if already:
                log.info(
                    "Plan leaves out %d torrents that seem to be on disk, e.g. %s",
                    len(already),
                    "; ".join(f"{d.title} <- {d.path}" for d in already[:5]),
                )
            spaces = disk_space(
                sorted(planned_folders | {c.folder for c in candidates if c.folder}, key=str),
                margin,
            )
            budgets = {space.disk: space.available for space in spaces}
            slots = max(0, profile.torrent_cap - view.count) if profile.torrent_cap else None
            plan = make_plan(
                profile,
                candidates,
                budgets,
                view.active,
                slots,
                options=options,
                disk_spaces=spaces,
            )
            return explain_inputs(plan, issues, already)

        return work

    def _plan_made(self, plan: Plan) -> None:
        self.store.save_plan(saved_items(plan), zen_added=plan.zen_added)
        self.zen_tab.plan_view.show_plan(plan)
        if not plan.items:
            log.info("Empty Plan: %s", [(issue.code, issue.count) for issue in plan.issues])
        s = self.settings
        targets = plan_categories(s.plan_categories, s.download_folders, s.indexer_categories)
        notices = []
        if getattr(self, "_plan_refresh_failed", False):
            notices.append(
                self.tr(
                    "Catalogue refresh failed. This Plan uses cached metadata; "
                    "retry the refresh later."
                )
            )
        if self.store.limited_categories().intersection(targets):
            notices.append(
                self.tr(
                    "Catalogue coverage is partial: older torrents may be missing. "
                    "Cached torrents remain usable for this Plan."
                )
            )
        if notices:
            self.zen_tab.plan_view.catalogue_notice.setText("\n".join(notices))
            self.zen_tab.plan_view.catalogue_notice.show()
        if plan.items:
            notice = self.zen_tab.plan_view.catalogue_notice
            notices.append(
                self.tr(
                    "Provisional estimates from cached metadata. Seeder counts update from "
                    "your torrent client after tracker responses."
                )
            )
            notice.setText("\n".join(notices))
            notice.show()
        self.band.set_plan(plan.zen_added if plan.items else None)

    def confirm_send(self) -> None:
        """Summary before sending, with the choice to refresh the Catalogue first."""
        plan = self.zen_tab.plan_view.plan
        if plan is None or not plan.items:
            return
        payback = plan.payback_days
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.tr("Send the Plan to your torrent client"))
        box.setText(
            self.tr(
                "{0} torrents · {1} Go to download · ≈ +{2} Zen/day · paid back in ≈ {3} "
                "days.\nCatalogue: {4}.\n\nEach .torrent is downloaded directly from c411 "
                "with your key and added to its Download Folder. A torrent whose files "
                "already exist there is refused."
            ).format(
                len(plan.items),
                f"{plan.download_size / 1e9:.1f}",
                f"{plan.zen_added:.2f}",
                f"{payback:.0f}" if payback is not None else "–",
                self.catalogue_age(),
            )
            + "\n\n"
            + self.zen_tab.plan_view.times.text()
        )
        send = box.addButton(self.tr("Send"), QMessageBox.ButtonRole.AcceptRole)
        refresh = box.addButton(self.tr("Refresh first"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is send:
            self.send_plan(plan)
        elif box.clickedButton() is refresh:
            self.make_plan(then=self.confirm_send)  # fetches the Plan's categories first

    def test_speed(self) -> None:
        self.zen_tab.plan_view.speed_testing()
        run_in_background(measure_download_speed, self._speed_measured, self._speed_failed)

    def _speed_measured(self, speed: float) -> None:
        self.settings.download_speed = speed
        self.settings.download_speed_tested = datetime.now().isoformat(timespec="minutes")
        self.settings.save(self.settings_path)
        log.info("Download speed tested: %.0f Mbit/s", speed * 8 / 1e6)
        view = self.zen_tab.plan_view
        view.set_speed(speed, self.settings.download_speed_tested)

    def _speed_failed(self, error: Exception) -> None:
        view = self.zen_tab.plan_view
        view.set_speed(self.settings.download_speed, self.settings.download_speed_tested)
        QMessageBox.warning(
            self,
            self.tr("Speed test"),
            self.tr("The speed test failed: {0}").format(str(error) or type(error).__name__),
        )

    def send_plan(self, plan: Plan) -> None:
        self.tabs.setCurrentWidget(self.zen_tab)
        self.zen_tab.pages.setCurrentIndex(2)
        if self.send_runner is not None:
            return
        qbit, indexer, reseeder = self.qbit(), self.indexer(), self.plan_reseeder()

        def fetch(c: PlanCandidate) -> bytes:
            assert isinstance(c.source, CatalogueRow)
            return indexer.fetch_torrent(candidate(indexer, c.source), retry=False)

        def ahead(candidates: list[PlanCandidate]) -> None:
            if not hasattr(indexer, "prefetch"):  # test stubs have none
                return
            indexer.prefetch(
                [
                    candidate(indexer, c.source)
                    for c in candidates
                    if isinstance(c.source, CatalogueRow)
                ]
            )

        store = self.store
        from torrentlinker.client_profiles import Connections

        connections = Connections(get_secret)
        settings_snapshot = self.settings.for_client(self.settings.active_client_id)

        def record(c: PlanCandidate, outcome: str, reason: str) -> None:
            store.mark_plan_item(c.infohash, outcome, reason)

        def work(stop: threading.Event, progress: Callable[[SendProgress], None]) -> SendReport:
            try:
                with indexer.background():  # the user's own searches and Reseeds go first
                    return send_plan(
                        plan,
                        qbit,
                        fetch,
                        reseeder,
                        on_progress=progress,
                        on_outcome=record,
                        stop=stop,
                        client_for=lambda identifier: connections.client(
                            settings_snapshot, identifier
                        ),
                        ahead=ahead,
                    )
            finally:
                if hasattr(indexer, "drop_prefetch"):
                    indexer.drop_prefetch()

        runner = SendRunner(work)
        runner.signals.progress.connect(self._send_progress)
        runner.signals.finished.connect(self._plan_sent)
        runner.signals.failed.connect(self._send_failed)
        self.send_runner = runner
        store.set_plan_sending(True)
        log.info("Sending a Plan of %d torrents", len(plan.items))
        self._send_progress(SendProgress(0, len(plan.items), "", 0, 0, 0))
        runner.start()

    def stop_sending(self) -> None:
        if self.send_runner is not None:
            self.send_runner.stop()

    def _send_progress(self, progress: SendProgress) -> None:
        self.zen_tab.plan_view.sending(progress)
        plan = self.zen_tab.plan_view.plan
        self.band.set_sending(progress, plan.zen_added if plan and plan.items else None)

    def _send_ended(self) -> None:
        self.send_runner = None
        self.store.set_plan_sending(False)
        self.zen_tab.plan_view.sending(None)
        self.band.set_sending(None)

    def _send_failed(self, error: Exception) -> None:
        self._send_ended()
        if not self.show_saved_plan():
            self.zen_tab.plan_view.show_plan(Plan())
        self.zen_tab.plan_view.failed(error)

    def show_saved_plan(self, interrupted: bool = False) -> bool:
        """Show what is left to send of the saved Plan; False if nothing is left."""
        saved = self.store.saved_plan()
        if saved is None:
            return False
        pending = saved.pending
        rows = {r.infohash: r for r in self.store.catalogue([i.infohash for i in pending])}
        plan = restore_plan(saved, rows)
        if not plan.items:
            self.store.clear_plan()
            return False
        view = self.zen_tab.plan_view
        view.show_plan(plan)
        left = (
            self.tr(
                "Sending was interrupted: {0} torrents of this Plan are left. "
                "Send to the torrent client to continue."
            )
            if interrupted
            else self.tr("Saved Plan: {0} torrents left to send.")
        )
        view.summary.setText(view.summary.text() + "\n" + left.format(len(plan.items)))
        self.band.set_plan(plan.zen_added)
        return True

    def plan_reseeder(self) -> Callable[[PlanCandidate], None]:
        """Reseed rows run the normal Reseed flow, with Verification (ADR-0002)."""
        qbit, store = self.qbit(), self.store

        def reseed(c: PlanCandidate) -> None:
            assert isinstance(c.source, ReseedSource)
            v = c.source.checked
            assert v.meta is not None and v.match is not None
            start_reseed(
                qbit,
                store,
                c.source.entry.item,
                v.meta,
                v.match,
                candidate_key(v.candidate),
                approve_disk_renames=self.reseed_consent.approve,
            )

        return reseed

    def _plan_sent(self, report: SendReport) -> None:
        self._send_ended()
        total = len(self.zen_tab.plan_view.plan.items) if self.zen_tab.plan_view.plan else 0
        log.info(
            "Plan sent: %d added, %d Reseeds, %d refused, %d failed%s",
            len(report.added),
            len(report.reseeded),
            len(report.refused),
            len(report.failed),
            ", stopped" if report.stopped else "",
        )
        if not self.show_saved_plan():
            self.zen_tab.plan_view.show_plan(Plan())
        lines = [self.tr("{0} torrents added to your torrent client.").format(len(report.added))]
        if report.reseeded:
            lines.append(self.tr("{0} Reseeds started.").format(len(report.reseeded)))
        if report.stopped:
            lines.append(
                self.tr(
                    "Stopped after {0} of {1} torrents. The rest of the Plan is saved: "
                    "send it again to continue, even after restarting the app."
                ).format(report.handled, total)
            )
        problems = [self.tr("Refused: {0} ({1})").format(t, why) for t, why in report.refused]
        problems += [self.tr("Failed: {0} ({1})").format(t, why) for t, why in report.failed]
        box = QMessageBox(
            QMessageBox.Icon.Information, self.tr("Plan sent"), "\n".join(lines), parent=self
        )
        if problems:
            box.setInformativeText(
                self.tr("{0} refused, {1} failed: see the details.").format(
                    len(report.refused), len(report.failed)
                )
            )
            box.setDetailedText("\n".join(problems))
        box.exec()
        self.zen_tab.seeding_view.refresh()
        if report.reseeded:
            self.check_verifications()  # shows them as Verifying… and keeps polling

    # Catalogue -------------------------------------------------------------

    def refresh_categories(self, then: Callable[[], object] | None = None) -> None:
        """Read the Indexer's category tree (caps) and keep it in the settings if it changed."""
        if not get_secret(INDEXER_API_KEY):
            if then is not None:
                then()
            return
        indexer = self.indexer()

        def work() -> dict[int, IndexerCategory]:
            caps = indexer.caps()
            return {c: IndexerCategory(n, caps.parents.get(c)) for c, n in caps.categories.items()}

        def done(categories: dict[int, IndexerCategory]) -> None:
            if categories and categories != self.settings.indexer_categories:
                log.info("Indexer categories updated: %d", len(categories))
                self.settings.indexer_categories = categories
                self.search_tab.refresh_categories()
                self.settings.save(self.settings_path)
                self.offer_plan_categories()
            if then is not None:
                then()

        def failed(error: Exception) -> None:
            log.info("Indexer categories not refreshed: %s", error)
            if then is not None:
                then()

        run_in_background(work, done, failed)

    def update_catalogue(self, then: Callable[[], None] | None = None) -> bool:
        """Fetch the newest torrents of the user's categories (at startup, or before
        sending a Plan); `then` runs once it is done. False if it could not start."""
        if self.catalogue_runner is not None or not get_secret(INDEXER_API_KEY):
            return False
        self._after_catalogue = then
        indexer, store, qbit = self.indexer(), self.store, self.qbit()
        url, folders = self.settings.indexer.url, self.settings.download_folders
        categories = dict(self.settings.indexer_categories)

        def work(stop: Callable[[], bool], progress: Progress) -> None:
            try:
                seeded = [t.hash for t in indexer_torrents(qbit.torrents(with_files=False), url)]
            except Exception as e:  # noqa: BLE001 - qBittorrent may be down; folders still count
                log.info("Catalogue update without qBittorrent: %s", e)
                seeded = []
            wanted = startup_categories(folders, categories, seeded, store)
            log.info("Catalogue update of categories %s", wanted)
            sync_catalogue(
                indexer,
                store,
                wanted,
                max_pages=STARTUP_PAGES,
                stop=stop,
                progress=progress,
                categories=categories,
            )

        self._run_catalogue(work)
        return True

    def crawl_catalogue(self) -> None:
        """Fetch every category of the Indexer, resuming a paused crawl (user action)."""
        if self.catalogue_runner is not None:
            self.statusBar().showMessage(self.tr("The Catalogue is already being updated"))
            return
        if not get_secret(INDEXER_API_KEY):
            QMessageBox.information(
                self, self.tr("Catalogue"), self.tr("Enter your Indexer API key in Settings first.")
            )
            return
        indexer, store = self.indexer(), self.store
        known = dict(self.settings.indexer_categories)
        position = self._crawl_position

        def work(stop: Callable[[], bool], progress: Progress) -> None:
            categories = known or {
                c: IndexerCategory(name, caps.parents.get(c))
                for caps in [indexer.caps()]
                for c, name in caps.categories.items()
            }
            wanted = crawl_categories(categories)
            for i, category in enumerate(wanted, 1):
                if stop():
                    return
                position[:] = [i, len(wanted)]
                sync_catalogue(
                    indexer,
                    store,
                    [category],
                    full=True,
                    stop=stop,
                    progress=progress,
                    categories=categories,
                )

        self._crawl_position[:] = [0, 0]
        self.zen_tab.catalogue.set_state(True, False)
        self._run_catalogue(work)

    def pause_catalogue(self) -> None:
        if self.catalogue_runner is not None:
            self.catalogue_runner.stop()
            self.zen_tab.catalogue.set_status(self.tr("Pausing after the current page…"))

    def _run_catalogue(self, work: Callable[[Callable[[], bool], Progress], None]) -> None:
        indexer = self.indexer()

        def in_background(stop: Callable[[], bool], progress: Progress) -> None:
            with indexer.background():  # the user's own searches go first
                work(stop, progress)

        runner = CatalogueRunner(in_background)
        self._catalogue_added: dict[int, int] = {}
        self._last_crawl_progress = None
        self._catalogue_error: Exception | None = None
        self.crawl_ticker.start()
        runner.signals.progress.connect(self._catalogue_progress)
        runner.signals.failed.connect(self._catalogue_failed)
        runner.signals.finished.connect(self._catalogue_finished)
        self.catalogue_runner = runner
        runner.start()

    def _catalogue_progress(self, p: CrawlProgress) -> None:
        self._catalogue_added[p.category] = p.added
        self._last_crawl_progress = p
        self._show_crawl_progress()

    def _show_crawl_progress(self) -> None:
        """Also redrawn twice a second while fetching, for the countdown and the total."""
        p = self._last_crawl_progress
        if p is None:
            return
        if p.source == SNAPSHOT_NAME:
            text = self.tr("Importing Zen Lab metadata: {0} torrents (+{1})").format(
                p.offset, p.added
            )
            self.band.set_catalogue(text)
            self.zen_tab.catalogue.set_status(text)
            self.statusBar().showMessage(text)
            if self._planning:
                self.zen_tab.plan_view.busy(True, text)
            return
        name = self.settings.indexer_categories.get(p.category)
        label = name.name if name else str(p.category)
        if name is not None and name.parent is not None:
            parent = self.settings.indexer_categories.get(name.parent)
            if parent is not None:
                label = f"{parent.name} / {label}"
        text = self.tr("updating {0}, page {1} (+{2})").format(label, p.pages, p.added)
        self.band.set_catalogue(text)
        wait = self._indexer.next_request_in() if self._indexer else 0
        suffix = self.tr(" · next request in {0} s").format(f"{wait:.0f}") if wait > 0.5 else ""
        size = self.store.catalogue_size()
        if self.zen_tab.catalogue.running:
            done, total = self._crawl_position
            status = self.tr("Category {0}/{1}: {2} · {3} torrents in the Catalogue").format(
                done, total, text, size
            )
        elif self._planning and self._pending_plan is None:
            status = self.tr(
                "Updating selected categories: {0} · {1} torrents in the Catalogue"
            ).format(text, size)
        else:  # a startup update may cover more categories than a queued Plan
            status = self.tr(
                "Updating your categories: {0} · {1} torrents in the Catalogue"
            ).format(text, size)
        self.zen_tab.catalogue.set_status(status + suffix)
        self.statusBar().showMessage(self.tr("Catalogue: {0}").format(status) + suffix)
        if self._planning:
            if self._pending_plan is not None:
                self.zen_tab.plan_view.busy(
                    True,
                    self.tr("Waiting for the Catalogue refresh to finish…") + " " + status + suffix,
                )
                return
            self.zen_tab.plan_view.busy(
                True, self.tr("Fetching the Catalogue for the Plan: {0}").format(status + suffix)
            )

    def _catalogue_failed(self, error: Exception) -> None:
        self._catalogue_error = error
        log.warning("Catalogue update failed: %s", error)
        self.statusBar().showMessage(
            self.tr("Catalogue update failed: {0}").format(error_text(error))
        )

    def _catalogue_finished(self, stopped: bool) -> None:
        self.catalogue_runner = None
        self.crawl_ticker.stop()
        self._show_catalogue_age()
        added, size = sum(self._catalogue_added.values()), self.store.catalogue_size()
        log.info(
            "Catalogue %s: +%d torrents, %d in total",
            "paused" if stopped else "updated",
            added,
            size,
        )
        message = (
            self.tr("Catalogue paused: +{0} torrents · {1} in total")
            if stopped
            else self.tr("Catalogue updated: +{0} torrents · {1} in total")
        )
        result = message.format(added, size)
        error = getattr(self, "_catalogue_error", None)
        if error is not None:
            result = self.tr("Catalogue update failed: {0}").format(error_text(error))
        if self.store.limited_categories():
            result += " · " + self.tr(
                "Partial Catalogue coverage: the Indexer limits how far back "
                "pages can be read. "
                "Cached torrents remain usable."
            )
        self.statusBar().showMessage(result, 15000)
        then, self._after_catalogue = self._after_catalogue, None
        always, self._after_catalogue_always = self._after_catalogue_always, None
        pending, self._pending_plan = self._pending_plan, None
        if then is not None and not stopped and error is None:
            then()
        if always is not None:
            always()  # e.g. a Plan: paused, it is made from the Catalogue fetched so far
        if pending is not None:
            if self.catalogue_runner is None:
                pending()
            else:
                self._pending_plan = pending

    def _show_catalogue_age(self) -> None:
        self.band.set_catalogue(self.catalogue_age())
        paused = self.store.crawl_paused()
        self.zen_tab.catalogue.set_state(False, paused)
        self.zen_tab.catalogue.set_status(
            self.catalogue_age()
            + (" · " + self.tr("whole-catalogue fetch paused") if paused else "")
            + (
                "\n"
                + self.tr(
                    "Partial Catalogue coverage: the Indexer limits how far back "
                    "pages can be read. "
                    "Cached torrents remain usable."
                )
                if self.store.limited_categories()
                else ""
            )
            + (
                "\n" + self.tr("Zen Lab snapshot imported; c411 data takes priority")
                if self.store.feed_state(SNAPSHOT_NAME).updated_at is not None
                else ""
            )
        )

    def catalogue_age(self) -> str:
        how_old = age(self.store.catalogue_updated_at(), time.time())
        if how_old is None:
            return self.tr("not fetched yet")
        amount, unit = how_old
        units = {"min": self.tr("{0} min"), "h": self.tr("{0} h"), "d": self.tr("{0} d")}
        return self.tr("{0} torrents, {1} old").format(
            self.store.catalogue_size(), units[unit].format(amount)
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self.profile_timer.stop()
        if self.companion_receiver is not None:
            self.companion_receiver.stop()
            self.companion_receiver = None
        self.reseed_consent.cancel()
        if self.media_tab.window() is self:
            self.media_tab.stop()
        if self.reading_room is not None:
            self.reading_room.stop()
        self.search_tab.stop()
        self.seeding_timer.stop()
        self._pending_plan = None
        if self.catalogue_runner is not None:
            self.catalogue_runner.stop()
        if self.send_runner is not None:
            self.send_runner.stop()
        super().closeEvent(event)

    def seeding_loader(self) -> Callable[[], Seeding]:
        """Build on the GUI thread the work that reads the Seeding view from qBittorrent."""
        qbit, profile, url = self.qbit(), self.settings.zen, self.settings.indexer.url
        uploads = self.settings.uploads
        categories = dict(self.settings.indexer_categories)
        store = self.store

        def work() -> Seeding:
            torrents = qbit.torrents(with_files=False)
            cached = observe_swarm(store, torrents, url)
            view = seeding(profile, torrents, url, uploads, catalogue=cached, categories=categories)
            report = sync_category_tags(
                qbit, ((r.torrent, r.category) for r in view.rows), categories
            )
            if report.updated or report.failed:
                log.info(
                    "Category tags: %d updated, %d failed, %d unknown",
                    report.updated,
                    report.failed,
                    report.unknown,
                )
            return replace(view, tag_sync=report)

        return work

    def _uploads_changed(self, uploads: int) -> None:
        self.settings.uploads = uploads
        if self.settings_path.exists():
            self.settings.save(self.settings_path)

    def default_query(self, entry: LibraryEntry) -> str:
        kind = entry.folder.kind
        last = build_queries(entry.item, kind, (), find_ids(entry.item), None)[-1]
        return last.q

    def searcher(self) -> Searcher:
        """Build on the GUI thread a search function that workers can call safely."""
        indexer = self.indexer()
        tmdb_key = get_secret(TMDB_API_KEY)
        tmdb = Tmdb(tmdb_key) if tmdb_key else None
        categories = {k: self.settings.categories(k) for k in ContentKind}

        def search(entry: LibraryEntry, override: str | None) -> list[Candidate]:
            kind = entry.folder.kind
            return search_candidates(
                indexer,
                entry.item,
                kind,
                categories[kind],
                indexer.supported_modes(),
                tmdb,
                override,
            )

        return search

    def match_rules(self) -> MatchRules:
        return self.settings.matching.rules()

    def _open_upload(self, entry: LibraryEntry) -> None:
        self.tabs.setCurrentWidget(self.upload_tab)
        self.upload_tab.select(entry.item.path)

    @agent_settings_change
    def add_library_folder(self) -> None:
        if not self.add_folder_action.isEnabled():
            return
        chosen = choose_directory(self, self.tr("Choose a Library Folder"))
        if not chosen:
            return
        path = Path(chosen).expanduser()
        if not path.is_dir():
            QMessageBox.warning(self, self.tr("Library"), self.tr("Not a folder: {0}").format(path))
            return
        if any(f.path.resolve() == path.resolve() for f in self.settings.library_folders):
            QMessageBox.information(
                self, self.tr("Library"), self.tr("This folder is already in the Library.")
            )
            return
        dialog = LibraryFolderDialog(path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        folders = [*self.settings.library_folders, dialog.folder()]
        try:
            replace(self.settings, library_folders=folders).save(self.settings_path)
        except OSError as error:
            QMessageBox.warning(
                self, self.tr("Library"), self.tr("Could not save the folder: {0}").format(error)
            )
            return
        self.settings.library_folders = folders
        if self.agent_runtime:
            self.agent_runtime.reset(self.settings)
        self._fill_folder_filter()
        self.library_search.clear()
        self.state_filter.setCurrentIndex(0)
        self.folder_filter.setCurrentIndex(self.folder_filter.findData(path))
        if self.tabs.currentWidget() is self.media_tab:
            self.media_tab.start_scan()
        else:
            self.scan()

    @agent_settings_change
    def save_library_folders(self, folders: list[LibraryFolder]) -> bool:
        if not self.add_folder_action.isEnabled() or self.batch is not None:
            self.statusBar().showMessage(self.tr("Wait for the Library operation to finish."))
            return False
        try:
            replace(self.settings, library_folders=folders).save(self.settings_path)
        except OSError as error:
            QMessageBox.warning(self, self.tr("Library Folders"), error_text(error))
            return False
        self.settings.library_folders = folders
        if self.agent_runtime:
            self.agent_runtime.reset(self.settings)
        self._fill_folder_filter()
        valid = {f.path for f in folders}
        self.library_model.set_entries(
            [entry for entry in self.library_model.entries if entry.folder.path in valid]
        )
        if folders:
            self.scan()
        return True

    def set_media_center(self, enabled: bool) -> None:
        if enabled == self.media_center_active:
            return
        if enabled:
            self.tabs.setCurrentWidget(self.media_tab)
            self._media_normal_geometry = self.saveGeometry()
            self._media_normal_state = self.windowState()
            self._media_status_visible = not self.statusBar().isHidden()
        self.media_center_active = enabled
        self.media_tab.set_center_mode(enabled)
        self.sidebar.setVisible(not enabled)
        self.app_header.setVisible(not enabled)
        self.statusBar().setVisible(not enabled and self._media_status_visible)
        self.content_layout.setContentsMargins(*((0, 0, 0, 0) if enabled else (24, 20, 24, 12)))
        self.content_layout.setSpacing(0 if enabled else 16)
        if enabled:
            self.showFullScreen()
        else:
            self.restoreGeometry(self._media_normal_geometry)
            self.setWindowState(self._media_normal_state)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and getattr(self, "media_center_active", False)
            and not self.isFullScreen()
        ):
            self.set_media_center(False)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self.media_center_active:
            self.set_media_center(False)
            event.accept()
        else:
            super().keyPressEvent(event)

    def _save_media_layout(self, value: str) -> None:
        if value not in ("cinematic", "focus", "collection"):
            return
        self.settings.media_layout = value
        self.settings.save(self.settings_path)

    def _select_client(self) -> None:
        identifier = self.client_selector.currentData()
        if identifier == self.settings.active_client_id:
            return
        from PySide6.QtCore import QThreadPool

        if QThreadPool.globalInstance().activeThreadCount() or (
            self.agent_runtime and self.agent_runtime.busy()
        ):
            self.client_selector.blockSignals(True)
            self.client_selector.setCurrentIndex(
                self.client_selector.findData(self.settings.active_client_id)
            )
            self.client_selector.blockSignals(False)
            self.statusBar().showMessage(
                self.tr("Wait for the current operation before changing client."), 5000
            )
            return
        self._replace_workspace(self.settings.for_client(identifier))

    @agent_settings_change
    def _replace_workspace(self, settings: Settings) -> None:
        if self.agent_runtime and self.agent_runtime.busy():
            self.statusBar().showMessage(self.tr("Wait for agent jobs before changing settings."))
            return
        self.set_media_center(False)
        settings.save(self.settings_path)
        self.verify_timer.stop()
        tab_title = self.tabs.tabText(self.tabs.currentIndex())
        replacement = MainWindow(settings, self.settings_path, self.store)
        replacement.agent_runtime = self.agent_runtime
        if replacement.agent_runtime:
            replacement.agent_runtime.setup._profile_workspace = replacement.account_workspace
        same_client = settings.active_client_id == self.settings.active_client_id
        if same_client:
            media_index = replacement.tabs.indexOf(replacement.media_tab)
            replacement.tabs.removeTab(media_index)
            replacement.media_tab.deleteLater()
            with QSignalBlocker(self.tabs):
                self.tabs.removeTab(self.tabs.indexOf(self.media_tab))
            self.media_tab.layout_changed.disconnect(self._save_media_layout)
            self.media_tab.center_mode_requested.disconnect(self.set_media_center)
            replacement.media_tab = self.media_tab
            replacement.media_tab.layout_changed.connect(replacement._save_media_layout)
            replacement.media_tab.center_mode_requested.connect(replacement.set_media_center)
            replacement.media_tab.set_center_mode(False)
            replacement.media_tab.set_media_layout(settings.media_layout)
            replacement.tabs.insertTab(media_index, self.media_tab, self.tr("Media"))
        else:
            self.media_tab.stop()
        if self.agent_runtime:
            self.agent_runtime.reset(settings)
        if same_client:
            replacement.media_tab.rebind(
                replacement.assistant_service,
                lambda: replacement.settings.active_client_id,
                replacement.add_library_folder,
            )
        replacement.restoreGeometry(self.saveGeometry())
        replacement_index = next(
            (
                i
                for i in range(replacement.tabs.count())
                if replacement.tabs.tabText(i) == tab_title
            ),
            0,
        )
        replacement.tabs.setCurrentIndex(replacement_index)
        replacement.show()
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.torrentlinker_window = replacement  # type: ignore[attr-defined]
        self.close()
        self.deleteLater()
        QTimer.singleShot(0, replacement, replacement.startup)

    @agent_settings_change
    def open_client_profiles(self) -> None:
        if self.agent_runtime and self.agent_runtime.busy():
            self.statusBar().showMessage(self.tr("Wait for agent jobs before changing settings."))
            return
        from PySide6.QtCore import QThreadPool

        if QThreadPool.globalInstance().activeThreadCount():
            self.statusBar().showMessage(
                self.tr("Wait for the current operation before changing client."), 5000
            )
            return
        from torrentlinker.gui.client_profiles import ClientProfilesDialog

        if ClientProfilesDialog(self.settings, self.store, self).exec():
            self._replace_workspace(self.settings)

    def open_assistant_connections(self) -> None:
        self.open_settings(assistant=True)

    @agent_settings_change
    def open_settings(self, *, assistant: bool = False, agents: bool = False) -> None:
        with ExitStack() as stack:
            self._settings_stack: ExitStack | None = stack
            try:
                self._edit_settings(assistant=assistant, agents=agents)
            finally:
                self._settings_stack = None

    def _export_diagnostics(self, parent: QWidget) -> None:
        from torrentlinker.diagnostics import build_report
        from torrentlinker.gui.diagnostics import export_report

        jobs = self.agent_runtime.service.jobs if self.agent_runtime else None
        export_report(parent, lambda: build_report(self.settings, self.store, jobs))

    def _edit_settings(self, *, assistant: bool, agents: bool) -> None:
        if self.agent_runtime and self.agent_runtime.busy():
            self.statusBar().showMessage(self.tr("Wait for agent jobs before changing settings."))
            return
        folders = list(self.settings.library_folders)
        dialog = SettingsDialog(self.settings, self)
        dialog.diagnostics_requested.connect(lambda: self._export_diagnostics(dialog))
        dialog.folder_editor.set_scan_errors(
            self.library_workspace.scan_errors, self.library_workspace.editor.scanned
        )
        if assistant:
            dialog.show_assistant_connections()
        if agents:
            dialog.show_agent_access()
        accepted = dialog.exec()
        for identifier in dialog.agent_approvals:
            # Run only after the settings transaction has released its suspension.
            # execute() still checks the reviewed proposal's settings fingerprint.
            QTimer.singleShot(
                0, lambda identifier=identifier: self._execute_agent_approval(identifier)
            )
        # Model connections apply at once, even when the dialog is cancelled.
        for chat in (self.assistant_tab, self.media_tab.assistant):
            if chat is not None and chat.service:
                chat.refresh()
        if accepted:
            self._lock_reading_room()
            self.torrents_tab.reset_connection()
            self.settings.capture_client()
            self.client_selector.setItemText(
                self.client_selector.currentIndex(), self.settings.profile().name
            )
            self.settings.save(self.settings_path)
            if self.agent_runtime:
                self.agent_runtime.reset(self.settings)
            log.info("settings written to %s", self.settings_path)
            self.apply_proxy()
            set_theme(self.settings.theme)
            self.media_tab.set_media_layout(self.settings.media_layout)
            self._fill_folder_filter()
            if not self._has_indexer_key():
                self._await_setup()
                return
            self.search_tab.refresh_categories()
            self.search_tab.refresh_estimates()
            self.offer_plan_categories()
            self.upload_tab.set_entries(self.upload_tab.entries)  # the Announce URL
            self.zen_tab.plan_view.keys = 1 + len(extra_indexer_keys())
            if not self._startup_complete:
                self._start_services()
            else:
                self.zen_tab.seeding_view.refresh()
                if self.settings.library_folders != folders:
                    self.scan()  # a new folder, depth or Content Kind changes every entry
        else:
            log.info("settings dialog cancelled")

    def _execute_agent_approval(self, identifier: str) -> None:
        if self.agent_runtime is None:
            return
        service = self.agent_runtime.service
        run_in_background(
            lambda: service.execute(identifier, approved=True),
            lambda _: self.statusBar().showMessage(self.tr("Approved proposal started."), 5000),
            lambda error: QMessageBox.warning(self, self.tr("Agent access"), str(error)),
        )

    def _fill_folder_filter(self) -> None:
        current = self.folder_filter.currentData()
        self.folder_filter.blockSignals(True)
        self.folder_filter.clear()
        self.folder_filter.addItem(self.tr("All Library Folders"), None)
        for f in self.settings.library_folders:
            self.folder_filter.addItem(str(f.path), f.path)
        index = self.folder_filter.findData(current)
        self.folder_filter.setCurrentIndex(max(index, 0))
        self.folder_filter.blockSignals(False)
        self._apply_filters()
        if hasattr(self, "library_workspace"):
            self.library_workspace.refresh()
            self.library_workspace.editor.set_folders(self.settings.library_folders)

    def _apply_filters(self) -> None:
        state = self.state_filter.currentData()  # Qt hands enum data back as plain str
        self.library_proxy.set_filters(
            ItemState(state) if state else None,
            self.folder_filter.currentData(),
            self.library_search.text(),
        )

    def selected_entries(self) -> list[LibraryEntry]:
        rows = self.library_view.selectionModel().selectedRows()
        return [self.library_proxy.data(r, Qt.ItemDataRole.UserRole) for r in rows]

    def _selection_changed(self, selected: QItemSelection, _deselected: QItemSelection) -> None:
        current = self.library_view.currentIndex()
        chosen = self.selected_entries()
        entry = None
        if current.isValid() and self.library_view.selectionModel().isRowSelected(
            current.row(), current.parent()
        ):
            entry = self.library_proxy.data(current.siblingAtColumn(0), Qt.ItemDataRole.UserRole)
        elif chosen:
            entry = chosen[0]
        if self.review.entry is not entry:
            self.review.set_entry(entry)

    # Batch search ----------------------------------------------------------

    def start_batch(self, selected_only: bool) -> None:
        if self.batch is not None:
            return
        pool = self.selected_entries() if selected_only else self.library_model.entries
        entries = auto_searchable(pool)
        if not entries:
            self.statusBar().showMessage(self.tr("No Orphans to search"))
            return
        rules, indexer, searcher, store = (
            self.match_rules(),
            self.indexer(),
            self.searcher(),
            self.store,
        )

        def search(entry: LibraryEntry) -> list[CheckedCandidate]:
            found = searcher(entry, store.item_query(entry.item.path))
            remember_candidates(store, indexer, entry.item.path, found)
            rejections = store.rejections(entry.item.path)
            return check_candidates(indexer, entry.item, found, rules, rejections)

        self._batch_mode = "search"
        self._begin_library_batch(BatchRunner(entries, search))
        self.batch_text = self.tr("Searching {0} Orphans…").format(len(entries))

    def start_library_batch(self, mode: str) -> None:
        if self.batch is not None:
            return
        snapshots = {}
        entries = []
        archives: list[tuple[LibraryEntry, CheckedCandidate]] = []
        for entry in self.library_model.entries:
            if entry.state is ItemState.SEEDED:
                continue
            rejected = self.store.rejections(entry.item.path)
            checked = [
                v
                for v in self.review.cache.get(entry.item.path, [])
                if candidate_key(v.candidate) not in rejected
            ]
            if mode == "reseed":
                archives.extend(
                    (entry, v)
                    for v in checked
                    if v.meta is not None and v.match is not None and v.match.is_full and v.unpack
                )
            eligible = [
                v
                for v in checked
                if (
                    not v.compared
                    if mode == "check"
                    else v.meta is not None
                    and v.match is not None
                    and v.match.is_full
                    and not v.unpack
                )
            ]
            if eligible:
                entries.append(entry)
                snapshots[entry.item.path] = checked if mode == "check" else eligible
        if archives:
            dialog = ReseedDialog(archives, sum(len(v) for v in snapshots.values()), self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            if dialog.archive is not None:
                self.review.reseed_archive(*dialog.archive)
                return
        if not entries:
            self.statusBar().showMessage(
                self.tr("No untested Candidates")
                if mode == "check"
                else self.tr("No Full Matches ready to reseed; archives need individual unpacking")
            )
            return
        indexer = self.indexer() if mode == "check" else None
        client = self.qbit() if mode == "reseed" else None
        rules, store = self.match_rules(), self.store
        seen: set[str] = set()

        def work(entry: LibraryEntry) -> list[CheckedCandidate]:
            result = list(snapshots[entry.item.path]) if mode == "check" else []
            for i, value in enumerate(snapshots[entry.item.path]):
                if runner.cancelled():
                    break
                if candidate_key(value.candidate) in store.rejections(entry.item.path):
                    continue
                try:
                    if mode == "check":
                        if not value.compared:
                            assert indexer is not None
                            result[i] = check_candidate(indexer, entry.item, value.candidate, rules)
                    else:
                        assert (
                            client is not None
                            and value.meta is not None
                            and value.match is not None
                        )
                        infohash = value.meta.infohash.lower()
                        if infohash in seen:
                            continue
                        start_reseed(
                            client,
                            store,
                            entry.item,
                            value.meta,
                            value.match,
                            candidate_key(value.candidate),
                            approve_disk_renames=self.reseed_consent.approve,
                        )
                        seen.add(infohash)
                        result.append(value)
                except AlreadyInClient:
                    assert value.meta is not None
                    seen.add(value.meta.infohash.lower())
                    runner.signals.already_present.emit(entry, value.meta.infohash)
                    continue
                except Exception as error:
                    runner.signals.error.emit(
                        entry, RuntimeError(f"{value.candidate.title}: {error_text(error)}")
                    )
            return result

        runner = BatchRunner(entries, work, orphans_only=False)
        self._batch_mode = mode
        self._begin_library_batch(runner)
        self.batch_text = (
            self.tr("Checking Candidates for {0} Local Items…")
            if mode == "check"
            else self.tr("Reseeding Full Matches for {0} Local Items…")
        ).format(len(entries))

    def _begin_library_batch(self, runner: BatchRunner) -> None:
        self.batch = runner
        self._batch_errors = []
        self._batch_reseeded = 0
        self._batch_existing = 0
        self.batch.signals.searched.connect(self._batch_result)
        self.batch.signals.already_present.connect(self._batch_already_present)
        self.batch.signals.error.connect(self._batch_error)
        self.batch.signals.finished.connect(self._batch_finished)
        self._set_batch_running(True)
        self.upload_tab.throttle_refresh(True)
        self.batch.start()

    def cancel_batch(self) -> None:
        if self.batch is not None:
            self.batch.cancel()
            self.batch_text = self.tr("Cancelling after the current item…")

    def _set_batch_running(self, running: bool) -> None:
        self.batch_selected_action.setEnabled(not running)
        self.batch_all_action.setEnabled(not running)
        self.check_all_action.setEnabled(not running)
        self.reseed_all_action.setEnabled(not running)
        self.scan_action.setEnabled(not running)
        self.rescan_action.setEnabled(not running)
        self.add_folder_action.setEnabled(not running)
        self.review.setEnabled(not running)
        self.cancel_action.setText(self.tr("Cancel batch") if running else self.tr("Cancel search"))
        self.cancel_action.setEnabled(running)
        if running:
            self.countdown.start()
        else:
            self.countdown.stop()

    def _show_batch_progress(self) -> None:
        wait = self._indexer.next_request_in() if self._indexer else 0
        suffix = self.tr(" · next request in {0} s").format(f"{wait:.1f}") if wait > 0.05 else ""
        self.statusBar().showMessage(self.batch_text + suffix)

    def _batch_result(
        self, index: int, total: int, entry: LibraryEntry, checked: list[CheckedCandidate]
    ) -> None:
        if self._batch_mode != "search":
            self.batch_text = self.tr("Processed {0}/{1}: {2}").format(
                index, total, entry.item.path.name
            )
            if self._batch_mode == "reseed":
                self._batch_reseeded += len(checked)
                if checked:
                    self._reseed_started(entry.item.path)
                return
            self.review.remember(entry, checked)
            self.library_model.set_status(entry.item.path, self._summary(checked))
            return
        self.batch_text = self.tr("Searched {0}/{1}: {2}").format(
            index, total, entry.item.path.name
        )
        self.review.remember(entry, checked)
        self.library_model.set_status(entry.item.path, self._summary(checked))

    def _show_match_zen(self, entry: LibraryEntry, checked: list[CheckedCandidate]) -> None:
        seeding = self.zen_tab.seeding_view.seeding
        alongside = seeding.active if seeding else []
        self.library_model.set_zen(
            entry.item.path, match_zen(self.settings.zen, checked, alongside)
        )

    def _summary(self, checked: list[CheckedCandidate]) -> str:
        if any(v.match and v.match.is_full and not v.unpack for v in checked):
            return self.tr("Full match found")
        if any(v.match and v.match.is_full for v in checked):
            return self.tr("Full match inside the archive")
        if any(v.match for v in checked):
            return self.tr("Partial match found")
        if checked:
            return self.tr("No match")
        return self.tr("No Candidates")

    def _batch_error(self, entry: LibraryEntry, error: Exception) -> None:
        if self._batch_mode != "search":
            self._batch_errors.append(f"{entry.item.path.name}: {error_text(error)}")
            return
        self.library_model.set_status(
            entry.item.path, self.tr("Search failed: {0}").format(error_text(error))
        )

    def _batch_already_present(self, entry: LibraryEntry, infohash: str) -> None:
        self._batch_existing += 1
        if self.store.verification(infohash) is not None:
            self._reseed_started(entry.item.path)
        else:
            self.library_model.set_status(entry.item.path, self.tr("Already in torrent client"))

    def _batch_finished(self, done: int) -> None:
        cancelled = self.batch is not None and self.batch.cancelled()
        self.batch = None
        self._set_batch_running(False)
        self.upload_tab.throttle_refresh(False)
        if self._batch_mode != "search":
            text = (
                self.tr("{0} Reseeds started; {1} already in torrent client").format(
                    self._batch_reseeded, self._batch_existing
                )
                if self._batch_mode == "reseed"
                else self.tr("Candidates checked for {0} Local Items").format(done)
            )
            if cancelled:
                text = self.tr("Batch cancelled. {0}").format(text)
            self.statusBar().showMessage(text)
            if self._batch_errors:
                box = QMessageBox(
                    QMessageBox.Icon.Warning, self.tr("Batch completed"), text, parent=self
                )
                box.setInformativeText(
                    self.tr("{0} errors: see details.").format(len(self._batch_errors))
                )
                box.setDetailedText("\n".join(self._batch_errors))
                box.exec()
            return
        self.statusBar().showMessage(self.tr("Batch search finished: {0} searched").format(done))

    def scan(self, refresh: bool = False) -> None:
        if not self.settings.library_folders:
            self.open_settings()
            return
        self.scan_action.setEnabled(False)
        self.rescan_action.setEnabled(False)
        self.add_folder_action.setEnabled(False)
        self.statusBar().showMessage(self.tr("Scanning…"))
        folders = list(self.settings.library_folders)
        previous = list(self.library_model.entries)
        qbit, ignore, store = self.qbit(), self.settings.matching.ignore, self.store
        url = self.settings.indexer.url

        def work():
            client_error = None
            try:
                torrents = indexer_contents(qbit, store, url)
            except Exception as error:
                client_error = error
                torrents = None
            result = build_library(folders, torrents, ignore, store, refresh, previous)
            result.client_error = client_error
            return result

        run_in_background(work, self._scan_done, self._scan_failed)

    def _scan_done(self, entries: list) -> None:  # type: ignore[type-arg]
        self.library_workspace.set_scan_errors(getattr(entries, "errors", []))
        self.library_model.set_entries(entries)
        self.upload_tab.set_entries(entries)
        self.scan_action.setEnabled(True)
        self.rescan_action.setEnabled(True)
        self.add_folder_action.setEnabled(True)
        self.statusBar().showMessage(self.tr("{0} Local Items").format(len(entries)))
        self.restore_searches(entries)
        if client_error := getattr(entries, "client_error", None):
            QMessageBox.warning(
                self,
                self.tr("Seeding status unknown"),
                self.tr("Files were scanned, but the Torrent Client is unavailable. ")
                + error_text(client_error),
            )
        errors = getattr(entries, "errors", [])
        if errors:
            self.statusBar().showMessage(self.tr("Scan incomplete: {0} errors").format(len(errors)))
            box = QMessageBox(
                QMessageBox.Icon.Warning,
                self.tr("Scan incomplete"),
                self.tr(
                    "Some paths could not be read. Previous items for these paths were kept. "
                    "Check that the drive or network share is accessible, then scan again."
                ),
                parent=self,
            )
            box.setDetailedText("\n".join(f"{error.path}: {error.message}" for error in errors))
            box.exec()

    def restore_searches(self, entries: list[LibraryEntry]) -> None:
        """Show each Local Item's last search again, from cached .torrent files only."""
        indexer, rules, store = self.indexer(), self.match_rules(), self.store
        searched = [e for e in entries if e.state is not ItemState.SEEDED]

        def work() -> list[tuple[LibraryEntry, list[CheckedCandidate]]]:
            restored = []
            for entry in searched:
                found = remembered_candidates(store, indexer, entry.item.path)
                if found is None:
                    continue
                rejections = store.rejections(entry.item.path)
                restored.append(
                    (entry, restore_checked(indexer, entry.item, found, rules, rejections))
                )
            return restored

        run_in_background(work, self._searches_restored, self._restore_failed)

    def _searches_restored(
        self, restored: list[tuple[LibraryEntry, list[CheckedCandidate]]]
    ) -> None:
        # Sort once afterwards, not per status and Zen update.
        self.library_proxy.setDynamicSortFilter(False)
        try:
            with self.upload_tab.defer_refresh():
                for entry, checked in restored:
                    if self.library_model.contains(entry):
                        self.review.remember(entry, checked)
                        self.library_model.set_status(entry.item.path, self._summary(checked))
        finally:
            self.library_proxy.setDynamicSortFilter(True)

    def _restore_failed(self, error: Exception) -> None:
        log.warning("could not restore previous searches: %s", error)

    def _scan_failed(self, error: Exception) -> None:
        self.scan_action.setEnabled(True)
        self.rescan_action.setEnabled(True)
        self.add_folder_action.setEnabled(True)
        self.statusBar().showMessage(self.tr("Scan failed; showing the previous scan"))
        QMessageBox.warning(self, self.tr("Scan failed"), error_text(error))

    # Verification ----------------------------------------------------------

    def _reseed_started(self, path: Path) -> None:
        self.library_model.set_status(path, self.tr("Verifying…"))
        self.verify_timer.start()

    def check_verifications(self) -> None:
        if self._checking:
            return
        self._checking = True
        targets = [
            (self._connections.client(self.settings, p.id), self.store.for_client(p.id))
            for p in self.settings.client_profiles
            if p.enabled
            and (
                p.id == self.settings.active_client_id
                or self.store.for_client(p.id).verification_hashes()
            )
        ]

        def work() -> tuple[list[Outcome], list[Path]]:
            outcomes: list[Outcome] = []
            pending: list[Path] = []
            for client, store in targets:
                try:
                    completed = check_verifications(client, store)
                    waiting = pending_verifications(client, store)
                    if store.client_id == self.settings.active_client_id:
                        outcomes += completed
                        pending += waiting
                except Exception:
                    log.warning("Verification unavailable for client %s", store.client_id)
            return outcomes, pending

        run_in_background(work, self._verified, self._verify_error)

    def _verified(self, result: tuple[list[Outcome], list[Path]]) -> None:
        self._checking = False
        outcomes, pending = result
        for outcome in outcomes:
            if outcome.verified and outcome.started:
                text = self.tr("Reseeded")
            elif outcome.verified:
                text = self.tr("Verified, left stopped: some files are absent")
            elif outcome.problem:
                text = self.tr("Reseed undone: {0}").format(outcome.problem)
            else:
                text = self.tr("Verification failed at {0}").format(f"{outcome.progress:.1%}")
            self.library_model.set_status(outcome.item_path, text)
        unpacked = [(o, self.store.take_unpacked(o.item_path)) for o in outcomes]
        for path in pending:
            self.library_model.set_status(path, self.tr("Verifying…"))
        if pending or any(
            self.store.for_client(p.id).verification_hashes()
            for p in self.settings.client_profiles
            if p.enabled
        ):
            self.verify_timer.start()
        else:
            self.verify_timer.stop()
        for outcome, archive in unpacked:
            if archive is not None and outcome.verified and outcome.started:
                self.offer_archive_removal(outcome.item_path, archive)
        if any(outcome.disk_renamed for outcome in outcomes):
            self.scan()

    def offer_archive_removal(self, folder: Path, archive: Path) -> None:
        """After an unpacked archive's Reseed is verified, offer to put the archive in the
        trash: its contents now seed from `folder` (ADR-0007)."""
        if not archive.is_file() or not folder.is_dir():
            return
        box = QMessageBox(
            QMessageBox.Icon.Question,
            self.tr("Unpack and Reseed"),
            self.tr(
                "{0} now seeds: your torrent client verified every file. They are the contents of "
                "{1}, so the archive ({2}) is no longer needed.\n\nMove it to the trash?"
            ).format(folder.name, archive.name, human_size(archive.stat().st_size)),
            parent=self,
        )
        trash = box.addButton(self.tr("Move to the trash"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(self.tr("Keep the archive"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not trash:
            log.info("archive kept after unpacking: %s", archive)
            return
        if QFile.moveToTrash(str(archive)):
            log.info("archive moved to the trash after unpacking: %s", archive)
        else:
            answer = QMessageBox.question(
                self,
                self.tr("Unpack and Reseed"),
                self.tr(
                    "That disk has no trash. Delete {0} permanently? This cannot be undone."
                ).format(archive.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                log.info("archive kept, no trash on its disk: %s", archive)
                return
            archive.unlink()
            log.info("archive deleted after unpacking: %s", archive)
        self.statusBar().showMessage(self.tr("{0} removed").format(archive.name), 10000)
        self.scan()  # the archive leaves the Library

    def _verify_error(self, error: Exception) -> None:
        self._checking = False  # the timer keeps running: the next poll retries
        self.statusBar().showMessage(self.tr("Could not check Verifications: {0}").format(error))
