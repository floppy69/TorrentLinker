"""Bounded, read-only Seeding pages using the desktop's Zen calculation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from torrentlinker.category_tags import category_path
from torrentlinker.seeding import Seeding
from torrentlinker.torrent_management import status, tracker_groups
from torrentlinker.zen import ZenProfile, compare_classes, weight


class SeedingFilters(BaseModel):
    state: str = ""
    tracker: str = ""
    tag: str = ""
    size_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    size_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    note_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    zen_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    weight_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    seed_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    days_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    def matches(self, row: dict[str, Any]) -> bool:
        if self.state and self.state != row["status"]:
            return False
        if self.tracker and self.tracker not in row["trackers"]:
            return False
        if self.tag and self.tag not in row["tags"]:
            return False
        for field, key, minimum in (
            ("size_min", "size", True),
            ("size_max", "size", False),
            ("note_min", "note", True),
            ("zen_min", "zen", True),
            ("weight_min", "weight", True),
            ("seed_max", "seeders", False),
            ("days_min", "seed_days", True),
        ):
            threshold = getattr(self, field)
            value = row[key]
            if threshold is not None and (
                value is None or (value < threshold if minimum else value > threshold)
            ):
                return False
        return True


def seeding_page(
    view: Seeding,
    profile: ZenProfile,
    uploads: int,
    *,
    query: str = "",
    filters: SeedingFilters | None = None,
    group: str = "",
    descendants: bool = False,
    sort: str = "zen",
    descending: bool = True,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Return category aggregates and one bounded, globally sorted torrent page.

    Parent totals include descendants. Unfiltered account totals and class estimates
    are independent of pagination and text filters. No private tracker URLs are exposed.
    """
    groups: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    matched = 0
    filters = filters or SeedingFilters()
    states: set[str] = set()
    trackers: set[str] = set()
    tags: set[str] = set()
    categories = {}
    for row in view.rows:
        torrent = row.torrent
        path = category_path(row.category, view.categories)
        keys = [path[:n] for n in range(1, len(path) + 1)] or [()]
        names = [view.categories[cid].name if cid in view.categories else str(cid) for cid in path]
        identity = "/".join(map(str, path)) if path else "unknown"
        record: dict[str, Any] = {
            "hash": torrent.hash,
            "name": torrent.name,
            "category": " / ".join(names),
            "category_id": identity,
            "size": torrent.total_size,
            "seeders": torrent.swarm_seeders if torrent.swarm_seeders >= 0 else None,
            "seed_days": torrent.seeding_time / 86400,
            "zen": row.zen,
            "note": row.note,
            "weight": weight(torrent.total_size),
            "ratio": torrent.ratio,
            "provisional_category": row.provisional_category,
            "seeding": torrent.is_seeding,
            "status": status(torrent),
            "trackers": list(tracker_groups(torrent)),
            "tags": sorted(torrent.tags),
        }
        states.add(record["status"])
        trackers.update(record["trackers"])
        tags.update(record["tags"])
        for depth, key in enumerate(keys):
            categories["/".join(map(str, key)) if key else "unknown"] = " / ".join(
                names[: depth + 1]
            )
        if not filters.matches(record):
            continue
        if query.strip().casefold() not in " ".join([torrent.name, *names]).casefold():
            continue
        matched += 1
        parent = ""
        for key in keys:
            identity = "/".join(map(str, key)) if key else "unknown"
            info = view.categories.get(key[-1]) if key else None
            summary = groups.setdefault(
                identity,
                {
                    "id": identity,
                    "parent": parent,
                    "category": key[-1] if key else None,
                    "name": info.name if info else "",
                    "count": 0,
                    "direct_count": 0,
                    "size": 0,
                    "zen": 0.0,
                    "note_sum": 0.0,
                    "note_count": 0,
                },
            )
            summary["count"] += 1
            summary["size"] += torrent.total_size
            summary["zen"] += row.zen or 0
            if row.note is not None:
                summary["note_sum"] += row.note
                summary["note_count"] += 1
            parent = identity
        groups[parent]["direct_count"] += 1
        if group == "all" or parent == group or descendants and parent.startswith(group + "/"):
            rows.append(record)
    for summary in groups.values():
        count = summary.pop("note_count")
        total = summary.pop("note_sum")
        summary["note"] = total / count if count else None
    # Unknown metrics sort last in either direction, never as known zeros.
    known = [r for r in rows if r[sort] is not None]
    unknown = [r for r in rows if r[sort] is None]
    known.sort(key=lambda r: r["hash"])
    known.sort(
        key=lambda r: r[sort].casefold() if isinstance(r[sort], str) else r[sort],
        reverse=descending,
    )
    rows = known + sorted(unknown, key=lambda r: r["hash"])
    return {
        "groups": list(groups.values()),
        "filter_options": {
            "state": sorted(states),
            "tracker": sorted(trackers),
            "tag": sorted(tags),
            "category": [
                {"value": key, "label": value}
                for key, value in sorted(categories.items(), key=lambda item: item[1].casefold())
            ],
        },
        "rows": rows[offset : offset + limit],
        "total": len(rows),
        "offset": offset,
        "matched": matched,
        "summary": {
            "count": view.count,
            "total": len(view.rows),
            "daily": view.day.total,
            "paid": view.day.paid,
        },
        "classes": [
            {"id": cls.value, "daily": day.total, "current": cls == profile.zen_class}
            for cls, day in compare_classes(profile, view.active, uploads).items()
        ],
        "uploads": uploads,
    }
