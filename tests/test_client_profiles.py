from pathlib import Path

import pytest

from torrentlinker.config import Settings
from torrentlinker.domain import PathMapping, TorrentClient
from torrentlinker.store import SavedPlanItem, Store


def test_legacy_settings_migrate_without_moving_credentials(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"client":"deluge","deluge":{"host":"https://seedbox.test"},'
        '"path_mappings":[{"local":"/mnt","qbit":"/data"}],'
        '"download_folders":{"default":"/mnt/books"}}'
    )
    settings = Settings.load(path)
    original = settings.profile()
    assert original.client is TorrentClient.DELUGE
    assert original.host == "https://seedbox.test"
    assert settings.secret_name("deluge-password") == "deluge-password"
    other = settings.add_client("Home NAS", TorrentClient.DELUGE)
    settings.select_client(other.id)
    settings.deluge.host = "http://nas:8112"
    settings.path_mappings = [PathMapping("/books", "/other")]
    settings.download_folders.default = "/books"
    assert settings.secret_name("deluge-password") != "deluge-password"
    settings.save(path)
    restored = Settings.load(path)
    assert restored.profile().name == "Home NAS"
    restored.profile().name = "Renamed NAS"
    restored.select_client("default")
    assert restored.deluge.host == "https://seedbox.test"
    assert restored.download_folders.default == "/mnt/books"
    assert restored.path_mappings == [PathMapping("/mnt", "/data")]
    assert restored.for_client(other.id).deluge.host == "http://nas:8112"
    assert restored.active_client_id == "default"
    with pytest.raises(ValueError):
        restored.for_client("missing")


def test_same_hash_verification_and_plans_stay_with_their_client(tmp_path):
    original = Store(tmp_path / "state.db")
    nas = original.for_client("nas")
    original.start_verification("abc", Path("/local"), "first")
    nas.start_verification("abc", Path("/nas"), "second")
    assert original.verification("abc").item_path == Path("/local")
    assert nas.verification("abc").item_path == Path("/nas")
    assert nas.verification_hashes() == ["abc"]
    nas.end_verification("abc")
    assert original.verification_hashes() == ["abc"]
    item = SavedPlanItem("abc", "Book", 123, 1, None, "/books", 1, 1)
    original.save_plan([item])
    nas.save_plan([item])
    nas.mark_plan_item("abc", "added")
    assert original.saved_plan().items[0].outcome is None
    assert Store(tmp_path / "state.db").for_client("nas").saved_plan().items[0].outcome == "added"


def test_queue_destination_survives_default_change_and_rename(tmp_path):
    from torrentlinker.download_queue import enqueue, entries
    from torrentlinker.indexer import Candidate, Indexer

    settings = Settings()
    remote = settings.add_client("Remote")
    store = Store(tmp_path / "queue.db")
    indexer = Indexer("https://example.test/api", "secret", cache=store)
    candidate = Candidate("Book", 123, "https://example.test/get?id=1", infohash="a" * 40)
    assert enqueue(store, indexer, candidate, tmp_path)
    assert enqueue(store.for_client(remote.id), indexer, candidate, tmp_path)
    settings.default_client_id = remote.id
    settings.profile(remote.id).name = "Renamed"
    assert len(entries(store)) == 1
    assert entries(store.for_client(remote.id))[0].client_id == remote.id
    assert len(entries(store, all_clients=True)) == 2


def test_distributed_plan_respects_client_and_shared_disk_budgets(tmp_path):
    from torrentlinker.downloads import DownloadFolders
    from torrentlinker.multi_plan import distributed_plan
    from torrentlinker.plan import disk_of
    from torrentlinker.store import CatalogueRow

    settings = Settings()
    settings.download_folders = DownloadFolders(default=str(tmp_path))
    settings.ensure_profiles()
    remote = settings.add_client("Remote")
    remote.download_folders = DownloadFolders(default=str(tmp_path))
    store = Store(tmp_path / "state.db")
    store.save_catalogue(
        [
            CatalogueRow(
                str(i).zfill(40), f"Book {i}", 1000, 1, 7000, "https://example.test/get", "", 0
            )
            for i in range(10)
        ]
    )

    class Client:
        def torrents(self, **kwargs):
            return []

    plan = distributed_plan(
        settings,
        store,
        {"default": Client(), remote.id: Client()},
        {"default": 2000, remote.id: 3000},
    )
    sizes = {
        identifier: sum(i.candidate.size for i in plan.items if i.candidate.client_id == identifier)
        for identifier in ("default", remote.id)
    }
    assert sizes["default"] <= 2000
    assert sizes[remote.id] <= 3000
    assert all(sizes.values())
    assert len({i.candidate.infohash for i in plan.items}) == len(plan.items)
    assert {s.disk for s in plan.disk_spaces} == {disk_of(tmp_path)}


def test_distributed_note_plan_reserves_space_for_highest_initial_score(tmp_path):
    from torrentlinker.downloads import DownloadFolders
    from torrentlinker.multi_plan import distributed_plan
    from torrentlinker.plan import PlanGoal, PlanOptions
    from torrentlinker.store import CatalogueRow
    from torrentlinker.zen import GB, ZenClass, ZenProfile

    settings = Settings()
    settings.zen = ZenProfile(ZenClass.SWARM_KEEPER)
    settings.plan_options = PlanOptions(PlanGoal.NOTE)
    settings.download_folders = DownloadFolders(default=str(tmp_path))
    settings.ensure_profiles()
    remote = settings.add_client("Remote")
    remote.download_folders = DownloadFolders(default=str(tmp_path))
    store = Store(tmp_path / "state.db")
    store.save_catalogue(
        [
            CatalogueRow("a" * 40, "Small A", GB, 100, 2000, "", "", 0),
            CatalogueRow("b" * 40, "Small B", GB, 100, 2000, "", "", 0),
            CatalogueRow("c" * 40, "Highest note", 10 * GB, 1, 2000, "", "", 0),
        ]
    )

    class Client:
        def torrents(self, **kwargs):
            return []

    plan = distributed_plan(
        settings,
        store,
        {"default": Client(), remote.id: Client()},
        {"default": 10 * GB, remote.id: 10 * GB},
    )

    assert plan.items[0].candidate.title == "Highest note"
    assert plan.items[0].note == 1.5
    assert len(plan.items) == 3


def test_saved_distributed_plan_keeps_its_destination(tmp_path):
    from torrentlinker.client_profiles import pending_work

    settings = Settings()
    remote = settings.add_client("Seedbox")
    store = Store(tmp_path / "state.db")
    item = SavedPlanItem("abc", "Book", 123, 1, None, "/books", 1, 1, client_id=remote.id)
    store.save_plan([item])
    settings.default_client_id = remote.id
    settings.profile(remote.id).name = "New name"
    reopened = Store(tmp_path / "state.db")
    assert reopened.saved_plan().pending[0].client_id == remote.id
    assert pending_work(settings, reopened, remote.id)
    assert not pending_work(settings, reopened, "default")


def test_desktop_switch_rebuilds_scoped_views_without_moving_the_queue(
    qtbot, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QApplication

    from torrentlinker.gui.main_window import MainWindow

    started = []
    monkeypatch.setattr(MainWindow, "startup", lambda window: started.append(window))
    settings = Settings()
    remote = settings.add_client("Seedbox")
    remote.host = "https://seedbox.test"
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "state.db"))
    window.show()
    window.shell_host.command("client", {"client_id": remote.id})
    qtbot.waitUntil(lambda: bool(started))
    replacement = started[0]
    qtbot.addWidget(replacement)
    assert QApplication.instance().torrentlinker_window is replacement
    assert replacement.store.client_id == remote.id
    assert replacement.settings.qbit.host == "https://seedbox.test"
    assert replacement.settings.profile().name == "Seedbox"
    assert Settings.load(tmp_path / "settings.json").profile().id == remote.id


def test_client_manager_cancel_keeps_existing_credentials(qtbot, tmp_path):
    from tests.settings_support import edit_field, settings_page
    from torrentlinker.credentials import get_secret, set_secret

    set_secret("qbit-password", "original")
    dialog = settings_page(qtbot, tmp_path)
    edit_field(qtbot, dialog.view, "Password", "replacement")
    assert get_secret("qbit-password") == "original"
    dialog.close()  # leave without saving
    assert get_secret("qbit-password") == "original"
    assert not dialog.setup.path.exists()


def test_distributed_plan_can_trade_large_download_for_minimum_count(tmp_path):
    from torrentlinker.downloads import DownloadFolders
    from torrentlinker.multi_plan import distributed_plan
    from torrentlinker.plan import PlanOptions
    from torrentlinker.store import CatalogueRow

    settings = Settings()
    settings.plan_options = PlanOptions(min_torrents=2, min_seeders=3)
    settings.download_folders = DownloadFolders(default=str(tmp_path))
    settings.ensure_profiles()
    store = Store(tmp_path / "state.db")
    store.save_catalogue(
        [
            CatalogueRow("a" * 40, "Large", 10000, 3, 7000, "", "", 0),
            CatalogueRow("b" * 40, "Small A", 2000, 10, 7000, "", "", 0),
            CatalogueRow("c" * 40, "Small B", 2000, 10, 7000, "", "", 0),
            CatalogueRow("d" * 40, "Below seed minimum", 100, 2, 7000, "", "", 0),
        ]
    )

    class Client:
        def torrents(self, **kwargs):
            return []

    plan = distributed_plan(settings, store, {"default": Client()}, {"default": 10000})
    assert {item.candidate.title for item in plan.items} == {"Small A", "Small B"}
    assert not plan.issues


def test_native_connection_carries_the_current_client_reseed_choice(monkeypatch):
    from tests.fake_qbit import FakeQbit
    from torrentlinker.client_profiles import Connections
    from torrentlinker.config import Settings

    monkeypatch.setattr("torrentlinker.client_profiles.connect", lambda *args: FakeQbit())
    settings = Settings()
    settings.ensure_profiles()
    connections = Connections(lambda _: "")
    assert connections.client(settings).reseed_policy.mode == "client"
    settings.profile().reseed_layout = "links"
    settings.profile().reseed_link_root = "/chosen/links"
    client = connections.client(settings)
    assert client.reseed_policy.mode == "links"
    assert client.reseed_policy.root == "/chosen/links"
