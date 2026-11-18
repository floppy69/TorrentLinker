"""Desktop host for the approved bundled Profile and its shared SVG charts."""

from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Signal, Slot

from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.profile_history import ProfileDay
from torrentlinker.profile_overview import PERIODS, overview
from torrentlinker.profile_workspace import AVATAR_MAX_BYTES, image_type

ASSETS = Path(__file__).parents[1] / "web" / "static" / "profile"


class ProfileBridge(ViewBridge):
    def __init__(self, view: ProfileView):
        super().__init__()
        self.view = view

    @Slot(str, str, result=str)
    def request(self, path: str, payload: str) -> str:
        try:
            body = json.loads(payload)
            if path == "refresh":
                self.view.refresh_requested.emit()
            elif (
                path == "period"
                and isinstance(body, dict)
                and type(body.get("days")) is int
                and body["days"] in PERIODS
            ):
                self.view.set_period(body["days"])
            else:
                raise ValueError("Unknown profile operation.")
            return json.dumps({"data": {}})
        except (ValueError, TypeError) as error:
            return json.dumps({"error": str(error)})


class ProfileView(BundledView):
    refresh_requested = Signal()

    def __init__(self, settings: QSettings | None = None, language: str = "en") -> None:
        self._settings = settings if settings is not None else QSettings()
        saved = self._settings.value("profile/period", 30)
        try:
            self.period = int(str(saved)) if int(str(saved)) in PERIODS else 30
        except (TypeError, ValueError):
            self.period = 30
        self.state: dict[str, Any] = {}
        self.history: list[ProfileDay] = []
        self.clients: dict[str, Any] | None = None
        self._avatar = ""
        self._busy = False
        self._notice = ""
        super().__init__(ProfileBridge(self), ASSETS, "profile", language)

    def set_period(self, days: int) -> None:
        if days not in PERIODS:
            raise ValueError("Invalid profile period.")
        self.period = days
        self._settings.setValue("profile/period", days)
        self.refresh()

    def show_state(self, state: dict[str, Any], history: list[ProfileDay] | None = None) -> None:
        self.state = state
        if history is not None:
            self.history = history
        self._notice = ""
        self.refresh()

    def show_avatar(self, data: bytes | None) -> None:
        kind = image_type(data) if data and len(data) <= AVATAR_MAX_BYTES else None
        self._avatar = (
            f"data:{kind};base64,{base64.b64encode(data).decode()}" if kind and data else ""
        )
        self.refresh()

    def show_torrent_clients(self, clients: dict[str, Any] | None) -> None:
        self.clients = clients
        self.refresh()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.refresh()

    def show_notice(self, text: str) -> None:
        self._notice = text
        self.refresh()

    def refresh(self) -> None:
        self.bridge.environment_value = json.dumps(
            {
                "language": self.language,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
                "days": self.period,
                "state": {
                    **self.state,
                    "overview": overview(self.state, self.history, self.period, date.today()),
                },
                "clients": self.clients,
                "avatar": self._avatar,
                "busy": self._busy,
                "notice": self._notice,
            }
        )
        self.bridge.ready()
