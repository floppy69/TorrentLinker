"""Scan: walk a Library Folder and list its Local Items."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from torrentlinker.domain import LibraryFolder, LocalItem
from torrentlinker.item_detection import detect_items

if TYPE_CHECKING:
    from torrentlinker.store import Store


@dataclass(frozen=True)
class ScanError:
    path: Path
    message: str


class ScanResult(list[LocalItem]):
    """Readable items plus paths whose contents could not be established."""

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[ScanError] = []

    def failed(self, path: Path, error: OSError) -> None:
        self.errors.append(ScanError(path, str(error)))

    def require_complete(self) -> ScanResult:
        """Planning must not mistake unreadable contents for absent downloads."""
        if self.errors:
            raise OSError(
                "Scan incomplete: "
                + "; ".join(f"{error.path}: {error.message}" for error in self.errors)
            )
        return self


def scan(
    folder: LibraryFolder,
    cache: Store | None = None,
    refresh: bool = False,
    *,
    seeded_roots: frozenset[Path] = frozenset(),
    catalogue_sizes: frozenset[int] = frozenset(),
) -> ScanResult:
    """List readable Local Items; never cache an incomplete item.

    In Automatic mode (no depth) items are detected; `seeded_roots` and
    `catalogue_sizes` help recognise them. Episodes also appear inside their pack."""
    result = ScanResult()
    if folder.depth is None:
        found = [
            (item.path, item.within)
            for item in detect_items(
                folder.path,
                folder.kind,
                seeded_roots=seeded_roots,
                catalogue_sizes=catalogue_sizes,
                on_error=result.failed,
            )
        ]
    else:
        found = [(path, None) for path in _entries_at_depth(folder.path, folder.depth, result)]
    for path, within in found:
        try:
            item = _local_item(path, cache, refresh)
        except OSError as error:
            result.failed(path, error)
        else:
            result.append(replace(item, within=within) if within else item)
    return result


def _entries_at_depth(root: Path, depth: int, result: ScanResult) -> list[Path]:
    """Entries `depth` levels below root; a file met earlier is an entry on its own."""
    if depth == 0:
        return [root]
    found: list[Path] = []
    level = [root]
    for remaining in range(depth, 0, -1):
        children: list[Path] = []
        for d in level:
            try:
                listed = sorted(d.iterdir())
            except OSError as error:
                result.failed(d, error)
                continue
            for child in listed:
                try:
                    if remaining == 1 or stat.S_ISREG(child.stat().st_mode):
                        found.append(child)
                    else:
                        children.append(child)
                except OSError as error:
                    result.failed(child, error)
        level = children
    return found


def scan_item(path: Path) -> LocalItem:
    """One Local Item read afresh, e.g. a folder the app just unpacked."""
    return _local_item(path, None, False)


def _local_item(path: Path, cache: Store | None, refresh: bool) -> LocalItem:
    base = path.parent
    metadata = path.stat()
    if stat.S_ISREG(metadata.st_mode):
        return LocalItem(path, {path.name: metadata.st_size})
    # A folder whose directories all keep their mtime has the same entries, so its file
    # list is reused without stat-ing every file. A file rewritten in place under the
    # same name is only noticed by a refresh (Rescan everything).
    signature = _signature(path) if cache else ""
    if cache and not refresh and (files := cache.cached_scan(path, signature)) is not None:
        return LocalItem(path, files)
    walked: dict[str, int] = {}
    for dirpath, _dirs, names in os.walk(path, onerror=_raise_walk_error):
        for name in names:
            f = Path(dirpath) / name
            walked[f.relative_to(base).as_posix()] = f.stat().st_size
    files = dict(sorted(walked.items()))
    if cache:
        cache.cache_scan(path, signature, files)
    return LocalItem(path, files)


def _signature(path: Path) -> str:
    parts = []
    for dirpath, dirs, _names in os.walk(path, onerror=_raise_walk_error):
        dirs.sort()
        parts.append(f"{dirpath}:{os.stat(dirpath).st_mtime_ns}")
    return "|".join(parts)


def _raise_walk_error(error: OSError) -> None:
    """os.walk otherwise treats an unreadable directory as empty."""
    raise error
