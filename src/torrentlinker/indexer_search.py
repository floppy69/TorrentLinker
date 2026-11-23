"""Native listing controls shared by agent discovery and the desktop search UI."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from torrentlinker.torrent_search import parse_facets, parse_tree

VIDEO_FILTERS = {
    "resolution": ("2160p", "1080p", "720p", "SD"),
    "source": ("BluRay", "Remux", "BDMV", "WEB-DL", "WEBRip", "DVDRip", "HDTV", "SDTV"),
    "codec": ("H.265", "H.264", "H.263", "H.262", "AV1"),
    "hdr": ("SDR", "HDR10", "HDR10+", "DV", "DV.HDR10", "DV.HDR10+"),
    "audioType": ("lossless", "lossy"),
    "channels": ("7.1", "5.1", "2.0", "1.0"),
    "lang": ("MULTI", "VFF", "TRUEFRENCH", "VOSTFR", "VFQ", "VF", "MULTI.VF2", "VF2"),
    "profile": ("compatibility", "pure", "hc_optimized", "optimization"),
}


def visible_facets(tree, category, facets):
    root = tree.root(category)
    return [
        facet
        for facet in facets
        if not (
            root == 1
            and (
                facet.slug == "langue"
                or (facet.slug in {"saison", "episode"} and not tree.series(category))
            )
        )
    ]


class IndexerFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Exact release year; year ranges are not supported.",
    )
    uploader: str = Field(default="", max_length=100)
    team: str = Field(
        default="",
        max_length=100,
        description="Release team name or slug, as on c411's team pages (case-insensitive).",
    )
    options: str = Field(
        default="",
        max_length=500,
        description="CSV option VALUE IDs returned by search_indexer_options, not group IDs.",
    )
    subcat: str = Field(
        default="",
        max_length=500,
        description="CSV positive child IDs within one root; category=-ID selects one child.",
    )
    resolution: str = Field(default="", max_length=100)
    source: str = Field(default="", max_length=200)
    codec: str = Field(default="", max_length=100)
    hdr: str = Field(default="", max_length=100)
    audioType: str = Field(default="", max_length=100)
    channels: str = Field(default="", max_length=100)
    profile: str = Field(default="", max_length=100)
    lang: str = Field(default="", max_length=100)
    exclusive: bool | None = None
    crew: bool | None = None
    palliative: Literal["", "include", "only"] = ""
    palliativeTail: bool | None = None
    sortBy: Literal[
        "createdAt",
        "seeders",
        "leechers",
        "size",
        "completions",
        "comments",
        "name",
        "category",
        "relevance",
    ] = "createdAt"
    sortOrder: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def known_values(self):
        for name, choices in VIDEO_FILTERS.items():
            value = getattr(self, name)
            if value and any(part not in choices for part in value.split(",")):
                raise ValueError(f"Use the exact CSV {name} choices from search_indexer_options.")
        for name in ("options", "subcat"):
            value = getattr(self, name)
            if value and any(
                not part.isascii() or not part.isdigit() or int(part) <= 0
                for part in value.split(",")
            ):
                raise ValueError(f"{name} requires CSV positive native value IDs.")
        return self

    def params(self):
        return {
            key: (str(value).lower() if isinstance(value, bool) else str(value))
            for key, value in self.model_dump().items()
            if value is not None and value != ""
        }

    def validate_native(self, indexer, category, query):
        tree = parse_tree(indexer.search_categories())
        if category is not None and category not in tree.categories:
            raise ValueError(
                "Unknown native category. Read search_indexer_options; do not use Torznab IDs."
            )
        root = tree.root(category)
        params = self.params()
        selected = category
        if self.subcat:
            if category is not None and category < 0:
                raise ValueError("Use category=-child OR filters.subcat, not both.")
            children = [int(value) for value in self.subcat.split(",")]
            roots = {tree.root(-child) for child in children}
            if None in roots or len(roots) != 1 or (root is not None and roots != {root}):
                raise ValueError(
                    "Subcategories must be available children of one selected native root."
                )
            root = roots.pop()
            selected = -children[0] if len(children) == 1 else root
        if root in tree.torznab_only and not set(params) <= {"sortBy", "sortOrder", "subcat"}:
            raise ValueError("Connect the extension to use XXX filters.")
        if any(getattr(self, name) for name in VIDEO_FILTERS) or self.crew:
            if root != 1:
                raise ValueError("Video filters/crew require the native Films & Videos root.")
        if self.options:
            if root is None:
                raise ValueError("Choose a native category before its option values.")
            facets = visible_facets(
                tree, selected, parse_facets(indexer.search_filter_options(root))
            )
            available = {value for facet in facets for _, value in facet.choices}
            if not set(self.options.split(",")).issubset(available):
                raise ValueError(
                    "Unknown or unavailable option values. "
                    "Read search_indexer_options for this category."
                )
        if self.sortBy == "relevance" and not query.strip():
            raise ValueError("Relevance sorting requires a text query.")
        if root is not None:
            params["category"] = str(root)
        if category is not None and category < 0:
            params["subcat"] = str(-category)
        return params


def search_options(indexer, category=None, fallback_categories=None, *, adult=True):
    if not indexer.is_c411:
        return {
            "backend": "torznab",
            "categories": fallback_categories or {},
            "facets": [],
            "advanced_filters_supported": False,
            "note": "Use text/category search; native c411 filters are unavailable here.",
        }
    tree = parse_tree(indexer.search_categories(), adult=adult)
    if category is not None and category not in tree.categories:
        raise ValueError("Unknown native category. Read options without a category first.")
    root = tree.root(category)
    facets = parse_facets(indexer.search_filter_options(root)) if root else []
    return {
        "backend": "c411-native",
        "categories": {str(key): asdict(value) for key, value in tree.categories.items()},
        "category_namespace": "Native roots positive; children negative; NOT Torznab IDs.",
        "root_colors": {str(key): value for key, value in tree.colors.items()},
        "root_category": root,
        "facets": [asdict(facet) for facet in visible_facets(tree, category, facets)],
        "global_filters": {
            "year": {
                "type": "integer",
                "minimum": 1900,
                "maximum": 2100,
                "meaning": "exact release year; no range API",
            },
            "uploader": {"type": "string", "max_length": 100},
            "team": {"type": "string", "max_length": 100, "meaning": "team name or slug"},
            "exclusive": {"type": "boolean"},
            "crew": {"type": "boolean", "root": 1},
            "palliative": {"choices": ["", "include", "only"]},
            "palliativeTail": {"type": "boolean"},
            "sortBy": IndexerFilters.model_json_schema()["properties"]["sortBy"],
            "sortOrder": {"choices": ["asc", "desc"]},
            "subcat": {"meaning": "CSV positive child IDs within one native root"},
            "options": {
                "meaning": "CSV option VALUE IDs from facets. "
                "Season/episode use option IDs, not numeric API fields."
            },
        },
        # XXX without a session: Torznab text/category search only; the panel says why.
        "adult_filters": "extension" if root in tree.torznab_only else "",
        "video_filters": VIDEO_FILTERS if root == 1 else {},
        "filter_schema": IndexerFilters.model_json_schema(),
        "note": "Read root/child IDs then their category options. Use exact returned value IDs. "
        "If this response is compacted, read_assistant_history can read its full archived "
        "receipt in bounded chunks; never invent omitted filter choices.",
    }
