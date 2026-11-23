"""Optional TMDb lookup of a title, for searching an Indexer by ID."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from torrentlinker import net
from torrentlinker.domain import ContentKind

API = "https://api.themoviedb.org/3"


@dataclass(frozen=True)
class TmdbInfo:
    """What TMDb says of a film or series, in French where it has it."""

    id: str
    type: str  # `movie` or `tv`, as c411's by-tmdb lookup spells it
    title: str  # the French title
    original_title: str
    year: str
    overview: str
    raw: dict[str, Any]  # the details answer, sent to c411 as the Draft's tmdbData


class Tmdb:
    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        self._key = api_key
        self._http = http or net.client(timeout=15)

    def _get(self, path: str, params: dict[str, str]) -> Any:
        headers = {}
        if len(self._key) > 40:  # a v4 read access token
            headers["Authorization"] = f"Bearer {self._key}"
        else:
            params = {**params, "api_key": self._key}
        response = self._http.get(API + path, params=params, headers=headers)
        response.raise_for_status()
        return response.json()

    def lookup(self, title: str, year: int | None, kind: ContentKind) -> str | None:
        if kind is ContentKind.MOVIE:
            path, year_param = "/search/movie", "year"
        elif kind is ContentKind.SERIES:
            path, year_param = "/search/tv", "first_air_date_year"
        else:
            return None
        params = {"query": title}
        if year:
            params[year_param] = str(year)
        results = self._get(path, params).get("results") or []
        return str(results[0]["id"]) if results else None

    def details(self, tmdb_id: str, media_type: str) -> TmdbInfo | None:
        """The French title, original title, year and synopsis of an id; None if unknown."""
        if media_type not in ("movie", "tv"):
            return None
        data = self._get(f"/{media_type}/{int(tmdb_id)}", {"language": "fr-FR"})
        if not isinstance(data, dict) or not data.get("id"):
            return None
        tv = media_type == "tv"
        return TmdbInfo(
            id=str(data["id"]),
            type=media_type,
            title=str(data.get("name" if tv else "title") or ""),
            original_title=str(data.get("original_name" if tv else "original_title") or ""),
            year=str(data.get("first_air_date" if tv else "release_date") or "")[:4],
            overview=str(data.get("overview") or ""),
            raw={**data, "media_type": media_type},
        )

    def certifications(self, tmdb_id: str, media_type: str) -> list[tuple[str, str]]:
        """Each country's age certification of a film (release dates) or series (content
        ratings), for Age Ratings."""
        if media_type == "movie":
            data = self._get(f"/movie/{int(tmdb_id)}/release_dates", {})
            return [
                (str(r.get("iso_3166_1") or ""), str(d.get("certification") or ""))
                for r in data.get("results") or []
                for d in r.get("release_dates") or []
            ]
        if media_type == "tv":
            data = self._get(f"/tv/{int(tmdb_id)}/content_ratings", {})
            return [
                (str(r.get("iso_3166_1") or ""), str(r.get("rating") or ""))
                for r in data.get("results") or []
            ]
        return []

    def videos(self, tmdb_id: str, media_type: str) -> list[dict]:
        """Trailer links only. Media bytes are never requested or downloaded here."""
        import re

        if media_type not in {"movie", "tv"}:
            return []
        data = self._get(f"/{media_type}/{int(tmdb_id)}/videos", {"language": "fr-FR"})
        return [
            {
                "key": row["key"],
                "name": str(row.get("name", "Trailer"))[:150],
                "language": str(row.get("iso_639_1", "")),
                "official": bool(row.get("official")),
            }
            for row in data.get("results", [])
            if row.get("site") == "YouTube"
            and row.get("type") in {"Trailer", "Teaser"}
            and re.fullmatch(r"[A-Za-z0-9_-]{11}", str(row.get("key", "")))
        ]
