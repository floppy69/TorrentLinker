"""Desktop data and owner preferences for the bundled Seeding page."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QSettings, Signal, Slot
from shiboken6 import isValid

from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.gui.errors import error_text
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.seeding import Seeding
from torrentlinker.web.seeding import SeedingFilters, seeding_page
from torrentlinker.zen import ZenDay, ZenProfile


class SeedingBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.view: SeedingView | None = None

    @Slot(int, str, str)
    def requestAsync(self, identifier: int, action: str, payload: str) -> None:
        view = self.view
        if view is None:
            return

        def done(value):
            if isValid(self):
                self.response.emit(identifier, json.dumps({"data": value}))

        def failed(error):
            if isValid(self):
                self.response.emit(identifier, json.dumps({"error": error_text(error)}))

        try:
            body = json.loads(payload)
            if not isinstance(body, dict) or body.pop("_client", view.client()) != view.client():
                raise ValueError("The target client changed. Reopen Seeding.")
            if action == "page":
                snapshot = view.seeding or Seeding([], ZenDay(), [])
                profile, uploads = view.profile(), view.uploads
                sort = body.get("sort", "zen")
                if sort not in {
                    "name",
                    "size",
                    "seeders",
                    "seed_days",
                    "zen",
                    "note",
                    "ratio",
                    "weight",
                }:
                    raise ValueError("Unknown Seeding sort.")
                offset, limit = int(body.get("offset", 0)), int(body.get("limit", 100))
                if offset < 0 or not 1 <= limit <= 200:
                    raise ValueError("Invalid Seeding page.")
                filters = SeedingFilters.model_validate(body)
                query, group = str(body.get("q", "")), str(body.get("group", ""))
                descending = str(body.get("descending", "true")).lower() == "true"
                run_in_background(
                    lambda: seeding_page(
                        snapshot,
                        profile,
                        uploads,
                        query=query,
                        filters=filters,
                        group=group,
                        descendants=str(body.get("descendants", "false")).lower() == "true",
                        sort=sort,
                        descending=descending,
                        offset=offset,
                        limit=limit,
                    ),
                    done,
                    failed,
                )
                return
            if action == "expanded":
                groups = body.get("groups")
                if (
                    not isinstance(groups, list)
                    or len(groups) > 10000
                    or any(not isinstance(group, str) or len(group) > 100 for group in groups)
                ):
                    raise ValueError("Invalid expanded categories.")
                view.preferences.setValue(view.preference_key(), groups)
            elif action == "refresh":
                view.reload()
            elif action == "uploads":
                count = body.get("uploads")
                if type(count) is not int or not 0 <= count <= 1_000_000:
                    raise ValueError("Enter a valid upload count.")
                view.uploads = count
                view.uploads_changed.emit(count)
                view.revision += 1
                view.refresh()
            else:
                raise ValueError("Unknown Seeding operation.")
            done(None)
        except (ValueError, TypeError, KeyError, OSError) as error:
            failed(error)


class SeedingView(BundledView):
    updated = Signal(object)
    unavailable = Signal()
    uploads_changed = Signal(int)

    def __init__(
        self,
        load: Callable[[], Callable[[], Seeding]],
        profile: Callable[[], ZenProfile] = ZenProfile,
        uploads: int = 0,
        *,
        preferences: QSettings | None = None,
    ) -> None:
        self.load, self.profile, self.uploads = load, profile, uploads
        self.seeding: Seeding | None = None
        self.preferences = preferences if preferences is not None else QSettings()
        self.client: Callable[[], str] = lambda: "default"
        self.scope = ""
        self.busy = False
        self.error = ""
        self.revision = 0
        bridge = SeedingBridge()
        super().__init__(bridge, Path(__file__).parents[1] / "web/static/seeding", "seeding")
        bridge.view = self
        self.refresh()

    def preference_key(self) -> str:
        return f"zen/seeding/{self.scope}/{self.client()}/expanded"

    def refresh(self) -> None:
        key = self.preference_key()
        if not self.preferences.contains(key):
            previous = self.preferences.value("zen/expanded_categories", [], type=list)
            if not isinstance(previous, list):
                previous = []
            self.preferences.setValue(
                key,
                [
                    value.removeprefix("category:") or "unknown"
                    for value in previous
                    if isinstance(value, str) and value.startswith("category:")
                ],
            )
        expanded = self.preferences.value(key, [], type=list)
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
                "active": self.isVisible(),
                "state": {
                    "client_id": self.client(),
                    "expanded": expanded,
                    "revision": self.revision,
                    "busy": self.busy,
                    "error": self.error,
                    "tags": asdict(self.seeding.tag_sync)
                    if self.seeding and self.seeding.tag_sync
                    else None,
                },
            }
        )
        self.bridge.ready()

    def reload(self, *, quiet: bool = False) -> None:
        if self.busy:
            return
        self.busy, self.error = True, ""
        self.refresh()
        try:
            work = self.load()
        except Exception as error:
            self._failed(error)
            return
        run_in_background(work, self.show_seeding, self._failed)

    def show_seeding(self, view: Seeding) -> None:
        self.busy, self.error = False, ""
        self.seeding = view
        self.revision += 1
        self.refresh()
        self.updated.emit(view)

    def _failed(self, error: Exception) -> None:
        self.busy, self.error = False, error_text(error)
        self.unavailable.emit()
        self.refresh()
