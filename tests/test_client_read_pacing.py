from pathlib import Path

import pytest

from tests.fake_qbit import FakeQbit
from torrentlinker.domain import Torrent
from torrentlinker.library import indexer_contents
from torrentlinker.store import Store


@pytest.mark.parametrize("latency", [0.001, 0.3, 3.0])
def test_bulk_file_reads_leave_client_headroom(tmp_path, latency):
    client = FakeQbit(
        by_hash={
            str(i): Torrent(str(i), str(i), Path("/data"), tracker="https://c411.org/announce")
            for i in range(20)
        }
    )
    now = [0.0]
    starts = []

    def files(infohash):
        starts.append(now[0])
        now[0] += latency
        return {"movie.mkv": 1}

    def sleep(seconds):
        now[0] += seconds

    client.files = files
    store = Store(tmp_path / "state.db")
    indexer_contents(client, store, "https://c411.org/api", clock=lambda: now[0], sleep=sleep)
    # No more than five starts/s, and measured reads use at most 20% of the loop.
    assert all(
        b - a >= max(0.2, latency * 5) - 1e-8 for a, b in zip(starts, starts[1:], strict=False)
    )
    indexer_contents(client, store, "https://c411.org/api", clock=lambda: now[0], sleep=sleep)
    assert len(starts) == 20  # the second scan is entirely cached


def test_desktop_plan_and_profile_share_the_same_client(qtbot, tmp_path):
    from torrentlinker.config import Settings
    from torrentlinker.gui.main_window import MainWindow

    settings = Settings()
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(window)
    plan_client = window.qbit()._inner
    profile_client = window._connections.client(settings, settings.active_client_id)._inner
    assert plan_client is profile_client


def test_cancel_during_backoff_keeps_files_read_so_far(tmp_path):
    import threading

    client = FakeQbit(
        by_hash={
            str(i): Torrent(str(i), str(i), Path("/data"), tracker="https://c411.org/announce")
            for i in range(2)
        }
    )
    stop = threading.Event()
    store = Store(tmp_path / "state.db")
    client.files = lambda infohash: {"movie.mkv": 1}
    with pytest.raises(InterruptedError):
        indexer_contents(
            client, store, "https://c411.org/api", stop=stop, progress=lambda *args: stop.set()
        )
    assert store.torrent_files(["0", "1"]) == {"0": {"movie.mkv": 1}}


def test_pacing_recovers_gradually_after_a_slow_read():
    from torrentlinker.read_pacing import ReadPacing

    pacing = ReadPacing()
    assert pacing.observe(3) == 12
    assert pacing.observe(0.001) > 13
    assert pacing.rate < 0.08


def test_plan_with_18000_torrents_never_requests_their_file_lists(qtbot, tmp_path, monkeypatch):
    from torrentlinker.config import Settings
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.store import CatalogueRow

    downloads = tmp_path / "downloads"
    downloads.mkdir()
    settings = Settings()
    settings.download_folders = DownloadFolders({2030: str(downloads)})
    settings.indexer_categories = {2030: IndexerCategory("Movies")}
    settings.plan_categories = [2030]
    store = Store(tmp_path / "state.db")
    store.save_catalogue([CatalogueRow("f" * 40, "New Film", 1000, 10, 2030, "", "", 1)])
    client = FakeQbit(
        by_hash={f"{i:040x}": Torrent(f"{i:040x}", f"Film {i}", downloads) for i in range(18000)}
    )
    calls = []

    def listing(tag=None, with_files=True):
        calls.append(with_files)
        assert not with_files
        return list(client.by_hash.values())

    def files(infohash):
        pytest.fail("Plan fetched a per-torrent file list")

    client.torrents = listing
    client.files = files
    window = MainWindow(settings, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "qbit", lambda: client)
    result = window.plan_maker()()
    assert len(result.items) == 1
    assert calls == [False]
