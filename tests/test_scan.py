from pathlib import Path

from torrentlinker.domain import LibraryFolder
from torrentlinker.scan import scan


def write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_each_top_level_entry_is_a_local_item(tmp_path: Path) -> None:
    write(tmp_path / "Movie.2020.mkv", 10)
    write(tmp_path / "Show.S01" / "e01.mkv", 20)
    write(tmp_path / "Show.S01" / "subs" / "e01.srt", 3)

    items = scan(LibraryFolder(tmp_path, depth=1))

    by_name = {i.path.name: i for i in items}
    assert set(by_name) == {"Movie.2020.mkv", "Show.S01"}
    assert by_name["Movie.2020.mkv"].files == {"Movie.2020.mkv": 10}
    assert by_name["Show.S01"].files == {"Show.S01/e01.mkv": 20, "Show.S01/subs/e01.srt": 3}
    assert by_name["Show.S01"].size == 23


def test_depth_two_lists_entries_inside_each_subfolder(tmp_path: Path) -> None:
    write(tmp_path / "Show" / "Season 1" / "e01.mkv", 5)
    write(tmp_path / "Show" / "Season 2" / "e01.mkv", 6)
    write(tmp_path / "Loose.File.mkv", 7)

    items = scan(LibraryFolder(tmp_path, depth=2))

    assert sorted(i.path.relative_to(tmp_path).as_posix() for i in items) == [
        "Loose.File.mkv",
        "Show/Season 1",
        "Show/Season 2",
    ]
    season1 = next(i for i in items if i.path.name == "Season 1")
    assert season1.files == {"Season 1/e01.mkv": 5}


# Scan cache ------------------------------------------------------------------

from torrentlinker.store import Store  # noqa: E402


def test_rescan_with_a_cache_gives_the_same_items(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write(lib / "Show" / "e01.mkv", 5)
    write(lib / "Movie.mkv", 7)
    store = Store(tmp_path / "s.db")

    first = scan(LibraryFolder(lib), store)
    again = scan(LibraryFolder(lib), store)

    assert again == first


def test_files_added_or_removed_inside_an_item_are_picked_up(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write(lib / "Show" / "Season 1" / "e01.mkv", 5)
    store = Store(tmp_path / "s.db")
    scan(LibraryFolder(lib), store)

    write(lib / "Show" / "Season 1" / "e02.mkv", 6)
    (lib / "Show" / "Season 1" / "e01.mkv").unlink()
    items = scan(LibraryFolder(lib), store)

    assert items[0].files == {"Show/Season 1/e02.mkv": 6}


def test_a_cached_item_that_disappeared_is_not_reported(tmp_path: Path) -> None:
    import shutil

    lib = tmp_path / "lib"
    write(lib / "Show" / "e01.mkv", 5)
    store = Store(tmp_path / "s.db")
    scan(LibraryFolder(lib), store)

    shutil.rmtree(lib / "Show")

    assert scan(LibraryFolder(lib), store) == []


def test_a_full_rescan_catches_a_file_rewritten_in_place_and_refreshes_the_cache(
    tmp_path: Path,
) -> None:
    import os

    lib = tmp_path / "lib"
    write(lib / "Show" / "e01.mkv", 5)
    store = Store(tmp_path / "s.db")
    scan(LibraryFolder(lib), store)
    show = lib / "Show"
    dir_mtime = show.stat().st_mtime_ns
    (show / "e01.mkv").write_bytes(b"y" * 9)  # same name: the folder's mtime may not move
    os.utime(show, ns=(dir_mtime, dir_mtime))

    assert scan(LibraryFolder(lib), store)[0].files == {"Show/e01.mkv": 5}  # cached
    assert scan(LibraryFolder(lib), store, refresh=True)[0].files == {"Show/e01.mkv": 9}
    assert scan(LibraryFolder(lib), store)[0].files == {"Show/e01.mkv": 9}


def test_depth_zero_keeps_the_selected_folder_whole(tmp_path: Path) -> None:
    write(tmp_path / "Book.epub", 4)
    items = scan(LibraryFolder(tmp_path, depth=0))
    assert len(items) == 1
    assert items[0].path == tmp_path
    assert items[0].size == 4
