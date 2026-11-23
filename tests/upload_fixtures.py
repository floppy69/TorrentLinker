"""External tracker boundary for Upload acceptance tests."""

import json
from pathlib import Path
from typing import Any

from torrentlinker.indexer import Candidate, SearchQuery

FIXTURES = Path(__file__).parent / "fixtures"


class StubIndexer:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.searches: list[SearchQuery] = []
        self.found: list[Candidate] = []
        self.search_error: Exception | None = None
        self.options_asked: list[int] = []
        self.by_ids: list[dict[str, str]] = []

    def search(self, query: SearchQuery) -> list[Candidate]:
        self.searches.append(query)
        if self.search_error:
            raise self.search_error
        return self.found

    def by_tmdb(self, ids: dict[str, str]) -> list[Candidate]:
        self.by_ids.append(ids)
        return self.found

    def save_draft(self, body: dict[str, Any]) -> int:
        self.saved.append(body)
        return 7

    def drafts(self) -> list[dict[str, Any]]:
        return [{"name": b["title"], "subcategory": {"name": "Objets"}} for b in self.saved]

    def category_options(self, subcategory: int) -> dict[str, Any]:
        self.options_asked.append(subcategory)
        if subcategory in (6, 51):
            return json.loads((FIXTURES / f"c411_options_{subcategory}.json").read_text("utf-8"))
        return {"data": []}
