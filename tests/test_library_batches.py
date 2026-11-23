from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from zipfile import ZipFile

from PySide6.QtWidgets import QDialog, QMessageBox

from tests.fake_qbit import FakeQbit
from tests.torrents import make_torrent
from torrentlinker.config import Settings
from torrentlinker.domain import ItemState, LibraryFolder
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.gui.reseed_dialog import ReseedDialog
from torrentlinker.indexer import Candidate
from torrentlinker.library import LibraryEntry
from torrentlinker.matching import Match, MatchRules
from torrentlinker.review import CheckedCandidate, check_candidate
from torrentlinker.scan import scan_item
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent


def setup(qtbot, tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    window = MainWindow(Settings(), tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    client = FakeQbit()
    monkeypatch.setattr(window, "qbit", lambda: client)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    path = tmp_path / "model.stl"
    path.write_bytes(b"model data" * 100)
    data = make_torrent(path)
    meta = read_torrent(data)
    candidate = Candidate(
        "Model", path.stat().st_size, "https://example.test/model", infohash=meta.infohash
    )
    indexer = SimpleNamespace(fetch_torrent=lambda c: data)
    monkeypatch.setattr(window, "indexer", lambda: indexer)
    entry = LibraryEntry(LibraryFolder(tmp_path), scan_item(path), ItemState.ORPHAN)
    checked = check_candidate(indexer, entry.item, candidate, MatchRules())
    window.library_model.set_entries([entry])
    return window, client, entry, checked, data


def finish(qtbot, window):
    qtbot.waitUntil(lambda: window.batch is None, timeout=5000)
    assert window.check_all_action.isEnabled()
    assert window.reseed_all_action.isEnabled()


def test_check_all_uses_untested_candidates_without_selection_and_preserves_checked(
    qtbot, tmp_path, monkeypatch
):
    window, _, entry, checked, data = setup(qtbot, tmp_path, monkeypatch)
    pending = CheckedCandidate(replace(checked.candidate, title="Untested", infohash="aa" * 20))
    rejected = CheckedCandidate(replace(checked.candidate, title="Rejected", infohash="bb" * 20))
    window.store.reject(entry.item.path, rejected.candidate.infohash, "user")
    window.review.remember(entry, [checked, pending, rejected])
    window.library_workspace.reseed.selected_paths = []
    calls = []
    monkeypatch.setattr(
        window,
        "indexer",
        lambda: SimpleNamespace(fetch_torrent=lambda c: calls.append(c.title) or data),
    )
    window.check_all_action.trigger()
    assert not window.reseed_all_action.isEnabled()
    finish(qtbot, window)
    assert calls == ["Untested"]
    results = window.review.cache[entry.item.path]
    assert results[0] is checked
    assert len(results) == 2 and results[1].match.is_full


def test_check_continues_after_one_candidate_fails(qtbot, tmp_path, monkeypatch):
    window, _, entry, checked, data = setup(qtbot, tmp_path, monkeypatch)
    bad = replace(checked.candidate, title="Broken", infohash="aa" * 20)
    window.review.remember(entry, [CheckedCandidate(bad), CheckedCandidate(checked.candidate)])

    def fetch(candidate):
        if candidate.title == "Broken":
            raise RuntimeError("download failed")
        return data

    monkeypatch.setattr(window, "indexer", lambda: SimpleNamespace(fetch_torrent=fetch))
    window.check_all_action.trigger()
    finish(qtbot, window)
    results = window.review.cache[entry.item.path]
    assert not results[0].compared and results[1].match.is_full
    assert len(window._batch_errors) == 1


def test_cancel_check_keeps_completed_results_and_skips_remaining(qtbot, tmp_path, monkeypatch):
    window, _, entry, checked, data = setup(qtbot, tmp_path, monkeypatch)
    second = replace(checked.candidate, title="Second", infohash="aa" * 20)
    window.review.remember(entry, [CheckedCandidate(checked.candidate), CheckedCandidate(second)])
    entered, release = Event(), Event()
    calls = []

    def fetch(candidate):
        calls.append(candidate.title)
        entered.set()
        release.wait(5)
        return data

    monkeypatch.setattr(window, "indexer", lambda: SimpleNamespace(fetch_torrent=fetch))
    window.check_all_action.trigger()
    try:
        qtbot.waitUntil(entered.is_set)
        window.cancel_action.trigger()
    finally:
        release.set()
    finish(qtbot, window)
    assert calls == [checked.candidate.title]
    results = window.review.cache[entry.item.path]
    assert results[0].compared and not results[1].compared
    assert "cancelled" in window.statusBar().currentMessage()


def test_reseed_all_only_adds_full_matches_once_and_starts_verification(
    qtbot, tmp_path, monkeypatch
):
    window, client, entry, checked, _ = setup(qtbot, tmp_path, monkeypatch)
    partial = replace(checked, match=Match({}, ("missing",), (), 0.5))
    window.review.remember(entry, [checked, checked, partial, CheckedCandidate(checked.candidate)])
    window.reseed_all_action.trigger()
    finish(qtbot, window)
    assert client.rechecked == [checked.meta.infohash]
    assert client.started == []
    assert window.store.verification(checked.meta.infohash) is not None
    assert window.verify_timer.isActive()
    assert window._batch_reseeded == 1
    # A second click cannot add a torrent already verifying.
    window.reseed_all_action.trigger()
    finish(qtbot, window)
    assert client.rechecked == [checked.meta.infohash]
    assert not window._batch_errors


def test_archive_preflight_routes_to_existing_unpack_confirmation(qtbot, tmp_path, monkeypatch):
    window, client, entry, checked, data = setup(qtbot, tmp_path, monkeypatch)
    archive = tmp_path / "model.zip"
    with ZipFile(archive, "w") as z:
        z.write(entry.item.path, entry.item.path.name)
    archived_entry = replace(entry, item=scan_item(archive))
    archived = check_candidate(
        SimpleNamespace(fetch_torrent=lambda c: data),
        archived_entry.item,
        checked.candidate,
        MatchRules(),
    )
    assert archived.unpack is not None and archived.match.is_full
    window.library_model.set_entries([archived_entry])
    window.review.remember(archived_entry, [archived])
    reviewed = []
    monkeypatch.setattr(window.review, "_unpack_and_reseed", lambda e, v: reviewed.append((e, v)))

    def choose(dialog):
        assert dialog.items.topLevelItemCount() == 1
        assert not dialog.ready_button.isEnabled()
        dialog.unpack_button.click()
        return dialog.result()

    monkeypatch.setattr(ReseedDialog, "exec", choose)
    window.reseed_all_action.trigger()
    assert reviewed == [(archived_entry, archived)]
    assert not archived.unpack.item.path.exists()
    assert not client.by_hash


def test_archive_preflight_can_cancel_or_send_only_ready_matches(qtbot, tmp_path, monkeypatch):
    window, client, entry, checked, data = setup(qtbot, tmp_path, monkeypatch)
    archive = tmp_path / "model.zip"
    with ZipFile(archive, "w") as z:
        z.write(entry.item.path, entry.item.path.name)
    archived_entry = replace(entry, item=scan_item(archive))
    archived = check_candidate(
        SimpleNamespace(fetch_torrent=lambda c: data),
        archived_entry.item,
        checked.candidate,
        MatchRules(),
    )
    window.library_model.set_entries([entry, archived_entry])
    window.review.remember(entry, [checked])
    window.review.remember(archived_entry, [archived])
    monkeypatch.setattr(ReseedDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window.reseed_all_action.trigger()
    assert window.batch is None and not client.by_hash
    monkeypatch.setattr(ReseedDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window.reseed_all_action.trigger()
    finish(qtbot, window)
    assert client.rechecked == [checked.meta.infohash]
    assert not archived.unpack.item.path.exists()


def test_reseed_check_reseed_preserves_finished_status_and_adds_new_matches(
    qtbot, tmp_path, monkeypatch
):
    from torrentlinker.reseed import check_verifications, pending_verifications

    window, client, entry, checked, _ = setup(qtbot, tmp_path, monkeypatch)
    window.review.remember(entry, [checked])
    window.reseed_all_action.trigger()
    finish(qtbot, window)
    client.finish_check(checked.meta.infohash, 1.0)
    window._verified(
        (check_verifications(client, window.store), pending_verifications(client, window.store))
    )
    assert not window.verify_timer.isActive()

    path = tmp_path / "new-model.stl"
    path.write_bytes(b"different model" * 100)
    data = make_torrent(path)
    meta = read_torrent(data)
    new_entry = replace(entry, item=scan_item(path))
    new_candidate = Candidate(
        "New model", path.stat().st_size, "https://example.test/new", infohash=meta.infohash
    )
    window.library_model.set_entries([entry, new_entry])
    window.review.remember(new_entry, [CheckedCandidate(new_candidate)])
    monkeypatch.setattr(window, "indexer", lambda: SimpleNamespace(fetch_torrent=lambda c: data))
    window.check_all_action.trigger()
    finish(qtbot, window)
    assert window.library_model.status[entry.item.path] == "Reseeded"
    window.reseed_all_action.trigger()
    finish(qtbot, window)
    assert client.rechecked == [checked.meta.infohash, meta.infohash]
    assert window._batch_reseeded == 1
    assert window._batch_existing == 1
    assert window.library_model.status[entry.item.path] == "Already in torrent client"
    assert window.library_model.status[new_entry.item.path] == "Verifying…"


def test_reseed_again_after_verification_does_not_claim_verification_continues(
    qtbot, tmp_path, monkeypatch
):
    from torrentlinker.reseed import check_verifications

    window, client, entry, checked, _ = setup(qtbot, tmp_path, monkeypatch)
    window.review.remember(entry, [checked])
    window.reseed_all_action.trigger()
    finish(qtbot, window)
    client.finish_check(checked.meta.infohash, 1.0)
    window._verified((check_verifications(client, window.store), []))
    window.reseed_all_action.trigger()
    finish(qtbot, window)
    assert "verification continues" not in window.statusBar().currentMessage()
    assert "already" in window.statusBar().currentMessage().lower()
    assert window.library_model.status[entry.item.path] == "Already in torrent client"
