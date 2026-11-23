"""The Cross-seed engines of the desktop app: the same runner as the web server's, over a
DesktopSetup per Torrent Client profile, started with the app and stopped when it quits."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from torrentlinker.config import Settings
from torrentlinker.crossseed import CrossSeed, CrossSeedRunner

if TYPE_CHECKING:
    from torrentlinker.store import Store
    from torrentlinker.web.library import LibraryEntry


class DesktopCrossSeed:
    def __init__(
        self,
        settings_path: Path,
        store: Store,
        entries: Callable[[], list[LibraryEntry]],
        interval: float = 30.0,
    ) -> None:
        self.settings_path, self.store, self.entries = settings_path, store, entries
        self.shutdown = threading.Event()
        self.runner = CrossSeedRunner(self.engines, self.shutdown, interval)
        self._root: object | None = None
        self._held: dict[str, CrossSeed] = {}

    def start(self) -> None:
        self.runner.start()

    def stop(self) -> None:
        self.shutdown.set()

    def engines(self) -> list[CrossSeed]:
        """One engine per enabled client profile, kept between passes (their workers are keyed
        by it) and given the settings as saved now."""
        from torrentlinker.agent.desktop import DesktopSetup
        from torrentlinker.web.library import Library

        settings = Settings.load(self.settings_path)
        settings.ensure_profiles()
        if self._root is None:
            self._root = DesktopSetup(
                settings, self.settings_path, self.store.for_client(settings.active_client_id)
            )
        root = self._root
        assert isinstance(root, DesktopSetup)
        root.settings = settings
        found = []
        for profile in settings.client_profiles:
            if not profile.enabled:
                continue
            held = self._held.get(profile.id)
            fresh = settings.for_client(profile.id)
            if held is None:
                setup = root.for_client(profile.id)
                setup.settings = fresh
                held = CrossSeed(setup, Library(setup), root)
                self._held[profile.id] = held
            elif held.setup.settings != fresh:
                held.setup.settings = fresh
                held.setup._client = None  # its connection may have changed
            held.library.entries = list(self.entries())
            found.append(held)
        return found
