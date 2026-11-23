"""Reseed and Plan against a real Transmission. Opt-in: point TL_TRANSMISSION_SANDBOX at a
throwaway Transmission, and TL_TRANSMISSION_DATA at a folder it sees at the same path
(see scripts/transmission_sandbox.py). Every torrent added is removed at the end, data
kept. Library files are checked to be unchanged, and never renamed to .part.
"""

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.test_qbit_integration import digest, library_with_ebook, scene_torrent, settle
from tests.torrents import make_torrent
from torrentlinker.domain import ItemState, LibraryFolder
from torrentlinker.matching import match
from torrentlinker.reconcile import classify
from torrentlinker.reseed import PARTIAL, TAG, VERIFYING, ReseedAborted, start_reseed
from torrentlinker.scan import scan
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent
from torrentlinker.transmission import PartialNamesOn, TransmissionApi

HOST = os.environ.get("TL_TRANSMISSION_SANDBOX", "")
DATA = os.environ.get("TL_TRANSMISSION_DATA", "")
pytestmark = pytest.mark.skipif(
    not (HOST and DATA), reason="set TL_TRANSMISSION_SANDBOX and TL_TRANSMISSION_DATA"
)


@pytest.fixture
def transmission() -> Iterator[TransmissionApi]:
    api = TransmissionApi(HOST)
    api.turn_off_partial_names()
    before = {t.hash for t in api.torrents(with_files=False)}
    yield api
    for t in api.torrents(with_files=False):
        if t.hash not in before:
            api.remove(t.hash)


@pytest.fixture
def shared() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(dir=DATA))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def no_part_files(folder: Path) -> list[Path]:
    return list(folder.rglob("*.part"))


def test_a_reseed_is_refused_while_part_names_are_on_until_turned_off(
    shared: Path, transmission: TransmissionApi
) -> None:
    transmission._call("session-set", **{"rename-partial-files": True})
    lib = library_with_ebook(shared)
    [item] = scan(LibraryFolder(lib))
    meta = read_torrent(scene_torrent(shared, item.path.read_bytes()))
    store = Store(shared / "s.db")

    with pytest.raises(PartialNamesOn) as refused:
        transmission.check()
    with pytest.raises(PartialNamesOn):
        start_reseed(transmission, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]
    assert transmission.torrent(meta.infohash) is None  # refused before adding

    refused.value.turn_off()
    assert transmission.check().startswith("4.")


def test_full_match_under_another_name_is_renamed_verified_and_started(
    shared: Path, transmission: TransmissionApi
) -> None:
    lib = library_with_ebook(shared)
    [item] = scan(LibraryFolder(lib))
    before = digest(item.path)
    meta = read_torrent(scene_torrent(shared, item.path.read_bytes()))
    m = match(item, meta.files)
    assert m is not None and m.is_full and m.renames
    store = Store(shared / "s.db")

    h = start_reseed(transmission, store, item, meta, m, meta.infohash)
    [outcome] = settle(transmission, store)  # type: ignore[arg-type]

    assert outcome.verified and outcome.started
    t = transmission.torrent(h)
    assert t is not None
    assert t.files == {item.path.name: item.size}
    assert t.tags == {TAG}
    assert classify([item], transmission.torrents()) == {item.path: ItemState.SEEDED}
    assert digest(item.path) == before


def test_a_renamed_folder_and_file_inside_it_are_reseeded(
    shared: Path, transmission: TransmissionApi
) -> None:
    pack = shared / "scene" / "Zweig.Pack.FR"
    pack.mkdir(parents=True)
    (pack / "a.epub").write_bytes(os.urandom(40000))
    (pack / "b.epub").write_bytes(os.urandom(50000))
    meta = read_torrent(make_torrent(pack))
    lib = shared / "lib"
    (lib / "Zweig").mkdir(parents=True)
    shutil.copy2(pack / "a.epub", lib / "Zweig" / "Le joueur.epub")
    shutil.copy2(pack / "b.epub", lib / "Zweig" / "b.epub")
    [item] = scan(LibraryFolder(lib))
    m = match(item, meta.files)
    assert m is not None and m.is_full
    store = Store(shared / "s.db")

    h = start_reseed(transmission, store, item, meta, m, meta.infohash)
    [outcome] = settle(transmission, store)  # type: ignore[arg-type]

    assert outcome.verified and outcome.started
    assert set(transmission.files(h)) == {"Zweig/Le joueur.epub", "Zweig/b.epub"}


def test_a_match_needing_other_folders_is_refused_and_removed(
    shared: Path, transmission: TransmissionApi
) -> None:
    pack = shared / "scene" / "Pack"
    pack.mkdir(parents=True)
    (pack / "a.epub").write_bytes(os.urandom(40000))
    meta = read_torrent(make_torrent(pack))
    lib = shared / "lib"
    lib.mkdir()
    shutil.copy2(pack / "a.epub", lib / "a.epub")  # flattened: no folder
    [item] = scan(LibraryFolder(lib))
    m = match(item, meta.files)
    if m is None or not m.renames:
        pytest.skip("the matcher does not propose this layout")
    store = Store(shared / "s.db")

    with pytest.raises(ReseedAborted, match="rename"):
        start_reseed(transmission, store, item, meta, m, meta.infohash)

    assert transmission.torrent(meta.infohash) is None
    assert (lib / "a.epub").exists()


def test_partial_match_is_verified_on_local_pieces_and_seeds_with_every_file_skipped(
    shared: Path, transmission: TransmissionApi
) -> None:
    pack = shared / "scene" / "Zweig.Pack"
    pack.mkdir(parents=True)
    (pack / "a.epub").write_bytes(os.urandom(40000))
    (pack / "b.epub").write_bytes(os.urandom(40000))
    meta = read_torrent(make_torrent(pack))
    lib = shared / "lib"
    (lib / "Zweig").mkdir(parents=True)
    shutil.copy2(pack / "a.epub", lib / "Zweig" / "a.epub")
    [item] = scan(LibraryFolder(lib))
    before = digest(lib / "Zweig" / "a.epub")
    m = match(item, meta.files)
    assert m is not None and not m.is_full
    store = Store(shared / "s.db")

    h = start_reseed(transmission, store, item, meta, m, meta.infohash)
    assert VERIFYING in transmission.torrents(tag=VERIFYING)[0].tags
    [outcome] = settle(transmission, store)  # type: ignore[arg-type]

    assert outcome.verified and outcome.started
    # Nothing wanted: the piece a.epub shares with the absent b.epub is never fetched.
    assert not any(f.wanted for f in transmission.file_listing(h))
    t = transmission.torrent(h)
    assert t is not None and PARTIAL in t.tags and VERIFYING not in t.tags
    assert not t.state.startswith("stopped")
    assert not (lib / "Zweig" / "b.epub").exists()
    assert no_part_files(lib) == []
    assert digest(lib / "Zweig" / "a.epub") == before


def test_same_size_but_different_data_fails_and_keeps_the_file(
    shared: Path, transmission: TransmissionApi
) -> None:
    lib = library_with_ebook(shared)
    [item] = scan(LibraryFolder(lib))
    before = digest(item.path)
    meta = read_torrent(scene_torrent(shared, os.urandom(item.size)))
    store = Store(shared / "s.db")

    h = start_reseed(transmission, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]
    [outcome] = settle(transmission, store)  # type: ignore[arg-type]

    assert not outcome.verified
    assert transmission.torrent(h) is None
    assert no_part_files(lib) == []
    assert digest(item.path) == before


def test_a_plan_torrent_downloads_into_its_download_folder_labelled_zen(
    shared: Path, transmission: TransmissionApi
) -> None:
    from torrentlinker.plan import PlanCandidate
    from torrentlinker.qbit import AlreadyInClient
    from torrentlinker.send import ZEN_TAG, send_one

    src = shared / "elsewhere" / "Zen.Release"
    src.mkdir(parents=True)
    (src / "a.bin").write_bytes(os.urandom(40000))
    data = make_torrent(src)
    meta = read_torrent(data)
    folder = shared / "dl"

    h = send_one(
        transmission, PlanCandidate(meta.infohash, meta.name, 40000, 1, 1, folder, 1), data
    )

    t = transmission.torrent(h)
    assert t is not None and t.save_path == folder and ZEN_TAG in t.tags
    assert not t.state.startswith("stopped")
    with pytest.raises(AlreadyInClient):
        transmission.download(data, str(shared / "dl3"), [ZEN_TAG])


def test_uploads_seed_from_the_local_files_under_their_own_names(
    shared: Path, transmission: TransmissionApi
) -> None:
    from tests.test_qbit_integration import check_uploads_seed_from_the_local_files

    check_uploads_seed_from_the_local_files(transmission, shared)
    assert not no_part_files(shared)


def test_tracker_updates_keep_tiers_and_private_keys(transmission, shared):
    from tests.tracker_support import check_tracker_updates

    check_tracker_updates(transmission, shared)
