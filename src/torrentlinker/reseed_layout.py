"""A client's Reseed layout choice and the identities of its prepared files."""

from __future__ import annotations

import stat
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from torrentlinker.domain import TorrentClient
from torrentlinker.paths import PathMapper
from torrentlinker.reseed_links import prepare_links, relative_path, source_identity, validate_links

if TYPE_CHECKING:
    from torrentlinker.config import Settings
    from torrentlinker.domain import LocalItem
    from torrentlinker.matching import Match
    from torrentlinker.torrent_meta import TorrentMeta

DISK_RENAME_CLIENTS = {TorrentClient.UTORRENT, TorrentClient.BITTORRENT, TorrentClient.RTORRENT}
LINK_TAG = "torrentlinker:links"
BOARD_TAG = "torrentlinker:board"
BOARD_CHECKING = "torrentlinker:board-checking"


def effective_layout(profile) -> str:
    if profile.client in DISK_RENAME_CLIENTS:
        return "links"
    return "links" if profile.reseed_layout == "links" else "client"


@dataclass(frozen=True)
class ReseedLayout:
    mode: str
    root: str
    mapper: PathMapper
    library_roots: tuple[Path, ...]
    validate_root: Callable[[str], Path] | None = None

    @classmethod
    def for_settings(
        cls, settings: Settings, validate_root: Callable[[str], Path] | None = None
    ) -> ReseedLayout:
        profile = settings.profile()
        return cls(
            effective_layout(profile),
            profile.reseed_link_root,
            PathMapper(settings.path_mappings),
            tuple(folder.path for folder in settings.library_folders),
            validate_root,
        )

    def prepare(self, item: LocalItem, meta: TorrentMeta, match: Match, root: str = "") -> dict:
        if self.mode == "links":
            if not (root or self.root):
                raise ValueError("Choose a Link Folder in this client's Reseed settings first.")
            destination = (
                self.validate_root(root or self.root)
                if self.validate_root
                else Path(root or self.root)
            )
            return {
                **prepare_links(
                    destination,
                    item,
                    meta,
                    match,
                    self.mapper,
                    list(self.library_roots),
                ),
                "layout": "links",
            }
        if match.unwanted or set(match.pairs) != set(meta.files):
            raise ValueError("The Reseed board requires every torrent file.")
        if len(set(match.pairs.values())) != len(match.pairs):
            raise ValueError("Each torrent file needs a separate local file.")
        files = []
        for expected, local in match.pairs.items():
            relative_path(expected)
            source = item.save_path / relative_path(local)
            identity = source_identity(source)
            if identity[2] != meta.files[expected]:
                raise ValueError("A source file changed size. Compare this item again.")
            files.append(
                {"name": expected, "local": local, "source": str(source), "identity": identity}
            )
        return {
            "layout": "client",
            "destination": str(item.save_path),
            "files": files,
            "hash": meta.infohash,
        }


def validate_layout(record: dict) -> None:
    if record.get("layout", "links") == "links":
        validate_links(record)
        return
    if record.get("layout") != "client":
        raise ValueError("Unknown prepared Reseed layout. Compare this item again.")
    for row in record["files"]:
        if source_identity(Path(row["source"])) != row["identity"]:
            raise ValueError("A source file changed since preparation. Compare it again.")


def uses_links(client) -> bool:
    policy = getattr(client, "reseed_policy", None)
    return policy is not None and policy.mode == "links"


def needs_disk_rename_review(client) -> bool:
    return bool(getattr(client, "requires_disk_renames", False)) and not uses_links(client)


def same_unicode_file(save_path: Path, old: str, new: str) -> bool:
    if old == new or unicodedata.normalize("NFC", old) != unicodedata.normalize("NFC", new):
        return False
    source, target = save_path / old, save_path / new
    try:
        return (
            stat.S_ISREG(source.lstat().st_mode)
            and stat.S_ISREG(target.lstat().st_mode)
            and source.samefile(target)
        )
    except OSError:
        return False  # no proven alias: retain the rename and the occupied-source guard


def validate_client_files(record: dict, files: dict[str, int]) -> None:
    """Accept only the prepared paths or proven filesystem normalization aliases."""
    if record.get("layout") != "client":
        return
    remaining = set(files)
    for row in record["files"]:
        local = row["local"]
        candidate = local if local in remaining else row["name"]
        if (
            candidate not in remaining
            or files[candidate] != row["identity"][2]
            or candidate != local
            and not same_unicode_file(Path(record["destination"]), candidate, local)
        ):
            raise ValueError("The client file layout changed. Review the torrent before retrying.")
        remaining.remove(candidate)
    if remaining:
        raise ValueError("The client file layout changed. Review the torrent before retrying.")
