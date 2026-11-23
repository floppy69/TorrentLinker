from pathlib import Path

import pytest

from tests.test_plan_interfaces import choose_plan_category, configure_plan
from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def test_main_window_opens(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()


def test_settings_open_on_the_connections_tab_with_hidden_keys(qtbot, tmp_path):
    from tests.settings_support import settings_page
    from tests.test_community_interfaces import js

    dialog = settings_page(qtbot, tmp_path)
    assert (
        js(qtbot, dialog.view, "document.querySelector('.settings-form h2').textContent")
        == "Connections"
    )
    assert js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('input[type=password]')].every(input=>input.value==='')",
    )
    assert js(qtbot, dialog.view, "document.querySelectorAll('input[type=password]').length") >= 4


def test_choosing_deluge_saves_it_and_the_app_connects_through_deluge(qtbot, tmp_path):
    from tests.settings_support import edit_field, save_group, settings_page
    from torrentlinker.credentials import get_secret
    from torrentlinker.deluge import DelugeApi
    from torrentlinker.domain import TorrentClient
    from torrentlinker.qbit import QbitApi

    dialog = settings_page(qtbot, tmp_path)
    edit_field(qtbot, dialog.view, "Client type", "deluge")
    edit_field(qtbot, dialog.view, "Address", "http://nas:8112")
    edit_field(qtbot, dialog.view, "Password", "secret")
    save_group(qtbot, dialog)
    settings = Settings.load(tmp_path / "settings.json")
    assert settings.client is TorrentClient.DELUGE
    assert settings.deluge.host == "http://nas:8112"
    assert get_secret("deluge-password") == "secret"
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    assert isinstance(window.qbit()._inner, DelugeApi)
    settings.client = TorrentClient.QBITTORRENT
    assert isinstance(window.qbit()._inner, QbitApi)


def test_choosing_transmission_saves_it_and_the_app_connects_through_it(qtbot, tmp_path):
    from tests.settings_support import edit_field, save_group, settings_page
    from torrentlinker.credentials import get_secret
    from torrentlinker.domain import TorrentClient
    from torrentlinker.qbit import QbitApi
    from torrentlinker.transmission import TransmissionApi

    dialog = settings_page(qtbot, tmp_path)
    edit_field(qtbot, dialog.view, "Client type", "transmission")
    edit_field(qtbot, dialog.view, "Address", "http://nas:9091")
    edit_field(qtbot, dialog.view, "Username", "me")
    edit_field(qtbot, dialog.view, "Password", "secret")
    save_group(qtbot, dialog)
    settings = Settings.load(tmp_path / "settings.json")
    assert settings.client is TorrentClient.TRANSMISSION
    assert settings.transmission.host == "http://nas:9091"
    assert get_secret("transmission-password") == "secret"
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    assert isinstance(window.qbit()._inner, TransmissionApi)
    settings.client = TorrentClient.QBITTORRENT
    assert isinstance(window.qbit()._inner, QbitApi)


@pytest.mark.parametrize("accept", [True, False])
def test_part_names_are_turned_off_only_if_the_user_agrees_then_the_action_runs_again(  # type: ignore[no-untyped-def]
    qtbot, monkeypatch, accept: bool
) -> None:
    from PySide6.QtWidgets import QMessageBox, QWidget

    from torrentlinker.gui.errors import offer_whole_names
    from torrentlinker.transmission import PartialNamesOn

    parent = QWidget()
    qtbot.addWidget(parent)
    answer = QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answer)
    done: list[str] = []

    assert offer_whole_names(
        parent, PartialNamesOn(lambda: done.append("off")), lambda: done.append("again")
    )
    assert not offer_whole_names(parent, RuntimeError("other"), lambda: done.append("never"))

    if accept:
        qtbot.waitUntil(lambda: done == ["off", "again"])
    else:
        qtbot.wait(50)
        assert done == []


def test_content_kind_chosen_in_settings_comes_back_as_a_content_kind(qtbot, tmp_path):
    from tests.settings_support import settings_page
    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.domain import ContentKind, LibraryFolder

    settings = Settings(library_folders=[LibraryFolder(tmp_path, 1, ContentKind.MODEL_3D)])
    dialog = settings_page(qtbot, tmp_path, settings, section="library")
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Edit').click()",
    )
    assert (
        js(qtbot, dialog.view, "document.querySelector('[aria-label=\"Content kind\"]').value")
        == "3d-model"
    )
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Save folder').click()",
    )
    qtbot.waitUntil(lambda: dialog.setup.path.exists())
    assert Settings.load(dialog.setup.path).library_folders[0].kind is ContentKind.MODEL_3D
    wait_js(qtbot, dialog.view, "!document.querySelector('#settings-error').textContent")


def test_library_exposes_seed_states_to_the_shared_view(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
    from torrentlinker.library import LibraryEntry

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    folder = LibraryFolder(tmp_path)
    window.library_model.set_entries(
        [
            LibraryEntry(folder, LocalItem(tmp_path / "a"), ItemState.ORPHAN),
            LibraryEntry(folder, LocalItem(tmp_path / "b"), ItemState.SEEDED),
        ]
    )

    rows = window.library_workspace.reseed.request("state", {})["rows"]
    assert [(r["name"], r["state"]) for r in rows] == [("a", "orphan"), ("b", "seeded")]


def test_a_typed_folder_path_is_added_to_the_library_folders(qtbot, tmp_path):
    from tests.settings_support import edit_field, settings_page
    from tests.test_community_interfaces import js

    folder = tmp_path / "library"
    folder.mkdir()
    dialog = settings_page(qtbot, tmp_path, section="library")
    edit_field(qtbot, dialog.view, "Folder on the TorrentLinker host", str(folder))
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Save folder').click()",
    )
    qtbot.waitUntil(lambda: bool(dialog.setup.settings.library_folders))
    assert [f.path for f in dialog.setup.settings.library_folders] == [folder]


def test_zen_profile_entered_in_settings_comes_back(qtbot, tmp_path):
    from tests.settings_support import edit_field, save_group, settings_page
    from tests.test_community_interfaces import js
    from torrentlinker.zen import ZenClass, ZenProfile

    settings = Settings(zen=ZenProfile(ZenClass.SWARM_KEEPER, 0.02, 20, 300))
    dialog = settings_page(qtbot, tmp_path, settings, section="zen")
    assert (
        js(
            qtbot,
            dialog.view,
            "document.querySelector('[aria-label=\"Seed hours per day\"]').value",
        )
        == "20"
    )
    edit_field(qtbot, dialog.view, "Class", "reuploader")
    save_group(qtbot, dialog)
    saved = Settings.load(dialog.setup.path)
    assert saved.zen.zen_class is ZenClass.REUPLOADER
    assert saved.zen.seed_hours == 20 and saved.zen.torrent_cap == 300


def test_main_window_opens_on_the_zen_tab_and_shows_the_seeding_view(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.domain import Torrent
    from torrentlinker.seeding import seeding
    from torrentlinker.zen import GB, ZenProfile

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    t = Torrent(
        "h",
        "Film",
        tmp_path,
        tracker="https://c411.org/a",
        swarm_seeders=100,
        seeding_time=90 * 86400,
        size=4 * GB,
        state="uploading",
    )

    window.zen_tab.seeding_view.show_seeding(seeding(ZenProfile(), [t], "https://c411.org/api"))

    assert window.tabs.currentWidget() is window.zen_tab
    assert window.tabs.tabText(1) == "Library"
    observed = window.zen_tab.seeding_view.seeding
    assert observed is not None and len(observed.rows) == 1
    assert observed.rows[0].zen is not None


def test_periodic_qbit_refresh_updates_estimates_after_a_tracker_response(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import Torrent
    from torrentlinker.plan import Plan
    from torrentlinker.store import CatalogueRow
    from torrentlinker.zen import GB, ZenClass, ZenProfile

    settings = Settings(zen=ZenProfile(ZenClass.SWARM_KEEPER))
    store = Store(tmp_path / "s.db")
    row = CatalogueRow("a" * 40, "Book", 4 * GB, 100, 7000, "u", "d", 123, "zen-lab")
    store.save_catalogue([row])
    t = Torrent(
        row.infohash,
        "Book",
        tmp_path,
        state="uploading",
        tracker="https://tracker.c411.org/announce",
        swarm_seeders=-1,
        size=4 * GB,
    )
    qbit = FakeQbit({row.infohash: t})
    window = MainWindow(settings, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    window.qbit = lambda: qbit  # type: ignore[assignment,method-assign,return-value]
    view = window.zen_tab.seeding_view
    view.show_seeding(window.seeding_loader()())
    before = view.seeding.day.total
    assert view.seeding.rows[0].torrent.swarm_seeders == -1
    assert store.catalogue()[0].seeders == 100

    window.zen_tab.plan_view.show_plan(Plan())
    qbit._set(row.infohash, swarm_seeders=5)
    with qtbot.waitSignal(view.updated, timeout=5000):
        window.seeding_timer.timeout.emit()

    assert view.seeding.rows[0].torrent.swarm_seeders == 5
    assert view.seeding.day.total > before
    cached = store.catalogue()[0]
    assert cached.seeders == 4  # the current user is already one of the five seeders
    assert cached.source == "zen-lab" and cached.seen_at == 123
    assert window.seeding_timer.interval() == 30_000


def test_download_folders_tab_flags_categories_left_without_a_folder(qtbot, tmp_path):
    from tests.settings_support import settings_page
    from tests.test_community_interfaces import js
    from torrentlinker.downloads import DownloadFolders, IndexerCategory

    settings = Settings(language="en")
    settings.indexer_categories = {
        2000: IndexerCategory("Films"),
        2030: IndexerCategory("VO", 2000),
        7000: IndexerCategory("Ebook"),
    }
    settings.download_folders = DownloadFolders({2000: "/dl/films"})
    dialog = settings_page(qtbot, tmp_path, settings, section="downloads")
    text = js(qtbot, dialog.view, "document.querySelector('.settings-form').textContent")
    assert "Films › VO" in text
    assert text.count("/dl/films") >= 2
    assert "EbookExcluded: no download folder" in text


def test_zen_band_shows_the_balance_and_explains_a_key_without_profile_scope(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.zen_view import ZenBand
    from torrentlinker.profile import ProfileError, ProfileProblem, UserProfile
    from torrentlinker.zen import ZenClass

    band = ZenBand()
    qtbot.addWidget(band)
    band.show_profile(
        UserProfile("v", "tanker", ZenClass.TANKER, 0.02, 12.5, False, "insufficient_balance")
    )
    assert "12.5" in band.values["balance"]
    assert "not enough Zen" in band.profile_notice

    band.show_profile_error(ProfileError(ProfileProblem.MISSING_SCOPE))
    assert "Profil (lecture)" in band.profile_notice


def test_profile_read_at_startup_fills_the_zen_profile(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.profile import UserProfile
    from torrentlinker.zen import ZenClass

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    refreshed = []
    window.zen_tab.seeding_view.reload = lambda: refreshed.append(True)  # type: ignore[method-assign]
    window._profile_read(
        UserProfile("v", "swarm-keeper", ZenClass.SWARM_KEEPER, 0.04, 3, True, None)
    )

    assert window.settings.zen.zen_class is ZenClass.SWARM_KEEPER
    assert window.settings.zen.tree_bonus == 0.04
    assert Settings.load(tmp_path / "settings.json").zen == window.settings.zen
    assert refreshed  # the Seeding view is estimated again with the new Class


def test_class_comparison_highlights_the_current_class_and_labels_reuploader_rough(qtbot) -> None:  # type: ignore[no-untyped-def]
    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.gui.seeding_view import SeedingView
    from torrentlinker.seeding import Seeding
    from torrentlinker.zen import ZenClass, ZenDay, ZenProfile

    widget = SeedingView(
        lambda: lambda: Seeding([], ZenDay(), []),
        lambda: ZenProfile(ZenClass.SWARM_KEEPER),
        uploads=10,
    )
    qtbot.addWidget(widget)
    widget.show()
    wait_js(qtbot, widget, "document.querySelector('#seeding-classes strong')!==null")
    assert js(
        qtbot,
        widget,
        "document.querySelector('#seeding-classes strong').textContent.includes('Swarm Keeper')",
    )
    assert js(
        qtbot, widget, "document.querySelector('#seeding-classes').textContent.includes('rough')"
    )
    assert js(
        qtbot, widget, "document.querySelector('#seeding-classes').textContent.includes('4.3')"
    )


def test_library_retains_zen_estimates_for_orphans_with_a_match(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]

    from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
    from torrentlinker.gui.library_model import LibraryModel
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import Match
    from torrentlinker.review import CheckedCandidate
    from torrentlinker.zen import GB

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    folder = LibraryFolder(tmp_path)
    entries = [
        LibraryEntry(folder, LocalItem(tmp_path / n), ItemState.ORPHAN) for n in ("a", "b", "c")
    ]
    window.library_model.set_entries(entries)
    full = Match({"x": "x"}, [], [], 1.0)
    window.review.remember(entries[0], [CheckedCandidate(Candidate("s", GB, "u", 3), match=full)])
    window.review.remember(
        entries[1], [CheckedCandidate(Candidate("b", 40 * GB, "u", 3), match=full)]
    )
    window.review.remember(entries[2], [CheckedCandidate(Candidate("n", GB, "u", 3))])

    col = LibraryModel.ZEN_COLUMN
    texts = [window.library_model.index(r, col).data() for r in range(3)]
    assert texts[0].startswith("≈") and texts[1].startswith("≈") and texts[2] == ""


def test_band_shows_the_catalogue_age(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import time

    from torrentlinker.store import CatalogueRow, CrawlState

    store = Store(tmp_path / "s.db")
    store.save_catalogue([CatalogueRow("aa" * 20, "Book", 1, 1, 7000, "u", "d", 0)])
    store.save_crawl_state(CrawlState(7000, updated_at=time.time() - 7200))

    window = MainWindow(Settings(), tmp_path / "settings.json", store)
    qtbot.addWidget(window)

    assert "1 torrents, 2 h old" in window.band.values["catalogue"]


def test_catalogue_update_runs_off_the_gui_thread_and_reports_progress(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_torznab import FakeTorznab
    from tests.test_indexer import FakeClock
    from torrentlinker.catalogue import update_categories
    from torrentlinker.indexer import Indexer

    fake, clock = FakeTorznab(), FakeClock()
    fake.add(7000, 150)
    indexer = Indexer(
        "https://c411.example/api/torznab",
        "K",
        http=fake.client(),
        clock=clock.time,
        sleep=clock.sleep,
    )
    store = Store(tmp_path / "s.db")
    window = MainWindow(Settings(), tmp_path / "settings.json", store)
    qtbot.addWidget(window)

    with qtbot.waitSignal(
        window.band.catalogue_changed, timeout=5000, check_params_cb=lambda t: "old" in t
    ):
        window._run_catalogue(
            lambda stop, progress: update_categories(
                indexer, store, [7000], stop=stop, progress=progress
            )
        )

    assert store.catalogue_size() == 150


def test_whole_catalogue_fetch_can_be_paused_and_offers_to_resume(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_torznab import FakeTorznab
    from tests.test_indexer import FakeClock
    from torrentlinker.credentials import set_secret
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.gui.settings_common import INDEXER_API_KEY
    from torrentlinker.indexer import Indexer

    fake, clock = FakeTorznab(), FakeClock()
    fake.add(2000, 1000)
    s = Settings()
    s.indexer.url = "https://c411.example/api/torznab"
    s.indexer_categories = {2000: IndexerCategory("Films")}
    set_secret(INDEXER_API_KEY, "K")
    store = Store(tmp_path / "s.db")
    window = MainWindow(s, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    serve = fake.handler

    def pause_after_first_page(request):  # type: ignore[no-untyped-def]
        assert window.catalogue_runner is not None
        window.catalogue_runner.stop()  # what the Pause button does; only sets a flag
        return serve(request)

    fake.handler = pause_after_first_page  # type: ignore[method-assign]
    window._indexer = Indexer(
        s.indexer.url, "K", http=fake.client(), clock=clock.time, sleep=clock.sleep
    )
    box = window.zen_tab.catalogue

    with qtbot.waitSignal(
        window.band.catalogue_changed, timeout=5000, check_params_cb=lambda t: "old" in t
    ):
        box.start_requested.emit()

    assert 0 < store.catalogue_size() < 1000
    assert store.crawl_paused()
    assert box.paused and not box.running


def test_plan_view_shows_zen_added_size_and_payback_and_the_band_follows(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem
    from torrentlinker.zen import GB

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    c = PlanCandidate("aa" * 20, "Film", 8 * GB, 4, 2000, tmp_path, 1)
    window._plan_made(Plan([PlanItem(c, 0.4)], 0.4))

    result = window.zen_tab.plan_view.state()["result"]
    assert result["zen"] == 0.4 and result["size"] == 8 * GB and result["payback_days"] == 20
    assert "+0.40" in window.band.values["plan"]
    assert len(window.zen_tab.plan_view.state()["result"]["rows"]) == 1


def test_the_plan_estimates_sending_and_downloading_times_from_a_speed_test(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from torrentlinker.gui import main_window
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem
    from torrentlinker.zen import GB

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    view = window.zen_tab.plan_view
    c = PlanCandidate("aa" * 20, "Book", 360 * GB // 1000, 4, 7000, tmp_path, 1)
    window._plan_made(Plan([PlanItem(c, 0.01)] * 1000, 10))

    # 1000 on one key: 280 in the first 20 minutes, then 280 every 20 minutes
    assert 3900 <= view.state()["result"]["sending_seconds"] < 3960
    assert view.state()["result"]["download_seconds"] is None

    monkeypatch.setattr(main_window, "measure_download_speed", lambda: 100_000_000.0)
    view.speed_test_requested.emit()
    qtbot.waitUntil(lambda: window.settings.download_speed is not None, timeout=5000)

    assert view.state()["result"]["download_seconds"] == 3600  # 360 GB at 100 MB/s
    assert view.state()["download_speed"] * 8 / 1e6 == 800
    assert Settings.load(tmp_path / "settings.json").download_speed == 100_000_000.0


def test_plan_maker_plans_catalogue_torrents_into_download_folders(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.store import CatalogueRow

    s = Settings()
    s.indexer_categories = {2000: IndexerCategory("Films"), 7000: IndexerCategory("Ebook")}
    s.download_folders = DownloadFolders({2000: str(tmp_path / "films")})
    store = Store(tmp_path / "s.db")
    store.save_catalogue(
        [
            CatalogueRow("aa" * 20, "Film", 1_000_000, 5, 2000, "u", "d", 0),
            CatalogueRow("bb" * 20, "Book", 1_000_000, 5, 7000, "u", "d", 0),
        ]
    )
    window = MainWindow(s, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    window.qbit = lambda: FakeQbit()  # type: ignore[assignment,method-assign,return-value]

    plan = window.plan_maker()()

    assert [i.candidate.title for i in plan.items] == ["Film"]
    assert plan.items[0].candidate.folder == tmp_path / "films"


def test_a_plan_leaves_out_books_already_in_the_library_and_says_so(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import ContentKind, ItemState, LibraryFolder, LocalItem
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.library import LibraryEntry
    from torrentlinker.store import CatalogueRow

    s = Settings()
    s.indexer_categories = {7000: IndexerCategory("Ebook")}
    s.download_folders = DownloadFolders({7000: str(tmp_path / "books")})
    store = Store(tmp_path / "s.db")
    store.save_catalogue(
        [
            CatalogueRow(
                "aa" * 20,
                "La.Confidente.Audrey.Lefevre.2026.FR.[EPUB]-G11",
                250_000,
                5,
                7000,
                "u",
                "d",
                0,
            ),
            CatalogueRow(
                "bb" * 20,
                "Submersion.Marc.Dugain.2026.FR.[EPUB]-G11",
                300_000,
                5,
                7000,
                "u",
                "d",
                0,
            ),
        ]
    )
    window = MainWindow(s, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    window.qbit = lambda: FakeQbit()  # type: ignore[assignment,method-assign,return-value]
    mine = tmp_path / "library" / "La confidente - Audrey Lefevre.epub"
    folder = LibraryFolder(tmp_path / "library", 1, ContentKind.EBOOK)
    window.library_model.set_entries(
        [LibraryEntry(folder, LocalItem(mine, {mine.name: 250_000}), ItemState.ORPHAN)]
    )

    plan = window.plan_maker()()
    window._plan_made(plan)

    assert [i.candidate.title for i in plan.items] == ["Submersion.Marc.Dugain.2026.FR.[EPUB]-G11"]
    [left_out] = plan.on_disk
    assert left_out.path == mine
    view = window.zen_tab.plan_view
    assert view.state()["result"]["excluded"] == 1
    assert "La.Confidente" in view.state()["result"]["on_disk"][0]["title"]


def test_sending_the_plan_adds_its_torrents_and_reports(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    from tests.fake_qbit import FakeQbit
    from tests.torrents import make_torrent
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem
    from torrentlinker.send import ZEN_TAG
    from torrentlinker.store import CatalogueRow
    from torrentlinker.torrent_meta import read_torrent

    src = tmp_path / "src" / "Film"
    src.mkdir(parents=True)
    (src / "f.mkv").write_bytes(b"x" * 1000)
    data = make_torrent(src)
    meta = read_torrent(data)
    row = CatalogueRow(meta.infohash, "Film", 1000, 3, 2000, "https://c411.example/dl/1", "", 0)
    plan = Plan(
        [
            PlanItem(
                PlanCandidate(meta.infohash, "Film", 1000, 3, 2000, tmp_path / "dl", 1, source=row),
                0.1,
            )
        ],
        0.1,
    )

    class StubIndexer:
        url, api_key = Settings().indexer.url, ""

        def background(self):  # type: ignore[no-untyped-def]
            import contextlib

            return contextlib.nullcontext()

        fetched: list[str] = []

        def fetch_torrent(self, c, retry=True):  # type: ignore[no-untyped-def]
            self.fetched.append(c.download_url)
            return data

        def next_request_in(self) -> float:
            return 0

        def unredact(self, text: str) -> str:
            return text

    qbit, stub = FakeQbit(), StubIndexer()
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.qbit = lambda: qbit  # type: ignore[assignment,method-assign,return-value]
    window._indexer = stub  # type: ignore[assignment]
    window.zen_tab.seeding_view.reload = lambda: None  # type: ignore[method-assign]
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()))
    window.zen_tab.plan_view.show_plan(plan)

    window.send_plan(plan)
    assert window.zen_tab.plan_view.state()["progress"] is not None
    assert window.zen_tab.plan_view.state()["busy"]
    qtbot.waitUntil(lambda: window.zen_tab.plan_view.report is not None, timeout=5000)

    assert stub.fetched == ["https://c411.example/dl/1"], shown
    [t] = qbit.torrents()
    assert ZEN_TAG in t.tags and t.save_path == tmp_path / "dl"
    assert window.zen_tab.plan_view.state()["report"]["added"] == ["Film"]
    assert window.zen_tab.plan_view.state()["progress"] is None
    assert window.send_runner is None


def test_sending_shows_progress_and_the_c411_limit_and_can_be_stopped(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from tests.fake_qbit import FakeQbit
    from torrentlinker.indexer import RateLimited
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem
    from torrentlinker.store import CatalogueRow

    rows = [
        CatalogueRow(f"{i:040x}", f"Book {i}", 1000, 3, 7020, f"https://c411.example/{i}", "", 0)
        for i in range(3)
    ]
    plan = Plan(
        [
            PlanItem(PlanCandidate(r.infohash, r.title, 1000, 3, 7020, tmp_path, 1, source=r), 0.1)
            for r in rows
        ],
        0.3,
    )

    class LimitedIndexer:
        url, api_key = Settings().indexer.url, ""

        def background(self):  # type: ignore[no-untyped-def]
            import contextlib

            return contextlib.nullcontext()

        def fetch_torrent(self, c, retry=True):  # type: ignore[no-untyped-def]
            raise RateLimited(30)

        def unredact(self, text: str) -> str:
            return text

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.qbit = lambda: FakeQbit()  # type: ignore[assignment,method-assign,return-value]
    window._indexer = LimitedIndexer()  # type: ignore[assignment]
    window.zen_tab.seeding_view.reload = lambda: None  # type: ignore[method-assign]
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()))
    view = window.zen_tab.plan_view
    view.show_plan(plan)

    window.send_plan(plan)
    qtbot.waitUntil(
        lambda: bool(view.state()["progress"] and view.state()["progress"]["retry_at"]),
        timeout=5000,
    )
    assert view.state()["progress"]["done"] == 0 and view.state()["progress"]["total"] == 3
    assert view.state()["result"]["zen"] == pytest.approx(0.3)  # the Plan's Zen stays in view
    assert view.state()["progress"]["zen_added"] == 0
    band = window.band.values["plan"]
    assert "+0.30" in band and "0/3" in band and "waiting" in band

    view.request("stop-send", {})
    qtbot.waitUntil(lambda: window.zen_tab.plan_view.report is not None, timeout=5000)

    assert view.state()["report"]["stopped"]
    assert view.state()["report"]["added"] == []
    assert window.send_runner is None
    assert not view.state()["busy"]


def test_refreshing_a_long_seeding_list_again_is_quick(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import time

    from PySide6.QtWidgets import QApplication

    from torrentlinker.domain import Torrent
    from torrentlinker.gui.zen_view import SeedingView
    from torrentlinker.seeding import Seeding, SeedingRow
    from torrentlinker.zen import ZenDay

    rows = [
        SeedingRow(Torrent(f"{i:040x}", f"Book.{i}.epub", tmp_path, {"b.epub": 1000 + i}), i / 1e4)
        for i in range(1300)
    ]
    view = SeedingView(lambda: lambda: Seeding([], ZenDay(), []))
    qtbot.addWidget(view)
    view.resize(900, 600)
    view.show()
    qtbot.waitExposed(view)
    view.show_seeding(Seeding(rows, ZenDay([r.zen or 0 for r in rows]), []))
    QApplication.processEvents()

    started = time.monotonic()
    view.show_seeding(Seeding(rows, ZenDay([r.zen or 0 for r in rows]), []))

    assert time.monotonic() - started < 5  # replacing filled cells took over a minute
    assert len(view.seeding.rows) == 1300


def test_plan_lists_reseeds_first_and_sends_them_through_verification(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from tests.torrents import make_torrent
    from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import match
    from torrentlinker.reseed import VERIFYING
    from torrentlinker.review import CheckedCandidate
    from torrentlinker.torrent_meta import read_torrent

    lib = tmp_path / "lib"
    lib.mkdir()
    f = lib / "book.epub"
    f.write_bytes(b"b" * 3000)
    item = LocalItem(f, {f.name: 3000})
    meta = read_torrent(make_torrent(f))
    m = match(item, meta.files)
    entry = LibraryEntry(LibraryFolder(lib), item, ItemState.ORPHAN)
    qbit = FakeQbit()
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.qbit = lambda: qbit  # type: ignore[assignment,method-assign,return-value]
    window.library_model.set_entries([entry])
    window.review.remember(
        entry, [CheckedCandidate(Candidate("Book", 3000, "u", 4, meta.infohash), meta, m, m)]
    )

    plan = window.plan_maker()()
    window.zen_tab.plan_view.show_plan(plan)

    [row] = plan.items
    assert row.candidate.reseed and plan.download_size == 0 and plan.zen_added > 0
    assert window.zen_tab.plan_view.state()["result"]["rows"][0]["reseed"]  # type: ignore[union-attr]
    window.plan_reseeder()(row.candidate)
    [t] = qbit.torrents()
    assert VERIFYING in t.tags and t.save_path == lib
    assert qbit.rechecked == [t.hash]


def test_the_plan_offers_every_category_and_remembers_the_choice(
    qtbot,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    from torrentlinker.downloads import DownloadFolders, IndexerCategory

    s = Settings()
    s.indexer_categories = {
        2000: IndexerCategory("Films"),
        2030: IndexerCategory("Films étrangers", parent=2000),
        7000: IndexerCategory("Ebook"),
    }
    s.download_folders = DownloadFolders({2000: str(tmp_path / "films")})
    window = MainWindow(s, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    view = window.zen_tab.plan_view

    assert [cid for cid, _name, _sub in view.category_options] == [2000, 2030, 7000]
    assert view.without_folder == {7000}
    labels = [name for _, name, _ in view.category_options]
    assert "Ebook" in labels and 7000 in view.state()["without_folder"]
    window.prefetch_categories = lambda categories: None  # type: ignore[method-assign]

    choose_plan_category(view, 2030)

    assert Settings.load(tmp_path / "settings.json").plan_categories == [2030]


def test_a_catalogue_update_shows_its_progress_and_its_result(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.catalogue import CrawlProgress
    from torrentlinker.downloads import IndexerCategory

    s = Settings()
    s.indexer_categories = {2030: IndexerCategory("Film", 2000)}
    window = MainWindow(s, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window._catalogue_added = {}

    window._catalogue_progress(CrawlProgress(2030, pages=3, added=250, offset=300))
    assert "Film" in window.statusBar().currentMessage()
    assert "Film" in window.zen_tab.catalogue.status_text

    window._catalogue_finished(stopped=False)
    assert "+250" in window.statusBar().currentMessage()


@pytest.mark.parametrize("count,paging_window", [(350, None), (1000, 600)])
def test_making_a_plan_fetches_its_categories_and_discloses_limits(
    qtbot, tmp_path: Path, count: int, paging_window: int | None
) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from tests.fake_torznab import FakeTorznab
    from torrentlinker.credentials import set_secret
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.gui.settings_common import INDEXER_API_KEY
    from torrentlinker.indexer import Indexer
    from torrentlinker.paths import MappedQbit, PathMapper

    films = tmp_path / "films"
    films.mkdir()
    s = Settings()
    s.indexer_categories = {2030: IndexerCategory("Film")}
    s.indexer.url = "https://c411.example/api/torznab"
    s.download_folders = DownloadFolders({2030: str(films)})
    store = Store(tmp_path / "s.db")
    window = MainWindow(s, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    set_secret(INDEXER_API_KEY, "K")
    torznab = FakeTorznab(window=paging_window)
    torznab.add(2030, count)
    window._indexer = Indexer(
        s.indexer.url, "K", http=torznab.client(), cache=store, sleep=lambda _s: None
    )
    window.qbit = lambda: MappedQbit(FakeQbit(), PathMapper([]))  # type: ignore[method-assign]

    window.make_plan()
    qtbot.waitUntil(lambda: window.zen_tab.plan_view.plan is not None, timeout=10_000)

    assert store.catalogue_size() == min(count, paging_window or count)
    assert window.zen_tab.plan_view.plan.items
    if paging_window is not None:
        assert "coverage is partial" in window.zen_tab.plan_view.notice
        assert "Partial Catalogue coverage" in window.zen_tab.catalogue.status_text
    else:
        assert "coverage is partial" not in window.zen_tab.plan_view.notice


@pytest.mark.parametrize("stop_early", [False, True])
def test_a_plan_waits_for_an_active_refresh_then_refreshes_its_own_categories(
    qtbot, tmp_path: Path, monkeypatch, stop_early: bool
) -> None:  # type: ignore[no-untyped-def]
    import threading

    from torrentlinker.credentials import set_secret
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.gui.settings_common import INDEXER_API_KEY
    from torrentlinker.plan import Plan

    settings = Settings()
    settings.indexer.url = "https://c411.example/api/torznab"
    settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    settings.download_folders = DownloadFolders({7000: str(tmp_path)})
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    set_secret(INDEXER_API_KEY, "K")
    started, release, planned = threading.Event(), threading.Event(), threading.Event()
    order: list[str] = []

    def active_refresh(stop, progress) -> None:  # type: ignore[no-untyped-def]
        started.set()
        release.wait(timeout=5)
        order.append("active refresh finished")

    def plan_refresh(indexer, store, targets, **kw) -> None:  # type: ignore[no-untyped-def]
        assert targets == [7000] and not kw["full"] and kw["bootstrap"]
        order.append("Plan categories refreshed")

    def build() -> Plan:
        order.append("Plan built")
        planned.set()
        return Plan()

    monkeypatch.setattr("torrentlinker.gui.main_window.sync_catalogue", plan_refresh)
    window.plan_maker = lambda **kw: build  # type: ignore[method-assign]
    window.zen_tab.plan_view.show_plan(Plan())  # a result from a previous request
    window._after_catalogue = lambda: order.append("active refresh callback")
    window._run_catalogue(active_refresh)
    assert started.wait(timeout=1)
    try:
        window.make_plan()
        assert window.zen_tab.plan_view.plan is None
        assert window.zen_tab.plan_view.state()["busy"]
        assert not planned.wait(timeout=0.2), (
            "Plan was built while the Catalogue was still refreshing"
        )
        if stop_early:
            window._stop_plan_fetch()
    finally:
        release.set()
        qtbot.waitUntil(lambda: window.catalogue_runner is None, timeout=5000)

    qtbot.waitUntil(lambda: window.zen_tab.plan_view.plan is not None, timeout=5000)
    expected = ["active refresh finished", "active refresh callback"]
    # Stopping explicitly allows planning from what was fetched so far.
    if not stop_early:
        expected += ["Plan categories refreshed"]
    # A stopped refresh does not run its success-only callback.
    else:
        expected.remove("active refresh callback")
    assert order == [*expected, "Plan built"]


def test_a_failed_plan_refresh_does_not_build_from_the_old_catalogue(
    qtbot, tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.credentials import set_secret
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.gui.settings_common import INDEXER_API_KEY
    from torrentlinker.plan import Plan

    settings = Settings()
    settings.indexer.url = "https://c411.example/api/torznab"
    settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    settings.download_folders = DownloadFolders({7000: str(tmp_path)})
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    set_secret(INDEXER_API_KEY, "K")
    builds = []

    def failed(*args, **kw) -> None:  # type: ignore[no-untyped-def]
        raise ValueError("Catalogue refresh failed")

    def build() -> Plan:
        builds.append(True)
        return Plan()

    monkeypatch.setattr("torrentlinker.gui.main_window.sync_catalogue", failed)
    window.plan_maker = lambda **kw: build  # type: ignore[method-assign]
    window.make_plan()
    qtbot.waitUntil(lambda: window.catalogue_runner is None, timeout=5000)

    assert not builds
    assert window.zen_tab.plan_view.plan is None
    assert "Could not make a Plan" in window.zen_tab.plan_view.state()["message"]
    assert not window.zen_tab.plan_view.state()["busy"]


@pytest.mark.parametrize("pending", [False, True])
def test_plan_progress_identifies_ebook_audio_and_its_selected_scope(
    qtbot, tmp_path: Path, pending: bool
) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.catalogue import CrawlProgress
    from torrentlinker.downloads import IndexerCategory

    settings = Settings()
    settings.indexer_categories = {
        7000: IndexerCategory("Ebook"),
        3030: IndexerCategory("Audio", 7000),
        3000: IndexerCategory("Audio"),
    }
    settings.plan_categories = [7000]
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window._planning = True
    window._catalogue_added = {}
    window._pending_plan = (lambda: None) if pending else None

    window._catalogue_progress(CrawlProgress(3000 if pending else 3030, 6, 0, 600, "c411-json"))

    text = window.zen_tab.plan_view.state()["message"]
    if pending:
        assert text.startswith("Waiting for the Catalogue refresh to finish")
        assert "Fetching the Catalogue for the Plan" not in text
    else:
        assert "Ebook / Audio" in text
        assert "selected categories" in text


def test_plan_controls_save_both_limits_and_change_the_actual_plan(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.plan import PlanGoal, PlanOptions
    from torrentlinker.store import CatalogueRow
    from torrentlinker.zen import GB

    settings = Settings()
    settings.indexer_categories = {7000: IndexerCategory("Ebook")}
    settings.download_folders = DownloadFolders({7000: str(tmp_path)})
    store = Store(tmp_path / "s.db")
    store.save_catalogue(
        [CatalogueRow(f"{i:040x}", f"Book {i}", GB, 5, 7000, "u", "d", 0) for i in range(4)]
    )
    path = tmp_path / "settings.json"
    window = MainWindow(settings, path, store)
    qtbot.addWidget(window)
    window.qbit = lambda: FakeQbit()  # type: ignore[assignment,method-assign,return-value]
    view = window.zen_tab.plan_view
    configure_plan(view, plan_goal="note", maximum_bytes=2 * GB, limit_torrents=False)
    assert settings.plan_options == PlanOptions(PlanGoal.NOTE, 2 * GB)
    assert len(window.plan_maker()().items) == 2
    configure_plan(view, limit_torrents=True, maximum_torrents=1)
    assert Settings.load(path).plan_options == PlanOptions(PlanGoal.NOTE, 2 * GB, 1)
    assert len(window.plan_maker()().items) == 1

    window._plan_made(window.plan_maker()())
    assert view.plan is not None and not view.state()["busy"]
    old_id = view.plan_id
    configure_plan(view, maximum_bytes=3 * GB)
    assert view.plan is None
    with pytest.raises(ValueError, match="Plan changed"):
        view.request("review", {"plan_id": old_id, "hashes": ["0" * 40]})
    configure_plan(view, max_seeders=10)
    assert settings.plan_options.max_seeders == 10
    configure_plan(view, max_seeders=4)
    assert Settings.load(path).plan_options.max_seeders == 4
    assert not window.plan_maker()().items
    configure_plan(view, max_seeders=5)
    assert len(window.plan_maker()().items) == 1
    restored = type(view)()
    qtbot.addWidget(restored)
    restored.set_options(Settings.load(path).plan_options)
    assert restored.options.max_seeders == 5
    configure_plan(view, max_seeders=None)
    assert settings.plan_options.max_seeders is None
    assert len(window.plan_maker()().items) == 1
    configure_plan(view, max_size=GB // 2)
    assert Settings.load(path).plan_options.max_size == GB // 2
    assert not window.plan_maker()().items
    configure_plan(view, min_size=2 * GB, max_size=2 * GB)
    assert not window.plan_maker()().items
    configure_plan(view, min_size=GB)
    assert settings.plan_options.min_size == GB and settings.plan_options.max_size == 2 * GB
    assert len(window.plan_maker()().items) == 1
    restored.set_options(Settings.load(path).plan_options)
    assert restored.options.min_size == GB and restored.options.max_size == 2 * GB
    view.busy(True)
    with pytest.raises(ValueError, match="current Plan operation"):
        configure_plan(view, maximum_bytes=4 * GB)


def test_plan_view_shows_notes_and_unused_disk_space_including_the_reserve(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.zen_view import PlanView
    from torrentlinker.plan import DiskSpace, Plan, PlanCandidate, PlanItem
    from torrentlinker.zen import GB

    view = PlanView()
    qtbot.addWidget(view)
    c = PlanCandidate("a" * 40, "Book", 4 * GB, 5, 7000, Path("/books"), "disk")
    plan = Plan(
        [PlanItem(c, 0.5, 1.35)],
        0.5,
        disk_spaces=(DiskSpace("disk", Path("/books"), 10 * GB, 2 * GB, 4 * GB),),
    )

    view.show_plan(plan)

    result = view.state()["result"]
    assert result["rows"][0]["note"] == 1.35 and result["average_note"] == 1.35
    assert len(result["storage"]) == 1
    assert result["storage"][0]["after_plan"] == 6 * GB


def test_a_refused_key_tells_the_user_where_to_fix_it(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.indexer import KeyRefused

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)

    window.zen_tab.plan_view.failed(KeyRefused(401))

    text = window.zen_tab.plan_view.state()["message"]
    assert "refused your API key (HTTP 401)" in text
    assert "Settings → Connections" in text and "torznab:read" in text


def test_a_plan_interrupted_by_a_crash_comes_back_with_what_is_left(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    from torrentlinker.store import CatalogueRow, SavedPlanItem

    store = Store(tmp_path / "s.db")
    store.save_catalogue(
        [CatalogueRow(h * 40, f"Book {h}", 1000, 2, 7020, f"u{h}", "", 0) for h in "ab"]
    )
    store.save_plan(
        [SavedPlanItem(h * 40, f"Book {h}", 1000, 2, 7020, str(tmp_path), 0.1, None) for h in "ab"]
    )
    store.set_plan_sending(True)
    store.mark_plan_item("a" * 40, "added")  # then the app crashed

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)

    view = window.zen_tab.plan_view
    assert view.plan is not None and [i.candidate.title for i in view.plan.items] == ["Book b"]
    assert "Sending was interrupted: 1 torrents" in view.notice
    assert view.plan is not None and not view.state()["busy"]


def test_stopping_a_send_keeps_the_rest_of_the_plan_and_finishing_clears_it(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from tests.fake_qbit import FakeQbit
    from tests.torrents import make_torrent
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem
    from torrentlinker.store import CatalogueRow
    from torrentlinker.torrent_meta import read_torrent

    torrents, rows = {}, []
    for name in ("A", "B"):
        src = tmp_path / "src" / name
        src.mkdir(parents=True)
        (src / "book.epub").write_bytes(name.encode() * 100)
        data = make_torrent(src)
        h = read_torrent(data).infohash
        torrents[f"u{name}"] = data
        rows.append(CatalogueRow(h, name, 100, 2, 7020, f"u{name}", "", 0))
    store = Store(tmp_path / "s.db")
    store.save_catalogue(rows)
    plan = Plan(
        [
            PlanItem(
                PlanCandidate(r.infohash, r.title, 100, 2, 7020, tmp_path / "dl", 1, source=r), 0.1
            )
            for r in rows
        ],
        0.2,
    )

    window = MainWindow(Settings(), tmp_path / "settings.json", store)
    qtbot.addWidget(window)

    import weakref

    the_window = weakref.ref(window)  # a plain reference would make a cycle with the window

    class StoppingIndexer:
        url, api_key = Settings().indexer.url, ""

        def background(self):  # type: ignore[no-untyped-def]
            import contextlib

            return contextlib.nullcontext()

        stop_once = True

        def fetch_torrent(self, c, retry=True):  # type: ignore[no-untyped-def]
            if self.stop_once:  # the user stops while A is being sent
                self.stop_once = False
                the_window().send_runner.stop()  # type: ignore[union-attr]
            return torrents[c.download_url]

        def unredact(self, text: str) -> str:
            return text

    window.qbit = lambda: FakeQbit()  # type: ignore[assignment,method-assign,return-value]
    window._indexer = StoppingIndexer()  # type: ignore[assignment]
    window.zen_tab.seeding_view.reload = lambda: None  # type: ignore[method-assign]
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()))
    window._plan_made(plan)

    window.send_plan(plan)
    qtbot.waitUntil(lambda: window.zen_tab.plan_view.report is not None, timeout=5000)

    assert window.zen_tab.plan_view.state()["report"]["stopped"]
    view = window.zen_tab.plan_view
    assert [i.candidate.title for i in view.plan.items] == ["B"]  # type: ignore[union-attr]
    saved = store.saved_plan()
    assert saved is not None and not saved.sending and [i.title for i in saved.pending] == ["B"]

    shown.clear()
    window.send_plan(view.plan)  # type: ignore[arg-type]
    qtbot.waitUntil(lambda: window.zen_tab.plan_view.report is not None, timeout=5000)

    assert store.saved_plan() is None
    assert view.plan is not None and not view.plan.items


def test_detect_adds_the_docker_path_and_check_counts_its_torrents(qtbot, tmp_path):
    from tests.fake_qbit import FakeQbit
    from tests.settings_support import settings_page
    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.domain import LibraryFolder, PathMapping, Torrent
    from torrentlinker.downloads import DownloadFolders

    nas = tmp_path / "nas"
    (nas / "ebooks").mkdir(parents=True)
    (nas / "ebooks" / "Zweig.epub").write_bytes(b"x" * 300)
    client = FakeQbit(default_path="/downloads")
    client.by_hash["a" * 40] = Torrent("a" * 40, "Zweig", Path("/data/ebooks"), {"Zweig.epub": 300})
    settings = Settings(language="en")
    settings.library_folders = [LibraryFolder(nas / "ebooks")]
    settings.download_folders = DownloadFolders({}, str(tmp_path / "elsewhere"))
    dialog = settings_page(qtbot, tmp_path, settings, section="paths")
    dialog.setup.connector = lambda *args, **kwargs: client
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent"
        "==='Detect mappings').click()",
    )
    qtbot.waitUntil(lambda: dialog.view.pending == 0)
    qtbot.wait(100)
    assert js(qtbot, dialog.view, "document.querySelector('#settings-error').textContent") == ""
    wait_js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].some(b=>b.textContent.endsWith('→ /data'))",
    )
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent"
        ".endsWith('→ /data')).click()",
    )
    assert js(
        qtbot,
        dialog.view,
        "document.querySelector('[aria-label=\"Folder on the TorrentLinker host\"]').value",
    ) == str(nas)
    assert not dialog.setup.settings.path_mappings
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Test mapping').click()",
    )
    wait_js(qtbot, dialog.view, "document.body.textContent.includes('1 of 1 torrents found')")
    assert "cannot save into" in js(qtbot, dialog.view, "document.body.textContent")
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Save folder').click()",
    )
    qtbot.waitUntil(lambda: bool(dialog.setup.settings.path_mappings))
    qtbot.waitUntil(lambda: dialog.view.pending == 0)
    assert dialog.setup.settings.path_mappings == [PathMapping(str(nas), "/data")]


def test_a_book_left_in_a_download_folder_is_left_out_of_the_plan(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.store import CatalogueRow

    books = tmp_path / "books"
    books.mkdir()
    # Its torrent was removed from qBittorrent, but the file stayed.
    (books / "La confidente - Audrey Lefevre.epub").write_bytes(b"x" * 250_000)
    s = Settings()
    s.indexer_categories = {7000: IndexerCategory("Ebook")}
    s.download_folders = DownloadFolders({7000: str(books)})
    store = Store(tmp_path / "s.db")
    store.save_catalogue(
        [
            CatalogueRow(
                "aa" * 20,
                "La.Confidente.Audrey.Lefevre.2026.FR.[EPUB]-G11",
                250_000,
                5,
                7000,
                "u",
                "d",
                0,
            ),
            CatalogueRow(
                "bb" * 20,
                "Submersion.Marc.Dugain.2026.FR.[EPUB]-G11",
                300_000,
                5,
                7000,
                "u",
                "d",
                0,
            ),
        ]
    )
    window = MainWindow(s, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    window.qbit = lambda: FakeQbit()  # type: ignore[assignment,method-assign,return-value]

    plan = window.plan_maker()()

    assert [i.candidate.title for i in plan.items] == ["Submersion.Marc.Dugain.2026.FR.[EPUB]-G11"]
    assert [d.path for d in plan.on_disk] == [books / "La confidente - Audrey Lefevre.epub"]


def test_a_match_inside_an_archive_offers_to_unpack_and_reseed(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import zipfile

    from tests.torrents import make_torrent
    from torrentlinker.domain import ContentKind, ItemState, LibraryFolder, LocalItem
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import IgnoreList, MatchRules
    from torrentlinker.review import check_candidates
    from torrentlinker.torrent_meta import read_torrent

    folder = tmp_path / "src" / "Xenomorph"
    folder.mkdir(parents=True)
    (folder / "xeno.stl").write_bytes(b"solid xeno " * 5000)
    lib = tmp_path / "lib"
    lib.mkdir()
    archive = lib / "Xenomorph (Alien) - nomnom.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(folder / "xeno.stl", "Xenomorph/xeno.stl")
    data = make_torrent(folder)
    item = LocalItem(archive, {archive.name: archive.stat().st_size})

    class Torrents:
        def fetch_torrent(self, c):  # type: ignore[no-untyped-def]
            return data

    size = sum(read_torrent(data).files.values())
    checked = check_candidates(
        Torrents(),  # type: ignore[arg-type]
        item,
        [Candidate("NomNom.figures.Alien.Xenomorph[STL]", size, "u", 4)],
        MatchRules(0.02, 0.5, IgnoreList.default()),
    )
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    entry = LibraryEntry(LibraryFolder(lib, 1, ContentKind.MODEL_3D), item, ItemState.ORPHAN)
    window.review.set_entry(entry)

    window.review._show(entry, checked)

    panel = window.review
    assert panel.candidates.item(0, 3).text() == "Full match inside the archive"  # type: ignore[union-attr]
    assert panel.reseed_button.text() == "Unpack and Reseed…"
    assert panel.reseed_button.isEnabled()
    assert panel.files.item(0, 2).text() == "✓ in the archive"  # type: ignore[union-attr]
    assert window._summary(checked) == "Full match inside the archive"


@pytest.mark.parametrize(
    "verified,started,choice,kept",
    [
        (True, True, "Move to the trash", False),
        (True, True, "Keep the archive", True),
        (False, False, None, True),  # Verification failed: nothing is offered
        (True, False, None, True),  # verified but left stopped: nothing is offered
    ],
)
def test_after_a_verified_unpack_the_archive_can_go_to_the_trash(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
    verified: bool,
    started: bool,
    choice: str | None,
    kept: bool,
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from torrentlinker.gui import main_window
    from torrentlinker.reseed import Outcome

    archive = tmp_path / "Tiamat.rar"
    archive.write_bytes(b"rar" * 100)
    folder = tmp_path / "Chuya Factory - Tiamat"
    folder.mkdir()
    store = Store(tmp_path / "s.db")
    store.remember_unpacked(folder, archive)
    window = MainWindow(Settings(), tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    window.scan = lambda refresh=False: None  # type: ignore[method-assign]
    asked: list[str] = []

    def answer(box: QMessageBox) -> None:
        asked.append(box.text())
        box.chosen = next((b for b in box.buttons() if b.text() == choice), None)  # type: ignore[attr-defined]

    monkeypatch.setattr(QMessageBox, "exec", answer)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box.chosen)
    trashed: list[str] = []

    def to_trash(path: str) -> bool:
        trashed.append(path)
        Path(path).unlink()
        return True

    monkeypatch.setattr(main_window.QFile, "moveToTrash", staticmethod(to_trash))

    window._verified(([Outcome(folder, "a" * 40, verified, 1.0, started)], []))

    assert bool(asked) == (choice is not None)
    if asked:
        assert "Tiamat.rar" in asked[0] and "verified every file" in asked[0]
    assert archive.exists() == kept
    assert trashed == ([] if kept else [str(archive)])
    assert store.take_unpacked(folder) is None  # never offered twice


def test_shop_badges_go_past_the_tree_bonus_limit(qtbot, tmp_path):
    from tests.settings_support import edit_field, save_group, settings_page
    from tests.test_community_interfaces import js

    dialog = settings_page(qtbot, tmp_path, section="zen")
    assert (
        js(
            qtbot,
            dialog.view,
            "document.querySelector('[aria-label=\"Tree bonus unlocked (%)\"]').max",
        )
        == "5"
    )
    edit_field(qtbot, dialog.view, "Tree bonus unlocked (%)", 5)
    edit_field(qtbot, dialog.view, "Shop badges bonus (%)", 12.5)
    save_group(qtbot, dialog)
    zen = Settings.load(dialog.setup.path).zen
    assert zen.tree_bonus == pytest.approx(0.05)
    assert zen.badge_bonus == pytest.approx(0.125)


def test_extra_api_keys_are_saved_and_each_gets_its_own_queues(qtbot, tmp_path):
    from tests.settings_support import edit_field, save_group, settings_page
    from tests.test_community_interfaces import js
    from torrentlinker.credentials import get_secret

    dialog = settings_page(qtbot, tmp_path)
    edit_field(qtbot, dialog.view, "Indexer API key", "main")
    add = (
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Add an API key').click()"
    )
    js(qtbot, dialog.view, add)
    edit_field(qtbot, dialog.view, "Additional API key 1", "second")
    js(qtbot, dialog.view, add)
    edit_field(qtbot, dialog.view, "Additional API key 2", "fourth")
    save_group(qtbot, dialog)
    assert get_secret("indexer-api-key-2") == "second"
    window = MainWindow(
        Settings.load(dialog.setup.path), tmp_path / "settings.json", Store(tmp_path / "s.db")
    )
    qtbot.addWidget(window)
    indexer = window.indexer()
    assert [slot.key for slot in indexer.slots] == ["main", "second", "fourth"]
    assert window.indexer() is indexer


def plan_window(qtbot, tmp_path: Path, monkeypatch, picked: str):  # type: ignore[no-untyped-def]
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.gui import main_window

    s = Settings()
    s.indexer_categories = {
        2000: IndexerCategory("Films & Vidéos"),
        2030: IndexerCategory("Film", parent=2000),
        5000: IndexerCategory("Série TV", parent=2000),
        2060: IndexerCategory("Animation", parent=2000),
        7000: IndexerCategory("Ebook"),
    }
    s.download_folders = DownloadFolders(
        {2030: str(tmp_path / "Film"), 5000: str(tmp_path / "Séries")}
    )
    s.plan_categories = [2030]
    window = MainWindow(s, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    fetched: list[list[int]] = []
    window.prefetch_categories = fetched.append  # type: ignore[method-assign]
    asked: list[str] = []
    monkeypatch.setattr(
        main_window, "choose_directory", lambda parent, title: asked.append(title) or picked
    )
    return window, fetched, asked


def test_choosing_a_category_without_a_folder_asks_for_one_and_fetches_it_meanwhile(
    qtbot,
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    window, fetched, asked = plan_window(qtbot, tmp_path, monkeypatch, str(tmp_path / "Ebooks"))

    choose_plan_category(window.zen_tab.plan_view, 7000)

    assert fetched == [[7000]]
    assert asked == ["Download Folder for Ebook"]
    saved = Settings.load(tmp_path / "settings.json")
    assert saved.plan_categories == [2030, 7000]
    assert saved.download_folders.by_category[7000] == str(tmp_path / "Ebooks")
    assert 7000 not in window.zen_tab.plan_view.without_folder


def test_cancelling_the_folder_leaves_the_category_out(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    window, _fetched, asked = plan_window(qtbot, tmp_path, monkeypatch, "")

    choose_plan_category(window.zen_tab.plan_view, 7000)

    assert asked and Settings.load(tmp_path / "settings.json").plan_categories == [2030]
    assert window.zen_tab.plan_view.chosen_categories == {2030}


def test_a_category_whose_subcategories_have_folders_can_skip_its_own(
    qtbot,
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from torrentlinker.catalogue import plan_categories

    window, _fetched, asked = plan_window(qtbot, tmp_path, monkeypatch, "")
    questions: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: questions.append(a[2]) or QMessageBox.StandardButton.No,
    )

    choose_plan_category(window.zen_tab.plan_view, 2000)

    assert "Film, Série TV have theirs" in questions[0] and asked == []
    s = Settings.load(tmp_path / "settings.json")
    assert s.plan_categories == [2000, 2030]
    # Its subcategories with a folder are fetched and planned; Animation has none.
    assert plan_categories([2000], s.download_folders, s.indexer_categories) == [2030, 5000]


@pytest.mark.parametrize("version", ["0.12.2", "0.13.0b1", "0.13.0-beta.1"])
def test_packaging_smoke_accepts_stable_and_prerelease_versions(monkeypatch, version, qapp):
    from torrentlinker import app

    monkeypatch.setattr(app, "installed_version", lambda: version)
    monkeypatch.setattr(app, "agent_smoke_checks", lambda: None)
    # The real shared page is rendered in test_bundled_assets; this checks versions.
    from torrentlinker import webview_smoke

    monkeypatch.setattr(webview_smoke, "webview_smoke_checks", lambda: None)
    app.smoke_checks()


def test_seeding_views_wait_while_hidden_and_catch_up_when_shown(qtbot):
    from torrentlinker.domain import Torrent
    from torrentlinker.gui.zen_view import ZenTab
    from torrentlinker.seeding import Seeding, SeedingRow
    from torrentlinker.zen import ZenClass, ZenDay, ZenProfile

    tab = ZenTab(lambda: lambda: Seeding([], ZenDay(), []), lambda: ZenProfile(ZenClass.TANKER))
    qtbot.addWidget(tab)
    rows = [SeedingRow(Torrent("a", "A film", Path("/data"), size=1024**2), 0.1)]
    view = Seeding(rows, ZenDay([0.1]), [])
    tab.seeding_view.show_seeding(view)
    assert tab.seeding_view.web is None  # no renderer until the page is shown
    assert tab.seeding_view.seeding is view
    tab.resize(900, 600)
    tab.pages.setCurrentIndex(1)  # Profile is first; show Seeding to resume its deferred work.
    tab.show()
    from tests.test_community_interfaces import wait_js

    wait_js(qtbot, tab.seeding_view, "document.querySelectorAll('.seeding-category').length===1")
    wait_js(
        qtbot,
        tab.seeding_view,
        "document.querySelector('#seeding-classes strong')?.textContent.includes('Tanker')",
    )


def test_seeding_and_catalogue_refreshes_wait_while_a_video_plays(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    refreshed = []
    window.zen_tab.seeding_view.reload = lambda quiet=False: refreshed.append(quiet)  # type: ignore[method-assign]
    window.media_tab.video_playing = True
    window._refresh_seeding_quietly()
    window._refresh_seeding_quietly()
    assert refreshed == []  # reading every seeded torrent would drop frames
    assert not window.refresh_whole_catalogue()
    window.media_tab.video_playing = False
    window.media_tab.video_playing_changed.emit(False)
    assert refreshed == [True]  # once, when the video stops
    window.media_tab.video_playing_changed.emit(False)
    assert refreshed == [True]


def test_profile_poll_waits_while_a_video_plays(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    shown = []
    window.show_account_profile = lambda: shown.append(True)  # type: ignore[method-assign]
    window.refresh_profile = lambda: None  # type: ignore[method-assign]
    window.media_tab.video_playing = True
    window._poll_account_profile()
    window._poll_account_profile()
    assert shown == []  # its keyring read and view refresh would drop frames
    window.media_tab.video_playing = False
    window.media_tab.video_playing_changed.emit(False)
    assert shown == [True]  # once, when the video stops
    window.media_tab.video_playing_changed.emit(False)
    assert shown == [True]
