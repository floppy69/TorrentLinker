"""Path Mappings against qBittorrent in a throwaway Docker container. Opt-in:

    data=$(mktemp -d); profile=$(mktemp -d)
    python scripts/qbit_sandbox.py "$profile" --docker
    docker run -d --rm --name tl-qbt -p 127.0.0.1:18090:8080 \\
        -e QBT_LEGAL_NOTICE=confirm -e PUID=$(id -u) -e PGID=$(id -g) \\
        -v "$profile:/config" -v "$data:/data" qbittorrentofficial/qbittorrent-nox:5.2.4-1
    TL_QBIT_DOCKER=http://127.0.0.1:18090 TL_QBIT_DOCKER_DATA="$data" \\
        pytest tests/test_docker_paths.py
    docker stop tl-qbt

The container sees the folder $data as /data, as a NAS or Docker volume would. Every
torrent added is removed at the end; the data is left for the folder's owner to delete.
"""

import os
import time
from pathlib import Path

import pytest

from tests.torrents import make_torrent
from torrentlinker.domain import PathMapping
from torrentlinker.paths import (
    MappedQbit,
    PathMapper,
    check_mappings,
    detect_mappings,
    unreachable_download_folders,
)
from torrentlinker.qbit import QbitApi
from torrentlinker.torrent_meta import read_torrent

HOST = os.environ.get("TL_QBIT_DOCKER", "")
DATA = Path(os.environ.get("TL_QBIT_DOCKER_DATA", "/nonexistent"))
pytestmark = pytest.mark.skipif(not HOST, reason="set TL_QBIT_DOCKER and TL_QBIT_DOCKER_DATA")


@pytest.mark.parametrize("normalization", ["NFC", "NFD"])
@pytest.mark.parametrize("layout", ["auto", "links"])
def test_reseed_workspace_verifies_mapped_accented_sources(qbit, normalization, layout):
    import tempfile
    import unicodedata

    from tests.test_reseed_workspace import run, workspace

    root = Path(tempfile.mkdtemp(prefix="linked-reseed-", dir=DATA))
    filename = unicodedata.normalize(normalization, "Été - mon film.mkv")
    board, _, original, links, meta = workspace(root, qbit, filename)
    board.setup.settings.path_mappings = [PathMapping(str(DATA), "/data")]
    board.setup.settings.profile().reseed_layout = layout
    before = original.read_bytes(), original.stat().st_ino, original.name
    result = run(board, original, links)
    assert not result["errors"], result
    assert result["seeded"] == 1
    torrent = qbit.torrent(meta.infohash)
    assert torrent and torrent.progress == 1
    assert torrent.save_path == Path("/data") / Path(result["rows"][0]["destination"]).relative_to(
        DATA
    )
    assert torrent.files == {
        "Release.mkv" if layout == "links" else original.name: original.stat().st_size
    }
    if layout == "auto":
        assert not list(links.iterdir())
    assert (original.read_bytes(), original.stat().st_ino, original.name) == before
    assert not list(original.parent.glob("Release*"))


@pytest.fixture
def qbit():  # type: ignore[no-untyped-def]
    api = QbitApi(HOST, "", "")
    before = {t.hash for t in api.torrents(with_files=False)}
    yield api
    for t in api.torrents(with_files=False):
        if t.hash not in before:
            api.remove(t.hash)


def release(folder: Path, name: str, size: int = 70_000) -> bytes:
    """A one-book release on the shared folder, and its .torrent."""
    book = folder / name
    book.mkdir(parents=True, exist_ok=True)
    (book / f"{name}.epub").write_bytes(os.urandom(size))
    return make_torrent(book)


def progress_after_check(api: QbitApi, h: str, timeout: float = 30) -> float:
    api.recheck(h)
    deadline = time.time() + timeout
    progress = 0.0
    while time.time() < deadline:
        time.sleep(0.5)
        t = api.torrent(h)
        if t is not None and not t.state.startswith("checking"):
            progress = t.progress
            if progress >= 1.0:
                break
    return progress


def wait_listed(api: QbitApi, h: str) -> None:
    deadline = time.time() + 15
    while api.torrent(h) is None:
        assert time.time() < deadline, "qBittorrent did not list the torrent"
        time.sleep(0.2)


def test_detect_finds_the_volume_and_check_confirms_it(qbit: QbitApi) -> None:
    data = release(DATA / "ebooks", "Zweig.Le.Joueur.D.Echecs")
    h = qbit.add(data, "/data/ebooks", ["torrentlinker:test"])  # as the user set it up
    wait_listed(qbit, h)

    def files(t):  # type: ignore[no-untyped-def]
        return found.files if (found := qbit.torrent(t.hash)) else {}

    mine = [t for t in qbit.torrents(with_files=False) if t.hash == h]
    detection = detect_mappings(mine, [DATA / "ebooks"], files)

    [suggestion] = detection.suggestions
    assert suggestion.mapping == PathMapping(str(DATA), "/data")
    [check] = check_mappings(mine, [suggestion.mapping])  # none outside every mapping
    assert (check.found, check.total) == (1, 1)


def test_a_reseed_through_the_mapping_finds_the_data_in_the_container(qbit: QbitApi) -> None:
    data = release(DATA / "library", "Sand.Indiana")
    h = read_torrent(data).infohash
    mapped = MappedQbit(qbit, PathMapper([PathMapping(str(DATA), "/data")]))

    mapped.add(data, str(DATA / "library"), ["torrentlinker:test"])  # this computer's path
    wait_listed(qbit, h)

    raw = qbit.torrent(h)
    assert raw is not None and str(raw.save_path) == "/data/library"
    seen = mapped.torrent(h)
    assert seen is not None and seen.save_path == DATA / "library"
    assert progress_after_check(qbit, h) == 1.0  # qBittorrent read the very same files


def test_without_the_mapping_qbittorrent_cannot_find_the_data(qbit: QbitApi) -> None:
    data = release(DATA / "unmapped", "Kafka.Le.Proces")
    h = read_torrent(data).infohash

    MappedQbit(qbit, PathMapper([])).add(data, str(DATA / "unmapped"), ["torrentlinker:test"])
    wait_listed(qbit, h)

    assert progress_after_check(qbit, h, timeout=10) == 0.0  # the bug 0.2 had


def test_a_plan_download_goes_to_the_download_folder_as_qbittorrent_sees_it(
    qbit: QbitApi, tmp_path: Path
) -> None:
    source = tmp_path / "elsewhere"
    data = release(source, "Dumas.Fernande")  # data not in the Download Folder: to download
    h = read_torrent(data).infohash
    mappings = [PathMapping(str(DATA), "/data")]

    MappedQbit(qbit, PathMapper(mappings)).download(data, str(DATA / "plan"), ["test"])
    wait_listed(qbit, h)

    raw = qbit.torrent(h)
    assert raw is not None and str(raw.save_path) == "/data/plan"
    default = qbit.default_save_path()
    assert default == "/downloads"
    assert unreachable_download_folders([DATA / "plan", source], mappings, default) == [source]
