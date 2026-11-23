"""Shared transport controls around the host's existing playback session."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QColor
from shiboken6 import isValid

from torrentlinker.gui.community_view import BundledView, ViewBridge


class PlayerBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self, view):
        super().__init__()
        self.view = view

    @Slot()
    def ready(self):
        self.view.connected = True
        super().ready()
        if self.view.pending_menu is not None:
            self.view.open_menu(queue=self.view.pending_menu)

    @Slot(int, str, str)
    def requestAsync(self, identifier: int, path: str, payload: str) -> None:
        try:
            body = json.loads(payload)
            if not isinstance(body, dict):
                raise ValueError("Invalid player operation.")
            if path == "interaction":
                self.view.keyboard_focus = bool(body.get("keyboard"))
                self.view.interacted.emit()
                value = None
            elif path == "layout":
                self.view.menu_open = bool(body.get("menu_open"))
                # Horizon's pause screen covers the picture; the page never asks for more.
                self.view.setFixedHeight(max(72, min(2000, int(body["height"]))))
                value = None
            elif path == "artwork":
                current = self.view.snapshot()
                if body.get("media_id") != current.get("media_id") or not current.get("item"):
                    raise ValueError("Player source changed.")
                self.view.artwork(
                    current["media_id"],
                    lambda value: self._respond(identifier, {"data": value}),
                    lambda error: self._respond(identifier, {"error": str(error)}),
                )
                return
            elif path == "command":
                current = self.view.snapshot()
                for key in ("client_id", "media_id", "source_token"):
                    if body.get(key) != current.get(key):
                        raise ValueError("Player source changed. Use the current controls.")
                action = body.get("action")
                if action not in {
                    "quality",
                    "audio",
                    "rate",
                    "toggle",
                    "seek",
                    "volume",
                    "previous",
                    "next",
                    "shuffle",
                    "repeat",
                    "select_track",
                    "fullscreen",
                    "stop",
                    "external",
                    "chat",
                    "center",
                    "expand",
                    "refresh-preview",
                    "queue-play",
                    "queue-remove",
                    "playlist-save",
                    "playlist-load",
                    "playlist-delete",
                }:
                    raise ValueError("Unknown player control.")
                if action in {"queue-play", "queue-remove", "playlist-save"} and body.get(
                    "queue_revision"
                ) != current.get("queue_revision"):
                    raise ValueError("The playback queue changed. Use the current controls.")
                values = body.get("values", {})
                if not isinstance(values, dict):
                    raise ValueError("Invalid player values.")
                value = self.view.command(action, values)
                self.view.refresh()
            else:
                raise ValueError("Unknown player operation.")
            self.response.emit(identifier, json.dumps({"data": value}))
        except (ValueError, TypeError, KeyError, OverflowError, OSError) as error:
            self.response.emit(identifier, json.dumps({"error": str(error)}))

    def _respond(self, identifier: int, result: dict) -> None:
        if isValid(self):
            self.response.emit(identifier, json.dumps(result))


class PlayerView(BundledView):
    interacted = Signal()

    def __init__(self, snapshot, command, artwork=None):
        self.snapshot = snapshot
        self.command = command
        self.artwork = artwork  # Horizon's bar shows the poster
        self.menu_open = False
        self.keyboard_focus = False
        self.connected = False
        self.pending_menu = None
        super().__init__(
            PlayerBridge(self), Path(__file__).parents[1] / "web" / "static" / "player", "player"
        )
        self.setFixedHeight(80)

    def _load_view(self):
        super()._load_view()
        self.web.page().setBackgroundColor(QColor(0, 0, 0, 0))

    def refresh(self):
        value = self.snapshot()
        self.language = value.get("language", "en")
        self.bridge.environment_value = json.dumps(value)
        self.bridge.environment.emit(self.bridge.environment_value)

    def close_menu(self):
        self.menu_open = False
        if self.web is not None:
            self.web.page().runJavaScript("setMenu(false)")

    def open_menu(self, *, queue=False):
        self.show()
        self.refresh()
        self.pending_menu = queue
        if self.web is not None and self.connected:
            self.pending_menu = None
            self.web.page().runJavaScript(
                "setMenu(true);"
                + ("document.getElementById('player-queue-details').open=true;" if queue else "")
            )

    def focus_fullscreen(self):
        self.refresh()
        if self.web is not None:
            self.web.setFocus()
            self.web.page().runJavaScript("document.getElementById('player-fullscreen').focus()")


class PlayerDetailsBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self, view):
        super().__init__()
        self.view = view

    @Slot(int, str, str)
    def requestAsync(self, identifier: int, path: str, payload: str) -> None:
        try:
            body = json.loads(payload)
            if not isinstance(body, dict):
                raise ValueError("Invalid details operation.")
            if path == "layout":
                self.view.wanted = max(0, int(body["height"]))
                self.view.setFixedHeight(min(self.view.wanted, self.view.max_height))
                self.view.height_changed.emit()
            elif path == "artwork":
                current = self.view.snapshot()
                if body.get("media_id") != current.get("media_id") or not current.get("item"):
                    raise ValueError("Player source changed.")
                self.view.artwork(
                    current["media_id"],
                    lambda value: self._respond(identifier, {"data": value}),
                    lambda error: self._respond(identifier, {"error": str(error)}),
                )
                return
            elif path == "command":
                current = self.view.snapshot()
                for key in ("client_id", "media_id", "source_token"):
                    if body.get(key) != current.get(key):
                        raise ValueError("Player source changed. Use the current controls.")
                values = body.get("values")
                if body.get("action") != "select_track" or not isinstance(values, dict):
                    raise ValueError("Unknown details control.")
                self.view.command("select_track", values)
            else:
                raise ValueError("Unknown details operation.")
            self._respond(identifier, {"data": None})
        except (ValueError, TypeError, KeyError, OverflowError, OSError) as error:
            self._respond(identifier, {"error": str(error)})

    def _respond(self, identifier: int, result: dict) -> None:
        if isValid(self):
            self.response.emit(identifier, json.dumps(result))


class PlayerDetailsView(BundledView):
    """The playing film's details under the picture: the same view as the Web UI's."""

    height_changed = Signal()

    def __init__(self, snapshot, command, artwork):
        self.snapshot = snapshot
        self.command = command
        self.artwork = artwork
        self.published = ""
        self.wanted = 200  # the page's own height
        self.max_height = 600  # the host keeps the picture first; beyond this the page scrolls
        super().__init__(
            PlayerDetailsBridge(self),
            Path(__file__).parents[1] / "web" / "static" / "player-details",
            "nowplaying",
        )
        self.setFixedHeight(200)  # until the page reports its own height

    def _load_view(self):
        super()._load_view()
        self.web.page().setBackgroundColor(QColor(0, 0, 0, 0))

    def refresh(self):
        value = self.snapshot()
        self.language = value.get("language", "en")
        encoded = json.dumps(value)
        # Called with every player update: the page renders only when its details change.
        if encoded == self.published:
            return
        self.published = encoded
        self.bridge.environment_value = encoded
        self.bridge.environment.emit(encoded)
