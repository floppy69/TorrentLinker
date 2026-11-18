"""Real symlinks and torrent hashes through the shared desktop/web workflow."""

import hashlib
import os
import threading
from pathlib import Path

import pytest

from tests.fake_qbit import FakeQbit
from tests.torrents import make_torrent
from torrentlinker.domain import ContentKind, ItemState, LibraryFolder, PathMapping
from torrentlinker.indexer import Candidate
from torrentlinker.library import LibraryEntry, indexer_contents
from torrentlinker.matching import Match, match
from torrentlinker.paths import PathMapper
from torrentlinker.reconcile import classify
from torrentlinker.reseed_links import prepare_links, validate_links
from torrentlinker.reseed_workspace import ReseedWorkspace
from torrentlinker.review import remember_candidates
from torrentlinker.scan import scan_item
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.web.jobs import JobStop
from torrentlinker.web.library import Library
from torrentlinker.web.security import ServerSecrets
from torrentlinker.web.setup import Setup


class CheckingClient(FakeQbit):
    outcome = 1.0

    def recheck(self, hash):
        super().recheck(hash)
        self.polls = 0

    def torrent(self, hash, **kwargs):
        if (
            hash in self.by_hash
            and hash in self.rechecked
            and self.by_hash[hash].state == "checkingUP"
        ):
            self.polls += 1
            if self.polls >= 2:
                self.finish_check(hash, self.outcome)
        return super().torrent(hash, **kwargs)


def workspace(tmp_path, client=None, filename="Été - mon film.mkv"):
    config, library_root, links = (tmp_path / name for name in ("config", "Library", "Links"))
    for directory in (config, library_root, links):
        directory.mkdir()
    original = library_root / filename
    original.write_bytes(b"original content" * 5000)
    release = tmp_path / "Release.mkv"
    release.write_bytes(original.read_bytes())
    data = make_torrent(release)
    release.unlink()
    meta = read_torrent(data)
    client = client or CheckingClient()
    setup = Setup(config, (library_root, links), ServerSecrets(config), lambda *args: client)
    setup.configured = True
    folder = LibraryFolder(library_root, 1, ContentKind.MOVIE)
    setup.settings.library_folders = [folder]
    setup.secrets.update({"indexer-api-key": "fixture-key"})
    indexer = setup.indexer()
    candidate = Candidate(
        meta.name,
        original.stat().st_size,
        "https://c411.org/download/fixture",
        infohash=meta.infohash,
    )
    remember_candidates(setup.store, indexer, original, [candidate])
    setup.store.cache_torrent(
        hashlib.sha1(indexer.redact(candidate.download_url).encode()).hexdigest(), data
    )
    library = Library(setup)
    library.entries = [LibraryEntry(folder, scan_item(original), ItemState.ORPHAN)]
    return ReseedWorkspace(library), client, original, links, meta


def run(board, original, links, action="all", stop=None, report=lambda _: None):
    return board.run([str(original)], action, str(links), stop or JobStop(), report)


def test_all_steps_use_links_and_seed_without_renaming_sources(tmp_path):
    board, client, original, links, meta = workspace(tmp_path)
    before = original.read_bytes(), original.stat().st_ino
    phases = []
    result = run(board, original, links, report=lambda p: phases.append(p["phase"]))
    assert not result["errors"], result
    assert result["seeded"] == 1
    row = result["rows"][0]
    assert row["stage"] == "seeding"
    link = Path(row["destination"]) / "Release.mkv"
    assert link.is_symlink() and link.resolve() == original
    assert (original.read_bytes(), original.stat().st_ino) == before
    assert not any("rename" in c for c in client.calls)
    assert client.started == [meta.infohash]
    assert {"find", "compare", "prepare", "local-hash", "client-hash", "seed"} <= set(phases)
    assert board.setup.store.for_client("another").reseed_records() == {}
    # The Library recognizes the original as seeded after restart/rescan.
    client._set(meta.infohash, tracker="https://c411.org/announce")
    torrents = indexer_contents(client, board.setup.store, "https://c411.org/api/torznab")
    assert classify([scan_item(original)], torrents)[original] == ItemState.SEEDED
    assert ReseedWorkspace(board.library).rows()[0]["stage"] == "seeding"


def test_pause_then_cancel_keeps_prepared_links_and_can_resume(tmp_path):
    board, client, original, links, _meta = workspace(tmp_path)
    stop, prepared = JobStop(), threading.Event()
    result = []

    def report(p):
        if p["phase"] == "prepare" and p.get("rows"):
            stop.paused.set()
            prepared.set()

    worker = threading.Thread(
        target=lambda: result.append(run(board, original, links, stop=stop, report=report))
    )
    worker.start()
    assert prepared.wait(5)
    assert not client.by_hash and not client.started
    stop.set()
    worker.join(5)
    assert not worker.is_alive()
    assert result[0]["cancelled"]
    destination = result[0]["rows"][0]["destination"]
    resumed = run(ReseedWorkspace(board.library), original, links)
    assert resumed["seeded"] == 1, resumed
    assert resumed["rows"][0]["destination"] == destination


def test_bad_source_hash_never_reaches_the_client(tmp_path):
    board, client, original, links, _meta = workspace(tmp_path)
    original.write_bytes(b"x" * original.stat().st_size)
    result = run(board, original, links)
    assert result["errors"] and not client.by_hash and not client.started
    assert original.read_bytes() == b"x" * original.stat().st_size


def test_failed_client_check_keeps_sources_and_never_seeds(tmp_path):
    client = CheckingClient()
    client.outcome = 0.0
    board, _, original, links, meta = workspace(tmp_path, client)
    before = original.read_bytes()
    result = run(board, original, links)
    assert result["errors"] and result["rows"][0]["stage"] == "incomplete"
    assert client.removed == [(meta.infohash, False)] and not client.started
    assert original.read_bytes() == before


def test_link_targets_use_client_mappings_and_validation_reads_originals(tmp_path):
    board, _, original, links, meta = workspace(tmp_path)
    item = scan_item(original)
    mapping = PathMapper([PathMapping(str(original.parent), "/client/library")])
    layout = prepare_links(links, item, meta, match(item, meta.files), mapping, [original.parent])
    link = Path(layout["destination"]) / "Release.mkv"
    assert os.readlink(link) == "/client/library/Été - mon film.mkv"
    validate_links(layout)  # the mapped absolute link is intentionally dangling locally
    link.unlink()
    link.symlink_to("/somewhere-else")
    with pytest.raises(ValueError, match="removed or changed"):
        validate_links(layout)


@pytest.mark.parametrize("unsafe", ["../escape", "/absolute", "dir/../../escape", "C:\\file"])
def test_unsafe_torrent_paths_do_not_create_any_layout(tmp_path, unsafe):
    board, _, original, links, meta = workspace(tmp_path)
    from dataclasses import replace

    item = scan_item(original)
    meta = replace(meta, files={unsafe: item.size})
    with pytest.raises(ValueError, match="Unsafe"):
        prepare_links(
            links, item, meta, Match({unsafe: original.name}), PathMapper([]), [original.parent]
        )
    assert list(links.iterdir()) == []


def test_link_folder_inside_library_and_symlink_roots_are_refused(tmp_path):
    board, _, original, links, meta = workspace(tmp_path)
    item = scan_item(original)
    found = match(item, meta.files)
    with pytest.raises(ValueError, match="outside"):
        prepare_links(original.parent, item, meta, found, PathMapper([]), [original.parent])
    alias = tmp_path / "alias"
    alias.symlink_to(links, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        prepare_links(alias, item, meta, found, PathMapper([]), [original.parent])


def test_changed_source_cannot_start_after_manual_verification(tmp_path):
    board, client, original, links, _meta = workspace(tmp_path)
    for action in ("find", "compare", "prepare", "verify"):
        result = run(board, original, links, action)
        assert not result["errors"], result
    assert result["rows"][0]["status"] == "verified" and not client.started
    original.write_bytes(b"z" * original.stat().st_size)
    result = run(board, original, links, "seed")
    assert result["errors"] and not client.started


def test_refresh_recovers_after_client_removal_without_moving_originals(tmp_path):
    board, client, original, links, meta = workspace(tmp_path)
    assert run(board, original, links)["seeded"] == 1
    destination = board.rows()[0]["destination"]
    client.remove(meta.infohash)
    refreshed = board.refresh_client()
    assert refreshed["rows"][0]["stage"] == "verify"
    assert refreshed["rows"][0]["status"] == "prepared"
    assert run(board, original, links)["seeded"] == 1
    assert board.rows()[0]["destination"] == destination


def test_foreign_torrent_is_never_adopted_removed_or_started(tmp_path):
    board, client, original, links, meta = workspace(tmp_path)
    client.add(meta.data, str(tmp_path / "foreign"), [])
    result = run(board, original, links)
    assert result["errors"] and not client.started and not client.removed
    assert client.torrent(meta.infohash).save_path == tmp_path / "foreign"


def test_linked_torrents_cannot_download_or_delete_through_management(tmp_path):
    from torrentlinker.torrent_management import manage

    board, client, original, links, meta = workspace(tmp_path)
    assert run(board, original, links)["seeded"] == 1
    assert manage(client, [meta.infohash], "delete")[0].outcome == "failed"
    assert manage(client, [meta.infohash], "want_files", file_indexes=[0])[0].outcome == "failed"
    client._set(meta.infohash, progress=0.2)
    starts = list(client.started)
    assert manage(client, [meta.infohash], "resume")[0].outcome == "verifying"
    assert client.started == starts and original.exists()


def test_other_items_compare_while_one_item_is_verifying(tmp_path):
    """A slow disk check must not hold up another item's candidate work."""
    board, client, original, links, meta = workspace(tmp_path)
    other = original.with_name("Another movie.mkv")
    other.write_bytes(original.read_bytes())
    folder = board.library.entries[0].folder
    board.library.entries.append(LibraryEntry(folder, scan_item(other), ItemState.ORPHAN))
    candidate = Candidate(
        meta.name, other.stat().st_size, "https://c411.org/download/fixture", infohash=meta.infohash
    )
    remember_candidates(board.setup.store, board.setup.indexer(), other, [candidate])
    hashing = threading.Event()
    compared = threading.Event()
    stop = JobStop()
    observed = []

    def report(p):
        observed.append(p)
        if p["path"] == str(original) and p["phase"] == "local-hash":
            hashing.set()
            assert compared.wait(3), "Candidate work blocked behind another item's hash check"
            stop.set()
        if p["path"] == str(other) and p["phase"] == "compare":
            assert hashing.wait(3), "First item did not reach verification"
            compared.set()

    result = board.run([str(original), str(other)], "all", str(links), stop, report)
    assert hashing.is_set() and compared.is_set(), result
    assert any(len(p.get("active", {})) > 1 for p in observed)


def test_paused_item_does_not_block_others_and_can_resume(tmp_path):
    board, client, original, links, meta = workspace(tmp_path)

    second = original.with_name("Second.mkv")
    second.write_bytes(original.read_bytes())
    entry = board.library.entries[0]
    board.library.entries.append(LibraryEntry(entry.folder, scan_item(second), ItemState.ORPHAN))
    candidate = Candidate(
        meta.name,
        second.stat().st_size,
        "https://c411.org/download/fixture",
        infohash=meta.infohash,
    )
    remember_candidates(board.setup.store, board.setup.indexer(), second, [candidate])
    board.control([str(original)], paused=True)
    stop = JobStop()
    saw_pause = []

    def progress(value):
        if value.get("path") == str(second) and value.get("phase") == "item-complete":
            saw_pause.append(str(original) in value["paused_paths"])
            board.control([str(original)], paused=False)

    result = board.run([str(original), str(second)], "find", str(links), stop, progress)
    assert result["done"] == 2
    assert saw_pause and saw_pause[0]


def test_scan_during_run_admits_new_items_without_restarting_library(tmp_path):
    board, client, original, links, meta = workspace(tmp_path)
    second = original.with_name("Newly discovered.mkv")
    stop = JobStop()
    scans = []

    def progress(value):
        if value["phase"] == "find" and not second.exists():
            second.write_bytes(original.read_bytes())
            board.request_scan()
        if value.get("scan_complete"):
            scans.append(value)
            stop.set()

    result = board.run([str(original)], "all", str(links), stop, progress)
    assert scans
    assert str(second) in {row["path"] for row in scans[0]["rows"]}
    assert result["total"] == 2
    assert result["cancelled"]


def test_missing_item_does_not_abort_other_items(tmp_path):
    board, client, original, links, meta = workspace(tmp_path)
    result = board.run(
        [str(tmp_path / "gone"), str(original)], "all", str(links), JobStop(), lambda p: None
    )
    assert result["done"] == 2
    assert len(result["errors"]) == 1
    assert client.started == [meta.infohash]


def test_completed_item_can_rejoin_the_active_run(tmp_path):
    board, _, original, links, _ = workspace(tmp_path)
    reports = []

    def progress(value):
        if value["phase"] == "item-complete":
            reports.append(value)
            if len(reports) == 1:
                board.enqueue([str(original)])

    result = board.run([str(original)], "find", str(links), JobStop(), progress)
    assert len(reports) == 2
    assert result["done"] == result["total"] == 1


def test_failed_scan_reports_error_and_other_item_still_seeds(tmp_path):
    board, client, original, links, meta = workspace(tmp_path)
    requested = []
    errors = []

    def progress(value):
        if value["phase"] == "find" and not requested:
            requested.append(True)
            (original.parent / "unsafe-link").symlink_to(original)
            board.request_scan()
        errors.extend(value.get("errors", []))

    result = board.run([str(original)], "all", str(links), JobStop(), progress)
    assert result["errors"] and errors
    assert "symbolic links" in result["errors"][0]["message"]
    assert client.started == [meta.infohash]


def test_selected_folder_scan_preserves_other_registered_folders_only(tmp_path):
    board, _, original, _, _ = workspace(tmp_path)
    extra = tmp_path / "Other"
    extra.mkdir()
    file = extra / "Book.epub"
    file.write_bytes(b"book")
    folder = LibraryFolder(extra, 1, ContentKind.EBOOK)
    board.setup.settings.library_folders.append(folder)
    board.library.entries.append(LibraryEntry(folder, scan_item(file), ItemState.ORPHAN))
    board.library.scan(JobStop(), lambda p: None, [str(original.parent)])
    assert file in {e.item.path for e in board.library.entries}
    board.setup.settings.library_folders.remove(folder)
    board.library.scan(JobStop(), lambda p: None)
    assert file not in {e.item.path for e in board.library.entries}
