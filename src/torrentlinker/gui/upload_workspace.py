"""Desktop host of the shared guided Upload view."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QFileDialog

from torrentlinker.agent.desktop import DesktopSetup
from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.upload_workspace import UploadWorkspace
from torrentlinker.web.library import Library
from torrentlinker.web.uploads import Uploads


class UploadBridge(ViewBridge):
    response = Signal(int, str)
    toolFinished = Signal(str, str, object)

    def __init__(self, board):
        super().__init__()
        self.board = board
        self.environment_value = "{}"

    @Slot(int, str, str)
    def requestAsync(self, identifier, action, payload):
        def done(value):
            self.response.emit(identifier, json.dumps({"data": value}, ensure_ascii=False))

        def failed(error):
            self.response.emit(identifier, json.dumps({"error": str(error)}))

        try:
            body = json.loads(payload)
            if body.pop("_client", self.board.owner.settings.active_client_id) != (
                self.board.owner.settings.active_client_id
            ):
                raise ValueError("The target client changed. Reopen Upload.")
            if action == "pick":
                if body.get("type") == "file":
                    path, _ = QFileDialog.getOpenFileName(
                        self.board,
                        "Choisir un fichier"
                        if self.board.language.startswith("fr")
                        else "Choose a file",
                    )
                else:
                    path = QFileDialog.getExistingDirectory(
                        self.board,
                        "Choisir un dossier"
                        if self.board.language.startswith("fr")
                        else "Choose a folder",
                    )
                if path:
                    self.board.selected_paths.add(Path(path).resolve())
                done({"selected": path})
            elif action == "save-artwork":
                import base64

                service = self.board.service(identifier=body["id"])
                data = service.request("asset-read", body)["src"]
                filename, _ = QFileDialog.getSaveFileName(
                    self.board,
                    (
                        "Enregistrer l’image rendue"
                        if self.board.language.startswith("fr")
                        else "Save rendered artwork"
                    ),
                    "render.png",
                    "PNG (*.png)",
                )
                if filename:
                    Path(filename).write_bytes(base64.b64decode(data.split(",", 1)[1]))
                done({"saved": bool(filename)})
            else:
                service = self.board.service(body.get("path", ""), body.get("id", ""))
                if action.startswith("tool-"):
                    from torrentlinker.upload_tool_jobs import tool_job

                    client = self.board.owner.settings.active_client_id
                    result = tool_job(
                        self.board.tool_jobs(),
                        service,
                        self.board.owner.settings.active_client_id,
                        action,
                        body,
                        completed=lambda kind, result: self.toolFinished.emit(client, kind, result),
                    )
                    done(result)
                else:
                    run_in_background(lambda: service.request(action, body), done, failed)
        except Exception as error:
            failed(error)


class UploadBoard(BundledView):
    def __init__(self, window):
        self.owner = window
        self.selected_paths: set[Path] = set()
        self.focus_request = None
        super().__init__(
            UploadBridge(self),
            Path(__file__).parents[1] / "web/static/upload",
            "upload",
            window.settings.language,
        )
        self.bridge.toolFinished.connect(self.tool_finished)
        self.setProperty("ownsScrolling", True)

    def service(self, path="", identifier=""):
        owner = self.owner
        setup = DesktopSetup(
            owner.settings,
            owner.settings_path,
            owner.store.for_client(owner.settings.active_client_id),
        )
        # A native picker grants access to precisely that source. A saved manual
        # draft preserves that explicit choice across application restarts.
        chosen = Path(path).resolve() if path else None
        if identifier:
            record = setup.store.local_draft(identifier)
            if record["form"].get("manual_source"):
                chosen = Path(record["path"]).resolve()
                setup._folder_candidate = chosen
        if chosen in self.selected_paths:
            setup._folder_candidate = chosen
        setup._upload_destinations = set(self.selected_paths)
        library = Library(setup)
        library.entries = list(owner.library_model.entries)
        uploads = Uploads(setup, library)
        uploads.approve_disk_renames = owner.reseed_consent.approve
        return UploadWorkspace(uploads)

    def refresh(self):
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "focus_request": self.focus_request,
                "language": self.language,
                "client": self.owner.settings.active_client_id,
                "active": self.isVisible(),
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
            }
        )
        self.bridge.ready()

    def focus_source(self, path):
        import time

        self.focus_request = {"path": path, "at": time.time_ns()}
        self.refresh()

    def tool_finished(self, client, kind, result):
        current = client == self.owner.settings.active_client_id
        if kind == "seed-upload":
            if current:
                self.owner._reseed_started(Path(result["path"]))
            else:
                self.owner.verify_timer.start()
        elif kind == "archive-extract" and current:
            self.owner.scan()

    def tool_jobs(self):
        if not hasattr(self, "_tool_jobs"):
            from PySide6.QtWidgets import QApplication

            from torrentlinker.torrent_management import safe_error
            from torrentlinker.web.jobs import Jobs

            directory = self.owner.settings_path.parent / "upload-tools"
            directory.mkdir(parents=True, exist_ok=True)
            self._tool_jobs = Jobs(directory, error_message=safe_error)
            QApplication.instance().aboutToQuit.connect(self._tool_jobs.close)
        return self._tool_jobs
