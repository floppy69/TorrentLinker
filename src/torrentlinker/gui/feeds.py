"""Desktop host for the shared RSS inbox and subscription editor."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Signal, Slot

from torrentlinker.feed_workspace import FeedWorkspace
from torrentlinker.feeds import candidate
from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.gui.torrent_details import TorrentDetailsDialog
from torrentlinker.torrent_management import safe_error


class FeedBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self, board):
        super().__init__()
        self.board = board

    @Slot(int, str, str)
    def requestAsync(self, identifier, action, payload):
        try:
            body = json.loads(payload)
            control = self.board.control()
            if body.pop("_client", None) != control.service.setup.settings.active_client_id:
                raise ValueError("The target client changed. Reopen RSS.")
            if action == "details":
                row = dict(body["row"])
                row["infohash"] = row.get("infohash") or row.get("hash")
                TorrentDetailsDialog(
                    candidate(row), control.feeds.indexer(), "—", "", self.board
                ).exec()
                self.response.emit(identifier, json.dumps({"data": {"ok": True}}))
            elif action == "api":

                def work():
                    try:
                        result = {
                            "data": FeedWorkspace(control).request(
                                body["path"], body.get("body"), body.get("method", "GET")
                            )
                        }
                    except Exception as error:
                        result = {"error": safe_error(error)}
                    return result

                run_in_background(
                    work,
                    lambda result: self.response.emit(
                        identifier, json.dumps(result, ensure_ascii=False)
                    ),
                    lambda error: self.response.emit(
                        identifier, json.dumps({"error": safe_error(error)})
                    ),
                )
            else:
                raise ValueError("Unknown RSS operation.")
        except Exception as error:
            self.response.emit(identifier, json.dumps({"error": safe_error(error)}))


class FeedsTab(BundledView):
    def __init__(self, control, parent=None):
        self.control = control
        self.owner = parent
        self.command = None
        self.sequence = 0
        super().__init__(FeedBridge(self), Path(__file__).parents[1] / "web/static/feeds", "feeds")
        if parent is not None:
            self.setParent(parent)

    def refresh(self):
        # Reading the host environment must not start connected services while
        # RSS is hidden. The owner already holds the current settings.
        settings = (
            self.owner.settings if self.owner is not None else self.control().service.setup.settings
        )
        self.language = settings.language
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "client": settings.active_client_id,
                "language": self.language,
                "active": self.isVisible(),
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
                "command": self.command,
            }
        )
        self.bridge.ready()

    def reload(self):
        self.refresh()

    def edit(self, identifier="", query=""):
        self.sequence += 1
        self.command = {
            "id": self.sequence,
            "action": "edit",
            "query": query,
            "identifier": identifier,
        }
        # Search subscriptions reveal the RSS page before opening its editor.
        window = self.window()
        if hasattr(window, "tabs"):
            window.tabs.setCurrentWidget(self)
        self.refresh()
