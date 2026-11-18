from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind, LibraryFolder
from torrentlinker.gui import main_window
from torrentlinker.store import Store


def window_for(qtbot, tmp_path, monkeypatch):
    window = main_window.MainWindow(
        Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db")
    )
    qtbot.addWidget(window)
    scans = []
    monkeypatch.setattr(window, "scan", lambda: scans.append(True))
    return window, scans


def test_library_add_folder_saves_kind_depth_and_shows_it(qtbot, tmp_path, monkeypatch):
    window, scans = window_for(qtbot, tmp_path, monkeypatch)
    folder = tmp_path / "films"
    folder.mkdir()
    window.library_workspace.reseed.request(
        "add-folder", {"local": str(folder), "kind": "movie", "depth": 2}
    )
    expected = [LibraryFolder(folder, 2, ContentKind.MOVIE)]
    assert window.settings.library_folders == expected
    assert Settings.load(window.settings_path).library_folders == expected
    assert scans == []
    window.library_workspace.reseed.request("remove-folder", {"local": str(folder)})
    assert folder.is_dir()
    assert window.settings.library_folders == []


def test_open_add_folder_does_not_save_or_scan(qtbot, tmp_path, monkeypatch):
    window, scans = window_for(qtbot, tmp_path, monkeypatch)
    window.add_folder_action.trigger()
    assert window.settings.library_folders == []
    assert not window.settings_path.exists()
    assert not scans


def test_folder_save_failure_keeps_current_settings(qtbot, tmp_path, monkeypatch):
    window, scans = window_for(qtbot, tmp_path, monkeypatch)

    def fail_save(self, path: Path):
        raise OSError("disk full")

    messages = []
    monkeypatch.setattr(Settings, "save", fail_save)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    assert not window.save_library_folders([LibraryFolder(tmp_path)], scan=False)
    assert window.settings.library_folders == []
    assert not scans
    assert "disk full" in messages[0]
