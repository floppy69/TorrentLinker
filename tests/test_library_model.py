from pathlib import Path

from torrentlinker.domain import LibraryFolder, LocalItem
from torrentlinker.gui.library_model import LibraryModel
from torrentlinker.library import ItemState, LibraryEntry


class NoScans(list[LibraryEntry]):
    """Entries that fail a per-item lookup walking the whole Library (#51)."""

    def __iter__(self):  # type: ignore[no-untyped-def]
        raise AssertionError("per-item lookups must not walk every Library entry")


def entry(name: str, size: int = 1) -> LibraryEntry:
    path = Path("/library") / name
    return LibraryEntry(
        LibraryFolder(Path("/library")), LocalItem(path, {name: size}), ItemState.ORPHAN
    )


def test_restored_searches_find_rows_without_walking_the_library(qtbot) -> None:
    model = LibraryModel()
    entries = [entry(f"Item.{i}") for i in range(3)]
    model.set_entries(entries)
    model.entries = NoScans(entries)  # the index was built when the entries were set
    changed: list[tuple[int, int]] = []
    model.dataChanged.connect(lambda first, _last: changed.append((first.row(), first.column())))

    model.set_status(entries[1].item.path, "Verifying…")
    model.set_zen(entries[2].item.path, 1.5)

    assert changed == [(1, 1), (2, model.ZEN_COLUMN)]
    assert model.contains(entries[0])
    assert not model.contains(entry("Item.0", size=2))  # rescanned since the search
    assert not model.contains(entry("Missing"))
