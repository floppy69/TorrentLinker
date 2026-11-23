from __future__ import annotations

import errno
import logging
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QFile, QSignalBlocker, Qt, QTimer, QTranslator
from PySide6.QtGui import QAction, QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
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
from torrentlinker.catalogue_sync import (
    LISTED_ROOTS,
    ROOT_NAMES,
    SNAPSHOT_NAME,
    TORZNAB_ONLY_CATEGORIES,
    fetch_all,
    fetch_root,
    refresh_catalogue,
    refresh_due,
    root_categories,
    save_site_counts,
    site_counts,
    sync_catalogue,
)
from torrentlinker.catalogue_workspace import catalogue_cards
from torrentlinker.category_tags import sync_category_tags
from torrentlinker.config import MEDIA_HORIZON_VIEWS, MEDIA_LAYOUTS, Settings
from torrentlinker.credentials import get_secret
from torrentlinker.domain import ContentKind, ItemState, LibraryFolder
from torrentlinker.downloads import IndexerCategory
from torrentlinker.ebooks import UNLOCK_COUNT, book_categories, book_roots, seeded_ebooks
from torrentlinker.gui.batch_runner import BatchRunner
from torrentlinker.gui.catalogue_runner import CatalogueRunner
from torrentlinker.gui.documentation import DocumentationTab
from torrentlinker.gui.ebook_reader import ReadingRoom
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.library_model import LibraryModel, human_size
from torrentlinker.gui.library_workspace import LibraryWorkspace
from torrentlinker.gui.reseed_consent import ReseedConsent
from torrentlinker.gui.reseed_dialog import ReseedDialog
from torrentlinker.gui.review_panel import ReviewPanel, Searcher
from torrentlinker.gui.search_workspace import SearchTab
from torrentlinker.gui.send_runner import SendRunner
from torrentlinker.gui.settings_common import (
    INDEXER_API_KEY,
    PROXY_PASSWORD,
    TMDB_API_KEY,
    choose_directory,
    extra_indexer_keys,
)
from torrentlinker.gui.settings_view import SettingsPage
from torrentlinker.gui.shell_host import ShellHost
from torrentlinker.gui.shell_view import WORKSPACES, ShellView
from torrentlinker.gui.tasks import run_in_background, run_with_progress
from torrentlinker.gui.theme import set_theme
from torrentlinker.gui.torrents_view import TorrentsTab
from torrentlinker.gui.update_notice import UpdateNotice
from torrentlinker.gui.upload_eligibility import UploadEligibility
from torrentlinker.gui.zen_view import ZenBand, ZenTab
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.library import (
    LibraryEntry,
    auto_searchable,
    build_library,
    indexer_contents,
    pack_episodes,
)
from torrentlinker.matching import MatchRules
from torrentlinker.paths import MappedQbit
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
from torrentlinker.qbit import AlreadyInClient
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
    find_candidates,
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
TORRENT_CLIENTS_EVERY = 60.0  # seconds between Profile reads of the Torrent Clients


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, settings_path: Path, store: Store) -> None:
        super().__init__()
        settings.ensure_profiles()
        store = store.for_client(settings.active_client_id)
        self.settings = settings
        self.settings_path = settings_path
        from torrentlinker.companion import CompanionReceiver
        from torrentlinker.profile_history import ProfileHistory
        from torrentlinker.profile_workspace import ProfileWorkspace

        self.account_workspace = ProfileWorkspace(
            settings_path.parent, history=ProfileHistory(store)
        )
        self.companion_receiver: CompanionReceiver | None = None
        self._profile_refreshing = False
        self._torrent_clients_busy = False
        self._scan_stop = threading.Event()
        self._avatar_token: str | None = None
        self._torrent_clients_at = -TORRENT_CLIENTS_EVERY
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
        self.apply_proxy()
        self._indexer_proxy = net.current()  # what the Indexer, once made, goes through
        self.running_version = installed_version()
        self.setWindowTitle(f"TorrentLinker {self.running_version}")
        available = self.screen().availableGeometry()
        self.resize(min(1280, available.width() - 40), min(800, available.height() - 60))

        toolbar = QToolBar(self.tr("Library"), self)
        toolbar.setMovable(False)
        toolbar.hide()
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
        match_toolbar.hide()
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
        self._batch_failed = 0
        self._batch_position = (0, 0)
        # A batch's bar, then its text, on the footer's left. A status message would hide
        # them, so the text is shown here instead while the batch runs.
        self.batch_status = QWidget()
        batch_status_box = QHBoxLayout(self.batch_status)
        batch_status_box.setContentsMargins(0, 0, 0, 0)
        self.batch_progress = QProgressBar()
        self.batch_progress.setFixedWidth(160)
        self.batch_progress.setTextVisible(False)
        self.batch_label = QLabel()
        batch_status_box.addWidget(self.batch_progress)
        batch_status_box.addWidget(self.batch_label, 1)
        self.batch_status.hide()
        self.countdown = QTimer(self)
        self.countdown.setInterval(250)
        self.countdown.timeout.connect(self._show_batch_progress)

        self.library_model = LibraryModel()
        self.reseed_consent = ReseedConsent(self, lambda: self.settings.client.display_name)
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
        self.review.reseed_started.connect(self._reseed_started)
        self.review.candidates_checked.connect(self._show_match_zen)
        self.zen_tab = ZenTab(self.seeding_loader, lambda: self.settings.zen, settings.uploads)
        from torrentlinker.gui.community_view import CommunityView

        self.community_view = CommunityView(
            self.account_workspace, i18n.pick_language(self.settings.language)
        )
        self.zen_tab.pages.addTab(self.community_view, self.tr("Community"))
        self.zen_tab.profile_view.language = self.settings.language
        self.zen_tab.catalogue.language = self.settings.language
        self.zen_tab.profile_view.refresh_requested.connect(self.refresh_profile)
        self.zen_tab.profile_view.refresh_requested.connect(self.refresh_torrent_clients)
        self.profile_timer = QTimer(self)
        self.profile_timer.setInterval(3000)
        self.profile_timer.timeout.connect(self._poll_account_profile)
        self._profile_held = False
        self.profile_timer.start()
        self.show_account_profile()
        self.zen_tab.seeding_view.uploads_changed.connect(self._uploads_changed)
        self.zen_tab.seeding_view.language = self.settings.language
        self.zen_tab.seeding_view.client = lambda: self.settings.active_client_id
        self.zen_tab.seeding_view.scope = str(self.settings_path.resolve())
        from torrentlinker.gui.workspace_tabs import WorkspaceTabs

        self.tabs = WorkspaceTabs()
        self.tabs.addTab(self.zen_tab, self.tr("Zen"))
        self.library_workspace = LibraryWorkspace(self, toolbar, match_toolbar)
        self.review.recovery_requested.connect(self.library_workspace.reseed.open_recovery)
        self.tabs.addTab(self.library_workspace, self.tr("Library"))
        self.upload_tab = UploadEligibility(self)
        self.review.candidates_checked.connect(self.upload_tab.remember)
        self.review.upload_blocker = self.upload_tab.why_not
        self.review.upload_requested.connect(self._open_upload)
        from torrentlinker.gui.upload_workspace import UploadBoard

        self.upload_workspace = UploadBoard(self)
        self.tabs.addTab(self.upload_workspace, self.tr("Upload"))
        self.search_tab = SearchTab(self)
        self.tabs.addTab(self.search_tab, self.tr("Search"))
        from torrentlinker.gui.feeds import FeedsTab

        self.feeds_tab = FeedsTab(lambda: self.assistant_service().agent.feed_control, self)
        self.tabs.addTab(self.feeds_tab, self.tr("RSS"))
        self.search_tab.subscribe_requested.connect(lambda query: self.feeds_tab.edit(query=query))
        self.torrents_tab = TorrentsTab(self)
        self.tabs.addTab(self.torrents_tab, self.tr("Torrents"))
        from torrentlinker.gui.assistant_view import AssistantPanel

        self.assistant_tab = AssistantPanel(self.assistant_service)
        self.assistant_tab.connectionsRequested.connect(self.open_assistant_connections)
        self.tabs.addTab(self.assistant_tab, self.tr("Assistant"))
        from torrentlinker.gui.media import MediaTab

        self.media_tab = MediaTab(
            self.assistant_service,
            lambda: self.settings.active_client_id,
            self.add_library_folder,
        )
        self.media_tab.set_media_layout(settings.media_layout)
        self.media_tab.set_media_horizon(settings.media_horizon)
        self.media_tab.set_adult(settings.adult_content)
        self.media_tab.refresh_on_first_open = True
        self.media_tab.layout_changed.connect(self._save_media_layout)
        self.media_tab.horizon_changed.connect(self._save_media_horizon)
        self.media_tab.center_mode_requested.connect(self.set_media_center)
        self.media_tab.client_requested.connect(self._media_client_requested)
        self.media_tab.video_playing_changed.connect(self._video_playing_changed)
        self.media_tab.connections_requested.connect(self.open_assistant_connections)
        self.media_tab.discussion_requested.connect(self.open_media_discussion)
        self.tabs.addTab(self.media_tab, self.tr("Media"))
        self.search_tab.manage_requested.connect(self.open_torrents)
        self.band = ZenBand(language=settings.language)
        self.band.refresh_requested.connect(self.refresh_profile)
        self.zen_tab.seeding_view.updated.connect(self.band.set_seeding)
        self.zen_tab.seeding_view.updated.connect(self.search_tab.set_seeding)
        self.zen_tab.seeding_view.updated.connect(self.library_model.set_seeding)
        self.zen_tab.seeding_view.unavailable.connect(lambda: self.library_model.set_seeding(None))
        self.zen_tab.seeding_view.updated.connect(self._update_reading_room)
        self.zen_tab.seeding_view.unavailable.connect(self._lock_reading_room)
        self.reading_room: ReadingRoom | None = None
        self._reader_view: Seeding | None = None
        self._reader_unlocked = False
        self.tabs.tabBar().hide()
        self.aggregate_clients = False
        self.setup_needed = False
        self.documentation_tab: DocumentationTab | None = None
        self.shell_host = ShellHost(self)
        self.navigation = ShellView("navigation", self.shell_host.snapshot, self.shell_host.command)
        self.sidebar = self.navigation
        self.sidebar.setFixedWidth(190)
        self.tabs.currentChanged.connect(self._sync_navigation)
        self.band.profile_notice_changed.connect(lambda _: self.shell_host.refresh())
        central = QWidget()
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self.sidebar)
        self.shell_layout = shell
        content = QWidget()
        central_layout = QVBoxLayout(content)
        self.content_layout = central_layout
        central_layout.setContentsMargins(24, 20, 24, 12)
        central_layout.setSpacing(16)
        self.app_header = ShellView("header", self.shell_host.snapshot, self.shell_host.command)
        central_layout.addWidget(self.app_header)
        self.update_notice = UpdateNotice(language=settings.language)
        central_layout.addWidget(self.update_notice)
        self.statusBar().addWidget(self.batch_status, 1)
        self.statusBar().addPermanentWidget(self.band, 3)
        # A wide workspace must not impose its minimum size on the desktop window.
        # Keep navigation and the status band visible; scroll only the workspace.
        self.workspace_scroll = QScrollArea()
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.workspace_scroll.setWidget(self.tabs)
        central_layout.addWidget(self.workspace_scroll, 1)
        shell.addWidget(content, 1)
        self.tabs.currentChanged.connect(self._workspace_changed)
        self.tabs.currentChanged.connect(self._settings_navigation)
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
        from torrentlinker.gui.plan_host import PlanHost

        self.plan_host = PlanHost(self)
        self.zen_tab.plan_view.language = settings.language
        self.zen_tab.plan_view.make_requested.connect(self.make_plan)
        self.zen_tab.plan_view.categories_changed.connect(self._plan_categories_changed)
        self.zen_tab.plan_view.set_options(self.settings.plan_options)
        self.zen_tab.plan_view.options_changed.connect(self._plan_options_changed)
        self.zen_tab.plan_view.stop_fetch_requested.connect(self._stop_plan_fetch)
        self.offer_plan_categories()
        self.zen_tab.plan_view.send_requested.connect(self.send_plan)
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
        self._single_root: int | None = None
        self._card_phase = "running"
        self._cards_drawn = 0.0
        self._site_counted = 0.0
        self._panel_fetch = False
        self.zen_tab.pages.currentChanged.connect(self._zen_page_changed)
        self.zen_tab.catalogue.start_requested.connect(lambda: self.crawl_catalogue())
        self.zen_tab.catalogue.category_requested.connect(self.crawl_catalogue)
        self.zen_tab.catalogue.pause_requested.connect(self.pause_catalogue)
        self.zen_tab.catalogue.plan_requested.connect(self._catalogue_plan_now)
        self._show_catalogue_age()
        self.verify_timer = QTimer(self)
        self.verify_timer.setInterval(3000)
        self.verify_timer.timeout.connect(self.check_verifications)
        self.seeding_timer = QTimer(self)
        self.seeding_timer.setInterval(30_000)
        self.seeding_timer.timeout.connect(self._refresh_seeding_quietly)
        self._seeding_held = False
        self._settings_page: SettingsPage | None = None  # while Settings is open
        self._settings_stack: ExitStack | None = None
        self._settings_timers: list[QTimer] = []
        self._settings_folders: list = []
        self._settings_return = 0
        self._settings_from_media_center = False
        # Checks often, fetches only once the whole Catalogue is REFRESH_INTERVAL old.
        self.catalogue_refresh_timer = QTimer(self)
        self.catalogue_refresh_timer.setInterval(10 * 60_000)
        self.catalogue_refresh_timer.timeout.connect(self.refresh_whole_catalogue)
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
        self.setup_needed = True
        self.shell_host.refresh()
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
        self.setup_needed = False
        self.shell_host.refresh()
        self.tabs.setEnabled(True)
        for index in range(self.tabs.count()):
            self.tabs.setTabEnabled(index, True)
        self.band.setEnabled(True)
        self.statusBar().showMessage(self.tr("Ready"))
        self.seeding_timer.start()
        self.catalogue_refresh_timer.start()
        QTimer.singleShot(0, self.check_verifications)
        QTimer.singleShot(0, self.zen_tab.seeding_view.reload)
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

    def open_torrents(self, hash: str = "") -> None:
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.feeds_tab) + 1)
        self.torrents_tab.focus_torrent(hash)

    def _workspace_changed(self, index: int) -> None:
        if (
            getattr(self, "media_center_active", False)
            and self.tabs.widget(index) is not self.media_tab
        ):
            self.set_media_center(False)
        self._sync_app_header()
        self._sync_workspace_scrolling()
        self.workspace_scroll.horizontalScrollBar().setValue(0)
        if self.tabs.widget(index) is self.zen_tab:  # opening on the Catalogue page
            self._zen_page_changed(self.zen_tab.pages.currentIndex())
        self.workspace_scroll.verticalScrollBar().setValue(0)
        if self.tabs.widget(index) is not self.torrents_tab:
            self.aggregate_clients = False
        zen = index < len(WORKSPACES) and index not in {5, 6, 7}
        self.band.setVisible(zen)
        self.shell_host.refresh()
        policy = (
            QSizePolicy.Policy.Ignored
            if index >= len(WORKSPACES) or index in {5, 6, 7}
            else QSizePolicy.Policy.Preferred
        )
        self.tabs.setSizePolicy(policy, policy)
        if self.tabs.currentWidget() is self.assistant_tab:
            self.assistant_tab.activate()
        if self.tabs.currentWidget() is self.media_tab:
            self.media_tab.activate()
        if self.reading_room is not None and self.tabs.currentWidget() is self.reading_room:
            self.reading_room.activate()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "shell_layout"):
            return
        compact = self.width() < 650
        self.shell_layout.setDirection(
            QHBoxLayout.Direction.TopToBottom if compact else QHBoxLayout.Direction.LeftToRight
        )
        if compact:
            self.sidebar.setMinimumWidth(0)
            self.sidebar.setMaximumWidth(16777215)
        else:
            self.sidebar.setFixedWidth(190)
            self.sidebar.setMinimumHeight(0)
            self.sidebar.setMaximumHeight(16777215)
        self.shell_host.refresh()

    def _sync_navigation(self, index: int) -> None:
        self.shell_host.refresh()

    def _update_reading_room(self, view: Seeding) -> None:
        if seeded_ebooks(view) < UNLOCK_COUNT:
            self._lock_reading_room()
            return
        self._reader_unlocked = True
        self._reader_view = view
        self.shell_host.refresh()
        if self.reading_room is not None:
            self.reading_room.set_roots(
                book_roots(self.settings, view), book_categories(self.settings, view)
            )

    def _lock_reading_room(self) -> None:
        self._reader_unlocked = False
        self._reader_view = None
        self.shell_host.refresh()
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
            self.assistant_tab.focus_composer()
            return
        if self.reading_room is not None and self.tabs.currentWidget() is self.reading_room:
            self.reading_room.filter.setFocus()
            return
        if self.tabs.currentWidget() is self.search_tab:
            self.search_tab.focus_search()
            return
        self.tabs.setCurrentIndex(1)
        self.library_workspace.reseed.focus_search()

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
        return self._connections.client(self.settings)

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
        self.zen_tab.profile_view.set_busy(True)
        credentials = (self.settings.indexer.url, get_secret(INDEXER_API_KEY))
        run_in_background(
            lambda: self.account_workspace.refresh(*credentials),
            self._profile_read,
            self._profile_failed,
        )

    def show_account_profile(self) -> None:
        self.account_workspace.bind(self.settings.indexer.url, get_secret(INDEXER_API_KEY))
        state = self.account_workspace.state()
        self.zen_tab.profile_view.show_state(state, self.account_workspace.history_days())
        if state.get("avatar") != self._avatar_token:
            self._avatar_token = state.get("avatar")
            image = self.account_workspace.avatar()
            self.zen_tab.profile_view.show_avatar(image[0] if image else None)
        if state["paired"] and self.companion_receiver is None:
            if time.monotonic() >= self._receiver_retry_at:
                self._receiver_retry_at = time.monotonic() + 30
                try:
                    self._start_companion_receiver()
                except OSError:
                    self.zen_tab.profile_view.show_notice(
                        self.tr(
                            "Browser connection unavailable. "
                            "Close the other TorrentLinker instance; retrying automatically."
                        )
                    )

    def _poll_account_profile(self) -> None:
        """The 3-second Profile poll. Its keyring read and view refresh take 40 to 85 ms on
        the GUI thread, a dropped frame each time, so it waits for a video to stop."""
        if self.media_tab.video_playing:
            self._profile_held = True
            return
        self.show_account_profile()
        if time.time() >= self.account_workspace.state()["refresh_after"]:
            self.refresh_profile()
        # Torrent Clients are asked at most once a minute, while Profile is shown.
        if (
            self.zen_tab.profile_view.isVisible()
            and time.monotonic() - self._torrent_clients_at >= TORRENT_CLIENTS_EVERY
        ):
            self.refresh_torrent_clients()

    def refresh_torrent_clients(self) -> None:
        """Seeding per Torrent Client and today's Zen Estimate for the Profile view."""
        from torrentlinker.profile_history import active_seeds
        from torrentlinker.profile_overview import torrent_clients_overview

        if not isValid(self) or self._torrent_clients_busy or not self._startup_complete:
            return  # before setup, a window contacts no client
        self._torrent_clients_busy = True
        self._torrent_clients_at = time.monotonic()

        def failing(error: Exception) -> Callable[[], list]:
            def fetch() -> list:
                raise error

            return fetch

        targets: list[tuple[str, Callable[[], list]]] = []
        for profile in self.settings.client_profiles:
            if not profile.enabled:
                continue
            try:
                client = self._connections.client(self.settings, profile.id)
                targets.append((profile.name, partial(client.torrents, with_files=False)))
            except Exception as error:  # shown as unavailable
                targets.append((profile.name, failing(error)))
        seeds = active_seeds(self.account_workspace.state().get("companion"))
        zen, url, uploads = self.settings.zen, self.settings.indexer.url, self.settings.uploads

        def done(result: dict) -> None:
            self._torrent_clients_busy = False
            if isValid(self):
                self.zen_tab.profile_view.show_torrent_clients(result)

        def failed(error: Exception) -> None:
            self._torrent_clients_busy = False
            log.info("Profile clients not read: %s", error)

        run_in_background(
            lambda: torrent_clients_overview(zen, targets, url, seeds, uploads), done, failed
        )

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
            QDesktopServices.openUrl(QUrl(connection_url(address, pairing["code"], account_id)))
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, self.tr("Browser companion"), str(error))

    def set_session_downloads(self, enabled: bool) -> None:
        try:
            self.account_workspace.set_session_downloads(enabled)
        except ValueError as error:
            QMessageBox.warning(self, self.tr("Browser companion"), str(error))

    def disconnect_companion(self) -> None:
        self.account_workspace.disconnect()
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
        self.zen_tab.profile_view.set_busy(False)
        self.show_account_profile()
        self.band.show_profile(profile)
        filled = profile.apply(self.settings.zen)
        if filled != self.settings.zen:
            self._update_settings(zen=filled)
            log.info("Zen Profile filled from c411: %s", filled)
            self.zen_tab.seeding_view.reload()

    def _profile_failed(self, error: Exception) -> None:
        self._profile_refreshing = False
        if not isValid(self):
            return
        self.zen_tab.profile_view.set_busy(False)
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
        folders = s.download_folders
        cats = {c: s.indexer_categories[c] for c in s.visible_categories(s.indexer_categories)}
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
        self._plan_options_changed(self.settings.plan_options)

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

    def plan_maker(self) -> Callable[[], Plan]:
        """Build on the GUI thread the work that makes a Plan (no Indexer request)."""
        s = self.settings
        if self._plan_destinations != {s.active_client_id: 0}:
            from torrentlinker.multi_plan import distributed_plan

            clients = {i: self._connections.client(s, i) for i in self._plan_destinations}
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
                adult=s.adult_content,
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
        if plan.items:
            notices.append(
                self.tr(
                    "Provisional estimates from cached metadata. Seeder counts update from "
                    "your torrent client after tracker responses."
                )
            )
        self.zen_tab.plan_view.set_notice("\n".join(notices))
        self.band.set_plan(plan.zen_added if plan.items else None)

    def confirm_send(self) -> None:
        self.zen_tab.plan_view.open_review()

    def test_speed(self) -> None:
        self.zen_tab.plan_view.speed_testing()
        run_in_background(measure_download_speed, self._speed_measured, self._speed_failed)

    def _speed_measured(self, speed: float) -> None:
        self._update_settings(
            download_speed=speed,
            download_speed_tested=datetime.now().isoformat(timespec="minutes"),
        )
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
        self._sending_plan: Plan | None = plan
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
        plan = getattr(self, "_sending_plan", None) or self.zen_tab.plan_view.plan
        self.band.set_sending(progress, plan.zen_added if plan and plan.items else None)

    def _send_ended(self) -> None:
        self.send_runner = None
        self.store.set_plan_sending(False)
        self.zen_tab.plan_view.sending(None)
        self.band.set_sending(None)

    def _send_failed(self, error: Exception) -> None:
        self._send_ended()
        self._sending_plan = None
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
        view.set_notice(left.format(len(plan.items)))
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
        self._sending_plan = None
        self._send_ended()
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
        self.zen_tab.plan_view.show_report(report)
        self.zen_tab.seeding_view.reload()
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
                self._update_settings(indexer_categories=categories)
                self.search_tab.refresh_categories()
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

    def _refresh_seeding_quietly(self) -> None:
        """The 30-second Seeding refresh. It reads every seeded torrent in Python, holding
        the interpreter lock long enough to drop video frames, so it waits for a video to
        stop, then runs once."""
        if self.media_tab.video_playing:
            self._seeding_held = True
            return
        self.zen_tab.seeding_view.reload(quiet=True)

    def _video_playing_changed(self, playing: bool) -> None:
        if not playing and self._seeding_held:
            self._seeding_held = False
            self._refresh_seeding_quietly()
        if not playing and self._profile_held:
            self._profile_held = False
            self._poll_account_profile()

    def refresh_whole_catalogue(self) -> bool:
        """Every few hours, the newest torrents of every category (timer). Waits for any
        other Catalogue work; False if nothing was started."""
        if (
            self.catalogue_runner is not None
            or self.media_tab.video_playing  # the next check, after the film, catches up
            or not get_secret(INDEXER_API_KEY)
            or not refresh_due(self.store)
        ):
            return False
        indexer, store = self.indexer(), self.store
        categories = dict(self.settings.indexer_categories)

        def work(stop: Callable[[], bool], progress: Progress) -> None:
            log.info("Refreshing the whole Catalogue")
            refresh_catalogue(indexer, store, categories, stop=stop, progress=progress)

        self._run_catalogue(work)
        return True

    def crawl_catalogue(self, root: int | None = None) -> None:
        """Fetch every category of the Indexer, resuming a paused crawl, or only the c411
        category `root` (user action, from the Catalogue panel)."""
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
            if indexer.is_c411:
                # Category by category, each to parity with the site: every page, the
                # big ones year by year, then the torrents c411 has deleted removed.
                if root is not None:
                    position[:] = [1, 1]
                    fetch_root(indexer, store, root, stop=stop, progress=progress)
                    return
                if not fetch_all(
                    indexer,
                    store,
                    stop=stop,
                    progress=progress,
                    position=lambda done, total: position.__setitem__(slice(None), [done, total]),
                ):
                    return
            wanted = (
                sorted(root_categories(root)) if root is not None else crawl_categories(categories)
            )
            if indexer.is_c411:  # XXX: only c411's Torznab search returns it
                wanted = [c for c in wanted if c in TORZNAB_ONLY_CATEGORIES]
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
        self._single_root = root
        self._panel_fetch = True
        self._card_phase = "running"
        self.zen_tab.catalogue.set_state(True, False)
        self._run_catalogue(work)
        self._show_catalogue_cards()

    def _catalogue_plan_now(self) -> None:
        self.zen_tab.pages.setCurrentIndex(2)
        self.make_plan()
        if self._pending_plan is not None:
            self._stop_plan_fetch()

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
        if p.source == "c411-prune":
            self._card_phase = "prune"
            if time.monotonic() - self._cards_drawn >= 2:
                self._show_catalogue_cards()
        if p.source in (SNAPSHOT_NAME, "c411-prune"):
            text = (
                self.tr("Importing Zen Lab metadata: {0} torrents (+{1})").format(p.offset, p.added)
                if p.source == SNAPSHOT_NAME
                else self.tr(
                    "Checking torrents no longer listed: {0} checked, {1} deleted on c411"
                ).format(p.pages, -p.added)
            )
            # Progress goes on the footer's left; its right keeps the Zen figures.
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
        self._card_phase = {"c411-capped": "year", "c411-prune": "prune"}.get(p.source, "running")
        if time.monotonic() - self._cards_drawn >= 2:
            self._show_catalogue_cards()
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
        self._single_root = None
        self._show_catalogue_age()
        if self._panel_fetch:  # a fetch from the Catalogue panel: compare with c411 again
            self._panel_fetch = False
            self.refresh_site_counts()
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

    def _fetching_root(self) -> int | None:
        """The c411 category being fetched now, if any."""
        if self.catalogue_runner is None or not self.zen_tab.catalogue.running:
            return None
        if self._single_root is not None:
            return self._single_root
        done, _total = self._crawl_position
        return LISTED_ROOTS[done - 1] if 0 < done <= len(LISTED_ROOTS) else None

    def _show_catalogue_cards(self) -> None:
        """One card per c411 category: the Catalogue's count against the site's."""
        self._cards_drawn = time.monotonic()
        current = self._fetching_root()
        self.zen_tab.catalogue.set_cards(
            catalogue_cards(
                self.store,
                adult=self.settings.adult_content,
                current=current,
                phase=self._card_phase,
                single_root=self._single_root,
            )
        )
        if current is not None:
            done, total = self._crawl_position
            self.zen_tab.catalogue.set_phase(
                self.tr("Category {0}/{1}: {2}").format(
                    max(done, 1), max(total, 1), ROOT_NAMES.get(current, str(current))
                ),
                (max(done, 1) - 1) / max(total, 1),
            )
        elif not self.zen_tab.catalogue.running:
            self.zen_tab.catalogue.set_phase(
                self.tr(
                    "Fetch every category, or one with its ⟳ button. A fetch reads it again "
                    "in full, then removes what c411 deleted."
                )
            )

    def _sync_workspace_scrolling(self) -> None:
        page = self.zen_tab.pages.currentWidget()
        self.zen_tab.setProperty("ownsScrolling", bool(page.property("ownsScrolling")))
        owns_scroll = bool(self.tabs.currentWidget().property("ownsScrolling"))
        policy = QSizePolicy.Policy.Ignored if owns_scroll else QSizePolicy.Policy.Preferred
        self.tabs.setSizePolicy(policy, policy)
        self.tabs.updateGeometry()

    def _zen_page_changed(self, index: int) -> None:
        self._sync_workspace_scrolling()
        if self.zen_tab.pages.widget(index) is self.zen_tab.catalogue_page:
            self.refresh_site_counts(max_age=3600)

    def refresh_site_counts(self, max_age: float = 0) -> None:
        """c411's count per category, for the cards: one request in the background, when
        the Catalogue page opens (at most hourly) and after each fetch."""
        if not get_secret(INDEXER_API_KEY) or time.time() - self._site_counted < max_age:
            return
        self._site_counted = time.time()
        indexer, store = self.indexer(), self.store
        if not indexer.is_c411:
            return

        def work() -> None:
            with indexer.background():
                save_site_counts(store, site_counts(indexer))

        def done(_result: object) -> None:
            if isValid(self):
                self._show_catalogue_cards()

        run_in_background(work, done, lambda error: log.info("c411 counts: %s", error))

    def _show_catalogue_age(self) -> None:
        self._show_catalogue_cards()
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
        self._scan_stop.set()
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
        if self.settings_path.exists():
            self._update_settings(uploads=uploads)
        else:
            self.settings.uploads = uploads

    def _update_settings(self, **fields: object) -> None:
        """Record what a background task learned. Settings may be open meanwhile: it edits
        its own copy and saves it as the owner goes, so both copies take the new values and
        the newest one is written. Without this, closing Settings dropped the update, and
        the update had overwritten what Settings had just saved."""
        targets = [self.settings]
        if self._settings_page is not None:
            targets.append(self._settings_page.setup.settings)
        for target in targets:
            for name, value in fields.items():
                setattr(target, name, value)
        targets[-1].save(self.settings_path)

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
        self.tabs.setCurrentWidget(self.upload_workspace)
        self.upload_tab.select(entry.item.path)

    @agent_settings_change
    def add_library_folder(self) -> None:
        if not self.add_folder_action.isEnabled():
            return
        self.tabs.setCurrentWidget(self.library_workspace)
        self.library_workspace.open_folders()
        self.library_workspace.reseed.folder_dialog_request += 1
        self.library_workspace.reseed.refresh()

    @agent_settings_change
    def save_library_folders(self, folders: list[LibraryFolder], *, scan: bool = True) -> bool:
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
        if folders and scan:
            self.scan()
        return True

    @agent_settings_change
    def save_reseed_folder(self, path: str, layout: str | None = None) -> bool:
        if layout is not None and layout not in {"auto", "client", "links"}:
            raise ValueError("Unknown Reseed layout.")
        self.settings.profile().reseed_link_root = path
        if layout is not None:
            self.settings.profile().reseed_layout = layout
        self.settings.save(self.settings_path)
        if self.agent_runtime:
            self.agent_runtime.reset(self.settings)
        return True

    @agent_settings_change
    def save_new_client_profile(self, profile, secrets, values) -> bool:
        secrets.update(values)
        self.settings.client_profiles.append(profile)
        try:
            self.settings.save(self.settings_path)
        except Exception:
            self.settings.client_profiles.remove(profile)
            raise
        if self.agent_runtime:
            self.agent_runtime.reset(self.settings)
        self.shell_host.refresh()
        return True

    def _media_client_requested(self, identifier: str) -> None:
        # The same switch as the page header's, which Media hides.
        try:
            self.shell_host.command("client", {"client_id": identifier})
        except ValueError as error:
            self.media_tab._set_notice(str(error))

    def _sync_app_header(self) -> None:
        # Media has its own menu: the page header and the space above it would only take
        # room from the films.
        center = getattr(self, "media_center_active", False)
        media = self.tabs.currentWidget() is self.media_tab
        self.app_header.setVisible(not center and not media)
        self.content_layout.setContentsMargins(
            *((0, 0, 0, 0) if center else (24, 0 if media else 20, 24, 12))
        )
        self.content_layout.setSpacing(0 if center else 16)

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
        self._sync_app_header()
        self.statusBar().setVisible(not enabled and self._media_status_visible)
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

    def _save_media_horizon(self, value: str) -> None:
        if value not in MEDIA_HORIZON_VIEWS:
            return
        self.settings.media_horizon = value
        self.settings.save(self.settings_path)

    def _save_media_layout(self, value: str) -> None:
        if value not in MEDIA_LAYOUTS:
            return
        self.settings.media_layout = value
        self.settings.save(self.settings_path)

    def _select_client(self, identifier: str) -> None:
        if identifier == self.settings.active_client_id:
            return
        from PySide6.QtCore import QThreadPool

        if QThreadPool.globalInstance().activeThreadCount() or (
            self.agent_runtime and self.agent_runtime.busy()
        ):
            self.shell_host.refresh()
            self.statusBar().showMessage(
                self.tr("Wait for the current operation before changing client."), 5000
            )
            return
        self._replace_workspace(self.settings.for_client(identifier))

    @agent_settings_change
    def _change_language(self, language: str) -> None:
        """Translate existing views without replacing their unsaved interaction state."""
        import json

        from PySide6.QtWidgets import QApplication

        from torrentlinker.gui.community_view import BundledView

        self.settings.language = language
        self.settings.save(self.settings_path)
        if self.agent_runtime is not None:
            self.agent_runtime.setup.settings.language = language
        app = QApplication.instance()
        if isinstance(app, QApplication):
            for translator in app.findChildren(QTranslator):
                app.removeTranslator(translator)
            self._language_translators = i18n.install(app, i18n.pick_language(language))
        for view in self.findChildren(BundledView):
            view.language = i18n.pick_language(language)
            environment = json.loads(view.bridge.environment_value or "{}")
            environment["language"] = view.language
            view.bridge.environment_value = json.dumps(environment)
            view.bridge.ready()
        for index, label in enumerate(
            ("Zen", "Library", "Upload", "Search", "RSS", "Torrents", "Assistant", "Media")
        ):
            self.tabs.setTabText(index, self.tr(label))
        for index, label in enumerate(("Profile", "Seeding", "Plan", "Catalogue")):
            self.zen_tab.pages.setTabText(index, self.zen_tab.tr(label))
        self.zen_tab.pages.setTabText(4, self.tr("Community"))
        self.band.set_catalogue(self.catalogue_age())
        self.shell_host.refresh()

    @agent_settings_change
    def _replace_workspace(self, settings: Settings) -> None:
        if self.agent_runtime and self.agent_runtime.busy():
            self.statusBar().showMessage(self.tr("Wait for agent jobs before changing settings."))
            return
        self.set_media_center(False)
        settings.save(self.settings_path)
        self.verify_timer.stop()
        tab_title = self.tabs.tabText(self.tabs.currentIndex())
        tab_key = self.shell_host.page()
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
            self.media_tab.horizon_changed.disconnect(self._save_media_horizon)
            self.media_tab.center_mode_requested.disconnect(self.set_media_center)
            self.media_tab.client_requested.disconnect(self._media_client_requested)
            self.media_tab.video_playing_changed.disconnect(self._video_playing_changed)
            self.media_tab.connections_requested.disconnect(self.open_assistant_connections)
            self.media_tab.discussion_requested.disconnect(self.open_media_discussion)
            replacement.media_tab = self.media_tab
            replacement.media_tab.layout_changed.connect(replacement._save_media_layout)
            replacement.media_tab.horizon_changed.connect(replacement._save_media_horizon)
            replacement.media_tab.center_mode_requested.connect(replacement.set_media_center)
            replacement.media_tab.client_requested.connect(replacement._media_client_requested)
            replacement.media_tab.video_playing_changed.connect(replacement._video_playing_changed)
            replacement.media_tab.connections_requested.connect(
                replacement.open_assistant_connections
            )
            replacement.media_tab.discussion_requested.connect(replacement.open_media_discussion)
            replacement.media_tab.set_center_mode(False)
            replacement.media_tab.set_media_layout(settings.media_layout)
            replacement.media_tab.set_media_horizon(settings.media_horizon)
            replacement.media_tab.set_adult(settings.adult_content)
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
        replacement.tabs.setCurrentIndex(
            WORKSPACES.index(tab_key) if tab_key in WORKSPACES else replacement_index
        )
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
        from PySide6.QtCore import QThreadPool

        # Said in a box: running updates redraw the status bar, which hid these refusals.
        if self.agent_runtime and self.agent_runtime.busy():
            message = self.tr("Wait for agent jobs before changing settings.")
        elif QThreadPool.globalInstance().activeThreadCount():
            # Clients are replaced, not edited: work in progress still uses the current one.
            message = self.tr("Wait for the current operation before changing client.")
        else:
            message = ""
        if message:
            QMessageBox.information(self, self.tr("Settings"), message)
            return
        self.open_settings(section="clients")

    def open_media_discussion(self, identifier: str) -> None:
        self.media_tab.close_chat()
        self.tabs.setCurrentWidget(self.assistant_tab)
        self.assistant_tab.select_conversation(identifier)

    def open_assistant_connections(self) -> None:
        self.open_settings(assistant=True)

    def open_settings(
        self, *, assistant: bool = False, agents: bool = False, section: str = "connections"
    ) -> None:
        """Settings is a page of this window; leaving it applies what was saved."""
        section = "assistant" if assistant else "agents" if agents else section
        if self._settings_page is not None:
            self._settings_page.show_section(section)
            self.tabs.setCurrentWidget(self._settings_page)
            return
        # Agents may not submit work while the settings they run under are being edited.
        stack = ExitStack()
        runtime = self.agent_runtime
        try:
            if runtime is not None and runtime.app is not None:
                runtime.sync(self.settings)
                stack.enter_context(runtime.editing_settings())
        except ValueError as error:
            stack.close()
            self.shell_host.refresh()
            QMessageBox.information(self, self.tr("Settings"), self.tr(str(error)))
            return
        self._settings_stack = stack
        self._settings_folders = list(self.settings.library_folders)
        # Settings saves each group immediately. Keep periodic desktop workers
        # from writing an older Settings snapshot while the page is open.
        self._settings_timers = [
            timer
            for timer in self.findChildren(QTimer)
            if timer.parent() is self and timer.isActive()
        ]
        for timer in self._settings_timers:
            timer.stop()
        self._settings_return = self.tabs.currentIndex()
        # Media Center hides the sidebar Settings needs; coming back to Media restores it.
        self._settings_from_media_center = self.media_center_active
        page = SettingsPage(self, section=section)
        self._settings_page = page
        self.tabs.addTab(page, self.tr("Settings"))
        self.tabs.setCurrentWidget(page)
        self.shell_host.refresh()

    def close_settings(self) -> None:
        """Back to the page Settings was opened from."""
        page = self._settings_page
        if page is None:
            return
        index = self._settings_return
        if self.tabs.widget(index) in (None, page) or not self.tabs.isTabEnabled(index):
            index = self.tabs.indexOf(self.media_tab)
        self.tabs.setCurrentIndex(index)

    def _settings_navigation(self, index: int) -> None:
        page = getattr(self, "_settings_page", None)  # pages are added before it exists
        if page is not None and self.tabs.widget(index) is not page:
            self._leave_settings()

    def _leave_settings(self) -> None:
        page = self._settings_page
        if page is None or self.tabs.currentWidget() is page:
            return  # the owner came back
        if page.view.pending:
            # A save is on its way: apply once it has landed.
            QTimer.singleShot(100, self._leave_settings)
            return
        self._settings_page = None
        self.tabs.removeTab(self.tabs.indexOf(page))
        page.view.close()
        page.deleteLater()
        for timer in self._settings_timers:
            timer.start()
        self._settings_timers = []
        stack, self._settings_stack = self._settings_stack, None
        if stack is not None:
            stack.close()
        if self._settings_from_media_center and self.tabs.currentWidget() is self.media_tab:
            self.set_media_center(True)
        self._settings_applied(page, self._settings_folders)

    def _export_diagnostics(self, parent: QWidget) -> None:
        from torrentlinker.diagnostics import build_report
        from torrentlinker.gui.diagnostics import export_report

        jobs = self.agent_runtime.service.jobs if self.agent_runtime else None
        export_report(parent, lambda: build_report(self.settings, self.store, jobs))

    def _settings_applied(self, page: SettingsPage, folders: list) -> None:
        accepted = page.saved
        if accepted and page.setup.settings.active_client_id != self.settings.active_client_id:
            self._replace_workspace(page.setup.settings)
            return
        if accepted:
            # Keep the Settings object used by existing workspaces authoritative.
            self.settings.__dict__.update(page.setup.settings.__dict__)
        for identifier in page.agent_approvals:
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
            self._plan_options_changed(self.settings.plan_options)
            self.zen_tab.plan_view.set_speed(
                self.settings.download_speed, self.settings.download_speed_tested
            )
            self._lock_reading_room()
            self.torrents_tab.reset_connection()
            self.settings.capture_client()
            self.shell_host.refresh()
            self.settings.save(self.settings_path)
            if self.agent_runtime:
                self.agent_runtime.reset(self.settings)
            log.info("settings written to %s", self.settings_path)
            self.apply_proxy()
            set_theme(self.settings.theme)
            self.media_tab.set_media_layout(self.settings.media_layout)
            self.media_tab.set_media_horizon(self.settings.media_horizon)
            self.media_tab.set_adult(self.settings.adult_content)
            self.search_tab.refresh_categories()
            self.offer_plan_categories()
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
                self.zen_tab.seeding_view.reload()
                if self.settings.library_folders != folders:
                    self.scan()  # a new folder, depth or Content Kind changes every entry
        else:
            log.info("settings left without changes")

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
        if hasattr(self, "library_workspace"):
            self.library_workspace.refresh()

    def selected_entries(self) -> list[LibraryEntry]:
        board = self.library_workspace.reseed
        library = board.service().library
        paths = {row["path"] for row in library.rows()}
        return [library.entry(path) for path in board.selected_paths if path in paths]

    # Batch search ----------------------------------------------------------

    def start_batch(self, selected_only: bool) -> None:
        if self.batch is not None:
            return
        pool = self.selected_entries() if selected_only else self.library_model.entries
        episodes = pack_episodes(pool)  # checked without searching, after their packs
        free = {e.item.path for e in episodes}
        entries = auto_searchable(pool) + episodes
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
            searching = entry.item.path not in free
            query = store.item_query(entry.item.path) if searching else None
            found, checked = find_candidates(
                store,
                indexer,
                entry.item,
                lambda: searcher(entry, query) if searching else [],
                rules,
                store.rejections(entry.item.path),
                use_catalogue=query is None,
            )
            remember_candidates(store, indexer, entry.item.path, found)
            return checked

        self._batch_mode = "search"
        self._begin_library_batch(BatchRunner(entries, search, orphans_only=False))
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
        self._batch_failed = 0
        self._batch_position = (0, len(runner.entries))
        self.batch_progress.setRange(0, max(1, len(runner.entries)))
        self.batch_progress.setValue(0)
        self.batch.signals.started.connect(self._batch_started)
        self.batch.signals.searched.connect(self._batch_result)
        self.batch.signals.already_present.connect(self._batch_already_present)
        self.batch.signals.error.connect(self._batch_error)
        self.batch.signals.waiting.connect(self._batch_waiting)
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
        self.batch_status.setVisible(running)
        if running:
            self.countdown.start()
        else:
            self.countdown.stop()

    def _show_batch_progress(self) -> None:
        wait = self._indexer.next_request_in() if self._indexer else 0
        suffix = self.tr(" · next request in {0} s").format(f"{wait:.1f}") if wait > 0.05 else ""
        self.batch_label.setText(self.batch_text + suffix)
        self.statusBar().clearMessage()

    def _batch_started(self, index: int, total: int, entry: LibraryEntry) -> None:
        """Say which item is being worked on as soon as it starts: one search can take a
        while when c411's request budget is busy."""
        self._batch_position = (index, total)
        self.batch_progress.setRange(0, max(1, total))
        self.batch_progress.setValue(index - 1)
        failed = self.tr(" · {0} failed").format(self._batch_failed) if self._batch_failed else ""
        if self._batch_mode != "search":
            self.batch_text = self.tr("Processing {0}/{1}: {2}").format(
                index, total, entry.item.path.name
            )
            return
        self.batch_text = (
            self.tr("Searching {0}/{1}: {2}").format(index, total, entry.item.path.name) + failed
        )
        self.library_model.set_status(entry.item.path, self.tr("Searching…"))

    def _batch_result(
        self, index: int, total: int, entry: LibraryEntry, checked: list[CheckedCandidate]
    ) -> None:
        self.batch_progress.setValue(index)
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
        self._batch_failed += 1
        index, total = self._batch_position
        self.batch_progress.setValue(index)
        if self._batch_mode != "search":
            self._batch_errors.append(f"{entry.item.path.name}: {error_text(error)}")
            return
        self.library_model.set_status(
            entry.item.path, self.tr("Search failed: {0}").format(error_text(error))
        )
        self.batch_text = self.tr("Search failed {0}/{1}: {2}: {3}").format(
            index, total, entry.item.path.name, error_text(error)
        )

    def _batch_waiting(self, entry: LibraryEntry, seconds: float) -> None:
        until = time.strftime("%H:%M:%S", time.localtime(time.time() + seconds))
        self.batch_text = self.tr(
            "c411 asks to wait: the batch resumes at {0} with {1}. Cancel to stop it."
        ).format(until, entry.item.path.name)
        self.library_model.set_status(
            entry.item.path, self.tr("Waiting for c411 until {0}").format(until)
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
        text = self.tr("Batch search finished: {0} searched").format(done)
        if self._batch_failed:
            text += self.tr(" · {0} failed").format(self._batch_failed)
        self.statusBar().showMessage(text)

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

        self._scan_stop = stop = threading.Event()

        def work(report):
            client_error = None
            try:
                torrents = indexer_contents(
                    qbit,
                    store,
                    url,
                    refresh=refresh,
                    stop=stop,
                    progress=lambda done, total, rate: report((done, total, rate)),
                )
            except InterruptedError:
                return previous
            except Exception as error:
                client_error = error
                torrents = None
            result = build_library(folders, torrents, ignore, store, refresh, previous)
            result.client_error = client_error
            return result

        def progress(value):
            if not stop.is_set() and isValid(self):
                done, total, rate = value
                self.statusBar().showMessage(
                    self.tr("Reading client files: {0}/{1} · up to {2} requests/s").format(
                        done, total, f"{rate:.2f}"
                    )
                )

        run_with_progress(work, progress, self._scan_done, self._scan_failed)

    def _scan_done(self, entries: list) -> None:  # type: ignore[type-arg]
        if self._scan_stop.is_set() or not isValid(self):
            return
        self.library_workspace.set_scan_errors(getattr(entries, "errors", []))
        self.library_model.set_entries(entries)
        self.upload_tab.set_entries(entries)
        self.scan_action.setEnabled(True)
        self.rescan_action.setEnabled(True)
        self.add_folder_action.setEnabled(True)
        episodes = sum(e.item.within is not None for e in entries)
        self.statusBar().showMessage(
            self.tr("{0} Local Items, {1} of them inside packs").format(len(entries), episodes)
            if episodes
            else self.tr("{0} Local Items").format(len(entries))
        )
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
        with self.upload_tab.defer_refresh():
            for entry, checked in restored:
                if self.library_model.contains(entry):
                    self.review.remember(entry, checked)
                    self.library_model.set_status(entry.item.path, self._summary(checked))

    def _restore_failed(self, error: Exception) -> None:
        log.warning("could not restore previous searches: %s", error)

    def _scan_failed(self, error: Exception) -> None:
        if self._scan_stop.is_set() or not isValid(self):
            return
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
                text = self.tr(
                    "Verified, left stopped: the Torrent Client did not confirm skipping "
                    "the absent files"
                )
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
