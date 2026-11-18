"""Persistent torrent layouts made of symlinks; source names are never changed."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path, PurePosixPath

from torrentlinker.domain import LocalItem
from torrentlinker.matching import Match
from torrentlinker.paths import PathMapper
from torrentlinker.torrent_meta import TorrentMeta


def plain_path(path: Path) -> Path:
    """Refuse traversing links, including dangling links and Windows junctions."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Use an absolute folder path without '..'.")
    for part in reversed((path, *path.parents)):
        try:
            value = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"A symbolic link or junction occupies this path: {part}")
    return path


def relative_path(value: str) -> Path:
    parts = PurePosixPath(value).parts
    if not parts or any(p in {"..", "/"} or "\\" in p or ":" in p for p in parts):
        raise ValueError("Unsafe torrent file path.")
    return Path(*parts)


def source_identity(path: Path) -> list[int]:
    value = plain_path(path).stat()
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(f"Not a regular source file: {path}")
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns]


def prepare_links(
    root: Path,
    item: LocalItem,
    meta: TorrentMeta,
    match: Match,
    mapper: PathMapper,
    library_roots: list[Path],
) -> dict:
    """Create an exclusive layout. A failed preparation removes only its own entries.

    Targets use the client's namespace: with Docker mappings they may be dangling
    from the app's view. Validation reads originals, and the client checks its view.
    """
    root = plain_path(root)
    if not root.is_dir():
        raise ValueError("Choose an existing, writable link folder.")
    if any(root.resolve().is_relative_to(p.resolve()) for p in library_roots):
        raise ValueError("Choose a link folder outside your Library Folders.")
    if match.unwanted or set(match.pairs) != set(meta.files):
        raise ValueError("Links require every torrent file, including small files.")
    if len(set(match.pairs.values())) != len(match.pairs):
        raise ValueError("Each torrent file needs a separate local file.")
    files: list[dict] = []
    for expected, local in match.pairs.items():
        relative_path(expected)
        source = item.save_path / relative_path(local)
        identity = source_identity(source)
        if identity[2] != meta.files[expected]:
            raise ValueError("A source file changed size. Compare this item again.")
        target = mapper.to_qbit(str(source))
        if os.name != "nt" and not target.startswith("/"):
            raise ValueError("The client and TorrentLinker need compatible symlink paths.")
        files.append(
            {"name": expected, "source": str(source), "target": target, "identity": identity}
        )
    destination = Path(tempfile.mkdtemp(prefix="torrentlinker-", dir=root))
    # Match the chosen root's access policy so a separate client service account
    # can traverse the layout. Source file permissions remain authoritative.
    destination.chmod(stat.S_IMODE(root.stat().st_mode) & 0o777)
    # Only these entries belong to this call; never recursively delete a layout.
    created: list[Path] = []
    directories = {destination}
    try:
        for row in files:
            link = destination / relative_path(row["name"])
            for parent in reversed(link.parents):
                if parent == destination or destination in parent.parents:
                    if parent not in directories:
                        parent.mkdir()  # exclusive, also refuses symlink collisions
                        directories.add(parent)
            link.symlink_to(row["target"])
            created.append(link)
    except BaseException:
        for link in reversed(created):
            if link.is_symlink():
                link.unlink()
        for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    return {"destination": str(destination), "files": files, "hash": meta.infohash}


def validate_links(record: dict) -> None:
    destination = plain_path(Path(record["destination"]))
    for row in record["files"]:
        link = destination / relative_path(row["name"])
        plain_path(link.parent)
        if not link.is_symlink() or os.readlink(link) != row["target"]:
            raise ValueError("A prepared link was removed or changed. Review the link folder.")
        if source_identity(Path(row["source"])) != row["identity"]:
            raise ValueError("A source file changed since preparation. Compare it again.")
