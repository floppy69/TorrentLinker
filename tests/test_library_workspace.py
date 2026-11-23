"""Library navigation and Candidate review through the desktop widgets."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget

from tests.test_library_folders import window_for


@pytest.fixture
def library_theme(qapp, monkeypatch):
    from torrentlinker.gui.theme import ThemeFollower, apply_theme

    palette, stylesheet, style = qapp.palette(), qapp.styleSheet(), qapp.style().objectName()
    follower = qapp.findChild(ThemeFollower)
    mode = follower.mode if follower else "auto"
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "")
    apply_theme(qapp, "dark")
    try:
        yield
    finally:
        current = qapp.findChild(ThemeFollower)
        if current and current is not follower:
            current.stop()
            current.deleteLater()
        elif follower:
            follower.mode = mode
        qapp.setStyle(style)
        qapp.setPalette(palette)
        qapp.setStyleSheet(stylesheet)


def test_library_uses_shared_list_and_review_has_no_duplicate_list(qtbot, tmp_path, monkeypatch):
    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    window.tabs.setCurrentIndex(1)
    window.show()
    tabs = window.findChild(QTabWidget, "librarySections")
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Reseed"]
    assert not hasattr(window, "library_view")
    assert window.review.expand_button.isHidden()
    assert [window.review.details_tabs.tabText(i) for i in range(4)] == [
        "Summary",
        "Files",
        "Description",
        "NFO",
    ]


def test_desktop_review_preserves_candidate_selection_across_local_items(
    qtbot, tmp_path, monkeypatch, library_theme
):
    import os
    from pathlib import Path

    from torrentlinker.domain import ContentKind, ItemState, LibraryFolder, LocalItem
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import FileComparison, Match
    from torrentlinker.review import CheckedCandidate
    from torrentlinker.torrent_meta import TorrentMeta

    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    folder = LibraryFolder(tmp_path / "Books", 1, ContentKind.EBOOK)
    entries = [
        LibraryEntry(folder, LocalItem(folder.path / name, {name: 400}), ItemState.ORPHAN)
        for name in ("The Time Machine.epub", "The War of the Worlds.epub")
    ]
    window.settings.library_folders = [folder]
    window._fill_folder_filter()
    window.library_model.set_entries(entries)
    first = CheckedCandidate(
        Candidate(
            "The.Time.Machine.1895.EN.EPUB",
            400,
            "https://example.test/1",
            seeders=12,
            infohash="a" * 40,
        ),
        meta=TorrentMeta("The Time Machine.epub", "a" * 40, {"The Time Machine.epub": 400}, b""),
        comparison=FileComparison({"The Time Machine.epub": "The Time Machine.epub"}),
        match=Match({"The Time Machine.epub": "The Time Machine.epub"}),
    )
    second = CheckedCandidate(
        Candidate("The.Time.Machine.Collection", 900, "https://example.test/2", infohash="b" * 40)
    )
    window.review.remember(entries[0], [first, second])
    window.tabs.setCurrentIndex(1)
    window.resize(1600, 1000)
    window.show()
    window.review.set_entry(entries[0])
    window.review.candidates.selectRow(1)
    window.review.set_entry(entries[1])
    window.review.set_entry(entries[0])
    assert window.review.selected().candidate.infohash == "b" * 40
    window.review.candidates.selectRow(0)
    window.review.details_tabs.setCurrentIndex(1)
    qtbot.wait(50)
    if destination := os.getenv("TL_WEB_SCREENSHOTS"):
        Path(destination).mkdir(parents=True, exist_ok=True)
        window.grab().save(str(Path(destination) / "library-desktop.png"))
        window.library_workspace.open_folders()
        qtbot.wait(50)
        window.grab().save(str(Path(destination) / "library-desktop-folders.png"))


def test_desktop_scans_new_folders_while_client_is_offline_and_recovers(
    qtbot, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from torrentlinker.domain import ItemState, LibraryFolder

    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    # Restore the public scan operation; window_for disables it for editor tests.
    from torrentlinker.gui.main_window import MainWindow

    monkeypatch.setattr(window, "scan", lambda: MainWindow.scan(window))

    class Client:
        offline = False

        def torrents(self, **kwargs):
            if self.offline:
                raise ConnectionError("offline")
            return []

    client = Client()
    monkeypatch.setattr(window, "qbit", lambda: client)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    first, second = tmp_path / "Books", tmp_path / "Films"
    first.mkdir()
    second.mkdir()
    (first / "Book.epub").write_bytes(b"book")
    (second / "Film.mkv").write_bytes(b"film")
    window.settings.library_folders = [LibraryFolder(first)]
    window.scan()
    qtbot.waitUntil(lambda: window.scan_action.isEnabled())
    client.offline = True
    window.settings.library_folders.append(LibraryFolder(second))
    window.scan()
    qtbot.waitUntil(lambda: window.scan_action.isEnabled())
    assert {entry.item.path.name for entry in window.library_model.entries} == {
        "Book.epub",
        "Film.mkv",
    }
    assert all(entry.state is ItemState.UNKNOWN for entry in window.library_model.entries)
    client.offline = False
    window.scan()
    qtbot.waitUntil(lambda: window.scan_action.isEnabled())
    assert all(entry.state is ItemState.ORPHAN for entry in window.library_model.entries)
    assert all(
        window.library_model.data(window.library_model.index(row, 1)) != "Seeding status unknown"
        for row in range(2)
    )


def test_disconnected_folder_keeps_items_and_visible_health_warning(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from torrentlinker.domain import LibraryFolder
    from torrentlinker.gui.main_window import MainWindow

    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    folder = tmp_path / "Books"
    folder.mkdir()
    (folder / "Book.epub").write_bytes(b"book")
    window.settings.library_folders = [LibraryFolder(folder)]
    window._fill_folder_filter()

    class Client:
        def torrents(self, **kwargs):
            return []

    monkeypatch.setattr(window, "qbit", lambda: Client())
    monkeypatch.setattr(QMessageBox, "exec", lambda *args: QMessageBox.StandardButton.Ok)
    MainWindow.scan(window)
    qtbot.waitUntil(lambda: window.scan_action.isEnabled())
    folder.rename(tmp_path / "disconnected")
    MainWindow.scan(window)
    qtbot.waitUntil(lambda: window.scan_action.isEnabled())
    assert window.library_model.rowCount() == 1
    assert str(folder) in window.library_workspace.reseed.request("state", {})["folder_errors"]


def test_desktop_evidence_inspects_claims_and_keeps_the_original(
    qtbot, tmp_path, monkeypatch, library_theme
):
    import os
    from pathlib import Path

    from pymediainfo import MediaInfo

    from tests.test_upload_video import FIXTURES
    from torrentlinker.domain import ItemState, LibraryFolder
    from torrentlinker.library import LibraryEntry
    from torrentlinker.scan import scan_item

    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    video = tmp_path / "Example.1080p.WEB-DL.DDP5.1.H264-TEAM.mkv"
    video.write_bytes(b"unchanged media")
    fixture = MediaInfo(
        (FIXTURES / "film_x264_1080p_fr.xml")
        .read_text()
        .replace("1920", "1280")
        .replace("1080", "720")
    )
    monkeypatch.setattr(
        MediaInfo,
        "parse",
        lambda *args, **kwargs: "MediaInfo fixture" if "output" in kwargs else fixture,
    )
    entry = LibraryEntry(LibraryFolder(tmp_path), scan_item(video), ItemState.ORPHAN)
    window.settings.library_folders = [entry.folder]
    window._fill_folder_filter()
    window.library_model.set_entries([entry])
    window.review.set_entry(entry)
    window.tabs.setCurrentIndex(1)
    window.review.details_tabs.setCurrentIndex(4)
    window.resize(1600, 1000)
    window.show()
    qtbot.mouseClick(window.review.evidence.inspect_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "720p" in window.review.evidence.output.toPlainText(), timeout=5000)
    assert "1080p" in window.review.evidence.output.toPlainText()
    assert video.read_bytes() == b"unchanged media"
    if destination := os.getenv("TL_UI_SCREENSHOTS"):
        Path(destination).mkdir(parents=True, exist_ok=True)
        window.grab().save(str(Path(destination) / "library-features-desktop.png"))
