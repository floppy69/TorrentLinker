import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from PySide6.QtCore import QObject, Qt, Signal

from tests.fake_qbit import FakeQbit
from tests.test_upload_completeness import complete_description, complete_form
from torrentlinker.domain import ContentKind, ItemState, LibraryFolder
from torrentlinker.gui.library_workspace import FolderEditor
from torrentlinker.gui.upload_view import UploadTab
from torrentlinker.indexer import Candidate, SearchQuery
from torrentlinker.library import LibraryEntry
from torrentlinker.matching import IgnoreList
from torrentlinker.scan import scan_item
from torrentlinker.store import Store
from torrentlinker.upload import ExistingQuery, Subcategory, Subcategory3D

ANNOUNCE = "https://c411.org/announce/secret"
FIXTURES = Path(__file__).parent / "fixtures"  # c411's own answers, recorded


class StubIndexer:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.searches: list[SearchQuery] = []
        self.found: list[Candidate] = []
        self.search_error: Exception | None = None
        self.options_asked: list[int] = []
        self.by_ids: list[dict[str, str]] = []

    def search(self, query: SearchQuery) -> list[Candidate]:
        self.searches.append(query)
        if self.search_error:
            raise self.search_error
        return self.found

    def by_tmdb(self, ids: dict[str, str]) -> list[Candidate]:
        self.by_ids.append(ids)
        return self.found

    def save_draft(self, body: dict[str, Any]) -> int:
        self.saved.append(body)
        return 7

    def drafts(self) -> list[dict[str, Any]]:
        return [{"name": b["title"], "subcategory": {"name": "Objets"}} for b in self.saved]

    def category_options(self, subcategory: int) -> dict[str, Any]:
        self.options_asked.append(subcategory)
        if subcategory in (6, 51):
            return json.loads((FIXTURES / f"c411_options_{subcategory}.json").read_text("utf-8"))
        return {"data": []}


def model(tmp_path: Path, name: str = "Petit étau de bureau.3mf") -> LibraryEntry:
    folder = LibraryFolder(tmp_path / "STL", 1, ContentKind.MODEL_3D)
    folder.path.mkdir(exist_ok=True)
    (folder.path / name).write_bytes(b"m" * 3000)
    return LibraryEntry(folder, scan_item(folder.path / name), ItemState.ORPHAN)


def tab(qtbot, tmp_path: Path, announce: str = ANNOUNCE) -> tuple[UploadTab, StubIndexer, FakeQbit]:  # type: ignore[no-untyped-def]
    indexer, qbit = StubIndexer(), FakeQbit()
    view = UploadTab(
        Store(tmp_path / "s.db"),
        lambda: indexer,  # type: ignore[arg-type,return-value]
        lambda: qbit,
        IgnoreList.default,
        lambda: announce,
        tmp_path / "uploads",
    )
    qtbot.addWidget(view)
    return view, indexer, qbit


@pytest.mark.parametrize("status", [200, 500])
def test_image_reply_after_upload_tab_is_deleted_is_ignored(qtbot, tmp_path, status):
    from threading import Event

    from PySide6.QtCore import QBuffer, QIODevice, QThreadPool
    from PySide6.QtGui import QImage

    started, release = Event(), Event()
    image = QImage(1, 1, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    png = bytes(buffer.data())

    def reply(request):
        started.set()
        assert release.wait(5)
        return httpx.Response(status, content=png)

    # This test owns deletion; do not register an already-deleted widget for QtBot cleanup.
    indexer = StubIndexer()
    view = UploadTab(
        Store(tmp_path / "s.db"),
        lambda: indexer,
        lambda: FakeQbit(),
        IgnoreList.default,
        lambda: ANNOUNCE,
        tmp_path / "uploads",
    )
    with httpx.Client(transport=httpx.MockTransport(reply)) as http:
        view._http = http
        try:
            view.image_url.setText("https://example.org/poster.png")
            qtbot.waitUntil(started.is_set)
            with qtbot.waitSignal(view.destroyed):
                view.deleteLater()
        finally:
            release.set()
            assert QThreadPool.globalInstance().waitForDone(5000)
        qtbot.wait(50)  # Deliver the completed worker callback to the GUI thread.


def test_only_searched_3d_orphans_without_a_match_may_be_uploaded(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    vise, archive = model(tmp_path), model(tmp_path, "Dragon.rar")
    nulled = model(tmp_path, "Autre.3mf").item
    other = LibraryEntry(LibraryFolder(tmp_path, 1, ContentKind.OTHER), nulled, ItemState.ORPHAN)
    view._picked[other.item.path] = 9  # Nulled: c411 has it, the app has no profile for it
    view.set_entries([vise, archive, other])

    assert view.candidates() == [vise, archive, other]
    assert "Search it first" in (view.why_not(vise) or "")
    assert "Nulled" in (view.why_not(other) or "")
    assert "not supported yet" in (view.why_not(other) or "")
    assert view.items.rowCount() == 0  # nothing ready: the rest hides behind Show all
    view.show_all.setChecked(True)
    assert view.items.rowCount() == 3
    view.show_all.setChecked(False)

    view.remember(vise, [])
    view.remember(archive, [])
    assert view.why_not(vise) is None
    assert view.why_not(archive) is None and view.needs_unpacking(archive)  # unpacked first
    assert view.items.rowCount() == 2
    assert view.items.item(0, 3).text() == "Archive: unpack it to upload"


def test_the_category_picker_defaults_from_the_kind_and_reruns_the_profile(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path
) -> None:
    view, _, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    loose = LibraryEntry(
        LibraryFolder(tmp_path / "STL", 2, ContentKind.OTHER), vise.item, ItemState.ORPHAN
    )
    view.set_entries([loose])
    view.remember(loose, [])

    assert view.items.rowCount() == 0  # no category: not ready, hidden behind Show all
    view.show_all.setChecked(True)
    assert view.why_not(loose) == "Choose a category"
    assert view.items.item(0, 3).text() == "Choose a category"
    view.items.selectRow(0)
    assert (
        view.category.currentData() is None and view.category.currentText() == "Choose a category"
    )
    assert not view.name.isEnabled() and not view.create_button.isEnabled()

    view.category.setCurrentIndex(view.category.findData(10))
    assert view.why_not(loose) is None and view.items.item(0, 3).text() == "Ready"
    assert view.name.text() == "Petit.Etau.De.Bureau.NOTAG.3MF"
    assert view.subcategory.count() == 3 and view.name.isEnabled()
    qtbot.waitUntil(view.create_button.isEnabled, timeout=5000)

    view.set_entries([loose, model(tmp_path)])  # a 3D folder defaults to Imprimante 3D
    view.remember(view.candidates()[1], [])
    view.items.selectRow(1 if view.shown[0] is loose else 0)
    assert view.category.currentData() == 10


def test_a_kind_whose_category_has_no_profile_yet_says_so(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    game = LibraryEntry(LibraryFolder(tmp_path, 1, ContentKind.OTHER), vise.item, ItemState.ORPHAN)
    view._picked[game.item.path] = 9  # Nulled: no profile for it
    view.set_entries([game])
    view.remember(game, [])
    view.show_all.setChecked(True)
    view.items.selectRow(0)

    assert "Nulled" in (view.why_not(game) or "") and "not supported yet" in view.problems.text()
    assert view.category.currentText() == "Nulled"
    view.category.setCurrentIndex(view.category.findData(10))  # the user can still pick 3D
    assert view.why_not(game) is None


def test_an_archive_that_cannot_be_read_cannot_be_unpacked(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    broken = model(tmp_path, "Dragon.zip")  # not a zip inside
    view.set_entries([broken])
    view.remember(broken, [])
    view.items.selectRow(0)

    qtbot.waitUntil(lambda: "cannot be read" in view.problems.text(), timeout=5000)
    assert view.create_button.text() == "Unpack…"
    assert not view.create_button.isEnabled()


def test_selecting_an_orphan_suggests_a_compliant_name_and_previews_the_nfo(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])

    view.items.selectRow(0)
    assert view.name.text() == "Petit.Etau.De.Bureau.NOTAG.3MF"
    view.source.setText("Printables")
    assert view.name.text() == "Petit.Etau.De.Bureau.Printables.3MF"
    assert "Petit.Etau.De.Bureau.Printables.3MF.3mf" in view.nfo.toPlainText()
    assert view.file_table.item(0, 0).text() == "Petit.Etau.De.Bureau.Printables.3MF.3mf"
    assert view.file_table.item(0, 1).text() == "Petit étau de bureau.3mf"
    assert "Printables" in view.description.toPlainText()
    assert "Informations" in view.preview.toPlainText()  # rendered, without BBCode
    qtbot.waitUntil(view.create_button.isEnabled, timeout=5000)

    view.name.setText("Petit étau")
    assert not view.create_button.isEnabled()


def test_no_announce_url_says_where_to_enter_it(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path, announce="")
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])
    view.items.selectRow(0)

    assert "Announce URL" in view.notice.text()
    assert not view.create_button.isEnabled()


def test_creating_a_draft_saves_it_and_seeds_from_the_local_file(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: shown.append(a[2]))
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a: asked.append(a[2]) or QMessageBox.StandardButton.Yes,
    )
    view, indexer, qbit = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])
    view.items.selectRow(0)
    started: list[Path] = []
    view.upload_started.connect(started.append)
    view.image_url.setText("https://example.org/cover.jpg")
    view._image_timer.stop()
    view.description.setPlainText(complete_description())

    qtbot.waitUntil(view.create_button.isEnabled, timeout=5000)
    view.queue_button.click()
    qtbot.waitUntil(lambda: view.local_drafts.record is not None, timeout=5000)
    assert not indexer.saved
    view.local_drafts.pages.setCurrentIndex(4)
    view.local_drafts.reviewed.setChecked(True)
    view.local_drafts.send_button.click()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert len(asked) == 1
    assert "saved as a Draft" in shown[0], shown
    assert indexer.saved[0]["title"] == "Petit.Etau.De.Bureau.NOTAG.3MF"
    [t] = qbit.torrents()
    assert set(t.files) == {"Petit étau de bureau.3mf"}
    assert started == [vise.item.path]
    qtbot.waitUntil(lambda: view.drafts.rowCount() == 1, timeout=5000)


@pytest.mark.parametrize("image_first", [False, True])
def test_draft_keeps_the_image_with_a_custom_description(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch, image_first: bool
) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    view, indexer, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])
    view.items.selectRow(0)
    url = "https://i.example/desk-vise.png"
    if image_first:
        view.image_url.setText(url)
    view.description.setPlainText(complete_description(text="[center][b]My desk vise[/b][/center]"))
    if not image_first:
        view.image_url.setText(url)
    view._image_timer.stop()
    qtbot.waitUntil(view.create_button.isEnabled, timeout=5000)
    view.queue_button.click()
    qtbot.waitUntil(lambda: view.local_drafts.record is not None, timeout=5000)
    assert not indexer.saved
    view.local_drafts.pages.setCurrentIndex(4)
    view.local_drafts.reviewed.setChecked(True)
    view.local_drafts.send_button.click()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)
    description = indexer.saved[0]["description"]
    assert f"[img]{url}[/img]" in description
    assert "[center][b]My desk vise[/b][/center]" in description
    qtbot.waitUntil(lambda: view.drafts.rowCount() == 1, timeout=5000)


def test_the_library_offers_an_upload_once_searched_without_a_match(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.config import Settings
    from torrentlinker.gui.main_window import MainWindow

    vise = model(tmp_path)
    window = MainWindow(
        Settings(library_folders=[vise.folder]),
        tmp_path / "settings.json",
        Store(tmp_path / "s.db"),
    )
    qtbot.addWidget(window)
    window.upload_tab.set_entries([vise])
    window.review.set_entry(vise)
    button = window.review.upload_button
    assert not button.isHidden() and not button.isEnabled()  # not searched yet

    window.review.remember(vise, [])
    assert button.isEnabled()
    button.click()

    assert window.tabs.currentWidget() is window.upload_tab
    assert window.upload_tab.entry == vise


def test_changing_library_folders_scans_again(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from dataclasses import replace

    from torrentlinker.config import Settings
    from torrentlinker.gui import main_window
    from torrentlinker.gui.main_window import MainWindow

    folder = LibraryFolder(tmp_path, 1, ContentKind.OTHER)
    window = MainWindow(
        Settings(library_folders=[folder]), tmp_path / "settings.json", Store(tmp_path / "s.db")
    )
    qtbot.addWidget(window)
    scans: list[bool] = []
    window.scan = lambda refresh=False: scans.append(refresh)  # type: ignore[method-assign]
    window.zen_tab.seeding_view.refresh = lambda quiet=False: None  # type: ignore[method-assign]
    # This exercises editing folders after connection setup has already completed.
    window._startup_complete = True
    monkeypatch.setattr(window, "_has_indexer_key", lambda: True)

    class Dialog(QObject):
        diagnostics_requested = Signal()
        agent_approvals = ()

        def __init__(self, settings: Settings, parent: object) -> None:
            super().__init__(parent)
            self.settings = settings
            self.folder_editor = FolderEditor(settings.library_folders, window)

        def exec(self) -> bool:
            self.settings.library_folders = [replace(folder, kind=ContentKind.MODEL_3D)]
            return True

    monkeypatch.setattr(main_window, "SettingsDialog", Dialog)
    window.open_settings()
    assert scans == [False]
    window.open_settings()  # nothing changed this time
    assert scans == [False]


def test_edits_to_the_description_survive_other_changes_until_reset(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])
    view.items.selectRow(0)

    view.description.setPlainText("[b]Mine[/b]")
    view.source.setText("Printables")
    assert view.description.toPlainText() == "[b]Mine[/b]"
    view.image_url.setText("https://i.example/v.png")
    assert view.description.toPlainText() == (
        "[center][img]https://i.example/v.png[/img][/center]\n\n[b]Mine[/b]"
    )

    view._reset("description")
    assert "[img]https://i.example/v.png[/img]" in view.description.toPlainText()


def test_image_changes_preserve_custom_text_and_other_images(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])
    view.items.selectRow(0)
    text = "[center][img]…[/img][/center]\nMy vise\n[img]https://i.example/extra.png[/img]"
    view.description.setPlainText(text)
    view.image_url.setText("https://i.example/first.png")
    assert view.description.toPlainText() == text.replace("…", "https://i.example/first.png")
    view.image_url.setText("https://i.example/second.png")
    assert view.description.toPlainText() == text.replace("…", "https://i.example/second.png")
    view._sync_description_image()
    assert view.description.toPlainText().count("second.png") == 1
    view.image_url.clear()
    assert view.description.toPlainText() == text
    view._image_timer.stop()


def test_an_archive_is_unpacked_next_to_it_then_its_folder_is_offered(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    import zipfile

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    folder = LibraryFolder(tmp_path / "STL", 1, ContentKind.MODEL_3D)
    folder.path.mkdir()
    archive = folder.path / "Dragon.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("Dragon/Corps.stl", b"c" * 1500)
        z.writestr("Dragon/Tete.stl", b"t" * 700)
    entry = LibraryEntry(folder, scan_item(archive), ItemState.ORPHAN)
    view, _, _ = tab(qtbot, tmp_path)
    view.set_entries([entry])
    view.remember(entry, [])
    view.items.selectRow(0)
    qtbot.waitUntil(lambda: view.file_table.rowCount() == 2, timeout=5000)
    qtbot.waitUntil(view.create_button.isEnabled, timeout=5000)
    assert view.create_button.text() == "Unpack…"
    assert view.name.text() == "Dragon.NOTAG.[PACK].STL"
    new: list[Path] = []
    view.unpacked.connect(new.append)

    view.create_button.click()
    qtbot.waitUntil(lambda: bool(new), timeout=5000)

    unpacked_folder = new[0]
    assert (unpacked_folder / "Dragon" / "Corps.stl").exists() or (
        unpacked_folder / "Corps.stl"
    ).exists()
    assert archive.exists()  # the archive stays until the Upload seeds
    assert view.store.take_unpacked(unpacked_folder) == archive
    # The Library scans; the new folder comes back selected, its archive's search kept.
    folder_entry = LibraryEntry(folder, scan_item(unpacked_folder), ItemState.ORPHAN)
    view.set_entries([entry, folder_entry])
    assert view.entry == folder_entry
    assert view.why_not(folder_entry) is None
    assert view.create_button.isHidden()
    assert view.queue_button.isEnabled()


def test_bbcode_renders_as_html_without_running_markup() -> None:
    from torrentlinker.bbcode import bbcode_to_html

    out = bbcode_to_html(
        "[center][img]https://i.example/a.png[/img][/center]\n[b]x[/b] <script>[*]y"
        "[url=javascript:alert(1)]no[/url]"
    )

    assert '<img src="https://i.example/a.png"' in out and "<b>x</b>" in out
    assert "&lt;script&gt;" in out and "<script>" not in out
    assert "javascript" in out and 'href="javascript' not in out


def test_warnings_show_beside_refusals_and_never_block_the_draft(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    vise, archive = model(tmp_path), model(tmp_path, "Dragon.rar")
    view.set_entries([vise, archive])
    view.remember(vise, [])
    view.remember(archive, [])
    view.items.selectRow(view.shown.index(vise))

    assert "independent creators" in view.warnings.text()
    assert "independent creators" not in view.problems.text()
    assert "coherent theme" not in view.warnings.text()  # only for a pack
    qtbot.waitUntil(view.create_button.isEnabled, timeout=5000)  # a Warning does not block

    view.subcategory.setCurrentIndex(view.subcategory.findData(Subcategory3D.PACK))
    assert "coherent theme" in view.warnings.text()
    qtbot.waitUntil(view.create_button.isEnabled, timeout=5000)


def test_selecting_an_item_lists_what_c411_already_has_once_per_session(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path
) -> None:
    view, indexer, _ = tab(qtbot, tmp_path)
    indexer.found = [
        Candidate("Etau.Pro.3MF", 2048, "d", 3, details_url="https://c411.org/torrent/abc"),
        Candidate("Etau <b>.STL", 1 << 20, "d", 12, details_url="https://c411.org/torrent/def"),
    ]
    vise, other = model(tmp_path), model(tmp_path, "Dragon.3mf")
    view.set_entries([vise, other])
    view.remember(vise, [])
    view.remember(other, [])
    assert indexer.searches == []  # nothing is searched until the user selects an item

    view.items.selectRow(0)
    qtbot.waitUntil(lambda: "Etau.Pro.3MF" in view.existing_view.toPlainText(), timeout=5000)
    text = view.existing_view.toPlainText()
    assert text.index("Etau <b>.STL") < text.index("Etau.Pro.3MF")  # most seeded first
    assert "https://c411.org/torrent/abc" in view.existing_view.toHtml()
    assert [q.params()["q"] for q in indexer.searches] == ["Dragon"]
    assert "(2)" in view.existing_box.title()

    view.items.selectRow(1)
    qtbot.waitUntil(lambda: len(indexer.searches) == 2, timeout=5000)
    view.items.selectRow(0)
    view.items.selectRow(1)
    qtbot.wait(100)
    assert len(indexer.searches) == 2  # cached for the session


def test_nothing_found_says_so_and_a_failed_search_is_tried_again(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, indexer, _ = tab(qtbot, tmp_path)
    entry = model(tmp_path)
    view.set_entries([entry])
    view.remember(entry, [])
    indexer.search_error = httpx.ConnectError("down")

    view.items.selectRow(0)
    qtbot.waitUntil(lambda: "could not be searched" in view.existing_status.text(), timeout=5000)
    indexer.search_error = None
    view.items.clearSelection()
    view.items.selectRow(0)

    qtbot.waitUntil(
        lambda: "No release found by this search" in view.existing_status.text(), timeout=5000
    )
    assert "may still belong to a c411 torrent" in view.existing_status.text()
    assert "Rescan the Library" in view.existing_status.text()
    assert len(indexer.searches) == 2
    assert view.existing_view.isHidden()


def test_the_list_of_existing_releases_collapses(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, indexer, _ = tab(qtbot, tmp_path)
    indexer.found = [Candidate("Etau.3MF", 1, "d", details_url="https://c411.org/torrent/abc")]
    entry = model(tmp_path)
    view.set_entries([entry])
    view.remember(entry, [])
    view.new_draft()
    view.show()
    view.items.selectRow(0)
    qtbot.waitUntil(lambda: view.existing_view.isVisible(), timeout=5000)

    view.existing_box.setChecked(False)

    assert not view.existing_view.isVisible()


@pytest.mark.parametrize("evidence", ["announce_list", "app_download", "catalogue"])
def test_client_pack_contents_are_not_offered_for_upload_after_scan(qtbot, tmp_path, evidence):
    from torrentlinker.domain import Torrent
    from torrentlinker.library import build_library, indexer_contents
    from torrentlinker.store import CatalogueRow

    view, _, client = tab(qtbot, tmp_path)
    entry = model(tmp_path)
    infohash = "b" * 40
    client.by_hash[infohash] = Torrent(
        infohash,
        "Pack with a different title",
        entry.item.save_path,
        dict(entry.item.files),
        tags=frozenset({"torrentlinker:search"}) if evidence == "app_download" else frozenset(),
        trackers=("https://tk.c411.tw/announce/private",) if evidence == "announce_list" else (),
    )
    if evidence == "catalogue":
        view.store.save_catalogue(
            [CatalogueRow(infohash, "Pack", entry.item.size, 1, 8010, "u", "d", 0)]
        )
    # An earlier empty name search must not override current client-file evidence.
    view.set_entries([entry])
    view.remember(entry, [])
    assert view.shown == [entry]

    contents = indexer_contents(client, view.store, "https://c411.org/api")
    view.set_entries(build_library([entry.folder], contents))

    assert view.entries[0].state is ItemState.SEEDED
    assert view.shown == []


class FilmProfile:
    """A stand-in for a video profile, to exercise Category Options the 3D one has none of."""

    category = 1
    subcategories = (Subcategory(6, "Film"),)
    renders_models = False
    media_extensions = ()
    dotted_names = True

    def draft_fields(self, item, ignore, files):  # type: ignore[no-untyped-def]
        return {}

    def image_is_sheet(self, subcategory):  # type: ignore[no-untyped-def]
        return False

    def inspect(self, item, ignore):  # type: ignore[no-untyped-def]
        pass

    def refusals(self, item, ignore, subcategory=None):  # type: ignore[no-untyped-def]
        return []

    def warnings(self, item, ignore, subcategory):  # type: ignore[no-untyped-def]
        return []

    def existing_query(self, item, ignore):  # type: ignore[no-untyped-def]
        return ExistingQuery("Film")

    def default_subcategory(self, item, ignore):  # type: ignore[no-untyped-def]
        return 6

    def suggested_name(self, item, ignore, source, subcategory):  # type: ignore[no-untyped-def]
        return "Film.2020.NOTAG"

    def suggested_options(self, item, ignore, types):  # type: ignore[no-untyped-def]
        return {1: [2]}  # from MediaInfo: a French track

    def nfo(self, title, files):  # type: ignore[no-untyped-def]
        return "nfo"

    def description(self, title, files, source, image_url):  # type: ignore[no-untyped-def]
        return "description"


def film_tab(qtbot, tmp_path: Path, monkeypatch):  # type: ignore[no-untyped-def]
    from torrentlinker.gui import upload_view

    monkeypatch.setitem(upload_view.PROFILES, 1, FilmProfile())
    view, indexer, qbit = tab(qtbot, tmp_path)
    entry = model(tmp_path)
    film = LibraryEntry(
        LibraryFolder(tmp_path / "STL", 2, ContentKind.MOVIE), entry.item, ItemState.ORPHAN
    )
    view.set_entries([film])
    view.remember(film, [])
    view.items.selectRow(0)
    return view, indexer, qbit


def test_the_options_of_a_subcategory_show_as_selectors_the_profile_prefills(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QComboBox, QListWidget

    view, indexer, _ = film_tab(qtbot, tmp_path, monkeypatch)

    qtbot.waitUntil(lambda: bool(view.option_types), timeout=5000)
    langue, genre, kind = (view._option_widgets[i] for i in (1, 5, 4))
    assert isinstance(langue, QListWidget) and isinstance(genre, QListWidget)
    assert isinstance(kind, QComboBox)
    assert view.options_form.labelForField(langue).text() == "Langue *"  # required
    assert view.options_form.labelForField(genre).text() == "Genre"
    assert view.chosen_options() == {1: [2], 5: [], 4: []}  # prefilled from the profile
    assert indexer.options_asked == [6]


def test_a_required_option_left_empty_blocks_the_draft_until_the_user_chooses(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    view, _, _ = film_tab(qtbot, tmp_path, monkeypatch)
    qtbot.waitUntil(lambda: bool(view.option_types), timeout=5000)
    assert view.create_button.isEnabled()

    langue = view._option_widgets[1]
    langue.item(1).setCheckState(Qt.CheckState.Unchecked)  # the profile's French track

    assert view.chosen_options()[1] == []
    assert "Choose a value for Langue" in view.problems.text()
    assert not view.create_button.isEnabled()

    langue.item(0).setCheckState(Qt.CheckState.Checked)  # the user's own pick
    assert view.chosen_options()[1] == [1]
    assert "Choose a value" not in view.problems.text()
    assert view.create_button.isEnabled()


def test_options_collapse_keeps_choices_and_editor_space(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    view, _, _ = film_tab(qtbot, tmp_path, monkeypatch)
    view.resize(1200, 900)
    view.new_draft()
    view.show()
    qtbot.waitUntil(lambda: bool(view.option_types), timeout=5000)
    assert view.options_body.isHidden()
    assert not view.options_toggle.isChecked()
    collapsed_height = view.options_box.sizeHint().height()

    qtbot.mouseClick(view.options_toggle, Qt.MouseButton.LeftButton)
    assert view.options_body.isVisible()
    assert view.options_toggle.arrowType() == Qt.ArrowType.DownArrow
    view._option_widgets[5].item(0).setCheckState(Qt.CheckState.Checked)
    choices = view.chosen_options()
    assert view.options_box.sizeHint().height() > collapsed_height + 100

    view._show_options()  # rebuilding the fields keeps the user's expanded state and picks
    assert view.options_body.isVisible()
    assert view.chosen_options() == choices
    qtbot.mouseClick(view.options_toggle, Qt.MouseButton.LeftButton)
    assert view.options_body.isHidden()
    assert view.options_toggle.arrowType() == Qt.ArrowType.RightArrow
    assert view.chosen_options() == choices
    view._show_options()
    assert view.options_body.isHidden()
    assert view.chosen_options() == choices


def test_the_users_choice_wins_over_the_profile_and_is_sent_in_the_draft(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    view, indexer, _ = film_tab(qtbot, tmp_path, monkeypatch)
    qtbot.waitUntil(lambda: bool(view.option_types), timeout=5000)

    view._option_widgets[5].item(0).setCheckState(Qt.CheckState.Checked)  # Action
    kind = view._option_widgets[4]
    kind.setCurrentIndex(kind.findData(38))  # 3D
    view.source.setText("WEB")  # regenerating keeps the picks

    assert view.chosen_options() == {1: [2], 5: [39], 4: [38]}
    view.image_url.setText("https://example.org/cover.jpg")
    view._image_timer.stop()
    view.description.setPlainText(complete_description(1, 6))
    view.nfo.setPlainText(complete_form(1, 6)["nfo"])
    view.queue_button.click()
    qtbot.waitUntil(lambda: view.local_drafts.record is not None, timeout=5000)
    assert not indexer.saved
    view.local_drafts.pages.setCurrentIndex(4)
    view.local_drafts.reviewed.setChecked(True)
    view.local_drafts.send_button.click()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)
    assert indexer.saved[0]["options"] == {"1": [2], "5": [39], "4": 38}
    assert indexer.saved[0]["subcategoryId"] == 6


def test_options_are_read_once_then_kept_until_refreshed(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    view, indexer, _ = film_tab(qtbot, tmp_path, monkeypatch)
    qtbot.waitUntil(lambda: bool(view.option_types), timeout=5000)

    view._show_options()  # from the store this time
    assert view.option_types and indexer.options_asked == [6]

    view._show_options(refresh=True)
    qtbot.waitUntil(lambda: indexer.options_asked == [6, 6], timeout=5000)


def test_options_that_cannot_be_read_say_so_and_block_the_draft(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    view, indexer, _ = film_tab(qtbot, tmp_path, monkeypatch)
    qtbot.waitUntil(lambda: bool(view.option_types), timeout=5000)

    def offline(subcategory: int) -> dict[str, Any]:
        raise OSError("offline")

    indexer.category_options = offline  # type: ignore[method-assign]
    view._show_options(refresh=True)

    qtbot.waitUntil(
        lambda: "Could not read the options" in view.options_status.text(), timeout=5000
    )
    assert not view.option_types and not view.create_button.isEnabled()
    assert not view.options_refresh.isHidden()
    assert not view.options_status.isHidden()  # failure/retry stay accessible when collapsed
    assert view.options_body.isHidden()


def test_3d_has_no_options_to_show_and_sends_none(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, indexer, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])
    view.items.selectRow(0)

    qtbot.waitUntil(lambda: indexer.options_asked == [51], timeout=5000)
    qtbot.waitUntil(view.create_button.isEnabled, timeout=5000)
    assert view.options_box.isHidden() and view.chosen_options() == {}


def test_the_3d_page_follows_the_selected_orphan_and_the_subcategory(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import shutil

    view, _, _ = tab(qtbot, tmp_path)
    box = model(tmp_path, "Boite.stl")
    shutil.copy(Path(__file__).parent / "fixtures" / "models" / "cube-binary.stl", box.item.path)
    box = LibraryEntry(box.folder, scan_item(box.item.path), ItemState.ORPHAN)
    view.set_entries([box])
    view.remember(box, [])
    view.new_draft()
    view.show()
    assert view.pages.isTabVisible(view.model_tab) is False  # nothing picked

    view.items.selectRow(0)

    qtbot.waitUntil(lambda: view.model_panel.viewer.display is not None, timeout=10000)
    assert view.pages.isTabVisible(view.model_tab)
    assert view.model_panel.sheet_button.isHidden()  # one model, an Objects upload
    pack = view.subcategory.findData(Subcategory3D.PACK)
    view.subcategory.setCurrentIndex(pack)
    assert not view.model_panel.sheet_button.isHidden()  # a Pack gets its contact sheet
    assert view.model_panel.upload_folder() == tmp_path / "uploads" / view.name.text()
    assert "[img]…[/img]" in view.description.toPlainText()  # the image is added on c411


def test_a_profile_reads_the_files_off_the_gui_thread_then_redoes_the_name(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    import threading

    from torrentlinker.audio_tags import AudioTags, TagCache
    from torrentlinker.gui import upload_view
    from torrentlinker.upload import AudioProfile

    readers: list[int] = []

    def reader(path: Path) -> AudioTags:
        readers.append(threading.get_ident())
        return AudioTags(
            "Daft Punk", "Discovery", "Intro", "2001", 1, 300.0, "MP3", 320, True, 44100, 0, 2
        )

    monkeypatch.setitem(upload_view.PROFILES, 3, AudioProfile(TagCache(reader)))
    view, _, _ = tab(qtbot, tmp_path)
    folder = LibraryFolder(tmp_path / "Music", 1, ContentKind.MUSIC)
    album = folder.path / "Album"
    album.mkdir(parents=True)
    for n in (1, 2):
        (album / f"{n}.mp3").write_bytes(b"x" * 100 * n)
    entry = LibraryEntry(folder, scan_item(album), ItemState.ORPHAN)
    view.set_entries([entry])
    view.remember(entry, [])
    view.items.selectRow(0)

    qtbot.waitUntil(lambda: view.name.text().startswith("Daft.Punk.Discovery.2001"), timeout=5000)
    assert readers and threading.get_ident() not in readers
    assert view.name.text() == "Daft.Punk.Discovery.2001.MP3.320kbps-NOTAG"
    assert view.subcategory.currentData() == 18


def test_an_identified_film_is_looked_up_on_c411_by_tmdb_id_once_inspected(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from tests.test_upload_video import FR_1080, LE_FILM, Tmdb, profile
    from torrentlinker.gui import upload_view

    video = profile({FR_1080: "film_x264_1080p_fr"}, tmdb=Tmdb(LE_FILM))
    monkeypatch.setitem(upload_view.PROFILES, 1, video)
    view, indexer, _ = tab(qtbot, tmp_path)
    indexer.found = [Candidate("Le.Film.2020.VFF.1080p.BluRay-TFA", 5, "", 4)]
    folder = LibraryFolder(tmp_path / "Films", 1, ContentKind.MOVIE)
    folder.path.mkdir()
    (folder.path / FR_1080).write_bytes(b"v" * 100)
    entry = LibraryEntry(folder, scan_item(folder.path / FR_1080), ItemState.ORPHAN)
    view.set_entries([entry])
    view.remember(entry, [])
    view.items.selectRow(0)

    qtbot.waitUntil(lambda: bool(indexer.by_ids), timeout=5000)
    assert indexer.by_ids == [{"tmdbId": "1", "tmdbType": "movie"}]
    assert indexer.searches == []  # not by title words
    qtbot.waitUntil(lambda: "(1)" in view.existing_box.title(), timeout=5000)
    assert view.subcategory.currentData() == 6
    assert view.name.text() == "Le.Film.Francais.2020.VFF.1080p.BluRay.AC3.5.1.x264-TFA"
    assert "Le Film Français" in view.warnings.text()
    assert view.files[0].torrent_path.endswith(f"{view.name.text()}.mkv")


def test_a_games_name_may_keep_its_spaces_and_accents(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    folder = LibraryFolder(tmp_path / "Roms", 1, ContentKind.GAME)
    folder.path.mkdir()
    (folder.path / "Zelda (Europe) (Fr,En).sfc").write_bytes(b"r" * 100)
    entry = LibraryEntry(
        folder, scan_item(folder.path / "Zelda (Europe) (Fr,En).sfc"), ItemState.ORPHAN
    )
    view._picked[entry.item.path] = 6  # Emulation: names are exempt from the dot rule
    view.set_entries([entry])
    view.remember(entry, [])
    view.items.selectRow(0)

    assert view.name.text() == "[SNES]Zelda [EU - MULTI] SFC"
    assert "dots between words" not in view.problems.text()
    qtbot.waitUntil(view.create_button.isEnabled, timeout=5000)
    assert view.files[0].torrent_path == "[SNES]Zelda [EU - MULTI] SFC.sfc"


def test_after_a_restart_a_persisted_search_without_candidates_is_ready(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    vise = model(tmp_path)
    other = model(tmp_path, "Autre.3mf")
    never = model(tmp_path, "Jamais cherche.3mf")
    store = Store(tmp_path / "s.db")
    store.remember_candidates(vise.item.path, "[]")
    store.remember_candidates(other.item.path, '[{"title": "t", "size": 1, "download_url": "u"}]')

    view, _, _ = tab(qtbot, tmp_path)  # a fresh view: nothing searched this session
    view.set_entries([vise, other, never])

    assert view.why_not(vise) is None
    assert view.why_not(other) is not None  # compared again by the Library first
    assert view.why_not(never) == "Search it first: c411 may already have it"


def test_local_upload_queue_keeps_edited_description_without_remote_draft(qtbot, tmp_path):
    view, indexer, qbit = tab(qtbot, tmp_path, announce="")
    entry = model(tmp_path)
    view.set_entries([entry])
    view.show_all.setChecked(True)
    view.items.selectRow(0)
    qtbot.waitUntil(lambda: bool(view.files))
    view.description.setPlainText("[b]Review this locally[/b]")
    assert view.queue_button.isEnabled()
    view.queue_button.click()
    qtbot.waitUntil(lambda: view.local_drafts.record is not None, timeout=5000)
    assert view.workspaces.currentWidget() is view.local_drafts
    assert indexer.saved == []
    assert view.local_drafts.record["status"] == "queued"
    view.local_drafts.description.setPlainText("[b]Corrected locally[/b]")
    view.local_drafts.save_button.click()
    qtbot.waitUntil(lambda: not view.local_drafts.busy, timeout=5000)
    assert view.store.local_drafts()[0]["form"]["description"].startswith(
        "[b]Corrected locally[/b]"
    )
    assert view.store.local_drafts()[0]["revision"] == 2
    assert indexer.saved == []
    assert not list((tmp_path / "uploads").glob("*.torrent"))

    screenshots = os.getenv("TL_UPLOAD_SCREENSHOTS")
    if screenshots:
        from PySide6.QtWidgets import QApplication

        from torrentlinker.gui.theme import apply_theme

        apply_theme(QApplication.instance(), "dark")
        view.resize(1000, 650)
        view.show()
        qtbot.wait(150)
        Path(screenshots).mkdir(parents=True, exist_ok=True)
        assert view.grab().save(str(Path(screenshots) / "desktop-upload-queue.png"))


def test_a_batch_rebuilds_the_upload_list_at_most_once_a_second(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    entries = [model(tmp_path, f"Pièce {i}.3mf") for i in range(3)]
    view.set_entries(entries)
    view.show_all.setChecked(True)
    fills: list[int] = []
    original = view._fill

    def counted() -> None:
        fills.append(1)
        original()

    view._fill = counted  # type: ignore[method-assign]
    view.throttle_refresh(True)
    for entry in entries:
        view.remember(entry, [])
    assert len(fills) == 3  # each search still asks, but only the first rebuilds at once
    assert view.why_not(entries[2]) is None
    assert "Search it first" in view.items.item(2, 3).text()  # not rebuilt yet

    view.throttle_refresh(False)  # the batch ended: show everything now
    assert "Search it first" not in view.items.item(2, 3).text()
