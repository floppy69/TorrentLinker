"""Shared Media library host; playback and the queue remain with the native Media session."""

import json
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QColor
from shiboken6 import isValid

from torrentlinker.config import MEDIA_HORIZON_VIEWS, MEDIA_LAYOUTS
from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.media_browser import MediaBrowserService


class MediaBrowserBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    @Slot(int, str, str)
    def requestAsync(self, identifier, path, payload):
        try:
            body = json.loads(payload)
            if path == "host":
                action = body.get("action")
                if action not in {
                    "play",
                    "preview",
                    "preroll-preview",
                    "studio-export",
                    "studio-preview",
                    "enqueue",
                    "queue",
                    "kind",
                    "chat",
                    "center",
                    "client",
                    "settings",
                    "selection",
                    "context",
                    "player",
                    "watch-layout",
                    "navigation",
                }:
                    raise ValueError("Unknown Media action")
                self.panel.hostRequested.emit(action, body.get("values", {}))
                self.response.emit(identifier, '{"data":null}')
                return
            if path == "preferences":
                if body.get("layout") in MEDIA_LAYOUTS:
                    self.panel.layout_value = body["layout"]
                    self.panel.hostRequested.emit("layout", {"layout": body["layout"]})
                if body.get("horizon") in MEDIA_HORIZON_VIEWS:
                    self.panel.horizon_value = body["horizon"]
                    self.panel.hostRequested.emit("horizon", {"horizon": body["horizon"]})
                self.response.emit(
                    identifier,
                    json.dumps(
                        {
                            "data": {
                                "layout": self.panel.layout_value,
                                "horizon": self.panel.horizon_value,
                            }
                        }
                    ),
                )
                return
            service = self.panel.get_service()
            # A panel operates on the host's selected client, never an arbitrary payload client.
            from urllib.parse import parse_qsl, urlencode, urlsplit

            parsed = urlsplit(path)
            query = dict(parse_qsl(parsed.query))
            query["client_id"] = self.panel.client_id()
            path = parsed.path + "?" + urlencode(query)
            values = body.get("body")
            if values is not None:
                values = {**values, "client_id": self.panel.client_id()}

            def work():
                try:
                    return {
                        "data": jsonable_encoder(
                            MediaBrowserService(service).request(
                                path, values, body.get("method", "GET")
                            )
                        )
                    }
                except Exception as error:
                    return {"error": service.jobs.error_message(error)}

            run_in_background(
                work,
                lambda result: self._complete(identifier, result, parsed.path, body.get("method")),
                lambda error: self._complete(identifier, {"error": str(error)}),
                coordinate=False,
            )
        except Exception as error:
            self.response.emit(identifier, json.dumps({"error": str(error)}))

    def _complete(self, identifier, result, path="", method="GET"):
        if not isValid(self):
            return
        if "error" not in result and path.startswith("media/playlists") and method != "GET":
            self.panel.hostRequested.emit("playlists-changed", {})
        self.response.emit(identifier, json.dumps(result))


class MediaBrowserPanel(BundledView):
    hostRequested = Signal(str, dict)

    def __init__(self, get_service, client_id, parent=None):
        self.get_service, self.client_id = get_service, client_id
        self.layout_value = "cinematic"
        self.horizon_value = "home"  # Horizon's view, chosen in Settings
        self.center_mode = False
        self.chat_open = False
        self.revision = 0
        self.kind, self.view = "video", "recent"
        self.queue: list[str] = []
        self.queue_music = True
        # A playing video's state, for the controls and details the view draws over its picture.
        self.playback: dict | None = None
        super().__init__(
            MediaBrowserBridge(self), Path(__file__).parents[1] / "web/static/media", "media"
        )
        if parent:
            self.setParent(parent)

    def _load_view(self):
        super()._load_view()
        # The film's picture sits behind the view's transparent slot (docs/specs/media-watch-page).
        self.web.page().setBackgroundColor(QColor(0, 0, 0, 0))

    def show_notice(self, text: str) -> None:
        if self.web and text:
            self.web.page().runJavaScript(
                "if(typeof toast==='function')toast(" + json.dumps(text) + ")"
            )

    def activate(self):
        """Reload browsing with the host's current settings."""
        self.revision += 1
        self.publish()

    def publish(self):
        """Send the host state; the view reloads only when the revision changes."""
        service = self.get_service()
        self.language = service.setup.settings.language
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "center_mode": self.center_mode,
                "chat_open": self.chat_open,
                "active": self.isVisible(),
                "revision": self.revision,
                "kind": self.kind,
                "view": self.view,
                "queue": self.queue,
                "queue_music": self.queue_music,
                "client_id": self.client_id(),
                "clients": [
                    {"id": row.id, "name": row.name}
                    for row in service.setup.settings.client_profiles
                    if row.enabled
                ],
                "language": self.language,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
                "adult_content": service.setup.settings.adult_content,
                "playback": self.playback,
            }
        )
        self.bridge.ready()
