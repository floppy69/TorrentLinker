"""Zen rules: how c411 pays Zen for seeding, as one dated data table (ADR-0005).

Sources, as of 2026-10:

- OFFICIAL — c411's guide (c411.org/guide/tokens): nightly payout for the previous
  day; the value of the torrents that count for the Class is summed, multiplied by the
  Class bonus, divided by 7; torrents are grouped by the bonuses that apply to them and
  each group is rounded to the nearest integer; Seed classes are prorated by the
  previous day's seed time with at least 30 minutes per torrent; size weight 0.29 at
  1 GB, 1 at 4 GB, 1.24 at 25 GB; Tanker Class bonus +5 % at 15 torrents up to +35 %
  at 750; the progression tree adds up to +5 %; worked example: a Tanker seeding 15
  films of 4 GB for 90 days (note ≈ 1.7) earns ≈ 4 Zen a day; up to ≈ 0.43 Zen per
  upload a day.
- ZEN LAB — reverse engineering of Zen Lab (zen.mma.dev): the exact weight curve, the
  rarity and seed-age tables, the Swarm Keeper Class bonus and the tree thresholds.
- OFFICIAL EXCERPT — Swarm Keeper scoring table supplied on 2026-10-22: the category
  base is 1.00 except XXX at 0.50, added before seed age and size/seeder bonuses.
  Other Classes' category bases are unconfirmed and still default to 1.00.
- OFFICIAL BONUS PAGE — c411's "Comment votre bonus est calculé", supplied on
  2026-10-22: the bonus adds sources, each under its own maximum. The Class grid
  (Swarm Keeper: +20 % from 5 torrents, +25 % from 15, +20 % from 50, +17.5 % from
  100, +20 % from 150, then +1 % per 50 more up to +25 %); the progression tree, up to
  +5 %, from challenges completed (reported by the profile as treeBonusBp); the shop's
  Pondération badges, added on top even when the grid is at its maximum.

- OFFICIAL FORMULA — c411's "Le calcul en cours", supplied on 2026-10-22:
  payout = round(T × P × S × I ÷ 7 × (1 + B)), with T the torrents counted, P the share
  of the day seeded, S their average weight, I their average note and B the bonus. With
  I averaged by weight, T × S × I is the sum of each torrent's weight × note, which is
  how torrents are counted here; the total is rounded once.

Every figure is an estimate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from urllib.parse import urlsplit

GB = 1_000_000_000  # c411 sizes are decimal: 1 Zen buys 1 Go of download credit
DIVISOR = 7  # OFFICIAL
MIN_SEED_HOURS = 0.5  # OFFICIAL: under 30 minutes a day a torrent counts nothing
MAX_TREE_BONUS = 0.05  # OFFICIAL BONUS PAGE
WEIGHT_EXPONENT = 0.119  # fitted to OFFICIAL FORMULA's 1.01, 1.24 and 1.38
UPLOAD_ZEN_PER_DAY = 0.43  # OFFICIAL, upper figure: rough Reuploader estimate per upload
KEEPER_CATEGORY_BASES = {6000: 0.5}  # OFFICIAL EXCERPT: other listed categories have base 1

# (minimum seed days, bonus) — ZEN LAB
DURATION_STEPS = ((180, 0.5), (90, 0.35), (30, 0.25), (7, 0.1))

# (minimum torrents, bonus), ascending: the last step reached applies. Tanker OFFICIAL
# from +5 % at 15 to +35 % at 750 (steps ZEN LAB); Swarm Keeper ZEN LAB (not monotonic).
TANKER_CLASS_STEPS = ((15, 0.05), (50, 0.1), (100, 0.15), (150, 0.2), (300, 0.25))
KEEPER_CLASS_STEPS = ((5, 0.2), (15, 0.25), (50, 0.2), (100, 0.175), (150, 0.2))


class ZenClass(StrEnum):
    TANKER = "tanker"
    SWARM_KEEPER = "swarm-keeper"
    REUPLOADER = "reuploader"

    @property
    def paid_on_seeding(self) -> bool:
        return self is not ZenClass.REUPLOADER


@dataclass(frozen=True)
class ZenProfile:
    """The user's own parameters that change Zen."""

    zen_class: ZenClass = ZenClass.TANKER
    tree_bonus: float = 0.0  # already unlocked on c411, e.g. 0.05 for +5 % (at most)
    seed_hours: float = 24.0  # per day
    torrent_cap: int = 0  # most torrents the user wants to seed; 0 = no cap
    badge_bonus: float = 0.0  # the shop's Pondération badges, on top of the Class maximum


@dataclass(frozen=True)
class ZenTorrent:
    """What a Zen Estimate needs to know of a torrent.

    `seeders` counts the whole swarm including the user (add 1 for a torrent the user
    does not seed yet). `seed_days` is the user's cumulative seed time on it.
    """

    size: int
    seeders: int
    seed_days: float = 0.0
    category: int | None = None


@dataclass(frozen=True)
class ZenDay:
    """A day of Zen for a set of torrents."""

    per_torrent: list[float] = field(default_factory=list)
    notes: list[float] = field(default_factory=list)
    multiplier: float = 1.0
    uploads: float = 0.0
    total: float = 0.0  # unrounded
    paid: int = 0  # the total rounded once, as c411 pays


# Rules ----------------------------------------------------------------------


def weight(size: int) -> float:
    """Size weight: 1 for a 4 GB film (OFFICIAL FORMULA).

    Up to 4 GB: (0.25 GB + size) / 4.25 GB. Above, it rises slowly; c411 gives 1.01 at
    4.29 GB (4.00 GiB), 1.24 at 25 GB and 1.38 at 60 GB, which a power curve fits within
    their rounding, where a straight line from 4 to 25 GB gives 1.00 at 4.29 GB.
    """
    gb = size / GB
    if gb <= 4:
        return (0.25 + gb) / 4.25
    return float((gb / 4) ** WEIGHT_EXPONENT)


def duration_bonus(seed_days: float) -> float:
    return next((bonus for days, bonus in DURATION_STEPS if seed_days >= days), 0.0)


def rarity_bonus(zen_class: ZenClass, size: int, seeders: int) -> float:
    """ZEN LAB. `seeders` includes the user."""
    gb, n = size / GB, seeders
    if zen_class is ZenClass.TANKER:
        if n < 41 or n > 250:
            return 0.0
        crowded = n >= 201
        if gb < 1:
            return 0.35 if crowded else 0.2
        return 0.35 if gb < 50 or crowded else 0.5
    if zen_class is ZenClass.SWARM_KEEPER:
        if n < 1:
            return 0.0
        if gb < 1:
            return 0.2 if n <= 24 else 0.0
        if gb < 5:
            if n <= 10 or 25 <= n <= 50:
                return 0.35
            return 0.2 if n <= 24 else 0.0
        if gb < 10:
            return 0.35 if n <= 50 else 0.0
        if gb < 50:
            return 0.5 if n <= 10 else 0.35 if n <= 50 else 0.0
        if gb < 100:
            return 0.5 if n <= 50 else 0.0
        return 0.5 if n <= 50 else 0.35 if n <= 199 else 0.0
    return 0.0


def note(zen_class: ZenClass, t: ZenTorrent) -> float:
    """Contribution note: category base + size/seeder bonus + seed-age bonus."""
    return (
        category_base(zen_class, t.category)
        + rarity_bonus(zen_class, t.size, t.seeders)
        + duration_bonus(t.seed_days)
    )


def class_bonus(zen_class: ZenClass, count: int) -> float:
    if zen_class is ZenClass.TANKER:
        if count >= 500:
            return 0.3 + 0.01 * min(5, (count - 500) // 50)
        steps = TANKER_CLASS_STEPS
    elif zen_class is ZenClass.SWARM_KEEPER:
        if count >= 200:
            return min(0.25, 0.2 + (count // 50 - 3) * 0.01)
        steps = KEEPER_CLASS_STEPS
    else:
        return 0.0
    bonus = 0.0
    for n, b in steps:
        if count >= n:
            bonus = b
    return bonus


def day_share(seed_hours: float) -> float:
    """Share of a full day's pay for the hours seeded."""
    return 0.0 if seed_hours < MIN_SEED_HOURS else min(seed_hours, 24.0) / 24.0


def category_base(zen_class: ZenClass, category: int | None) -> float:
    if zen_class is ZenClass.SWARM_KEEPER and category is not None:
        return KEEPER_CATEGORY_BASES.get(category // 1000 * 1000, 1.0)
    return 1.0


# Estimates --------------------------------------------------------------------


def extra_bonus(profile: ZenProfile) -> float:
    """The tree bonus c411 grants (never inferred: its challenges take time) and badges."""
    return min(profile.tree_bonus, MAX_TREE_BONUS) + profile.badge_bonus


def estimate(profile: ZenProfile, torrents: Sequence[ZenTorrent], uploads: int = 0) -> ZenDay:
    """Zen a day for seeding `torrents` (plus `uploads` for a Reuploader)."""
    upload_zen = uploads * UPLOAD_ZEN_PER_DAY if profile.zen_class is ZenClass.REUPLOADER else 0
    if not profile.zen_class.paid_on_seeding or not torrents:
        zeros = [0.0] * len(torrents)
        return ZenDay(zeros, zeros, 1.0, upload_zen, upload_zen, round(upload_zen))
    cls = profile.zen_class
    notes = [note(cls, t) for t in torrents]
    values = [n * weight(t.size) for n, t in zip(notes, torrents, strict=True)]
    multiplier = 1 + class_bonus(cls, len(torrents)) + extra_bonus(profile)
    scale = multiplier / DIVISOR * day_share(profile.seed_hours)
    per_torrent = [v * scale for v in values]
    total = sum(per_torrent)
    return ZenDay(per_torrent, notes, multiplier, upload_zen, total + upload_zen, round(total))


def added_values(
    profile: ZenProfile, torrents: Sequence[ZenTorrent], alongside: Sequence[ZenTorrent] = ()
) -> list[float]:
    """Zen Estimate of each of `torrents` if one of them were added to `alongside`.

    Fast: the Class multiplier is that of `alongside` plus one torrent, so thousands of
    Catalogue torrents can be ranked at once.
    """
    if not profile.zen_class.paid_on_seeding or not torrents:
        return [0.0] * len(torrents)
    cls = profile.zen_class
    count = len(alongside) + 1
    scale = (
        (1 + class_bonus(cls, count) + extra_bonus(profile))
        / DIVISOR
        * day_share(profile.seed_hours)
    )
    return [note(cls, t) * weight(t.size) * scale for t in torrents]


def torrent_zen(
    profile: ZenProfile, torrent: ZenTorrent, alongside: Sequence[ZenTorrent] = ()
) -> float:
    """Zen Estimate of one torrent seeded alongside the user's current torrents."""
    return added_values(profile, [torrent], alongside)[0]


def compare_classes(
    profile: ZenProfile, torrents: Sequence[ZenTorrent], uploads: int = 0
) -> dict[ZenClass, ZenDay]:
    """What the same seeding would earn in each Class.

    The tree bonus already unlocked belongs to the current Class; the others start
    their tree at 0. Shop badges count in every Class. The Reuploader figure is rough: it
    counts `uploads` at the guide's upper figure per upload.
    """
    return {
        c: estimate(
            replace(
                profile,
                zen_class=c,
                tree_bonus=profile.tree_bonus if c is profile.zen_class else 0.0,
            ),
            torrents,
            uploads,
        )
        for c in ZenClass
    }


def is_indexer_torrent(tracker: str, indexer_url: str) -> bool:
    """Same-site trackers, including c411's alternate announce host."""
    host = _host(tracker)
    site = ".".join(_host(indexer_url).split(".")[-2:])
    if site == "c411.org" and host == "tk.c411.tw":
        return True
    return bool(host and site) and (host == site or host.endswith("." + site))


def _host(url: str) -> str:
    return (urlsplit(url if "//" in url else "//" + url).hostname or "").lower()


def seed_days(seeding_time: float) -> float:
    """Cumulative seed days from qBittorrent's seeding time in seconds.

    A lower bound of c411's count: qBittorrent forgets time seeded before the torrent
    was (re)added.
    """
    return seeding_time / 86400
