"""Desktop host for the bundled Documentation view and offline guide assets."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget
from shiboken6 import isValid

from torrentlinker import documentation as docs
from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.web.documentation import render


class DocumentationBridge(ViewBridge):
    response = Signal(int, str)

    @Slot(int, str, str)
    def requestAsync(self, identifier: int, action: str, payload: str) -> None:
        try:
            body = json.loads(payload)
            if not isinstance(body, dict):
                raise ValueError("Invalid Documentation request.")
            if action == "open-link":
                url = QUrl(str(body.get("url", "")))
                if url.scheme() not in {"http", "https"} or not url.host() or url.userInfo():
                    raise ValueError("Unsupported link.")
                QDesktopServices.openUrl(url)
                self._complete(identifier, {"data": None})
                return

            def work():
                try:
                    if action == "index":
                        value = docs.guides(body.get("language", "en"))
                    elif action == "page":
                        value = {"html": render(body["path"])}
                    elif action == "image":
                        path = docs.document_path(body["path"])
                        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                            raise ValueError("Not a guide image.")
                        kind = "png" if path.suffix.lower() == ".png" else "jpeg"
                        value = {
                            "src": f"data:image/{kind};base64,"
                            + base64.b64encode(path.read_bytes()).decode()
                        }
                    else:
                        raise ValueError("Unknown Documentation operation.")
                    return {"data": value}
                except (ValueError, KeyError, TypeError, OSError) as error:
                    return {"error": str(error)}

            run_in_background(
                work,
                lambda result: self._complete(identifier, result),
                lambda error: self._complete(identifier, {"error": str(error)}),
                coordinate=False,
            )
        except (ValueError, TypeError) as error:
            self._complete(identifier, {"error": str(error)})

    def _complete(self, identifier: int, result: dict) -> None:
        if isValid(self):
            self.response.emit(identifier, json.dumps(result))


class DocumentationTab(BundledView):
    def __init__(self, language: str = "en") -> None:
        self.guide = ""
        self.fragment = ""
        self.navigation_revision = 0
        super().__init__(
            DocumentationBridge(),
            Path(__file__).parents[1] / "web/static/documentation",
            "documentation",
            language,
        )

    def open_guide(self, name: str, fragment: str = "") -> None:
        self.guide = name
        self.fragment = fragment
        self.navigation_revision += 1
        self.refresh()

    def refresh(self) -> None:
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
                "active": self.isVisible(),
                "guide": self.guide,
                "fragment": self.fragment,
                "navigation_revision": self.navigation_revision,
            }
        )
        self.bridge.ready()


def show_guide(parent: QWidget, name: str, fragment: str = "") -> QDialog:
    """Open an allowlisted guide in a nonmodal reader for an Assistant citation."""
    allowed = {g["path"] for language in ("en", "fr") for g in docs.guides(language)}
    if name not in allowed:
        raise ValueError("Not a bundled guide.")
    docs.document_path(name)
    dialog = QDialog(parent)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.setWindowTitle("TorrentLinker documentation")
    dialog.resize(1000, 750)
    layout = QVBoxLayout(dialog)
    reader = DocumentationTab(name.split("/")[1])
    layout.addWidget(reader)
    reader.open_guide(name, fragment)
    dialog.show()
    return dialog
