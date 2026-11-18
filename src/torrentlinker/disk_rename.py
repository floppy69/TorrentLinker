"""Explicitly approved disk renames for µTorrent and rTorrent, with a durable undo journal.

No file contents are written. Targets must be absent; overlapping renames and
symlinks are refused. Journal recovery never overwrites an occupied original path.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import torf

from torrentlinker.domain import LocalItem
from torrentlinker.matching import Match
from torrentlinker.torrent_meta import TorrentMeta


class DiskRenameError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiskMove:
    source: Path
    target: Path
    identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class DiskRenamePlan:
    infohash: str
    title: str
    moves: tuple[DiskMove, ...]


RenameApproval = Callable[[DiskRenamePlan], bool]


def _identity(path: Path) -> tuple[int, int, int, int]:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode):
        raise DiskRenameError(f"Not a regular file: {path}")
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _path(base: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if not parts or any(p in {"..", "/"} or "\\" in p or ":" in p for p in parts):
        raise DiskRenameError(f"Unsafe file path: {relative}")
    result = base.joinpath(*parts)
    for parent in [result, *result.parents]:
        reparse = (
            os.name == "nt"
            and parent.exists()
            and getattr(parent.lstat(), "st_file_attributes", 0) & 0x400
        )
        if parent.is_symlink() or reparse:
            raise DiskRenameError(f"Cannot rename through a symbolic link: {parent}")
    if not result.resolve().is_relative_to(base.resolve()):
        raise DiskRenameError(f"File is outside the Library Folder: {relative}")
    return result


def plan_disk_renames(item: LocalItem, meta: TorrentMeta, match: Match) -> DiskRenamePlan:
    if match.unwanted or set(match.pairs) != set(meta.files):
        raise DiskRenameError("Disk renames require every torrent file to be present")
    if len(set(match.pairs.values())) != len(match.pairs):
        raise DiskRenameError("One local file cannot be renamed to several torrent files")
    moves = []
    for torrent_path, local_path in match.renames.items():
        source = _path(item.save_path, local_path)
        target = _path(item.save_path, torrent_path)
        identity = _identity(source)
        if os.path.lexists(target):
            raise DiskRenameError(f"Cannot rename: destination already exists: {target}")
        for parent in target.parents:
            if parent.exists() and not parent.is_dir():
                raise DiskRenameError(f"Cannot create a folder at: {parent}")
        if identity[2] != meta.files[torrent_path]:
            raise DiskRenameError(f"File size differs from the torrent: {source}")
        moves.append(DiskMove(source, target, identity))
    return DiskRenamePlan(meta.infohash, meta.name, tuple(moves))


def verify_local_data(
    item: LocalItem,
    meta: TorrentMeta,
    match: Match,
    *,
    checkpoint: Callable[[], None] = lambda: None,
    progress: Callable[[int, int], None] = lambda done, total: None,
) -> None:
    """Check all pieces against original files before any disk rename or client add."""
    torrent = torf.Torrent.read_stream(io.BytesIO(meta.data), validate=False)
    hashes = torrent.metainfo["info"]["pieces"]
    length = meta.piece_length
    if length <= 0 or not hashes or len(hashes) % 20:
        raise DiskRenameError("The torrent has no valid piece hashes")
    piece = hashlib.sha1()
    filled = index = 0
    read = 0
    total = sum(meta.files.values())

    def finish() -> None:
        nonlocal piece, filled, index
        if piece.digest() != hashes[index * 20 : (index + 1) * 20]:
            raise DiskRenameError("Local files do not match the torrent. No files were renamed.")
        index += 1
        piece, filled = hashlib.sha1(), 0

    for path, size in meta.files.items():
        source = _path(item.save_path, match.pairs[path])
        before = _identity(source)
        if before[2] != size:
            raise DiskRenameError(f"File size differs from the torrent: {source}")
        with source.open("rb") as stream:
            while chunk := stream.read(min(length - filled, 1024 * 1024)):
                checkpoint()
                piece.update(chunk)
                filled += len(chunk)
                read += len(chunk)
                progress(read, total)
                if filled == length:
                    finish()
        if _identity(source) != before:
            raise DiskRenameError(f"File changed during verification: {source}")
    if filled:
        finish()
    if index * 20 != len(hashes):
        raise DiskRenameError("The torrent's piece count does not match the local files")


def _rename_noreplace(source: Path, target: Path) -> None:
    if os.name == "nt":
        os.rename(source, target)  # Windows refuses an occupied destination.
    elif sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise DiskRenameError("This system cannot safely rename without overwriting files")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))
    else:
        raise DiskRenameError("Disk renames are supported on Windows and Linux only")


def journal_path(folder: Path, infohash: str) -> Path:
    if len(infohash) != 40 or any(c not in "0123456789abcdef" for c in infohash.lower()):
        raise DiskRenameError("Invalid torrent hash for rename journal")
    return folder / "reseed-renames" / (infohash.lower() + ".json")


def apply_disk_renames(folder: Path, plan: DiskRenamePlan, client_id: str) -> None:
    journal = journal_path(folder, plan.infohash)
    journal.parent.mkdir(parents=True, exist_ok=True)
    # Save the full plan before the first rename. Recovery distinguishes a move
    # that happened from one that did not using the file identity at either path.
    payload = [
        {"source": str(m.source), "target": str(m.target), "identity": m.identity}
        for m in plan.moves
    ]
    with journal.open("x", encoding="utf-8") as stream:
        json.dump({"client": client_id, "moves": payload}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    for move in plan.moves:
        # Recheck after the user took time to read the confirmation.
        if _identity(move.source) != move.identity:
            raise DiskRenameError(f"File changed since the rename was proposed: {move.source}")
        _path(move.source.parent, move.source.name)
        _path(move.target.parent, move.target.name)
        move.target.parent.mkdir(parents=True, exist_ok=True)
        _rename_noreplace(move.source, move.target)


def owns_journal(folder: Path, infohash: str, client_id: str) -> bool:
    journal = journal_path(folder, infohash)
    return bool(
        client_id
        and journal.exists()
        and json.loads(journal.read_text(encoding="utf-8"))["client"] == client_id
    )


def undo_disk_renames(folder: Path, infohash: str) -> None:
    journal = journal_path(folder, infohash)
    if not journal.exists():
        return
    for move in reversed(json.loads(journal.read_text(encoding="utf-8"))["moves"]):
        source, target = Path(move["source"]), Path(move["target"])
        identity = tuple(move["identity"])
        _path(source.parent, source.name)
        _path(target.parent, target.name)
        if os.path.lexists(source):
            if _identity(source) == identity:
                continue  # not moved, or already restored after an interrupted undo
            raise DiskRenameError(f"Cannot restore the original name; it is occupied: {source}")
        if not target.exists() or _identity(target) != identity:
            raise DiskRenameError(f"Cannot restore a file that changed or disappeared: {target}")
        source.parent.mkdir(parents=True, exist_ok=True)
        _rename_noreplace(target, source)
    journal.unlink()


def keep_disk_renames(folder: Path, infohash: str) -> None:
    journal_path(folder, infohash).unlink(missing_ok=True)
