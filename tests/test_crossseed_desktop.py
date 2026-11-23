"""The desktop app runs the Cross-seed engines, one per enabled client profile."""

import threading

from torrentlinker import crossseed_desktop
from torrentlinker.config import Settings
from torrentlinker.crossseed_desktop import DesktopCrossSeed
from torrentlinker.store import Store


class Rules:
    paused = True


class Engine:
    passes = 0

    def __init__(self, setup, library, root):
        self.setup, self.library, self.root = setup, library, root
        self.rules = Rules()

    def settle(self):
        Engine.passes += 1

    def targets(self):
        return []


def test_the_desktop_runs_one_engine_per_enabled_client_until_it_quits(tmp_path, monkeypatch):
    monkeypatch.setattr(crossseed_desktop, "CrossSeed", Engine)
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.ensure_profiles()
    settings.save(path)
    desktop = DesktopCrossSeed(path, Store(tmp_path / "state.db"), list, interval=0.01)

    first = desktop.engines()
    assert [e.setup.settings.active_client_id for e in first] == [settings.active_client_id]
    assert desktop.engines() == first  # kept, so its workers stay keyed to it

    Engine.passes = 0
    desktop.start()
    for _ in range(500):
        if Engine.passes >= 2:
            break
        threading.Event().wait(0.01)
    desktop.stop()
    assert Engine.passes >= 2
    assert desktop.shutdown.is_set()
