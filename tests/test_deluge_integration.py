"""Reseed and Plan against a real Deluge. Opt-in: point TL_DELUGE_SANDBOX at a throwaway
Deluge Web UI with the Label plugin on, and TL_DELUGE_DATA at a folder Deluge sees at the
same path (e.g. a Docker volume mounted at its own host path).

    TL_DELUGE_SANDBOX=http://127.0.0.1:18112 TL_DELUGE_DATA=/tmp/deluge-data \
        pytest tests/test_deluge_integration.py

Every torrent added is removed at the end (data kept). Library files are checked to be
unchanged.
"""

import os
import shutil
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.test_qbit_integration import digest, library_with_ebook, scene_torrent, settle
from tests.torrents import make_torrent
from torrentlinker.deluge import GUARD_SPEED, DelugeApi
from torrentlinker.domain import ItemState, LibraryFolder
from torrentlinker.matching import match
from torrentlinker.reconcile import classify
from torrentlinker.reseed import PARTIAL, TAG, VERIFYING, start_reseed
from torrentlinker.scan import scan
from torrentlinker.store import Store
from torrentlinker.torrent_meta import read_torrent

HOST = os.environ.get("TL_DELUGE_SANDBOX", "")
PASSWORD = os.environ.get("TL_DELUGE_SANDBOX_PASSWORD", "deluge")
DATA = os.environ.get("TL_DELUGE_DATA", "")
pytestmark = pytest.mark.skipif(not (HOST and DATA), reason="set TL_DELUGE_SANDBOX and _DATA")


@pytest.fixture
def deluge() -> Iterator[DelugeApi]:
    api = DelugeApi(HOST, PASSWORD)
    before = {t.hash for t in api.torrents(with_files=False)}
    yield api
    for t in api.torrents(with_files=False):
        if t.hash not in before:
            api.remove(t.hash)


@pytest.fixture
def shared() -> Iterator[Path]:
    """A temp folder Deluge sees at the same path."""
    path = Path(tempfile.mkdtemp(dir=DATA))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def guard(api: DelugeApi, h: str) -> float:
    status = api._call("core.get_torrent_status", h, ["max_download_speed"])
    return float(status["max_download_speed"])


def test_check_reports_the_version(deluge: DelugeApi) -> None:
    assert deluge.check().startswith("2.")
    assert deluge.default_save_path()


def test_full_match_under_another_name_is_renamed_verified_and_started(
    shared: Path, deluge: DelugeApi
) -> None:
    lib = library_with_ebook(shared)
    [item] = scan(LibraryFolder(lib))
    before = digest(item.path)
    meta = read_torrent(scene_torrent(shared, item.path.read_bytes()))
    m = match(item, meta.files)
    assert m is not None and m.is_full and m.renames
    store = Store(shared / "s.db")

    h = start_reseed(deluge, store, item, meta, m, meta.infohash)
    [outcome] = settle(deluge, store)  # type: ignore[arg-type]

    assert outcome.verified and outcome.started
    t = deluge.torrent(h)
    assert t is not None
    assert t.files == {item.path.name: item.size}
    assert t.tags == {TAG}
    assert not t.state.startswith("stopped")
    assert guard(deluge, h) == -1  # full speed once started
    assert classify([item], deluge.torrents()) == {item.path: ItemState.SEEDED}
    assert digest(item.path) == before


def test_partial_match_is_verified_on_local_pieces_and_seeds_with_every_file_skipped(
    shared: Path, deluge: DelugeApi
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

    h = start_reseed(deluge, store, item, meta, m, meta.infohash)
    assert guard(deluge, h) == pytest.approx(GUARD_SPEED)
    assert VERIFYING in deluge.torrents(tag=VERIFYING)[0].tags
    [outcome] = settle(deluge, store)  # type: ignore[arg-type]

    assert outcome.verified and outcome.started
    # Nothing wanted: the piece a.epub shares with the absent b.epub is never fetched.
    assert not any(f.wanted for f in deluge.file_listing(h))
    t = deluge.torrent(h)
    assert t is not None and PARTIAL in t.tags and VERIFYING not in t.tags
    assert deluge.torrents(tag=VERIFYING) == []
    assert not t.state.startswith("stopped")
    assert guard(deluge, h) == -1
    assert not (lib / "Zweig" / "b.epub").exists()
    assert digest(lib / "Zweig" / "a.epub") == before


def test_same_size_but_different_data_fails_and_keeps_the_file(
    shared: Path, deluge: DelugeApi
) -> None:
    lib = library_with_ebook(shared)
    [item] = scan(LibraryFolder(lib))
    before = digest(item.path)
    meta = read_torrent(scene_torrent(shared, os.urandom(item.size)))
    store = Store(shared / "s.db")

    h = start_reseed(deluge, store, item, meta, match(item, meta.files), meta.infohash)  # type: ignore[arg-type]
    [outcome] = settle(deluge, store)  # type: ignore[arg-type]

    assert not outcome.verified
    assert deluge.torrent(h) is None
    assert digest(item.path) == before
    assert store.rejections(item.path)


def test_a_plan_torrent_downloads_into_its_download_folder_labelled_zen(
    shared: Path, deluge: DelugeApi
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

    h = send_one(deluge, PlanCandidate(meta.infohash, meta.name, 40000, 1, 1, folder, 1), data)

    t = deluge.torrent(h)
    assert t is not None
    assert t.save_path == folder
    assert ZEN_TAG in t.tags
    assert not t.state.startswith("stopped")
    with pytest.raises(AlreadyInClient):
        deluge.download(data, str(shared / "dl3"), [ZEN_TAG])
    deluge.remove(h)
    for _ in range(50):
        if deluge.torrent(h) is None:
            break
        time.sleep(0.1)
    assert deluge.torrent(h) is None


def test_uploads_seed_from_the_local_files_under_their_own_names(
    shared: Path, deluge: DelugeApi
) -> None:
    from tests.test_qbit_integration import check_uploads_seed_from_the_local_files

    check_uploads_seed_from_the_local_files(deluge, shared)


def test_tracker_updates_keep_tiers_and_private_keys(deluge, shared):
    from tests.tracker_support import check_tracker_updates

    check_tracker_updates(deluge, shared)
