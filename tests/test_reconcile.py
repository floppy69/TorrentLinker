from pathlib import Path

import pytest

from torrentlinker.domain import ItemState, LocalItem, Torrent
from torrentlinker.reconcile import classify

LIB = Path("/lib")

movie = LocalItem(LIB / "Movie.mkv", {"Movie.mkv": 10})
show = LocalItem(LIB / "Show", {"Show/e01.mkv": 1, "Show/e02.mkv": 2})


def test_item_covered_by_a_torrent_is_seeded_and_others_are_orphans() -> None:
    torrents = [Torrent("h1", "Movie.mkv", LIB, {"Movie.mkv": 10})]

    states = classify([movie, show], torrents)

    assert states == {movie.path: ItemState.SEEDED, show.path: ItemState.ORPHAN}


def test_item_with_only_some_files_in_torrents_is_partially_seeded() -> None:
    torrents = [Torrent("h1", "Show", LIB, {"Show/e01.mkv": 1})]

    assert classify([show], torrents) == {show.path: ItemState.PARTIALLY_SEEDED}


def test_files_of_one_item_spread_over_several_torrents_count_as_seeded() -> None:
    torrents = [
        Torrent("h1", "e01.mkv", LIB / "Show", {"e01.mkv": 1}),
        Torrent("h2", "e02.mkv", LIB / "Show", {"e02.mkv": 2}),
    ]

    assert classify([show], torrents) == {show.path: ItemState.SEEDED}


def test_local_ignored_files_do_not_make_an_item_partially_seeded() -> None:
    from torrentlinker.matching import IgnoreList

    movie_dir = LocalItem(LIB / "Movie", {"Movie/movie.mkv": 10, "Movie/Thumbs.db": 1})
    torrents = [Torrent("h1", "Movie", LIB, {"Movie/movie.mkv": 10})]

    states = classify([movie_dir], torrents, IgnoreList.default())

    assert states == {movie_dir.path: ItemState.SEEDED}


def test_only_orphans_are_searched_automatically() -> None:
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.library import LibraryEntry, auto_searchable

    folder = LibraryFolder(LIB)
    entries = [
        LibraryEntry(folder, movie, ItemState.SEEDED),
        LibraryEntry(folder, show, ItemState.PARTIALLY_SEEDED),
        LibraryEntry(folder, LocalItem(LIB / "x"), ItemState.ORPHAN),
    ]

    assert [e.item.path.name for e in auto_searchable(entries)] == ["x"]


def test_only_indexer_torrents_make_items_seeded_and_only_their_files_are_read(
    tmp_path: Path,
) -> None:
    from tests.fake_qbit import FakeQbit
    from torrentlinker.library import indexer_contents
    from torrentlinker.store import CatalogueRow, Store

    url = "https://c411.org/api/torznab"
    book = LocalItem(LIB / "Book.epub", {"Book.epub": 5})
    music = LocalItem(LIB / "Album", {"Album/a.flac": 7})
    client = FakeQbit()
    client.by_hash = {
        "a" * 40: Torrent(
            "a" * 40, "Movie.mkv", LIB, {"Movie.mkv": 10}, tracker="https://tracker.c411.org/a"
        ),
        # Stopped, so no tracker yet: known from the Catalogue
        "b" * 40: Torrent("b" * 40, "Book.epub", LIB, {"Book.epub": 5}),
        "c" * 40: Torrent(
            "c" * 40, "Album", LIB, {"Album/a.flac": 7}, tracker="https://other.example/a"
        ),
        "d" * 40: Torrent(
            "d" * 40, "Show", LIB, dict(show.files), frozenset({"torrentlinker:zen"})
        ),
    }
    read: list[str] = []
    files = client.files
    client.files = lambda h: read.append(h) or files(h)  # type: ignore[method-assign]
    store = Store(tmp_path / "s.db")
    store.save_catalogue([CatalogueRow("b" * 40, "Book", 5, 1, 7000, "u", "d", 0)])

    torrents = indexer_contents(client, store, url)

    assert sorted(read) == ["a" * 40, "b" * 40, "d" * 40]  # never the other tracker's
    assert classify([movie, book, music, show], torrents) == {
        movie.path: ItemState.SEEDED,
        book.path: ItemState.SEEDED,
        music.path: ItemState.ORPHAN,  # seeded for another tracker: searched on c411
        show.path: ItemState.SEEDED,
    }


@pytest.mark.parametrize("active_tracker", ["", "https://other.example/announce"])
def test_c411_pack_files_are_seeded_when_only_the_tracker_list_identifies_c411(
    tmp_path, active_tracker
):
    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import ContentKind, LibraryFolder
    from torrentlinker.library import build_library, indexer_contents
    from torrentlinker.store import Store

    folder = tmp_path / "models"
    part = folder / "Enemy - Ravenous Reapers x3"
    part.mkdir(parents=True)
    (part / "model.stl").write_bytes(b"mesh")
    source = Torrent(
        "a" * 40,
        "A differently named c411 pack",
        folder,
        {"Enemy - Ravenous Reapers x3/model.stl": 4},
        state="stoppedUP",
        tracker=active_tracker,
        trackers=("https://other.example/announce", "https://tk.c411.tw/announce/private"),
    )
    client = FakeQbit(by_hash={source.hash: source})
    # No Catalogue entry and no TorrentLinker tag: the client's announce list is evidence.
    contents = indexer_contents(client, Store(tmp_path / "state.db"), "https://c411.org/api")
    entries = build_library([LibraryFolder(folder, kind=ContentKind.MODEL_3D)], contents)

    assert len(entries) == 1
    assert entries[0].state is ItemState.SEEDED
    assert entries[0].torrent_hashes == frozenset({source.hash})


@pytest.mark.parametrize("client_location_updated", [False, True])
def test_app_download_moved_files_follow_the_current_client_location(
    tmp_path, client_location_updated
):
    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import ContentKind, LibraryFolder
    from torrentlinker.library import build_library, indexer_contents
    from torrentlinker.store import Store

    downloads, destination = tmp_path / "downloads", tmp_path / "library"
    downloads.mkdir()
    destination.mkdir()
    original = downloads / "model.stl"
    original.write_bytes(b"mesh")
    moved = destination / original.name
    original.rename(moved)
    source = Torrent(
        "a" * 40,
        "Downloaded pack",
        destination if client_location_updated else downloads,
        {moved.name: 4},
        tags=frozenset({"torrentlinker:search"}),
    )
    client = FakeQbit(by_hash={source.hash: source})
    contents = indexer_contents(client, Store(tmp_path / "state.db"), "https://c411.org/api")
    entries = build_library([LibraryFolder(destination, kind=ContentKind.MODEL_3D)], contents)

    assert entries[0].item.path == moved
    assert entries[0].state is (ItemState.SEEDED if client_location_updated else ItemState.ORPHAN)
    assert entries[0].torrent_hashes == (
        frozenset({source.hash}) if client_location_updated else frozenset()
    )


def test_extracted_app_download_is_not_mislabelled_as_seeding_the_archive(tmp_path):
    import zipfile

    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import ContentKind, LibraryFolder
    from torrentlinker.library import build_library, indexer_contents
    from torrentlinker.store import Store

    downloads, library = tmp_path / "downloads", tmp_path / "library"
    downloads.mkdir()
    library.mkdir()
    archive = downloads / "c411-pack.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("Enemy - Ravenous Reapers x3/model.stl", b"mesh")
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(library)
    source = Torrent(
        "a" * 40,
        "c411-pack.zip",
        downloads,
        {archive.name: archive.stat().st_size},
        tags=frozenset({"torrentlinker:search"}),
    )
    client = FakeQbit(by_hash={source.hash: source})
    contents = indexer_contents(client, Store(tmp_path / "state.db"), "https://c411.org/api")
    entries = build_library([LibraryFolder(library, kind=ContentKind.MODEL_3D)], contents)

    assert entries[0].item.files == {"Enemy - Ravenous Reapers x3/model.stl": 4}
    assert entries[0].state is ItemState.ORPHAN
    assert entries[0].torrent_hashes == frozenset()


def test_mapped_app_download_pack_is_recognized_inside_a_library_subfolder(tmp_path):
    from tests.fake_qbit import FakeQbit
    from torrentlinker.domain import ContentKind, LibraryFolder, PathMapping
    from torrentlinker.library import build_library, indexer_contents
    from torrentlinker.paths import MappedQbit, PathMapper
    from torrentlinker.store import Store

    folder = tmp_path / "mapped"
    pack = folder / "Bundle"
    model = pack / "Enemy - Ravenous Reapers x3"
    model.mkdir(parents=True)
    (model / "model.stl").write_bytes(b"mesh")
    source = Torrent(
        "a" * 40,
        "Bundle",
        Path("/remote/downloads"),
        {"Bundle/Enemy - Ravenous Reapers x3/model.stl": 4},
        tags=frozenset({"torrentlinker:search"}),
    )
    client = MappedQbit(
        FakeQbit(by_hash={source.hash: source}),
        PathMapper([PathMapping(str(folder), "/remote/downloads")]),
    )
    contents = indexer_contents(client, Store(tmp_path / "state.db"), "https://c411.org/api")
    entries = build_library([LibraryFolder(pack, kind=ContentKind.MODEL_3D)], contents)

    assert entries[0].item.path == model
    assert entries[0].state is ItemState.SEEDED
    assert entries[0].torrent_hashes == frozenset({source.hash})


def test_file_lists_are_read_once_paced_and_again_only_when_asked(tmp_path: Path) -> None:
    from tests.fake_qbit import FakeQbit
    from torrentlinker.library import indexer_contents
    from torrentlinker.store import Store

    url = "https://c411.org/api/torznab"
    client = FakeQbit()
    client.by_hash = {
        h * 40: Torrent(h * 40, n, LIB, {n: 1}, tracker="https://tracker.c411.org/a")
        for h, n in (("a", "One.mkv"), ("b", "Two.mkv"))
    }
    read: list[str] = []
    files = client.files
    now = [0.0]

    def slow_files(h: str) -> dict[str, int]:
        read.append(h)
        now[0] += 0.3  # the client takes 0.3 s to answer
        return files(h)

    client.files = slow_files  # type: ignore[method-assign]
    pauses: list[float] = []
    store = Store(tmp_path / "s.db")

    def scan(**kw: object) -> list[Torrent]:
        return indexer_contents(client, store, url, clock=lambda: now[0], sleep=pauses.append, **kw)

    first = scan()
    assert len(read) == 2 and pauses == pytest.approx([1.2, 1.2])  # leave 80% of the cycle idle
    assert scan() == first and len(read) == 2  # the next scan asks for no file list
    store.forget_torrent_files("b" * 40)  # e.g. files renamed inside it by a Reseed
    scan()
    assert read[2:] == ["b" * 40]
    scan(refresh=True)  # Rescan everything reads every list again
    assert sorted(read[3:]) == ["a" * 40, "b" * 40]


def test_known_files_reads_a_torrent_once(tmp_path: Path) -> None:
    from tests.fake_qbit import FakeQbit
    from torrentlinker.library import known_files
    from torrentlinker.store import Store

    client = FakeQbit()
    client.by_hash = {"a" * 40: Torrent("a" * 40, "One.mkv", LIB, {"One.mkv": 1})}
    read: list[str] = []
    files = client.files
    client.files = lambda h: read.append(h) or files(h)  # type: ignore[method-assign]
    store = Store(tmp_path / "s.db")

    assert known_files(client, store, "a" * 40) == {"One.mkv": 1}
    assert known_files(client, store, "A" * 40) == {"One.mkv": 1}  # any case
    assert read == ["a" * 40]
