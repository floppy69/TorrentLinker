"""Native c411 search metadata and pagination, separate from Torznab searches."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from torrentlinker.catalogue_sync import ROOTS, SUBCATS, download_url
from torrentlinker.downloads import IndexerCategory
from torrentlinker.indexer import Candidate, Indexer, SearchQuery, publication_time

SERIES_SLUGS = {"serie-tv", "animation-serie", "emission-tv", "serie-documentaire"}


@dataclass(frozen=True)
class SearchTree:
    # Roots use positive native IDs; children negative IDs to avoid ID collisions.
    categories: dict[int, IndexerCategory]
    slugs: dict[int, str]
    colors: dict[int, str] = field(default_factory=dict)  # root ID -> "#rrggbb"
    torznab_only: frozenset[int] = frozenset()  # roots offered through Torznab, no native filters

    def root(self, selected: int | None) -> int | None:
        if selected is None or selected not in self.categories:
            return None
        return self.categories[selected].parent if selected < 0 else selected

    def series(self, selected: int | None) -> bool:
        return selected == 1 or self.slugs.get(selected or 0) in SERIES_SLUGS


ADULT_ROOT = 8  # c411's native XXX category (Torznab 6000)


def parse_tree(payload: dict[str, Any], *, adult: bool = True) -> SearchTree:
    """c411's category tree; without `adult`, XXX is left out (Settings → Adult content)."""
    categories, slugs, colors, torznab_only = {}, {}, {}, set()
    for root in payload["data"]:
        rid = int(root["id"])
        if rid == ADULT_ROOT and not adult:
            continue
        categories[rid] = IndexerCategory(str(root["name"]))
        slugs[rid] = str(root.get("slug", ""))
        if root.get("torznabOnly") is True:
            torznab_only.add(rid)
        if re.fullmatch(r"#[0-9a-fA-F]{6}", str(root.get("color", ""))):
            colors[rid] = str(root["color"])
        for child in root.get("subcategories", []):
            cid = -int(child["id"])
            categories[cid] = IndexerCategory(str(child["name"]), rid)
            slugs[cid] = str(child.get("slug", ""))
    return SearchTree(categories, slugs, colors, frozenset(torznab_only))


@dataclass(frozen=True)
class SearchFacet:
    slug: str
    label: str
    choices: tuple[tuple[str, str], ...]  # label, option-value ID


def parse_facets(payload: dict[str, Any]) -> list[SearchFacet]:
    return [
        SearchFacet(
            str(group["slug"]),
            str(group["name"]),
            tuple((str(v["value"]), str(v["id"])) for v in group["values"]),
        )
        for group in payload["data"]
        if group.get("values")
    ]


@dataclass(frozen=True)
class ListingRow:
    """What the listing shows beyond a Candidate; display only, never ranked on."""

    leechers: int = 0
    completions: int = 0
    comments: int = 0
    uploader: str = ""
    exclusive: bool = False
    freeleech: bool = False
    title: str = ""  # the film, series or album, not the release name
    year: int | None = None
    rating: float | None = None
    kind: str = ""  # movie, tv, game, music, book ...
    poster_url: str = ""  # a TMDB https URL; never fetched by the listing itself
    tags: tuple[tuple[str, str], ...] = ()  # (kind, text): lang, resolution, source, audio, ...
    original_title: str = ""
    runtime: int | None = None  # minutes
    directors: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()
    overview: str = ""
    cast: tuple[str, ...] = ()
    backdrop_url: str = ""  # a TMDB https URL, for the hover card
    language: str = ""  # c411's own wording, e.g. "Multi VF2 (FR + QC inclus)"
    quality: str = ""  # c411's own wording, e.g. "WEB-DL 1080"


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(s for v in value if (s := _text(v.get("name") if isinstance(v, dict) else v)))


def listing_tags(tech: Any) -> tuple[tuple[str, str], ...]:
    """Badges for a row, from c411's parsed `tech` block, in reading order."""
    if not isinstance(tech, dict):
        return ()
    languages = [s for v in tech.get("languages") or [] if (s := _text(v))]
    if len(languages) > 3:  # a release with many dubs would fill the row; the rest are implied
        languages = [*languages[:3], f"+{len(languages) - 3}"]
    audio = " ".join(
        s for s in (_text(tech.get("audioCodec")), _text(tech.get("audioChannels"))) if s
    )
    hdr = _text(tech.get("hdrFormat"))
    tags = (
        ("lang", ".".join(languages)),
        ("resolution", _text(tech.get("resolution"))),
        ("source", _text(tech.get("source"))),
        ("audio", audio),
        ("codec", _text(tech.get("videoCodec"))),
        ("hdr", "" if hdr.upper() == "SDR" else hdr),
    )
    return tuple((kind, text) for kind, text in tags if text)


def parse_listing_row(item: dict[str, Any]) -> ListingRow:
    media: dict[str, Any] = item["media"] if isinstance(item.get("media"), dict) else {}
    year, rating = media.get("year"), media.get("rating")
    poster = _text(item.get("posterUrl"))
    backdrop = _text(media.get("backdropUrl"))
    runtime = media.get("runtime")
    return ListingRow(
        _count(item.get("leechers")),
        _count(item.get("completions")),
        _count(item.get("comments")),
        _text(item.get("uploader")),
        item.get("isExclusive") is True,
        item.get("isFreeleech") is True,
        _text(media.get("title")),
        year if isinstance(year, int) and 1800 <= year <= 2200 else None,
        float(rating) if isinstance(rating, int | float) and 0 < rating <= 10 else None,
        _text(media.get("kind")),
        poster if poster.startswith("https://") else "",
        listing_tags(item.get("tech")),
        _text(media.get("originalTitle")),
        runtime if isinstance(runtime, int) and runtime > 0 else None,
        _strings(media.get("directors")),
        _strings(media.get("genres")),
        _text(media.get("overview")),
        _strings(media.get("cast")),
        backdrop if backdrop.startswith("https://") else "",
        _text(item.get("language")),
        _text(item.get("quality")),
    )


@dataclass(frozen=True)
class SearchPage:
    rows: list[Candidate]
    page: int
    total: int
    per_page: int
    total_pages: int
    labels: dict[str, str]
    palliative: frozenset[str]
    palliative_matches: int | None = None
    palliative_fallback: bool | None = None
    palliative_count: int | None = None
    details: dict[str, ListingRow] = field(default_factory=dict)  # by infohash
    root_counts: dict[int, int] = field(default_factory=dict)  # native root ID -> matches
    subcategory_counts: dict[int, int] = field(default_factory=dict)  # native child ID -> matches
    total_size: int | None = None  # bytes over all matches, when the listing says so

    @property
    def has_more(self) -> bool:
        return bool(self.rows) and self.page < self.total_pages

    @property
    def limited(self) -> bool:
        return self.total > self.per_page * self.total_pages


def _adult_listing(indexer: Indexer, params: dict[str, str], page: int) -> SearchPage | None:
    """XXX, which the key's listing hides: through the signed-in session when there is one,
    else by Torznab (6000 and its children) with only the text and category applied."""
    if indexer.adult_session:
        payload = indexer.adult_read("/api/torrents?" + urlencode(sorted(params.items())))
        if payload is not None:
            return _native_page(indexer, payload)
    cats = tuple(
        SUBCATS[ADULT_ROOT][int(child)]
        for child in params.get("subcat", "").split(",")
        if child.isdigit() and int(child) in SUBCATS[ADULT_ROOT]
    ) or (ROOTS[ADULT_ROOT],)
    found = indexer.search(
        SearchQuery(q=params.get("name", ""), categories=cats, limit=100, offset=(page - 1) * 100)
    )
    return SearchPage(
        found,
        page,
        (page - 1) * 100 + len(found),
        100,
        page + int(len(found) == 100),
        {c.infohash.lower(): "XXX" for c in found if c.infohash},
        frozenset(),
    )


def native_search(indexer: Indexer, params: dict[str, str], page: int = 1) -> SearchPage:
    params = {**params, "page": str(page), "perPage": "100", "viewMode": "flat"}
    if params.get("category") == str(ADULT_ROOT):
        if not indexer.adult_content():
            raise ValueError("Adult content is off in Settings.")
        return _adult_listing(indexer, params, page)  # type: ignore[return-value]
    return _native_page(indexer, indexer.catalogue_json(params))


def _native_page(indexer: Indexer, payload: dict[str, Any]) -> SearchPage:
    rows, labels, palliative, details = [], {}, set(), {}
    for item in payload["data"]:
        h = str(item["infoHash"]).lower()
        if len(h) != 40 or any(ch not in "0123456789abcdef" for ch in h):
            raise ValueError("Invalid torrent hash in search response")
        root, child = item.get("category") or {}, item.get("subcategory") or {}
        native_root, native_child = int(root.get("id") or 0), int(child.get("id") or 0)
        category = SUBCATS.get(native_root, {}).get(native_child) or ROOTS.get(native_root)
        rows.append(
            Candidate(
                str(item["name"]),
                int(item["size"]),
                indexer.unredact(download_url(h)),
                int(item.get("seeders") or 0),
                h,
                f"https://c411.org/torrents/{h}",
                (category,) if category is not None else (),
                published_at=publication_time(item.get("createdAt")),
            )
        )
        labels[h] = " / ".join(str(obj["name"]) for obj in (root, child) if obj.get("name"))
        if item.get("palliativeSince"):
            palliative.add(h)
        details[h] = parse_listing_row(item)
    meta = payload["meta"]
    return SearchPage(
        rows,
        int(meta["page"]),
        int(meta["total"]),
        int(meta["perPage"]),
        int(meta["totalPages"]),
        labels,
        frozenset(palliative),
        meta.get("palliativeMatches"),
        meta.get("palliativeFallback"),
        meta.get("palliativeCount"),
        details,
        _counts(meta.get("categories")),
        _counts(meta.get("subcategories")),
        total_size if isinstance(total_size := meta.get("totalSize"), int) else None,
    )


def _counts(value: Any) -> dict[int, int]:
    """`[{"id": 1, "count": 12}, ...]` from the listing's meta, ignoring malformed entries."""
    if not isinstance(value, list):
        return {}
    return {
        entry["id"]: _count(entry.get("count"))
        for entry in value
        if isinstance(entry, dict) and isinstance(entry.get("id"), int)
    }
