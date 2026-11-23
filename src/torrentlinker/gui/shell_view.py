"""Bundled application chrome with explicit host-owned actions."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Signal, Slot

from torrentlinker.gui.community_view import BundledView, ViewBridge

WORKSPACES = ("zen", "library", "upload", "search", "feeds", "torrents", "assistant", "media")
REGION_ACTIONS = {
    "navigation": {"navigate", "theme", "language", "shortcuts"},
    "header": {"navigate", "client"},
    "band": {"refresh-profile"},
    "update": {"release", "dismiss"},
    "help": {"close"},
}


class ShellBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self, view):
        super().__init__()
        self.view = view

    @Slot(int, str, str)
    def requestAsync(self, identifier: int, action: str, payload: str) -> None:
        try:
            values = json.loads(payload)
            if not isinstance(values, dict):
                raise ValueError("Invalid shell action.")
            if action == "layout":
                if self.view.region != "navigation" or self.view.compact:
                    self.view.setFixedHeight(max(28, min(600, int(values["height"]))))
                result = None
            elif action in REGION_ACTIONS[self.view.region]:
                result = self.view.command(action, values)
                self.view.refresh()
            else:
                raise ValueError("Unknown shell action.")
            self.response.emit(identifier, json.dumps({"data": result}))
        except (ValueError, TypeError, KeyError, OverflowError, OSError) as error:
            self.response.emit(identifier, json.dumps({"error": str(error)}))


class ShellView(BundledView):
    def __init__(self, region, snapshot, command, *, language="en"):
        if region not in REGION_ACTIONS:
            raise ValueError("Unknown shell region.")
        self.region = region
        self.snapshot = snapshot
        self.command = command
        self.compact = False
        super().__init__(
            ShellBridge(self), Path(__file__).parents[1] / "web/static/shell", "shell", language
        )
        if region != "navigation":
            self.setFixedHeight(40 if region in {"band", "update"} else 100)

    def refresh(self):
        value = self.snapshot()
        self.language = value.get("language", self.language)
        self.compact = bool(value.get("compact"))
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
                **value,
                "region": self.region,
            }
        )
        self.bridge.environment.emit(self.bridge.environment_value)
