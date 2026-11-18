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
            elif action == "advanced":
                self.board.open_tools(body)
                done({"ok": True})
            else:
                service = self.board.service(body.get("path", ""), body.get("id", ""))
                run_in_background(lambda: service.request(action, body), done, failed)
        except Exception as error:
            failed(error)


class UploadBoard(BundledView):
    def __init__(self, window):
        self.owner = window
        self.selected_paths: set[Path] = set()
        super().__init__(
            UploadBridge(self),
            Path(__file__).parents[1] / "web/static/upload",
            "upload",
            window.settings.language,
        )
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
        library = Library(setup)
        library.entries = list(owner.library_model.entries)
        return UploadWorkspace(Uploads(setup, library))

    def refresh(self):
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "client": self.owner.settings.active_client_id,
                "active": self.isVisible(),
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
            }
        )
        self.bridge.ready()

    def open_tools(self, body):
        from PySide6.QtWidgets import QDialog, QVBoxLayout

        tools = self.owner.upload_tab
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Upload preparation tools"))
        dialog.resize(1200, 850)
        layout = QVBoxLayout(dialog)
        layout.addWidget(tools)
        if body.get("id"):
            tools.edit_saved_details(self.owner.store.local_draft(body["id"]))
        else:
            tools.select(Path(body["path"]))
        dialog.exec()
        tools.setParent(self.owner)
        tools.hide()
        self.refresh()
