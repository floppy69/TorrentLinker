"""Turn an Orphan's Candidates into Matches, and remember them between launches."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from torrentlinker.archives import ArchiveError, Unpacked, unpack, unpacked
from torrentlinker.disk_rename import RenameApproval
from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.indexer import Candidate, Indexer, SearchMode
from torrentlinker.matching import FileComparison, Match, MatchRules, compare, is_plausible, match
from torrentlinker.qbit import Qbit
from torrentlinker.queries import ExternalIds, build_queries, find_ids, parse_name
from torrentlinker.reseed import start_reseed
from torrentlinker.scan import scan_item
from torrentlinker.store import Store
from torrentlinker.tmdb import Tmdb
from torrentlinker.torrent_meta import TorrentMeta, read_torrent
from torrentlinker.zen import ZenProfile, ZenTorrent, torrent_zen


@dataclass(frozen=True)
class CheckedCandidate:
    candidate: Candidate
    meta: TorrentMeta | None = None
    comparison: FileComparison | None = None
    match: Match | None = None
    # Set when the Match is with the archive's contents: Reseeding means unpacking first.
    unpack: Unpacked | None = None

    @property
    def compared(self) -> bool:
        return self.meta is not None


def candidate_key(candidate: Candidate) -> str:
    """Stable identity of a Candidate, used for Rejections. Never contains the API key."""
    return candidate.infohash or candidate.details_url or candidate.download_url.split("?")[0]


def search_candidates(
    indexer: Indexer,
    item: LocalItem,
    kind: ContentKind,
    categories: tuple[int, ...],
    caps_modes: dict[SearchMode, set[str]] | None,
    tmdb: Tmdb | None = None,
    override: str | None = None,
) -> list[Candidate]:
    """Run the item's queries in order (ID first, then name) until one finds Candidates."""
    ids = find_ids(item)
    if tmdb and not (ids.imdb or ids.tmdb) and kind.has_external_ids:
        info = parse_name(item)
        try:
            found = tmdb.lookup(str(info.get("title", "")), info.get("year"), kind)
        except Exception:  # noqa: BLE001 - the lookup is a best-effort hint
            found = None
        ids = ExternalIds(tmdb=found)
    for query in build_queries(item, kind, categories, ids, caps_modes, override):
        if candidates := indexer.search(query):
            return candidates
    return []


def catalogue_candidates(store: Store, indexer: Indexer, item: LocalItem) -> list[Candidate]:
    """Catalogue torrents of the item's exact size: checked before any search, they cost
    `.torrent` downloads but none of the hourly search budget."""
    return [
        Candidate(
            r.title,
            r.size,
            indexer.unredact(r.download_url),
            r.seeders,
            r.infohash,
            r.details_url,
            categories=(r.category,) if r.category is not None else (),
            metadata={"discovery": "catalogue"},
        )
        for r in store.catalogue_sized(item.size)
    ]


# Files this small match by size by coincidence too often to be worth a comparison.
LAYOUT_MIN_FILE_SIZE = 256 * 1024


def index_cached_layouts(store: Store) -> None:
    """Read every cached .torrent not yet in the layout index (no network)."""
    for key in store.unindexed_torrent_keys():
        data = store.cached_torrent(key)
        try:
            meta = read_torrent(data) if data is not None else None
        except Exception:  # noqa: BLE001 - an unreadable cache file is skipped for good
            meta = None
        store.index_layout(key, meta.infohash if meta else "", meta.files if meta else {})


def layout_candidates(
    store: Store,
    indexer: Indexer,
    item: LocalItem,
    rules: MatchRules,
    rejections: Mapping[str, str] = {},
    known: frozenset[str] = frozenset(),
) -> list[CheckedCandidate]:
    """Matches among the .torrent files already cached, found by the item's file sizes
    whatever the torrent's total: a season pack of which a few episodes are missing
    locally, or a torrent of one episode of a local season folder. Costs no request;
    only Matches are kept, and only torrents the Catalogue knows, so each has its page."""
    index_cached_layouts(store)
    sizes = {
        s
        for p, s in item.files.items()
        if s >= LAYOUT_MIN_FILE_SIZE and not rules.ignore.matches(p)
    }
    result: list[CheckedCandidate] = []
    seen = set(known)
    for key, infohash in store.layouts_holding(sizes) if sizes else []:
        row = store.catalogue_row(infohash) if infohash else None
        if row is None or infohash in seen:
            continue
        data = store.cached_torrent(key)
        if data is None:
            continue
        candidate = Candidate(
            row.title,
            row.size,
            indexer.unredact(row.download_url),
            row.seeders,
            row.infohash,
            row.details_url,
            categories=(row.category,) if row.category is not None else (),
            metadata={"discovery": "layout"},
        )
        if candidate_key(candidate) in rejections:
            continue
        checked = _compared(item, candidate, read_torrent(data), rules)
        if checked.match is not None:
            indexer.keep_torrent(candidate, data)
            result.append(checked)
            seen.add(infohash)
    return result


def find_candidates(
    store: Store,
    indexer: Indexer,
    item: LocalItem,
    search: Callable[[], list[Candidate]],
    rules: MatchRules,
    rejections: Mapping[str, str] = {},
    *,
    use_catalogue: bool = True,
) -> tuple[list[Candidate], list[CheckedCandidate]]:
    """Candidates and their checks: the Catalogue first, then cached torrents holding
    the item's files, then `search` unless these already gave a Full Match. A typed
    query (`use_catalogue=False`) always searches. Returns every Candidate, to
    remember, and every check, in that order."""
    found: list[Candidate] = catalogue_candidates(store, indexer, item) if use_catalogue else []
    checked = check_candidates(indexer, item, found, rules, rejections)
    known = {(c.infohash or "").lower() for c in found if c.infohash}
    if use_catalogue:
        layouts = layout_candidates(store, indexer, item, rules, rejections, frozenset(known))
        found += [v.candidate for v in layouts]
        checked += layouts
        known |= {(v.candidate.infohash or "").lower() for v in layouts}
    if any(v.match is not None and v.match.is_full for v in checked):
        return found, checked
    searched = [c for c in search() if not c.infohash or c.infohash.lower() not in known]
    return found + searched, checked + check_candidates(indexer, item, searched, rules, rejections)


def check_candidates(
    indexer: Indexer,
    item: LocalItem,
    candidates: Iterable[Candidate],
    rules: MatchRules,
    rejections: Mapping[str, str] = {},
) -> list[CheckedCandidate]:
    """Fetch the .torrent of every size-plausible, non-rejected Candidate and compare files.

    An archive is also compared by what it holds: its unpacked size, then its files.
    """
    result = []
    inside = unpacked(item)
    for c in candidates:
        if candidate_key(c) in rejections:
            continue
        if not is_plausible(c.size, item, rules.size_tolerance) and not (
            inside and is_plausible(c.size, inside.item, rules.size_tolerance)
        ):
            result.append(CheckedCandidate(c))
            continue
        result.append(check_candidate(indexer, item, c, rules))
    return result


def remember_candidates(
    store: Store, indexer: Indexer, item_path: Path, candidates: Iterable[Candidate]
) -> None:
    """Keep the last search's Candidates, so the Library shows them at the next launch."""
    rows = [{**asdict(c), "download_url": indexer.redact(c.download_url)} for c in candidates]
    store.remember_candidates(item_path, json.dumps(rows))


def remembered_candidates(
    store: Store, indexer: Indexer, item_path: Path
) -> list[Candidate] | None:
    """The Candidates of the Local Item's last search, or None if it was never searched."""
    text = store.remembered_candidates(item_path)
    if text is None:
        return None
    candidates = []
    for row in json.loads(text):
        row["download_url"] = indexer.unredact(row["download_url"])
        row["categories"] = tuple(row.get("categories", ()))
        candidates.append(Candidate(**row))
    return candidates


def restore_checked(
    indexer: Indexer,
    item: LocalItem,
    candidates: Iterable[Candidate],
    rules: MatchRules,
    rejections: Mapping[str, str] = {},
) -> list[CheckedCandidate]:
    """Compare remembered Candidates again using only cached .torrent files (no network)."""
    result = []
    for c in candidates:
        if candidate_key(c) in rejections:
            continue
        data = indexer.cached_torrent(c)
        if data is None:
            result.append(CheckedCandidate(c))
            continue
        result.append(_compared(item, c, read_torrent(data), rules))
    return result


def check_candidate(
    indexer: Indexer, item: LocalItem, candidate: Candidate, rules: MatchRules
) -> CheckedCandidate:
    return _compared(item, candidate, read_torrent(indexer.fetch_torrent(candidate)), rules)


def _compared(
    item: LocalItem, candidate: Candidate, meta: TorrentMeta, rules: MatchRules
) -> CheckedCandidate:
    plain = CheckedCandidate(
        candidate,
        meta,
        compare(item, meta.files, rules.ignore),
        match(item, meta.files, rules),
    )
    if candidate.metadata.get("discovery") == "compatible":
        return (
            plain
            if plain.match is not None and not plain.match.unwanted
            else replace(plain, match=None)
        )
    if plain.match is not None and plain.match.is_full:
        return plain
    inside = unpacked(item)
    found = match(inside.item, meta.files, rules) if inside else None
    if inside is None or found is None:
        return plain
    if plain.match is not None and plain.match.coverage >= found.coverage:
        return plain
    return CheckedCandidate(
        candidate, meta, compare(inside.item, meta.files, rules.ignore), found, inside
    )


def compare_candidate(
    item: LocalItem, candidate: Candidate, meta: TorrentMeta, rules: MatchRules
) -> CheckedCandidate:
    """The Candidate's Match with the item, from a .torrent already in hand."""
    return _compared(item, candidate, meta, rules)


def unpack_and_reseed(
    qbit: Qbit,
    store: Store,
    checked: CheckedCandidate,
    rules: MatchRules,
    progress: Callable[[int, int], None] = lambda done, total: None,
    *,
    approve_disk_renames: RenameApproval | None = None,
    before_reseed: Callable[[], None] = lambda: None,
) -> tuple[str, LocalItem]:
    """Unpack the archive into its new folder, then Reseed the torrent against it.

    The unpacked files are compared again before the Reseed, which still verifies them.
    """
    if checked.unpack is None or checked.meta is None:
        raise ArchiveError("this Candidate is not a Match with an archive's contents")
    unpack(checked.unpack, progress)
    local = scan_item(checked.unpack.item.path)
    found = match(local, checked.meta.files, rules)
    if found is None:
        raise ArchiveError("the unpacked files do not match the torrent")
    before_reseed()
    key = candidate_key(checked.candidate)
    h = start_reseed(
        qbit,
        store,
        local,
        checked.meta,
        found,
        key,
        approve_disk_renames=approve_disk_renames,
    )
    # Once Verification passes, the user is offered to put the archive in the trash.
    store.remember_unpacked(local.path, checked.unpack.archive)
    return h, local


def match_zen(
    profile: ZenProfile,
    checked: Iterable[CheckedCandidate],
    alongside: Sequence[ZenTorrent] = (),
) -> float | None:
    """Zen Estimate of the best Match once reseeded, or None without a Match.

    The user joins the Candidate's seeders, with a seed age of 0.
    """
    values = [
        torrent_zen(profile, ZenTorrent(v.candidate.size, v.candidate.seeders + 1), alongside)
        for v in checked
        if v.match is not None
    ]
    return max(values) if values else None
