"""Path Mappings: translate between this app's view of a path and qBittorrent's.

qBittorrent in Docker or on a NAS sees the same folders under other paths. The user can
let the app detect the mappings from qBittorrent's own torrents, then check them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from torrentlinker.domain import PathMapping, Torrent, TorrentFile
from torrentlinker.matching import Match
from torrentlinker.qbit import Qbit
from torrentlinker.torrent_meta import TorrentMeta, read_torrent


def _is_windows(path: str) -> bool:
    return "\\" in path or (len(path) >= 2 and path[1] == ":")


def _split(path: str) -> list[str]:
    return [p for p in path.replace("\\", "/").split("/") if p]


def _join(prefix: str, rest: list[str]) -> str:
    sep = "\\" if _is_windows(prefix) else "/"
    if not rest:
        return prefix
    return prefix.rstrip("/\\") + sep + sep.join(rest)


def _strip_prefix(path: str, prefix: str) -> list[str] | None:
    """Remaining segments of `path` under `prefix`, or None if it is not under it."""
    p, pre = _split(path), _split(prefix)
    if _is_windows(prefix):
        p_cmp, pre_cmp = [s.casefold() for s in p], [s.casefold() for s in pre]
    else:
        p_cmp, pre_cmp = p, pre
    if p_cmp[: len(pre_cmp)] != pre_cmp:
        return None
    return p[len(pre) :]


class PathMapper:
    def __init__(self, mappings: Iterable[PathMapping]) -> None:
        self.mappings = list(mappings)

    def to_qbit(self, local: str) -> str:
        translated = self._translate(local, [(m.local, m.qbit) for m in self.mappings])
        if translated is not None:
            return translated
        # Queue destinations are resolved before sending. On Windows this turns
        # a mapped drive into its UNC path; on POSIX it can resolve a symlink.
        # Resolve local roots only on a miss, never remote client paths. Do not
        # cache aliases: a network drive may be remounted between operations.
        aliases = []
        for mapping in self.mappings:
            try:
                aliases.append((str(Path(mapping.local).resolve(strict=True)), mapping.qbit))
            except (OSError, RuntimeError):
                continue  # An unavailable root does not establish an alias.
        translated = self._translate(local, aliases)
        return local if translated is None else translated

    def to_local(self, qbit: str) -> str:
        translated = self._translate(qbit, [(m.qbit, m.local) for m in self.mappings])
        return qbit if translated is None else translated

    @staticmethod
    def _translate(path: str, pairs: list[tuple[str, str]]) -> str | None:
        best: tuple[int, str, list[str]] | None = None
        for src, dst in pairs:
            rest = _strip_prefix(path, src)
            if rest is not None and (best is None or len(_split(src)) > best[0]):
                best = (len(_split(src)), dst, rest)
        return None if best is None else _join(best[1], best[2])


def is_video(data: bytes) -> bool:
    """Whether a torrent is a film or episodes: its largest file is a video."""
    from torrentlinker.media import VIDEO

    files = read_torrent(data).files
    if not files:
        return False
    largest = max(files, key=lambda name: files[name])
    return PurePosixPath(largest).suffix.lower() in VIDEO


class MappedQbit:
    """The Qbit port seen through Path Mappings: callers only ever handle local paths."""

    def __init__(
        self, inner: Qbit, mapper: PathMapper, *, sequential_video: bool = False, reseed_policy=None
    ) -> None:
        self._inner = inner
        self.reseed_policy = reseed_policy
        self._mapper = mapper
        self.sequential_video = sequential_video  # films and episodes download in order

    def tracker_updates_supported(self) -> bool:
        if not all(
            hasattr(self._inner, name)
            for name in ("announce_entries", "apply_announces", "reannounce")
        ):
            return False
        check = getattr(self._inner, "tracker_updates_supported", None)
        return check() if check else True

    def announce_entries(self, hash: str):
        read = getattr(self._inner, "announce_entries", None)
        if read is None:
            raise ValueError("Tracker updates are unsupported by this client.")
        return read(hash)

    def apply_announces(self, hash: str, before, after) -> None:
        apply = getattr(self._inner, "apply_announces", None)
        if apply is None:
            raise ValueError("Tracker updates are unsupported by this client.")
        apply(hash, before, after)

    def reannounce(self, hash: str) -> None:
        announce = getattr(self._inner, "reannounce", None)
        if announce is None:
            raise ValueError("Tracker updates are unsupported by this client.")
        announce(hash)

    @property
    def supports_category_tags(self) -> bool:
        return self._inner.supports_category_tags

    @property
    def requires_disk_renames(self) -> bool:
        return bool(getattr(self._inner, "requires_disk_renames", False))

    @property
    def client_name(self) -> str:
        return str(getattr(self._inner, "client_name", ""))

    @property
    def supports_partial_reseeds(self) -> bool:
        return bool(getattr(self._inner, "supports_partial_reseeds", True))

    @property
    def can_delete_files(self) -> bool:
        return bool(getattr(self._inner, "can_delete_files", True))

    @property
    def reseed_client_id(self) -> str:
        return str(getattr(self._inner, "reseed_client_id", ""))

    def _local(self, t: Torrent) -> Torrent:
        return replace(t, save_path=Path(self._mapper.to_local(str(t.save_path))))

    def torrents(self, tag: str | None = None, with_files: bool = True) -> list[Torrent]:
        return [self._local(t) for t in self._inner.torrents(tag=tag, with_files=with_files)]

    def torrent(self, hash: str, with_files: bool = True) -> Torrent | None:
        t = self._inner.torrent(hash) if with_files else self._inner.torrent(hash, with_files=False)
        return self._local(t) if t else None

    def export_torrent(self, hash: str) -> bytes:
        export = getattr(self._inner, "export_torrent", None)
        if export is None:
            raise ValueError("This client cannot export torrent metadata")
        return export(hash)

    def files(self, hash: str) -> dict[str, int]:
        return self._inner.files(hash)

    def file_listing(self, hash: str) -> list[TorrentFile]:
        return self._inner.file_listing(hash)

    def add(self, data: bytes, save_path: str, tags: list[str]) -> str:
        return self._inner.add(data, self._mapper.to_qbit(save_path), tags)

    def reseed_layout(self, meta: TorrentMeta, match: Match) -> Match:
        prepare = getattr(self._inner, "reseed_layout", None)
        return prepare(meta, match) if prepare else match

    def download(
        self, data: bytes, save_path: str, tags: list[str], *, sequential: bool = False
    ) -> str:
        target = self._mapper.to_qbit(save_path)
        if sequential or (self.sequential_video and is_video(data)):
            return self._inner.download(data, target, tags, sequential=True)
        return self._inner.download(data, target, tags)

    def rename_file(self, hash: str, old: str, new: str) -> None:
        self._inner.rename_file(hash, old, new)

    def set_file_priority(self, hash: str, indexes: list[int], priority: int) -> None:
        self._inner.set_file_priority(hash, indexes, priority)

    def recheck(self, hash: str) -> None:
        self._inner.recheck(hash)

    def piece_states(self, hash: str) -> list[int]:
        return self._inner.piece_states(hash)

    def pause(self, hash: str) -> None:
        self._inner.pause(hash)

    def resume(self, hash: str) -> None:
        self._inner.resume(hash)

    def start(self, hash: str) -> None:
        self._inner.start(hash)

    def remove(self, hash: str, *, delete_files: bool = False) -> None:
        self._inner.remove(hash, delete_files=delete_files)

    def add_tags(self, hash: str, tags: list[str]) -> None:
        self._inner.add_tags(hash, tags)

    def set_category(self, hash: str, category: str) -> bool:
        """Give the torrent a category; False when the client cannot."""
        manage = getattr(self._inner, "manage_control", None)
        if manage is None or "category" not in getattr(self._inner, "management_controls", ()):
            return False
        manage(hash, "category", {"category": category, "tags": []})
        return True

    def add_tags_many(self, hashes: list[str], tags: list[str]) -> None:
        self._inner.add_tags_many(hashes, tags)

    def remove_tags(self, hash: str, tags: list[str]) -> None:
        self._inner.remove_tags(hash, tags)


# Detection and checks ---------------------------------------------------------

ANCESTORS = 4  # how far above each local folder detection looks for qBittorrent's tree
TRIES_PER_PATH = 3  # torrents tried in each qBittorrent save path


@dataclass(frozen=True)
class MappingSuggestion:
    mapping: PathMapping
    torrents: int  # qBittorrent torrents found on this computer through it


@dataclass(frozen=True)
class Detection:
    suggestions: list[MappingSuggestion]
    same_paths: int  # torrents found at the very path qBittorrent reports
    not_found: list[str]  # qBittorrent save paths found nowhere under the given folders


def detect_mappings(
    torrents: Iterable[Torrent],
    folders: Iterable[Path],
    files: Callable[[Torrent], dict[str, int]] = lambda t: t.files,
    is_file: Callable[[Path, int], bool] | None = None,
) -> Detection:
    """Find where qBittorrent's torrents are on this computer, and the mappings that say so.

    `torrents` are as qBittorrent reports them; `files(t)` gives a torrent's files, read
    for a few torrents of each save path only. A torrent's largest file is looked for, by
    name and size, under each folder and the folders above it. The mapping is the part of
    both paths before the end they share.
    """
    is_file = is_file or _is_file_of_size
    by_path: dict[str, list[Torrent]] = {}
    for t in torrents:
        by_path.setdefault(str(t.save_path), []).append(t)
    starts = _starts(folders)
    found: Counter[PathMapping] = Counter()
    same = 0
    not_found = []
    for qbit_path, group in sorted(by_path.items()):
        pair = None
        for t in group[:TRIES_PER_PATH]:
            if not (listed := files(t)):
                continue
            name, size = max(listed.items(), key=lambda f: f[1])
            if pair := _locate(qbit_path, name, size, starts, is_file):
                break
        if pair is None:
            not_found.append(qbit_path)
        elif pair.local == pair.qbit:
            same += len(group)
        else:
            found[pair] += len(group)
    suggestions = [MappingSuggestion(m, n) for m, n in found.most_common()]
    return Detection(suggestions, same, not_found)


def _is_file_of_size(path: Path, size: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size == size
    except OSError:
        return False


def _starts(folders: Iterable[Path]) -> list[Path]:
    """The folders and a few levels above each, where qBittorrent's tree may begin."""
    seen: dict[Path, None] = {}
    for folder in folders:
        for p in [folder, *folder.parents][: ANCESTORS + 1]:
            seen[p] = None
    return list(seen)


def _locate(
    qbit_path: str,
    name: str,
    size: int,
    starts: list[Path],
    is_file: Callable[[Path, int], bool],
) -> PathMapping | None:
    segments = _split(qbit_path)
    file_parts = _split(name)
    for keep in range(len(segments), -1, -1):  # the longest shared end first
        tail = segments[len(segments) - keep :]
        for start in starts:
            local = start.joinpath(*tail) if tail else start
            if is_file(local.joinpath(*file_parts), size):
                return _shortest(str(local), qbit_path)
    return None


def _shortest(local: str, qbit: str) -> PathMapping:
    """The mapping with the end both paths share removed, keeping a folder on each side."""
    a, b = _split(local), _split(qbit)
    fold = _is_windows(local) or _is_windows(qbit)
    while (
        len(a) > 1
        and len(b) > 1
        and (a[-1].casefold() == b[-1].casefold() if fold else a[-1] == b[-1])
    ):
        a, b = a[:-1], b[:-1]
    return PathMapping(_rebuild(local, a), _rebuild(qbit, b))


def _rebuild(original: str, segments: list[str]) -> str:
    if _is_windows(original):
        return "\\".join(segments) if len(segments) > 1 else segments[0] + "\\"
    return "/" + "/".join(segments)


@dataclass(frozen=True)
class MappingCheck:
    mapping: PathMapping | None  # None: torrents outside every mapping
    found: int  # torrents whose folder exists on this computer
    total: int
    missing: list[str]  # some qBittorrent save paths that do not exist here
    probe: str = ""  # empty: not run, "verified": cleaned up successfully, otherwise an error


def check_mappings(
    torrents: Iterable[Torrent],
    mappings: list[PathMapping],
    is_dir: Callable[[Path], bool] = Path.is_dir,
) -> list[MappingCheck]:
    """For each mapping, how many of qBittorrent's torrents it leads to on this computer."""
    mapper = PathMapper(mappings)
    totals: Counter[PathMapping | None] = Counter()
    found: Counter[PathMapping | None] = Counter()
    missing: dict[PathMapping | None, list[str]] = {}
    exists: dict[str, bool] = {}
    for t in torrents:
        qbit_path = str(t.save_path)
        used = _applying(qbit_path, mappings)
        totals[used] += 1
        if qbit_path not in exists:
            exists[qbit_path] = is_dir(Path(mapper.to_local(qbit_path)))
            if not exists[qbit_path]:
                missing.setdefault(used, []).append(qbit_path)
        if exists[qbit_path]:
            found[used] += 1
    return [
        MappingCheck(m, found[m], totals[m], missing.get(m, [])[:5])
        for m in [*mappings, None]
        if totals[m] or m is not None
    ]


def _applying(qbit_path: str, mappings: list[PathMapping]) -> PathMapping | None:
    best = None
    for m in mappings:
        if _strip_prefix(qbit_path, m.qbit) is not None and (
            best is None or len(_split(m.qbit)) > len(_split(best.qbit))
        ):
            best = m
    return best


def unreachable_download_folders(
    folders: Iterable[Path], mappings: list[PathMapping], qbit_default: str
) -> list[Path]:
    """Download Folders qBittorrent probably cannot see: no mapping covers them although
    qBittorrent's own download folder does not exist on this computer (Docker, NAS…)."""
    if not qbit_default or Path(qbit_default).is_dir():
        return []  # qBittorrent seems to share this computer's paths
    mapper = PathMapper(mappings)
    return [f for f in folders if mapper.to_qbit(str(f)) == str(f)]
