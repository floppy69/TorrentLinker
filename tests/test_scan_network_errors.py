from pathlib import Path

from torrentlinker.domain import LibraryFolder
from torrentlinker.scan import scan


def test_network_error_on_entry_keeps_healthy_items(tmp_path, monkeypatch):
    good = tmp_path / "healthy.mkv"
    bad = tmp_path / ".movie.mkv.vWcFP6"
    good.write_bytes(b"good")
    bad.write_bytes(b"bad")
    original = Path.stat

    def stat(path, *args, **kwargs):
        if path == bad:
            error = OSError(59, "Erreur réseau inattendue", str(path))
            error.winerror = 59
            raise error
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    result = scan(LibraryFolder(tmp_path))
    assert [item.path for item in result] == [good]
    assert result.errors[0].path == bad
    assert "59" in result.errors[0].message


def test_unreadable_root_is_partial_not_empty_success(tmp_path, monkeypatch):
    original = Path.iterdir

    def iterdir(path):
        if path == tmp_path:
            raise PermissionError(13, "Access denied", str(path))
        return original(path)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    result = scan(LibraryFolder(tmp_path))
    assert result == []
    assert result.errors[0].path == tmp_path


def test_directory_network_error_preserves_previous_subtree(tmp_path, monkeypatch):
    import os

    from torrentlinker.domain import ItemState
    from torrentlinker.library import LibraryEntry, build_library
    from torrentlinker.store import Store

    folder = LibraryFolder(tmp_path / "lib")
    show = folder.path / "Show"
    show.mkdir(parents=True)
    (show / "ep.mkv").write_bytes(b"episode")
    good = folder.path / "good.mkv"
    good.write_bytes(b"good")
    store = Store(tmp_path / "state.db")
    first = build_library([folder], [], cache=store)
    from torrentlinker.scan import _signature

    signature = _signature(show)
    old = next(e for e in first if e.item.path == show)
    # Retain the Torrent Client's known state, rather than classify an incomplete item.
    old = LibraryEntry(folder, old.item, ItemState.SEEDED, frozenset({"a"}))
    original = os.scandir

    def scandir(path):
        if Path(path) == show:
            error = OSError(59, "Erreur réseau inattendue", str(path))
            error.winerror = 59
            raise error
        return original(path)

    monkeypatch.setattr(os, "scandir", scandir)
    result = build_library([folder], [], cache=store, refresh=True, previous=[old])
    assert {e.item.path for e in result} == {show, good}
    assert old in result
    assert len(result.errors) == 1
    assert result.errors[0].path == show
    monkeypatch.setattr(os, "scandir", original)
    # A failed refresh must not overwrite the previous complete cache.
    assert store.cached_scan(show, signature) == {"Show/ep.mkv": 7}


def test_disappearing_file_is_reported_and_other_items_survive(tmp_path, monkeypatch):
    good = tmp_path / "good.mkv"
    gone = tmp_path / "gone.mkv"
    good.write_bytes(b"good")
    gone.write_bytes(b"gone")
    original = Path.stat

    def stat(path, *args, **kwargs):
        if path == gone:
            raise FileNotFoundError(2, "File disappeared", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    result = scan(LibraryFolder(tmp_path))
    assert [item.path for item in result] == [good]
    assert result.errors[0].path == gone


def test_healthy_hidden_file_is_not_excluded(tmp_path):
    path = tmp_path / ".movie.mkv"
    path.write_bytes(b"film")
    result = scan(LibraryFolder(tmp_path))
    assert [item.path for item in result] == [path]
    assert result.errors == []


def test_unavailable_root_preserves_previous_library(tmp_path, monkeypatch):
    from torrentlinker.library import build_library

    path = tmp_path / "old.mkv"
    path.write_bytes(b"old")
    folder = LibraryFolder(tmp_path)
    previous = build_library([folder], [])

    def denied(path):
        raise PermissionError(13, "Access denied", str(path))

    monkeypatch.setattr(Path, "iterdir", denied)
    result = build_library([folder], [], previous=previous)
    assert result == previous
    assert result.errors[0].path == tmp_path


def test_web_partial_scan_keeps_previous_entries_and_cancellation(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    from torrentlinker.config import Settings
    from torrentlinker.library import build_library
    from torrentlinker.store import Store
    from torrentlinker.web import library as web_library
    from torrentlinker.web.setup import StorageUnavailableError

    bad = tmp_path / "bad"
    good = tmp_path / "good"
    bad.mkdir()
    good.mkdir()
    (bad / "old.mkv").write_bytes(b"old")
    (good / "healthy.mkv").write_bytes(b"healthy")
    folders = [LibraryFolder(bad), LibraryFolder(good)]
    setup = SimpleNamespace(
        settings=Settings(library_folders=folders), store=Store(tmp_path / "s.db")
    )
    library = web_library.Library(setup)
    library.entries = build_library(folders[:1], [])
    monkeypatch.setattr(library, "client", lambda: None)
    monkeypatch.setattr(web_library, "indexer_contents", lambda *args, **kwargs: [])

    def check(path, stop):
        if path == bad:
            raise StorageUnavailableError("Network error 59")

    monkeypatch.setattr(library, "check_tree", check)
    result = library.scan(threading.Event(), lambda value: None)
    assert result["partial"] is True
    assert result["errors"][0]["path"] == str(bad)
    assert {entry.item.path.name for entry in library.entries} == {"old.mkv", "healthy.mkv"}
    previous = list(library.entries)
    stop = threading.Event()

    def progress(value):
        stop.set()

    assert library.scan(stop, progress) == {"cancelled": True}
    assert library.entries == previous


def test_desktop_partial_scan_reports_error_and_preserves_seeded_item(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from tests.fake_qbit import FakeQbit
    from torrentlinker.config import Settings
    from torrentlinker.domain import ItemState, LocalItem
    from torrentlinker.gui import main_window
    from torrentlinker.library import LibraryEntry
    from torrentlinker.store import Store

    bad = tmp_path / "bad.mkv"
    good = tmp_path / "healthy.mkv"
    bad.write_bytes(b"bad")
    good.write_bytes(b"healthy")
    folder = LibraryFolder(tmp_path)
    window = main_window.MainWindow(
        Settings(library_folders=[folder]), tmp_path / "settings.json", Store(tmp_path / "s.db")
    )
    qtbot.addWidget(window)
    old = LibraryEntry(folder, LocalItem(bad, {"bad.mkv": 3}), ItemState.SEEDED, frozenset({"a"}))
    window.library_model.set_entries([old])
    monkeypatch.setattr(window, "qbit", lambda: FakeQbit())
    monkeypatch.setattr(window, "restore_searches", lambda entries: None)
    original = Path.stat

    def stat(path, *args, **kwargs):
        if path == bad:
            raise OSError(59, "Unexpected network error", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    messages = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: messages.append(box.detailedText()))
    window.scan()
    qtbot.waitUntil(lambda: bool(messages))
    assert str(bad) in messages[0]
    assert old in window.library_model.entries
    assert any(e.item.path == good for e in window.library_model.entries)
    assert "incomplete" in window.statusBar().currentMessage()
    assert window.scan_action.isEnabled()


def test_depth_traversal_directory_network_error_preserves_only_failed_subtree(
    tmp_path, monkeypatch
):
    from torrentlinker.library import build_library

    bad = tmp_path / "bad"
    good = tmp_path / "good"
    bad.mkdir()
    good.mkdir()
    (bad / "old.mkv").write_bytes(b"old")
    (good / "healthy.mkv").write_bytes(b"healthy")
    folder = LibraryFolder(tmp_path, depth=2)
    previous = build_library([folder], [])
    original = Path.iterdir
    attempts = []

    def iterdir(path):
        if path == bad:
            attempts.append(path)
            error = OSError(59, "Erreur réseau inattendue", str(path))
            error.winerror = 59
            raise error
        return original(path)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    result = build_library([folder], [], previous=previous)
    assert {e.item.path for e in result} == {bad / "old.mkv", good / "healthy.mkv"}
    assert result.errors[0].path == bad
    assert attempts == [bad]


def test_partial_web_job_status_and_client_are_preserved(tmp_path):
    from torrentlinker.web.jobs import Jobs

    jobs = Jobs(tmp_path)
    try:
        identifier = jobs.submit("scan", lambda stop, progress: {"partial": True}, client_id="nas")
        jobs.executor.shutdown(wait=True)
        result = jobs.get(identifier)
        assert result["status"] == "partial"
        assert result["client_id"] == "nas"
        assert result["result"]["partial"] is True
    finally:
        jobs.close()


def test_planning_requires_complete_scan(tmp_path, monkeypatch):
    import pytest

    def denied(path):
        raise PermissionError(13, "Access denied", str(path))

    monkeypatch.setattr(Path, "iterdir", denied)
    result = scan(LibraryFolder(tmp_path))
    with pytest.raises(OSError, match="Scan incomplete"):
        result.require_complete()


def test_web_preflight_cancellation_keeps_previous_entries(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    from torrentlinker.config import Settings
    from torrentlinker.web.library import Library

    library = Library(SimpleNamespace(settings=Settings(library_folders=[LibraryFolder(tmp_path)])))
    previous = library.entries
    stop = threading.Event()

    def cancel(path, event):
        event.set()
        raise ValueError("Scan cancelled.")

    monkeypatch.setattr(library, "check_tree", cancel)
    assert library.scan(stop, lambda value: None) == {"cancelled": True}
    assert library.entries is previous
