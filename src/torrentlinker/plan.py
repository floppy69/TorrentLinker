"""Plan: which Catalogue torrents to download and seed for Zen or their note.

A greedy fill under each disk's free space and the torrent cap, tried over several
orderings for Zen, or highest initial note first for Note, with smaller downloads
breaking ties. It is a heuristic.
Reseeds come first: they cost no download (ADR-0004).
"""

from __future__ import annotations

import math
import os
import re
import shutil
import unicodedata
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable, Collection, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath

from torrentlinker import ratelimit
from torrentlinker.domain import ItemState, LocalItem, is_adult_category
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.library import LibraryEntry
from torrentlinker.plan_diagnostics import PlanIssue
from torrentlinker.review import CheckedCandidate
from torrentlinker.store import CatalogueRow, SavedPlan, SavedPlanItem
from torrentlinker.zen import GB, ZenProfile, ZenTorrent, added_values, estimate, note, weight

DEFAULT_MARGIN = 0.10  # share of each disk kept free


class PlanGoal(StrEnum):
    ZEN = "zen"
    NOTE = "note"


@dataclass(frozen=True)
class PlanOptions:
    goal: PlanGoal = PlanGoal.NOTE
    max_download_bytes: int = 0  # 0 = no additional limit
    max_torrents: int | None = None  # additional torrents in this Plan, including Reseeds
    max_seeders: int | None = None  # current swarm, before the user joins
    min_size: int = 0  # bytes per torrent; 0 = no minimum
    max_size: int = 0  # bytes per torrent; 0 = no maximum

    def admits(self, size: int, seeders: int) -> bool:
        """Whether a torrent of this size and current swarm may enter the Plan."""
        return (
            (self.max_seeders is None or seeders <= self.max_seeders)
            and size >= self.min_size
            and (self.max_size <= 0 or size <= self.max_size)
        )


@dataclass(frozen=True)
class DiskSpace:
    disk: Hashable
    folder: Path  # one Download Folder representing the disk
    free: int
    reserved: int
    download: int = 0

    @property
    def available(self) -> int:
        return max(0, self.free - self.reserved)

    @property
    def after_plan(self) -> int:
        return self.free - self.download


@dataclass(frozen=True)
class PlanCandidate:
    infohash: str
    title: str
    size: int
    seeders: int  # the swarm without the user
    category: int | None
    folder: Path | None  # Download Folder; None for a Reseed
    disk: Hashable = None
    reseed: bool = False
    source: object = field(default=None, compare=False)  # CatalogueRow, or the Reseed's data

    client_id: str = ""

    @property
    def download_size(self) -> int:
        return 0 if self.reseed else self.size

    def as_zen(self) -> ZenTorrent:
        # Plan candidates start with no cumulative seed time, regardless of release age.
        return ZenTorrent(self.size, self.seeders + 1, 0.0, self.category)


def note_priority(candidate: PlanCandidate, score: float) -> tuple[float, int, str]:
    """Highest individual initial note first; smaller downloads break equal-note ties."""
    return -score, candidate.download_size, candidate.infohash


@dataclass(frozen=True)
class PlanItem:
    candidate: PlanCandidate
    zen: float  # ≈ Zen/day it adds
    note: float | None = None


@dataclass(frozen=True)
class OnDisk:
    """A Catalogue torrent left out of the Plan: its data seems to be on disk already."""

    infohash: str
    title: str
    path: Path  # the local file or Local Item that seems to hold it


@dataclass(frozen=True)
class Plan:
    items: list[PlanItem] = field(default_factory=list)
    zen_added: float = 0.0  # ≈ Zen/day the whole Plan adds to current seeding
    goal: PlanGoal = PlanGoal.ZEN
    disk_spaces: tuple[DiskSpace, ...] = ()
    on_disk: tuple[OnDisk, ...] = ()
    issues: tuple[PlanIssue, ...] = ()

    @property
    def average_note(self) -> float | None:
        values = [(i.note, weight(i.candidate.size)) for i in self.items if i.note is not None]
        return sum(n * w for n, w in values) / sum(w for _, w in values) if values else None

    @property
    def download_size(self) -> int:
        return sum(i.candidate.download_size for i in self.items)

    @property
    def payback_days(self) -> float | None:
        """Days of the added Zen to pay the download back (1 Zen buys 1 Go)."""
        if self.zen_added <= 0:
            return None
        return self.download_size / GB / self.zen_added

    def sending_seconds(self, keys: int) -> float:
        """Time to send the Plan: one .torrent per download from the Indexer, spread over
        the `keys` API keys, each within c411's limits.

        Reseeds fetch nothing new: their .torrent came with the search.
        """
        downloads = sum(1 for i in self.items if not i.candidate.reseed)
        return ratelimit.sending_seconds(downloads, keys)

    def download_seconds(self, bytes_per_second: float) -> float:
        """Time for qBittorrent to download the Plan's data at this speed, at best."""
        return self.download_size / bytes_per_second


def explain_inputs(plan: Plan, issues: Sequence[PlanIssue], existing: Sequence[OnDisk]) -> Plan:
    """Use upstream exclusions when no candidate reached the optimizer."""
    reasons = plan.issues
    if not plan.items and reasons == (PlanIssue("no_candidates"),):
        reasons = tuple(issues) + ((PlanIssue("on_disk", len(existing)),) if existing else ())
        reasons = reasons or plan.issues
    return replace(plan, issues=reasons, on_disk=tuple(existing))


EXTRAS = 64 * 1024  # bytes a torrent may hold beyond the local data: .nfo, cover…
NOISE = frozenset(
    "epub pdf mobi azw azw3 cbz cbr djvu txt doc docx rtf fb2 mp3 m4b flac "
    "french francais vff vf multi notag ebook ebooks livre book books "
    "the and les des une pour avec dans sur par aux".split()
)


def _normalise(title: str) -> str:
    """Title words, lower-cased and accent-stripped, so matches ignore case and accents."""
    plain = unicodedata.normalize("NFKD", title)
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).casefold()
    return plain


def on_disk(candidates: Iterable[PlanCandidate], items: Iterable[LocalItem]) -> list[OnDisk]:
    """Downloads whose data seems already in the Library, compared without any request.

    A Local Item, or one of its files, must be the torrent's size or up to EXTRAS
    smaller, and its name must look like the torrent's: most significant words in common
    (Jaccard ≥ SIMILAR) and no other volume number. Only a search in the Library can
    confirm it, by comparing the torrent's files.
    """
    pieces: list[tuple[int, _Name, Path]] = []
    for item in items:
        pieces.append((item.size, _name(item.path.name), item.path))
        if len(item.files) > 1:
            for name, size in item.files.items():
                pieces.append((size, _name(name), item.save_path / PurePosixPath(name)))
    pieces.sort(key=lambda p: p[0])
    sizes = [p[0] for p in pieces]
    found = []
    for c in candidates:
        if c.reseed:
            continue
        low, high = bisect_left(sizes, c.size - EXTRAS), bisect_right(sizes, c.size)
        if low == high:
            continue
        title = _name(c.title)
        for _size, local, path in pieces[low:high]:
            if _similar(local, title):
                found.append(OnDisk(c.infohash, c.title, path))
                break
    return found


SIMILAR = 0.7  # checked on 1,800 real ebooks: lower lets an author's other books match


@dataclass(frozen=True)
class _Name:
    words: frozenset[str]  # significant words: no accents, case, format or release tag
    numbers: frozenset[int]  # volume or part numbers; years left out


def _name(name: str) -> _Name:
    plain = unicodedata.normalize("NFKD", name)
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).casefold()
    words = frozenset(w for w in re.split(r"[^0-9a-z]+", plain) if len(w) >= 3 and not w.isdigit())
    numbers = frozenset(n for n in map(int, re.findall(r"\d+", plain)) if not 1900 <= n < 2100)
    return _Name(words - NOISE, numbers)


def _similar(a: _Name, b: _Name) -> bool:
    if a.numbers and b.numbers and not a.numbers & b.numbers:
        return False  # T1 and T2 of a series
    shared = len(a.words & b.words)
    if shared == 0 or shared < min(2, len(a.words), len(b.words)):
        return False
    return shared / len(a.words | b.words) >= SIMILAR


def saved_items(plan: Plan) -> list[SavedPlanItem]:
    """The Plan's downloads as saved; Reseeds depend on this session's searches."""
    return [
        SavedPlanItem(
            c.infohash,
            c.title,
            c.size,
            c.seeders,
            c.category,
            str(c.folder),
            i.zen,
            i.note,
            client_id=c.client_id,
        )
        for i in plan.items
        if not (c := i.candidate).reseed and c.folder is not None
    ]


def restore_plan(saved: SavedPlan, rows: Mapping[str, CatalogueRow]) -> Plan:
    """What is left to send of a saved Plan; a torrent gone from the Catalogue is dropped."""
    items = [
        PlanItem(
            PlanCandidate(
                i.infohash,
                i.title,
                i.size,
                i.seeders,
                i.category,
                Path(i.folder),
                source=rows[i.infohash],
                client_id=i.client_id,
            ),
            i.zen,
            i.note,
        )
        for i in saved.pending
        if i.infohash in rows
    ]
    left = sum(i.zen for i in items)
    whole = sum(i.zen for i in saved.items)
    if saved.zen_added is None or whole <= 0:
        return Plan(items, left)
    # The Plan's total counts how its torrents change each other's Zen; keep its share.
    return Plan(items, saved.zen_added * left / whole)


ORDERINGS: dict[str, Callable[[PlanCandidate, float], float]] = {
    "zen per GB": lambda c, v: v / max(c.size / GB, 1e-9),
    "zen": lambda c, v: v,
    "zen per √GB": lambda c, v: v / math.sqrt(max(c.size / GB, 1e-9)),
}


def make_plan(
    profile: ZenProfile,
    candidates: Sequence[PlanCandidate],
    budgets: Mapping[Hashable, int],
    seeding: Sequence[ZenTorrent] = (),
    slots: int | None = None,
    *,
    options: PlanOptions = PlanOptions(),
    disk_spaces: Sequence[DiskSpace] = (),
) -> Plan:
    """Choose candidates within each disk's budget (bytes) and `slots` more torrents."""
    original_count = len(candidates)
    candidates = [c for c in candidates if options.admits(c.size, c.seeders)]
    issues: list[PlanIssue] = []
    if slots is not None and slots <= 0:
        issues.append(PlanIssue("torrent_cap"))
    if options.max_torrents is not None and options.max_torrents <= 0:
        issues.append(PlanIssue("plan_cap"))
    if not profile.zen_class.paid_on_seeding:
        issues.append(PlanIssue("zen_class"))
    elif options.goal is PlanGoal.ZEN and profile.seed_hours <= 0:
        issues.append(PlanIssue("seed_hours"))
    if original_count and not candidates:
        issues.append(PlanIssue("filters", original_count))

    values = added_values(profile, [c.as_zen() for c in candidates], seeding)
    notes = {
        c.infohash: note(profile.zen_class, c.as_zen())
        if profile.zen_class.paid_on_seeding
        else 0.0
        for c in candidates
    }
    valued = [
        (c, v)
        for c, v in zip(candidates, values, strict=True)
        if (v if options.goal is PlanGoal.ZEN else notes[c.infohash]) > 0
    ]
    reseeds = sorted(
        (cv for cv in valued if cv[0].reseed),
        key=lambda cv: (
            note_priority(cv[0], notes[cv[0].infohash])
            if options.goal is PlanGoal.NOTE
            else (-cv[1], 0, "")
        ),
    )
    reseeded = {c.infohash for c, _ in reseeds}
    downloads = [cv for cv in valued if not cv[0].reseed and cv[0].infohash not in reseeded]
    room = slots if slots is not None else len(candidates)
    room = max(0, room)
    if options.max_torrents is not None:
        room = min(room, max(0, options.max_torrents))
    first = reseeds[:room]
    base = estimate(profile, seeding).total
    best = Plan(goal=options.goal, disk_spaces=tuple(disk_spaces))
    if options.goal is PlanGoal.NOTE:
        orderings = [sorted(downloads, key=lambda cv: note_priority(cv[0], notes[cv[0].infohash]))]
    else:
        orderings = [
            sorted(downloads, key=lambda cv, r=rank: -r(cv[0], cv[1]))  # type: ignore[misc]
            for rank in ORDERINGS.values()
        ]
    for ordered in orderings:
        chosen = first + _fill(
            ordered, dict(budgets), room - len(first), options.max_download_bytes
        )
        torrents = [*seeding, *(c.as_zen() for c, _ in chosen)]
        day = estimate(profile, torrents)
        plan = Plan(
            [
                PlanItem(c, z, notes[c.infohash])
                for (c, _), z in zip(chosen, day.per_torrent[len(seeding) :], strict=True)
            ],
            day.total - base,
            options.goal,
            tuple(
                DiskSpace(
                    s.disk,
                    s.folder,
                    s.free,
                    s.reserved,
                    sum(c.download_size for c, _ in chosen if c.disk == s.disk),
                )
                for s in disk_spaces
            ),
        )
        if options.goal is PlanGoal.NOTE or plan.zen_added > best.zen_added:
            best = plan
    if not best.items:
        if not issues and valued:
            blocked = Counter[str]()
            for c, _ in valued:
                if not c.reseed:
                    if c.size > budgets.get(c.disk, 0):
                        blocked["disk_space"] += 1
                    if options.max_download_bytes > 0 and c.size > options.max_download_bytes:
                        blocked["download_limit"] += 1
            issues.extend(PlanIssue(code, count) for code, count in blocked.items())
        if not issues:
            issues.append(PlanIssue("no_gain" if candidates else "no_candidates"))
        best = Plan(goal=options.goal, disk_spaces=tuple(disk_spaces), issues=tuple(issues))
    return best


def _fill(
    ordered: list[tuple[PlanCandidate, float]],
    budgets: dict[Hashable, int],
    room: int,
    max_download_bytes: int = 0,
) -> list[tuple[PlanCandidate, float]]:
    chosen: list[tuple[PlanCandidate, float]] = []
    remaining = max_download_bytes if max_download_bytes > 0 else None
    for c, v in ordered:
        if len(chosen) >= room:
            break
        if budgets.get(c.disk, 0) >= c.size and (remaining is None or c.download_size <= remaining):
            budgets[c.disk] -= c.size
            if remaining is not None:
                remaining -= c.download_size
            chosen.append((c, v))
    return chosen


@dataclass(frozen=True)
class ReseedSource:
    """What a Reseed row needs to run the Reseed flow (ADR-0002)."""

    entry: LibraryEntry
    checked: CheckedCandidate


def reseed_candidates(
    profile: ZenProfile,
    found: Iterable[tuple[LibraryEntry, Sequence[CheckedCandidate]]],
    in_client: set[str],
    seeding: Sequence[ZenTorrent] = (),
    *,
    options: PlanOptions = PlanOptions(),
) -> list[PlanCandidate]:
    """One Reseed row per Orphan with a Full Match, chosen for the Plan's goal.

    Partial Matches are left out: after Verification they stay stopped and earn nothing.
    """
    result = []
    for entry, checked in found:
        if entry.state is not ItemState.ORPHAN:
            continue
        full = [
            v
            for v in checked
            if v.match is not None
            and v.match.is_full
            and v.unpack is None  # a Plan never unpacks: that is the user's choice
            and v.meta is not None
            and v.meta.infohash.lower() not in in_client
            and options.admits(v.candidate.size, v.candidate.seeders)
        ]
        if not full:
            continue
        rows = [_reseed_row(entry, v) for v in full]
        values = (
            added_values(profile, [r.as_zen() for r in rows], seeding)
            if options.goal is PlanGoal.ZEN
            else [note(profile.zen_class, r.as_zen()) for r in rows]
        )
        result.append(max(zip(values, rows, strict=True), key=lambda vr: vr[0])[1])
    return result


def _reseed_row(entry: LibraryEntry, v: CheckedCandidate) -> PlanCandidate:
    assert v.meta is not None
    c = v.candidate
    return PlanCandidate(
        v.meta.infohash.lower(),
        c.title,
        c.size,
        c.seeders,
        c.categories[0] if c.categories else None,
        None,
        None,
        reseed=True,
        source=ReseedSource(entry, v),
    )


def catalogue_candidates(
    rows: Iterable[CatalogueRow],
    folders: DownloadFolders,
    categories: Mapping[int, IndexerCategory],
    in_client: set[str],
    disk_of: Callable[[Path], Hashable],
    only: Collection[int] | None = None,
    plan_exclusions: Iterable[str] = (),
    *,
    issues: list[PlanIssue] | None = None,
    adult: bool = False,
) -> list[PlanCandidate]:
    """Catalogue torrents a Plan may download: not in qBittorrent, alive, in a category
    that has a Download Folder, not carrying an excluded title, not XXX unless `adult`
    (Settings → Adult content), and, if `only` is given, in one of those categories (a
    category includes its subcategories)."""
    resolved: dict[int | None, Path | None] = {}
    disks: dict[Path, Hashable] = {}
    excluded = {unicodedata.normalize("NFKD", w) for w in plan_exclusions}
    excluded = {
        "".join(ch for ch in w if not unicodedata.combining(ch)).casefold() for w in excluded
    }
    result = []
    rejected = Counter[str]()
    count = 0
    for r in rows:
        count += 1
        if r.category is None:
            rejected["unknown_category"] += 1
            continue
        if (only is not None and not _within(r.category, only, categories)) or (
            not adult and is_adult_category(r.category)
        ):
            rejected["category"] += 1
            continue
        if r.infohash.lower() in in_client:
            rejected["in_client"] += 1
            continue
        if r.seeders < 1:
            rejected["no_seeders"] += 1
            continue
        if excluded and any(
            word in excluded for word in re.split(r"[^0-9a-z]+", _normalise(r.title))
        ):
            rejected["excluded_title"] += 1
            continue
        category = r.category
        if category not in resolved:
            resolved[category] = folders.resolve(category, categories)
        folder = resolved[category]
        if folder is None:
            rejected["no_folder"] += 1
            continue
        if folder not in disks:
            disks[folder] = disk_of(folder)
        result.append(
            PlanCandidate(
                r.infohash.lower(),
                r.title,
                r.size,
                r.seeders,
                category,
                folder,
                disks[folder],
                source=r,
            )
        )
    if issues is not None and not result:
        if count > rejected["category"] + rejected["unknown_category"]:
            rejected.pop("category", None)
            rejected.pop("unknown_category", None)
        issues.extend(PlanIssue(code, total) for code, total in rejected.most_common())
        if not count:
            issues.append(PlanIssue("catalogue_empty"))
    return result


def _within(
    category: int, chosen: Collection[int], categories: Mapping[int, IndexerCategory]
) -> bool:
    seen: set[int] = set()
    current: int | None = category
    while current is not None and current not in seen:
        if current in chosen:
            return True
        seen.add(current)
        known = categories.get(current)
        current = known.parent if known else None
    return False


# Disks ------------------------------------------------------------------------


def existing_ancestor(path: Path) -> Path:
    """The folder itself, or its nearest parent that exists (it is created on download)."""
    for p in (path, *path.parents):
        if p.exists():
            return p
    return Path(path.anchor or ".")


def disk_of(path: Path) -> int:
    return os.stat(existing_ancestor(path)).st_dev


def disk_budgets(
    folders: Iterable[Path],
    margin: float = DEFAULT_MARGIN,
    usage: Callable[[Path], tuple[int, int, int]] = shutil.disk_usage,
    disk: Callable[[Path], Hashable] = disk_of,
) -> dict[Hashable, int]:
    """Bytes a Plan may use on each disk holding Download Folders: free space minus a
    margin of the disk's size kept free."""
    return {s.disk: s.available for s in disk_space(folders, margin, usage=usage, disk=disk)}


def disk_space(
    folders: Iterable[Path],
    margin: float = DEFAULT_MARGIN,
    usage: Callable[[Path], tuple[int, int, int]] = shutil.disk_usage,
    disk: Callable[[Path], Hashable] = disk_of,
) -> list[DiskSpace]:
    """One physical-space reading per disk, including disks without eligible torrents."""
    spaces: dict[Hashable, DiskSpace] = {}
    for folder in folders:
        d = disk(folder)
        if d in spaces:
            continue
        total, _used, free = usage(existing_ancestor(folder))
        spaces[d] = DiskSpace(d, folder, free, int(margin * total))
    return list(spaces.values())
