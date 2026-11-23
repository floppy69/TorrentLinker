"""Library handoff and source preservation after retiring the native Upload editor."""

from pathlib import Path

from torrentlinker.domain import ContentKind, ItemState, LibraryFolder
from torrentlinker.library import LibraryEntry
from torrentlinker.scan import scan_item
from torrentlinker.store import Store


def model(tmp_path: Path, name: str = "Petit étau de bureau.3mf") -> LibraryEntry:
    folder = LibraryFolder(tmp_path / "STL", 1, ContentKind.MODEL_3D)
    folder.path.mkdir(exist_ok=True)
    (folder.path / name).write_bytes(b"m" * 3000)
    return LibraryEntry(folder, scan_item(folder.path / name), ItemState.ORPHAN)


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

    assert window.tabs.currentWidget() is window.upload_workspace
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
    window.zen_tab.seeding_view.reload = lambda quiet=False: None  # type: ignore[method-assign]
    # This exercises editing folders after connection setup has already completed.
    window._startup_complete = True
    monkeypatch.setattr(window, "_has_indexer_key", lambda: True)

    from tests.test_startup import SettingsPageDouble

    class Page(SettingsPageDouble):
        def __init__(self, parent, *, section) -> None:
            super().__init__(parent, saved=True)
            folders = [replace(folder, kind=ContentKind.MODEL_3D)]
            self.setup.settings.library_folders = folders

    monkeypatch.setattr(main_window, "SettingsPage", Page)
    window.open_settings()
    window.close_settings()
    assert scans == [False]
    window.open_settings()  # nothing changed this time
    window.close_settings()
    assert scans == [False]


def test_bbcode_renders_as_html_without_running_markup() -> None:
    from torrentlinker.bbcode import bbcode_to_html

    out = bbcode_to_html(
        "[center][img]https://i.example/a.png[/img][/center]\n[b]x[/b] <script>[*]y"
        "[url=javascript:alert(1)]no[/url]"
    )

    assert '<img src="https://i.example/a.png"' in out and "<b>x</b>" in out
    assert "&lt;script&gt;" in out and "<script>" not in out
    assert "javascript" in out and 'href="javascript' not in out
