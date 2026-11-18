"""Desktop host for the same guided Library workspace as the Web UI."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog

from torrentlinker.agent.desktop import DesktopSetup
from torrentlinker.domain import LibraryFolder
from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.gui.tasks import run_in_background, run_with_progress
from torrentlinker.reseed_workspace import ReseedWorkspace
from torrentlinker.web.jobs import JobStop
from torrentlinker.web.library import Library
from torrentlinker.web.setup import Connection, FolderSetup

ASSETS = Path(__file__).parents[1] / "web" / "static" / "reseed"


class ReseedBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self, board):
        super().__init__()
        self.board = board
        self.environment_value = "{}"

    @Slot(int, str, str)
    def requestAsync(self, identifier: int, action: str, payload: str) -> None:
        def done(value):
            self.response.emit(identifier, json.dumps({"data": value}, ensure_ascii=False))

        def failed(error):
            self.response.emit(identifier, json.dumps({"error": str(error)}))

        try:
            body = json.loads(payload)
            if not isinstance(body, dict):
                raise ValueError("Invalid reseed request.")
            if (
                body.get("_client", self.board.owner.settings.active_client_id)
                != self.board.owner.settings.active_client_id
            ):
                raise ValueError("The target client changed. Reopen the Library.")
            body.pop("_client", None)
            if action == "preview-folder":
                setup = self.board.service().setup
                # Desktop paths are chosen by the local owner, not server roots.
                setup._folder_candidate = Path(body["local"]).expanduser().resolve()
                run_in_background(lambda: setup.preview_folder(FolderSetup(**body)), done, failed)
            elif action == "add-client":
                self.board.add_client(body, done, failed)
            else:
                done(self.board.request(action, body))
        except Exception as error:
            failed(error)


class ReseedBoard(BundledView):
    def __init__(self, window):
        self.owner = window
        self.rows: list[dict] = []
        self.running = False
        self.stop = JobStop()
        self.link_root = window.settings.profile().reseed_link_root
        self.progress_value: dict = {}
        self.error = ""
        self.current_service: ReseedWorkspace | None = None
        self.configuring = False
        self.activity: list[dict] = []
        self.scan_errors: list[str] = []
        self.requested_tab = "reseed"
        self.folder_dialog_request = 0
        self.scanning = False
        super().__init__(ReseedBridge(self), ASSETS, "reseed", window.settings.language)
        self.setMinimumHeight(620)
        window.library_model.modelReset.connect(self.refresh_rows)
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.stop_run)
        self.refresh_rows()

    def service(self):
        setup = DesktopSetup(
            self.owner.settings,
            self.owner.settings_path,
            self.owner.store.for_client(self.owner.settings.active_client_id),
        )
        if self.link_root:
            setup._folder_candidate = Path(self.link_root)
        library = Library(setup)
        library.entries = list(self.owner.library_model.entries)
        return ReseedWorkspace(library)

    def refresh_rows(self):
        if self.running and self.current_service:
            self.current_service.library.entries = list(self.owner.library_model.entries)
            self.rows = self.current_service.rows()
        else:
            self.link_root = self.owner.settings.profile().reseed_link_root
            self.rows = self.service().rows()
        self.refresh()

    def refresh(self):
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
                "active": self.isVisible(),
                "client": self.owner.settings.active_client_id,
                "tab": self.requested_tab,
                "folder_dialog_request": self.folder_dialog_request,
            }
        )
        self.bridge.ready()

    def request(self, action, body):
        if action == "state":
            setup = self.service().setup.snapshot()
            return {
                "rows": self.rows,
                "activity": self.activity,
                "folder_errors": self.scan_errors,
                "setup": setup,
                "running": self.running,
                "paused": self.stop.paused.is_set(),
                "progress": self.progress_value,
                "error": self.error,
                "scanning": self.scanning or "" in self.progress_value.get("active", {}),
            }
        if action == "tab":
            self.requested_tab = body["tab"]
        elif action == "run":
            self.start(body.get("paths", []), "all", body.get("key", ""))
        elif action == "enqueue":
            if not self.current_service:
                raise ValueError("Start the reseed workflow first.")
            self.current_service.enqueue(body["paths"], body.get("key", ""))
        elif action == "pause-item":
            if not self.current_service:
                raise ValueError("Start the reseed workflow first.")
            self.current_service.control(body["paths"], paused=bool(body["paused"]))
            self.progress_value["paused_paths"] = sorted(self.current_service.paused_paths())
        elif action == "pause":
            self.stop.paused.set() if body["paused"] else self.stop.paused.clear()
        elif action == "stop":
            self.stop_run()
        elif action == "scan":
            if self.running and self.current_service:
                self.current_service.request_scan(body.get("folders"))
            else:
                if self.scanning:
                    raise ValueError("A folder scan is already running.")
                service = self.service()
                self.current_service = service
                self.scanning = True
                self.stop = JobStop()
                run_with_progress(
                    lambda report: service.library.scan(self.stop, report, body.get("folders")),
                    lambda value: None,
                    self.scan_finished,
                    self.failed,
                )
        elif action == "browse":
            return {
                "selected": QFileDialog.getExistingDirectory(
                    self, self.tr("Choose folder"), body.get("path", "")
                )
            }
        elif action == "manage-folders":
            self.owner.library_workspace.open_folders()
        elif action == "review":
            self.owner.library_workspace.open_review(body["path"])
        elif action in {"settings", "add-folder", "remove-folder", "save-root"}:
            if self.running or self.scanning or self.configuring:
                raise ValueError("Stop the current operation before changing settings.")
            if action == "settings":
                self.owner.open_settings()
            elif action == "remove-folder":
                if self.owner.store.for_client(
                    self.owner.settings.active_client_id
                ).verification_hashes():
                    raise ValueError("Finish pending Reseed Verifications before removing folders.")
                folders = [
                    f for f in self.owner.settings.library_folders if str(f.path) != body["local"]
                ]
                if not self.owner.save_library_folders(folders, scan=False):
                    raise ValueError("Wait for the current Library operation to finish.")
            elif action == "add-folder":
                path = Path(body["local"]).expanduser().resolve()
                if not path.is_dir():
                    raise ValueError("Folder is unavailable.")
                values = FolderSetup(**body)
                original = body.get("original_local", "")
                if (
                    original
                    and Path(original) != path
                    and self.owner.store.for_client(
                        self.owner.settings.active_client_id
                    ).verification_hashes()
                ):
                    raise ValueError(
                        "Finish pending Reseed Verifications before changing folder paths."
                    )
                if original and not any(
                    str(f.path) == original for f in self.owner.settings.library_folders
                ):
                    raise ValueError("The Library Folder no longer exists. Reopen the dialog.")
                folders = [
                    f
                    for f in self.owner.settings.library_folders
                    if f.path != path and str(f.path) != original
                ]
                folders.append(LibraryFolder(path, values.depth, values.kind))
                if not self.owner.save_library_folders(folders, scan=False):
                    raise ValueError(
                        "The folder could not be saved. Wait for the current operation."
                    )
            else:
                path = Path(body["path"]).expanduser().resolve()
                if not path.is_dir():
                    raise ValueError("Folder is unavailable.")
                if not self.owner.save_reseed_folder(str(path)):
                    raise ValueError("Wait for the current settings operation to finish.")
                self.link_root = str(path)
            self.refresh_rows()
            if action == "add-folder":
                return {"ok": True, "local": str(path)}
        else:
            raise ValueError("Unknown reseed operation.")
        return {"ok": True}

    def add_client(self, body, done, failed):
        if self.running or self.scanning or self.configuring:
            raise ValueError("Stop the current operation before changing clients.")
        connection = Connection(**body)
        if not connection.name.strip():
            raise ValueError("Enter a name for this Torrent Client.")
        setup = self.service().setup
        profile = setup.settings.add_client(connection.name, connection.client)
        self.configuring = True

        def work():
            return setup.for_client(profile.id).test_client(connection, save=False)

        def finished(result):
            self.configuring = False
            from torrentlinker.web.setup import CLIENT_SETTINGS

            name = CLIENT_SETTINGS[connection.client]
            profile.host = connection.host
            profile.username = connection.username
            target = setup.for_client(profile.id)
            values = {}
            if connection.password is not None:
                values[target.settings.secret_name(name + "-password")] = connection.password
            if connection.api_key is not None and name == "qbit":
                values[target.settings.secret_name("qbit-api-key")] = connection.api_key
            try:
                if not self.owner.save_new_client_profile(profile, target.secrets, values):
                    raise ValueError("Wait for the current settings operation to finish.")
            except Exception as error:
                failed(error)
                return
            done({**result, "client_id": profile.id})
            QTimer.singleShot(
                0,
                lambda: self.owner.client_selector.setCurrentIndex(
                    self.owner.client_selector.findData(profile.id)
                ),
            )

        def failure(error):
            self.configuring = False
            failed(error)

        run_in_background(work, finished, failure)

    def scan_finished(self, result):
        self.scanning = False
        if self.current_service:
            self.owner.library_model.set_entries(list(self.current_service.library.entries))

    def start(self, paths, action, key=""):
        if self.scanning or self.configuring:
            raise ValueError("Wait for the current setup or initial scan to finish.")
        if self.running:
            raise ValueError("A reseed workflow is already active.")
        service = self.service()
        if action != "refresh":
            service.setup._indexer = self.owner.indexer()
        self.current_service = service
        self.stop = JobStop()
        self.running, self.error = True, ""
        self.progress_value = {}
        run_with_progress(
            lambda report: service.run(paths, action, self.link_root, self.stop, report, key),
            self.progress,
            self.finished,
            self.failed,
        )

    def progress(self, value):
        if value.get("scan_complete") and self.current_service:
            self.owner.library_model.set_entries(list(self.current_service.library.entries))
        self.progress_value = value
        self.error = "\n".join(e["message"] for e in value.get("errors", []))
        if "rows" in value:
            self.rows = value["rows"]

    def stop_run(self):
        self.stop.set()

    def finished(self, result):
        self.running = False
        self.rows = result["rows"]
        self.error = "\n".join(e["message"] for e in result.get("errors", []))
        self.progress_value = {"active": {}, "paused_paths": []}
        self.refresh()

    def failed(self, error):
        self.scanning = False
        self.running = False
        self.error = str(error)
        self.refresh_rows()
