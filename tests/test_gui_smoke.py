from pathlib import Path

import pytest

from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def test_main_window_opens(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()


def test_settings_open_on_the_connections_tab_with_hidden_keys(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLineEdit

    from torrentlinker.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    assert dialog.tabs.currentIndex() == 0
    assert dialog.indexer_key.echoMode() == QLineEdit.EchoMode.Password
    assert dialog.tmdb_key.echoMode() == QLineEdit.EchoMode.Password


def test_choosing_deluge_saves_it_and_the_app_connects_through_deluge(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path
) -> None:
    from torrentlinker.credentials import get_secret
    from torrentlinker.deluge import DelugeApi
    from torrentlinker.domain import TorrentClient
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.gui.settings_dialog import DELUGE_PASSWORD, SettingsDialog
    from torrentlinker.qbit import QbitApi
    from torrentlinker.store import Store

    settings = Settings()
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    assert dialog.client_forms.currentIndex() == 0  # qBittorrent, as before
    assert isinstance(dialog._form_qbit(), QbitApi)

    dialog.client.setCurrentIndex(dialog.client.findData(TorrentClient.DELUGE.value))
    assert dialog.client_forms.currentWidget().isAncestorOf(dialog.deluge_host)
    dialog.deluge_host.setText("http://nas:8112")
    dialog.deluge_password.setText("secret")
    assert isinstance(dialog._form_qbit(), DelugeApi)
    dialog._save()

    assert settings.client is TorrentClient.DELUGE
    assert settings.deluge.host == "http://nas:8112"
    assert get_secret(DELUGE_PASSWORD) == "secret"
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.qbit()
    assert isinstance(window.qbit()._inner, DelugeApi)
    settings.client = TorrentClient.QBITTORRENT
    window.qbit()
    assert isinstance(window.qbit()._inner, QbitApi)  # a new choice takes effect at once


def test_choosing_transmission_saves_it_and_the_app_connects_through_it(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path
) -> None:
    from torrentlinker.credentials import get_secret
    from torrentlinker.domain import TorrentClient
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.gui.settings_dialog import TRANSMISSION_PASSWORD, SettingsDialog
    from torrentlinker.store import Store
    from torrentlinker.transmission import TransmissionApi

    settings = Settings()
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    dialog.client.setCurrentIndex(dialog.client.findData(TorrentClient.TRANSMISSION.value))
    assert dialog.client_forms.currentWidget().isAncestorOf(dialog.transmission_host)
    dialog.transmission_host.setText("http://nas:9091")
    dialog.transmission_user.setText("me")
    dialog.transmission_password.setText("secret")
    assert isinstance(dialog._form_qbit(), TransmissionApi)
    dialog._save()

    assert settings.client is TorrentClient.TRANSMISSION
    assert (settings.transmission.host, settings.transmission.username) == ("http://nas:9091", "me")
    assert get_secret(TRANSMISSION_PASSWORD) == "secret"
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    window.qbit()
    assert isinstance(window.qbit()._inner, TransmissionApi)


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


def test_content_kind_chosen_in_settings_comes_back_as_a_content_kind(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.domain import ContentKind, LibraryFolder
    from torrentlinker.gui.settings_dialog import SettingsDialog

    s = Settings()
    s.library_folders = [LibraryFolder(Path("/windocs/STL"), 1, ContentKind.MODEL_3D)]
    dialog = SettingsDialog(s)
    qtbot.addWidget(dialog)

    [folder] = dialog._read_folders()

    assert folder.kind is ContentKind.MODEL_3D


def test_library_state_filter_keeps_only_the_chosen_state(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
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

    window.state_filter.setCurrentIndex(window.state_filter.findText("Orphan"))

    assert window.library_proxy.rowCount() == 1


def test_a_typed_folder_path_is_added_to_the_library_folders(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    dialog.typed_folder.setText(str(tmp_path))
    dialog._add_typed_folder()

    assert [f.path for f in dialog._read_folders()] == [tmp_path]


def test_zen_profile_entered_in_settings_comes_back(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.settings_dialog import SettingsDialog
    from torrentlinker.zen import ZenClass, ZenProfile

    s = Settings()
    s.zen = ZenProfile(ZenClass.SWARM_KEEPER, 0.02, 20, 300)
    dialog = SettingsDialog(s)
    qtbot.addWidget(dialog)

    assert dialog._read_zen() == s.zen
    dialog.zen_class.setCurrentIndex(2)
    assert dialog._read_zen().zen_class is ZenClass.REUPLOADER


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
    assert len(window.zen_tab.seeding_view.table.torrents) == 1
    assert "≈" in window.zen_tab.seeding_view.table.torrents["h"].text(4)  # type: ignore[union-attr]


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
    assert view.table.torrents[row.infohash].text(2) == "–"
    assert store.catalogue()[0].seeders == 100

    window.zen_tab.plan_view.show_plan(Plan())
    qbit._set(row.infohash, swarm_seeders=5)
    with qtbot.waitSignal(view.updated, timeout=5000):
        window.seeding_timer.timeout.emit()

    assert view.table.torrents[row.infohash].text(2) == "5"
    assert view.seeding.day.total > before
    cached = store.catalogue()[0]
    assert cached.seeders == 4  # the current user is already one of the five seeders
    assert cached.source == "zen-lab" and cached.seen_at == 123
    assert window.seeding_timer.interval() == 30_000


def test_download_folders_tab_flags_categories_left_without_a_folder(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.downloads import DownloadFolders
    from torrentlinker.gui.settings_dialog import COL_FOLDER, COL_RESOLVED, SettingsDialog
    from torrentlinker.indexer import Caps

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    dialog._set_categories(Caps({2000: "Films", 2030: "VO", 7000: "Ebook"}, {}, {2030: 2000}))
    dialog.download_table.item(0, COL_FOLDER).setText("/dl/films")  # type: ignore[union-attr]

    assert dialog._read_download_folders() == DownloadFolders({2000: "/dl/films"})
    used = [dialog.download_table.item(r, COL_RESOLVED).text() for r in range(3)]  # type: ignore[union-attr]
    assert used[:2] == ["/dl/films", "/dl/films"]
    assert "excluded" in used[2]


def test_zen_band_shows_the_balance_and_explains_a_key_without_profile_scope(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.zen_view import ZenBand
    from torrentlinker.profile import ProfileError, ProfileProblem, UserProfile
    from torrentlinker.zen import ZenClass

    band = ZenBand()
    qtbot.addWidget(band)
    band.show_profile(
        UserProfile("v", "tanker", ZenClass.TANKER, 0.02, 12.5, False, "insufficient_balance")
    )
    assert "12.5" in band.balance.text()
    assert "not enough Zen" in band.message.text()

    band.show_profile_error(ProfileError(ProfileProblem.MISSING_SCOPE))
    assert "Profil (lecture)" in band.message.text()


def test_profile_read_at_startup_fills_the_zen_profile(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.profile import UserProfile
    from torrentlinker.zen import ZenClass

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    refreshed = []
    window.zen_tab.seeding_view.refresh = lambda: refreshed.append(True)  # type: ignore[method-assign]
    window._profile_read(
        UserProfile("v", "swarm-keeper", ZenClass.SWARM_KEEPER, 0.04, 3, True, None)
    )

    assert window.settings.zen.zen_class is ZenClass.SWARM_KEEPER
    assert window.settings.zen.tree_bonus == 0.04
    assert Settings.load(tmp_path / "settings.json").zen == window.settings.zen
    assert refreshed  # the Seeding view is estimated again with the new Class


def test_class_comparison_highlights_the_current_class_and_labels_reuploader_rough(qtbot) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.zen_view import ClassComparison
    from torrentlinker.zen import ZenClass, ZenProfile

    widget = ClassComparison(lambda: ZenProfile(ZenClass.SWARM_KEEPER), uploads=10)
    qtbot.addWidget(widget)

    assert "<b>" in widget.labels[ZenClass.SWARM_KEEPER].text()
    assert "<b>" not in widget.labels[ZenClass.TANKER].text()
    assert "rough" in widget.labels[ZenClass.REUPLOADER].text()
    assert "4.30" in widget.labels[ZenClass.REUPLOADER].text()


def test_library_shows_zen_per_day_for_orphans_with_a_match_and_sorts_it(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

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
    window.library_proxy.sort(col, Qt.SortOrder.DescendingOrder)
    top = window.library_proxy.index(0, 0).data(Qt.ItemDataRole.UserRole)
    assert top is entries[1]


def test_band_shows_the_catalogue_age(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import time

    from torrentlinker.store import CatalogueRow, CrawlState

    store = Store(tmp_path / "s.db")
    store.save_catalogue([CatalogueRow("aa" * 20, "Book", 1, 1, 7000, "u", "d", 0)])
    store.save_crawl_state(CrawlState(7000, updated_at=time.time() - 7200))

    window = MainWindow(Settings(), tmp_path / "settings.json", store)
    qtbot.addWidget(window)

    assert "1 torrents, 2 h old" in window.band.catalogue.text()


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
    from torrentlinker.gui.settings_dialog import INDEXER_API_KEY
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
        box.fetch_button.click()

    assert 0 < store.catalogue_size() < 1000
    assert store.crawl_paused()
    assert "Resume" in box.fetch_button.text()


def test_plan_view_shows_zen_added_size_and_payback_and_the_band_follows(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.plan import Plan, PlanCandidate, PlanItem
    from torrentlinker.zen import GB

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    c = PlanCandidate("aa" * 20, "Film", 8 * GB, 4, 2000, tmp_path, 1)
    window._plan_made(Plan([PlanItem(c, 0.4)], 0.4))

    summary = window.zen_tab.plan_view.summary.text()
    assert "≈ +0.40 Zen/day" in summary and "8.0 Go" in summary and "20 days" in summary
    assert "+0.40" in window.band.plan.text()
    assert window.zen_tab.plan_view.table.rowCount() == 1


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
    assert "Sending to the torrent client: ≈ 1 h 05" in view.times.text()
    assert "test your speed" in view.times.text()

    monkeypatch.setattr(main_window, "measure_download_speed", lambda: 100_000_000.0)
    view.speed_button.click()
    qtbot.waitUntil(lambda: window.settings.download_speed is not None, timeout=5000)

    assert "Downloading the data: ≈ 1 h 00 at best" in view.times.text()  # 360 GB at 100 MB/s
    assert "800 Mbit/s" in view.times.text()
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
    assert "1 torrents left out: they seem to be on disk already" in view.summary.text()
    assert "La.Confidente" in view.summary.toolTip()


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
    window.zen_tab.seeding_view.refresh = lambda: None  # type: ignore[method-assign]
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()))
    window.zen_tab.plan_view.show_plan(plan)

    window.send_plan(plan)
    assert window.zen_tab.plan_view.send_progress.isVisibleTo(window)
    assert window.zen_tab.plan_view.stop_send_button.isVisibleTo(window)
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert stub.fetched == ["https://c411.example/dl/1"], shown
    [t] = qbit.torrents()
    assert ZEN_TAG in t.tags and t.save_path == tmp_path / "dl"
    assert "1 torrents added" in shown[0]
    assert not window.zen_tab.plan_view.send_progress.isVisibleTo(window)
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
    window.zen_tab.seeding_view.refresh = lambda: None  # type: ignore[method-assign]
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()))
    view = window.zen_tab.plan_view
    view.show_plan(plan)

    window.send_plan(plan)
    qtbot.waitUntil(lambda: "limiting downloads" in view.summary.text(), timeout=5000)
    assert "0 of 3" in view.summary.text()
    assert "≈ +0.30 Zen/day" in view.summary.text()  # the Plan's Zen stays in view
    assert "≈ +0.00 Zen/day sent" in view.summary.text()
    band = window.band.plan.text()
    assert "+0.30" in band and "0/3" in band and "waiting" in band

    view.stop_send_button.click()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert "Stopped after 0 of 3" in shown[0]
    assert window.send_runner is None
    assert view.make_button.isEnabled()


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
    assert len(view.table.torrents) == 1300


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
    assert window.zen_tab.plan_view.table.item(0, 1).text() == "Reseed (0 Go)"  # type: ignore[union-attr]
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
    labels = [a.text() for a in view.categories_menu.actions()]
    assert any("Ebook" in t and "no Download Folder" in t for t in labels)
    window.prefetch_categories = lambda categories: None  # type: ignore[method-assign]

    view._toggle(2030, True)

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
    assert "Film" in window.zen_tab.catalogue.status.text()

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
    from torrentlinker.gui.settings_dialog import INDEXER_API_KEY
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
        assert "coverage is partial" in window.zen_tab.plan_view.catalogue_notice.text()
        assert "Partial Catalogue coverage" in window.zen_tab.catalogue.status.text()
    else:
        assert "coverage is partial" not in window.zen_tab.plan_view.catalogue_notice.text()


@pytest.mark.parametrize("stop_early", [False, True])
def test_a_plan_waits_for_an_active_refresh_then_refreshes_its_own_categories(
    qtbot, tmp_path: Path, monkeypatch, stop_early: bool
) -> None:  # type: ignore[no-untyped-def]
    import threading

    from torrentlinker.credentials import set_secret
    from torrentlinker.downloads import DownloadFolders, IndexerCategory
    from torrentlinker.gui.settings_dialog import INDEXER_API_KEY
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
        assert not window.zen_tab.plan_view.make_button.isEnabled()
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
    from torrentlinker.gui.settings_dialog import INDEXER_API_KEY
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
    assert "Could not make a Plan" in window.zen_tab.plan_view.summary.text()
    assert window.zen_tab.plan_view.make_button.isEnabled()


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

    text = window.zen_tab.plan_view.summary.text()
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
    view.goal.setCurrentIndex(view.goal.findData("note"))
    view.download_limit.setValue(2)

    assert not view.torrent_limit.isEnabled()
    assert settings.plan_options == PlanOptions(PlanGoal.NOTE, 2 * GB)
    assert len(window.plan_maker()().items) == 2

    view.limit_torrents.setChecked(True)
    view.torrent_limit.setValue(1)
    assert view.torrent_limit.isEnabled()
    assert Settings.load(path).plan_options == PlanOptions(PlanGoal.NOTE, 2 * GB, 1)
    assert len(window.plan_maker()().items) == 1

    # Changing an option invalidates a previous result instead of sending an old Plan.
    window._plan_made(window.plan_maker()())
    assert view.send_button.isEnabled()
    view.download_limit.setValue(3)
    assert view.plan is None and not view.send_button.isEnabled()
    assert not view.seeder_limit.isEnabled()
    view.low_seeders.setChecked(True)
    assert view.seeder_limit.isEnabled()
    assert settings.plan_options.max_seeders == 10
    view.seeder_limit.setValue(4)
    assert Settings.load(path).plan_options.max_seeders == 4
    assert not window.plan_maker()().items  # every test torrent has five seeders
    view.seeder_limit.setValue(5)
    assert len(window.plan_maker()().items) == 1
    restored = type(view)()
    qtbot.addWidget(restored)
    restored.set_options(Settings.load(path).plan_options)
    assert restored.low_seeders.isChecked() and restored.seeder_limit.value() == 5
    view.low_seeders.setChecked(False)
    assert not view.seeder_limit.isEnabled() and settings.plan_options.max_seeders is None
    assert len(window.plan_maker()().items) == 1
    view.max_size.setValue(0.5)  # every test torrent is 1 GB
    assert Settings.load(path).plan_options.max_size == GB // 2
    assert not window.plan_maker()().items
    view.min_size.setValue(2)  # above the maximum: the maximum follows
    assert view.max_size.value() == 2
    assert not window.plan_maker()().items
    view.min_size.setValue(1)
    assert settings.plan_options.min_size == GB and settings.plan_options.max_size == 2 * GB
    assert len(window.plan_maker()().items) == 1
    restored.set_options(Settings.load(path).plan_options)
    assert restored.min_size.value() == 1 and restored.max_size.value() == 2
    view.busy(True)
    assert not view.goal.isEnabled() and not view.download_limit.isEnabled()
    assert not view.limit_torrents.isEnabled() and not view.torrent_limit.isEnabled()
    assert not view.low_seeders.isEnabled() and not view.seeder_limit.isEnabled()
    assert not view.min_size.isEnabled() and not view.max_size.isEnabled()


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

    assert view.table.item(0, 3).text() == "1.35"
    assert "average note 1.35" in view.summary.text()
    assert view.space_table.rowCount() == 1
    assert view.space_table.item(0, 4).data(256) == 6 * GB


def test_a_refused_key_tells_the_user_where_to_fix_it(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.indexer import KeyRefused

    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)

    window.zen_tab.plan_view.failed(KeyRefused(401))

    text = window.zen_tab.plan_view.summary.text()
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
    assert "Sending was interrupted: 1 torrents" in view.summary.text()
    assert view.send_button.isEnabled()


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
    window.zen_tab.seeding_view.refresh = lambda: None  # type: ignore[method-assign]
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()))
    window._plan_made(plan)

    window.send_plan(plan)
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert "The rest of the Plan is saved" in shown[0]
    view = window.zen_tab.plan_view
    assert [i.candidate.title for i in view.plan.items] == ["B"]  # type: ignore[union-attr]
    saved = store.saved_plan()
    assert saved is not None and not saved.sending and [i.title for i in saved.pending] == ["B"]

    shown.clear()
    window.send_plan(view.plan)  # type: ignore[arg-type]
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert store.saved_plan() is None
    assert view.plan is not None and not view.plan.items


def test_detect_adds_the_docker_path_and_check_counts_its_torrents(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import LibraryFolder, PathMapping, Torrent
    from torrentlinker.downloads import DownloadFolders
    from torrentlinker.gui.settings_dialog import COL_CHECK, COL_LOCAL, COL_QBIT, SettingsDialog

    nas = tmp_path / "nas"
    (nas / "ebooks").mkdir(parents=True)
    (nas / "ebooks" / "Zweig.epub").write_bytes(b"x" * 300)
    qbit = FakeQbit(default_path="/downloads")
    qbit.by_hash["a" * 40] = Torrent("a" * 40, "Zweig", Path("/data/ebooks"), {"Zweig.epub": 300})
    s = Settings()
    s.library_folders = [LibraryFolder(nas / "ebooks")]
    s.download_folders = DownloadFolders({}, str(tmp_path / "elsewhere"))
    dialog = SettingsDialog(s)
    qtbot.addWidget(dialog)
    dialog._form_qbit = lambda: qbit  # type: ignore[assignment,method-assign,return-value]

    dialog.detect_button.click()
    qtbot.waitUntil(
        lambda: (c := dialog.mappings.item(0, COL_CHECK)) is not None and "of" in c.text(),
        timeout=5000,
    )

    assert dialog.mappings.item(0, COL_LOCAL).text() == str(nas)  # type: ignore[union-attr]
    assert dialog.mappings.item(0, COL_QBIT).text() == "/data"  # type: ignore[union-attr]
    assert dialog.mappings.item(0, COL_CHECK).text() == "✓ 1 of 1"  # type: ignore[union-attr]
    status = dialog.paths_status.text()
    assert "1 torrents found" in status
    assert "cannot save into them" in status and str(tmp_path / "elsewhere") in status
    dialog._save()
    assert s.path_mappings == [PathMapping(str(nas), "/data")]


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


def test_shop_badges_go_past_the_tree_bonus_limit(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    dialog.tree_bonus.setValue(12.5)  # c411's tree stops at +5 %
    dialog.badge_bonus.setValue(12.5)  # badges add on top of every maximum

    zen = dialog._read_zen()
    assert zen.tree_bonus == pytest.approx(0.05) and zen.badge_bonus == pytest.approx(0.125)
    s = Settings()
    s.zen = zen
    s.save(tmp_path / "settings.json")
    assert Settings.load(tmp_path / "settings.json").zen.badge_bonus == pytest.approx(0.125)


def test_extra_api_keys_are_saved_and_each_gets_its_own_queues(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.credentials import get_secret
    from torrentlinker.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    dialog.indexer_key.setText("main")
    dialog.extra_keys[0].setText("second")
    dialog.extra_keys[2].setText("fourth")  # gaps are fine

    dialog._save_secrets()

    assert get_secret("indexer-api-key-2") == "second"
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    indexer = window.indexer()
    assert [slot.key for slot in indexer.slots] == ["main", "second", "fourth"]
    assert window.indexer() is indexer  # kept while the keys stay the same


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

    window.zen_tab.plan_view._toggle(7000, True)

    assert fetched == [[7000]]
    assert asked == ["Download Folder for Ebook"]
    saved = Settings.load(tmp_path / "settings.json")
    assert saved.plan_categories == [2030, 7000]
    assert saved.download_folders.by_category[7000] == str(tmp_path / "Ebooks")
    assert 7000 not in window.zen_tab.plan_view.without_folder


def test_cancelling_the_folder_leaves_the_category_out(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    window, _fetched, asked = plan_window(qtbot, tmp_path, monkeypatch, "")

    window.zen_tab.plan_view._toggle(7000, True)

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

    window.zen_tab.plan_view._toggle(2000, True)

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
    app.smoke_checks()


def test_seeding_views_wait_while_hidden_and_catch_up_when_shown(qtbot):
    from torrentlinker.domain import Torrent
    from torrentlinker.gui.zen_view import ZenTab
    from torrentlinker.seeding import Seeding, SeedingRow
    from torrentlinker.zen import ZenClass, ZenDay, ZenProfile

    tab = ZenTab(lambda: lambda: Seeding([], ZenDay(), []), lambda: ZenProfile(ZenClass.TANKER))
    qtbot.addWidget(tab)
    hidden = [True]
    tab.defer_while_hidden(lambda: hidden[0])
    rows = [SeedingRow(Torrent("a", "A film", Path("/data"), size=1024**2), 0.1)]
    view = Seeding(rows, ZenDay([0.1]), [])
    tab.seeding_view.show_seeding(view)
    assert tab.seeding_view.table.torrents == {}  # not rebuilt while out of sight
    assert "0 torrents" not in tab.seeding_view.total.text()  # the cheap summary still updates
    assert tab.seeding_view.seeding is view
    tab.resize(900, 600)
    hidden[0] = False
    tab.pages.setCurrentIndex(1)  # Profile is first; show Seeding to resume its deferred work.
    tab.show()
    qtbot.waitUntil(lambda: "a" in tab.seeding_view.table.torrents, timeout=3000)
    qtbot.waitUntil(lambda: "<b>" in tab.comparison.labels[ZenClass.TANKER].text(), timeout=3000)


def test_seeding_and_catalogue_refreshes_wait_while_a_video_plays(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    refreshed = []
    window.zen_tab.seeding_view.refresh = lambda quiet=False: refreshed.append(quiet)  # type: ignore[method-assign]
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
