"""Age Ratings on the French CNC scale; ratings from other countries are mapped to it (#127).

A French rating applies on its own. A mapped foreign one is only a suggestion until a person
confirms it, since the scales do not match exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCALE = ("TP", "10", "12", "16", "18")  # Tous publics, −10, −12, −16, −18
FRANCE = "FR"
# Tried in this order when TMDb has no French certification.
FOREIGN = ("US", "GB", "DE")

FRENCH = {
    "tp": "TP",
    "tous publics": "TP",
    "tout public": "TP",
    "u": "TP",
    "0": "TP",
    **{f"{sign}{age}": age for age in ("10", "12", "16", "18") for sign in ("", "-", "−")},
}
MAPPED = {
    "US": {
        "g": "TP",
        "pg": "10",
        "pg-13": "12",
        "r": "16",
        "nc-17": "18",
        "tv-y": "TP",
        "tv-y7": "TP",
        "tv-g": "TP",
        "tv-pg": "10",
        "tv-14": "12",
        "tv-ma": "16",
    },
    "GB": {"u": "TP", "pg": "10", "12": "12", "12a": "12", "15": "16", "18": "18", "r18": "18"},
    "DE": {"0": "TP", "6": "TP", "12": "12", "16": "16", "18": "18"},
}
COUNTRIES = {
    "fr": FRANCE,
    "fra": FRANCE,
    "france": FRANCE,
    "us": "US",
    "usa": "US",
    "united states": "US",
    "gb": "GB",
    "uk": "GB",
    "united kingdom": "GB",
    "de": "DE",
    "deu": "DE",
    "germany": "DE",
    "deutschland": "DE",
    "fsk": "DE",
}


@dataclass(frozen=True)
class Found:
    """A rating read from a source: applied when French, a suggestion otherwise."""

    rating: str  # on the CNC scale
    country: str
    original: str  # as the source wrote it

    @property
    def french(self) -> bool:
        return self.country == FRANCE

    def suggestion(self, source: str) -> dict:
        return {
            "rating": self.rating,
            "country": self.country,
            "original": self.original,
            "source": source,
        }


def rank(rating: str | None) -> int | None:
    """The rating's place on the scale, for comparing with an age limit."""
    return SCALE.index(rating) if rating in SCALE else None


def mapped(country: str, value: str) -> Found | None:
    """A certification from one country, on the French scale."""
    text = value.strip()
    key = text.casefold()
    country = country.upper()
    if country == FRANCE:
        rating = FRENCH.get(key)
    else:
        rating = MAPPED.get(country, {}).get(key)
    return Found(rating, country, text) if rating else None


def parse(value: str) -> Found | None:
    """An NFO's `<mpaa>` or `<certification>`: "FR:12", "France:-12", "Rated R", "FSK 16",
    "US:PG-13 / GB:15"… A French value wins; without a country, a value only the French
    scale writes ("-12", "Tous publics") is French, anything else is tried abroad."""
    found = [f for part in re.split(r"[/|,]", value) if (f := _one(part))]
    return next((f for f in found if f.french), found[0] if found else None)


def _one(value: str) -> Found | None:
    text = re.sub(r"(?i)^\s*rated\s+", "", value).strip()
    if not text or len(text) > 40:
        return None
    match = re.match(r"(?i)^(fsk)\s*(\d+)$", text) or re.match(r"^([^:]+?)\s*:\s*(.+)$", text)
    if match:
        country = COUNTRIES.get(match[1].strip().casefold())
        return mapped(country, match[2]) if country else None
    if text.casefold() in FRENCH and not text.isdigit():
        return mapped(FRANCE, text)
    for country in FOREIGN:
        if found := mapped(country, text):
            return found
    return None


def from_tmdb(certifications: list[tuple[str, str]]) -> Found | None:
    """TMDb's certifications by country: the French one, else the first mapped foreign one."""
    by_country: dict[str, str] = {}
    for country, value in certifications:
        if value.strip() and country.upper() not in by_country:
            by_country[country.upper()] = value
    for country in (FRANCE, *FOREIGN):
        if country in by_country and (found := mapped(country, by_country[country])):
            return found
    return None
