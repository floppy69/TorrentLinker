"""Library navigation and Candidate review through the desktop widgets."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QTabWidget

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


def test_candidate_review_can_expand_without_losing_the_local_item(qtbot, tmp_path, monkeypatch):
    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    window.tabs.setCurrentIndex(1)
    window.library_workspace.sections.setCurrentWidget(window.library_workspace.explorer)
    window.show()
    tabs = window.findChild(QTabWidget, "librarySections")
    assert tabs is not None
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Local Items",
        "Reseed",
    ]
    expand = window.findChild(QPushButton, "expandCandidateReview")
    assert expand is not None
    qtbot.mouseClick(expand, Qt.MouseButton.LeftButton)
    assert not window.library_view.isVisible()
    assert window.review.isVisible()
    qtbot.mouseClick(expand, Qt.MouseButton.LeftButton)
    assert window.library_view.isVisible()
    assert [window.review.details_tabs.tabText(i) for i in range(4)] == [
        "Summary",
        "Files",
        "Description",
        "NFO",
    ]


def test_short_review_dialog_scrolls_instead_of_crushing_the_review(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QScrollArea

    from torrentlinker.domain import ContentKind, ItemState, LibraryFolder, LocalItem
    from torrentlinker.library import LibraryEntry

    window, _ = window_for(qtbot, tmp_path, monkeypatch)
    entry = LibraryEntry(
        LibraryFolder(tmp_path, 1, ContentKind.EBOOK),
        LocalItem(tmp_path / "Book.epub", {"Book.epub": 400}),
        ItemState.ORPHAN,
    )
    window.library_model.set_entries([entry])
    window.resize(1400, 700)
    window.tabs.setCurrentIndex(1)
    window.show()
    workspace = window.library_workspace

    def inspect_dialog(dialog):
        dialog.resize(1100, 700)
        dialog.show()
        qtbot.waitExposed(dialog)
        scroll = dialog.findChild(QScrollArea)
        assert scroll is not None
        review = window.review.height()
        assert review >= window.review.minimumSizeHint().height()
        for height in (400, 600, 900):
            workspace.grip.resize_pane(height)
            qtbot.waitUntil(lambda: workspace.items.geometry().bottom() < workspace.grip.y())
            assert workspace.grip.geometry().bottom() < window.review.y()
            assert window.review.height() >= review
        assert window.library_view.height() > 800
        assert scroll.verticalScrollBar().maximum() > 0
        workspace.grip.resize_pane(0)
        assert workspace.items.height() == workspace.items.minimumSizeHint().height()
        dialog.resize(1400, 1400)
        qtbot.waitUntil(lambda: window.review.height() > 600)
        dialog.close()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", inspect_dialog)
    workspace.open_review(str(entry.item.path))
    assert workspace.sections.currentWidget() is workspace.reseed


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
    window.library_view.selectRow(0)
    window.review.candidates.selectRow(1)
    window.library_view.selectRow(1)
    window.library_view.selectRow(0)
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
    assert "Scan incomplete" in window.library_workspace.rail.item(1).text()
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
        qtbot.mouseClick(window.review.expand_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: not window.library_view.isVisible())
        assert not window.library_workspace.combine.isVisible()
        qtbot.wait(100)  # allow queued Qt layout requests before grabbing the rendered panel
        window.grab().save(str(Path(destination) / "library-evidence-desktop-expanded.png"))


def test_desktop_repair_requires_experimental_opt_in(qtbot, tmp_path, library_theme):
    import os
    import threading
    from pathlib import Path

    from tests.fake_qbit import FakeQbit
    from tests.torrents import make_torrent
    from torrentlinker.gui.repair_dialog import RepairDialog
    from torrentlinker.indexer import Candidate
    from torrentlinker.repair import Repairs
    from torrentlinker.scan import scan_item

    video = tmp_path / "Example.mkv"
    video.write_bytes(b"A" * 1024 * 1024)
    data = make_torrent(video)
    video.write_bytes(b"B" * 128 + b"A" * (1024 * 1024 - 128))
    repository = Repairs(tmp_path, "test")
    repository.diagnose(
        scan_item(video),
        Candidate("Example", video.stat().st_size, "https://example.invalid", seeders=2),
        data,
        threading.Event(),
    )
    dialog = RepairDialog(None, repository, FakeQbit())
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.prepare_button.isEnabled()
    qtbot.mouseClick(dialog.experimental, Qt.MouseButton.LeftButton)
    assert dialog.prepare_button.isEnabled()
    assert not dialog.start_button.isEnabled()
    if destination := os.getenv("TL_UI_SCREENSHOTS"):
        dialog.grab().save(str(Path(destination) / "library-repair-desktop.png"))
