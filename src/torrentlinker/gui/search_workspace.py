"""Desktop Search host. Search and queue rendering live in the shared panel."""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from torrentlinker.agent.desktop import DesktopOperations, DesktopSetup
from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.search_workspace import SearchWorkspace
from torrentlinker.torrent_management import safe_error
from torrentlinker.web.jobs import Jobs


class SearchSetup(DesktopSetup):
    def save(self):
        # Folder edits are merged into the live settings on the GUI thread.
        # Writing this worker's snapshot could overwrite a later client switch.
        pass


class SearchBridge(ViewBridge):
    response = Signal(int, str)
    finished = Signal(int, object, object)

    def __init__(self, board):
        super().__init__()
        self.board = board
        self.finished.connect(self.completed)

    @Slot(int, object, object)
    def completed(self, identifier, service, result):
        changed = bool(service.setup.download_folder_changes)
        service.setup.apply_download_folder_changes(self.board.owner.settings)
        if changed:
            self.board.owner.settings.save(self.board.owner.settings_path)
        self.response.emit(identifier, json.dumps(result, ensure_ascii=False))

    @Slot(int, str, str)
    def requestAsync(self, identifier, action, payload):
        board = self.board

        def done(value):
            self.response.emit(identifier, json.dumps({"data": value}, ensure_ascii=False))

        def failed(error):
            self.response.emit(identifier, json.dumps({"error": safe_error(error)}))

        try:
            body = json.loads(payload)
            if body.pop("_client", None) != board.owner.settings.active_client_id:
                raise ValueError("The target client changed. Reopen Search.")
            if action == "preferences":
                settings = QSettings()
                if body.get("tl-search-density") in {"comfortable", "compact"}:
                    settings.setValue("search/density", body["tl-search-density"])
                if body.get("tl-search-posters") in {"0", "1"}:
                    settings.setValue("search/posters", body["tl-search-posters"] == "1")
                done(
                    {
                        "tl-search-density": settings.value("search/density", "comfortable"),
                        "tl-search-posters": "1"
                        if settings.value("search/posters", True, bool)
                        else "0",
                    }
                )
            elif action == "score-profile":
                from torrentlinker.release_score.preferences import Preferences

                original = board.owner.settings.release_score
                updated = Preferences.model_validate(original).model_dump(by_alias=True)
                updated["active"] = body.get("active")
                updated = Preferences.model_validate(updated).model_dump(by_alias=True)
                board.owner.settings.release_score = updated
                try:
                    board.owner.settings.save(board.owner.settings_path)
                except Exception:
                    board.owner.settings.release_score = original
                    raise
                done({"ok": True})
            elif action == "pick":
                done(
                    {
                        "selected": QFileDialog.getExistingDirectory(
                            board, QCoreApplication.translate("SearchTab", "Choose a folder")
                        )
                    }
                )
            elif action == "navigate":
                if body.get("page") not in {"search", "queue"}:
                    raise ValueError("Unknown Search page.")
                board.page = body["page"]
                board.refresh()
                done({"ok": True})
            elif action == "details":
                board.tab.open_details(body["row"])
                done({"ok": True})
            elif action == "subscribe":
                board.tab.subscribe_requested.emit(body.get("query", ""))
                done({"ok": True})
            elif action == "torrents":
                board.tab.manage_requested.emit(body.get("hashes", []))
                done({"ok": True})
            else:
                service = board.service()

                def work():
                    try:
                        result = {"data": service.request(action, body)}
                    except Exception as error:
                        result = {"error": safe_error(error)}
                    self.finished.emit(identifier, service, result)

                board.requests.submit(work)
        except Exception as error:
            failed(error)


class SearchBoard(BundledView):
    def __init__(self, tab, owner):
        self.tab, self.owner = tab, owner
        self.services = {}
        self.page = "search"
        self.jobs = None
        self.requests = ThreadPoolExecutor(max_workers=4, thread_name_prefix="search-panel")
        super().__init__(
            SearchBridge(self),
            Path(__file__).parents[1] / "web/static/search",
            "search",
            owner.settings.language,
        )

    def service(self):
        if self.jobs is None:
            directory = self.owner.settings_path.parent / "search-jobs"
            directory.mkdir(parents=True, exist_ok=True)
            self.jobs = Jobs(directory, error_message=safe_error)
        client = self.owner.settings.active_client_id
        if client not in self.services:
            setup = SearchSetup(
                self.owner.settings, self.owner.settings_path, self.owner.store.for_client(client)
            )
            self.services[client] = SearchWorkspace(DesktopOperations(setup), self.jobs)
        service = self.services[client]
        # Never replace the settings used by an in-flight job.
        if not self.jobs.active() and service.setup.settings != self.owner.settings:
            service.setup.settings = copy.deepcopy(self.owner.settings)
            service.setup._client = None
            service.setup._indexer = None
        return service

    def refresh(self):
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "indexer": self.owner.settings.indexer.url,
                "language": self.language,
                "client": self.owner.settings.active_client_id,
                "adult": self.owner.settings.adult_content,
                "active": self.isVisible(),
                "page": self.page,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
            }
        )
        self.bridge.ready()


class SearchTab(QWidget):
    subscribe_requested = Signal(str)
    manage_requested = Signal(list)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setProperty("ownsScrolling", True)
        self.board = SearchBoard(self, owner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.board)
        for sequence, command in (
            ("Ctrl+W", "close"),
            ("Ctrl+Tab", "next"),
            ("Ctrl+Shift+Tab", "previous"),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda command=command: self.tab_shortcut(command))

    def tab_shortcut(self, command):
        if self.board.web:
            self.board.web.page().runJavaScript(
                "window.searchTabShortcut(" + json.dumps(command) + ")"
            )

    def focus_search(self):
        self.show_results()
        if self.board.web:
            self.board.web.page().runJavaScript("document.getElementById('search-query').focus()")

    def show_results(self):
        self.board.page = "search"
        self.board.refresh()
        self.board.web.page().runJavaScript("navigate('search')")

    def show_queue(self):
        self.board.page = "queue"
        self.board.refresh()
        self.board.web.page().runJavaScript("navigate('queue')")

    def set_seeding(self, view):
        self.board.service().operations.observed = [row.torrent for row in view.rows]
        self.board.refresh()

    def refresh_categories(self):
        self.board.refresh()

    def refresh_estimates(self):
        self.board.refresh()

    def open_details(self, row):
        if self.board.web:
            self.board.web.page().runJavaScript("guard(()=>openDetail(" + json.dumps(row) + "))")

    def stop(self):
        self.board.requests.shutdown(wait=True, cancel_futures=True)
        if self.board.jobs is not None:
            self.board.jobs.close()
            self.board.jobs = None
