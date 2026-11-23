"""The Indexers Settings section on the desktop: the same operations as `/api/indexers*`
and `/api/cross-seed/settings`, called on the Setup instead of over HTTP."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from torrentlinker.web.setup import (
    CrossSeedRules,
    IndexerEntry,
    IndexerHubEntry,
    IndexerHubImport,
    Setup,
)


class IndexersPanel:
    def __init__(self, setup: Setup) -> None:
        self.setup = setup

    def request(self, path: str, body: dict[str, Any] | None = None, method: str = "GET") -> Any:
        setup, body = self.setup, body or {}
        parts = path.strip("/").split("/")
        if parts[0] == "cross-seed" and len(parts) == 2:
            rules = {
                "settings": lambda: CrossSeedRules(**body),
                "pause": lambda: CrossSeedRules(paused=True),
                "resume": lambda: CrossSeedRules(paused=False),
            }.get(parts[1])
            if rules is None:
                raise ValueError("Unknown Indexers operation.")
            return setup.set_cross_seed(rules())
        if parts[0] != "indexers":
            raise ValueError("Unknown Indexers operation.")
        if len(parts) == 1:
            if method == "GET":
                return {
                    "indexers": setup.indexer_rows(),
                    "cross_seed": asdict(setup.settings.cross_seed),
                }
            return setup.add_indexer(IndexerEntry(**body))
        if parts[1] == "probe":
            return setup.probe_indexer(IndexerEntry(**body))
        if parts[1] == "hub":
            action = parts[2] if len(parts) > 2 else ""
            if action == "":
                if method == "GET":
                    return setup.hub_state()
                return setup.connect_hub(IndexerHubEntry(**body))
            if action == "available":
                return setup.hub_available()
            if action == "import":
                return setup.import_hub(IndexerHubImport(**body))
            if action == "sync":
                return setup.sync_hub()
            if action == "disconnect":
                setup.disconnect_hub()
                return {"ok": True}
            raise ValueError("Unknown Indexers operation.")
        identifier = parts[1]
        if len(parts) == 2:
            return setup.update_indexer(identifier, IndexerEntry(**body))
        if parts[2] == "probe":
            return setup.probe_indexer(IndexerEntry(**body), identifier)
        if parts[2] == "test":
            return setup.test_indexer_entry(identifier)
        if parts[2] == "remove":
            setup.remove_indexer(identifier)
            return {"ok": True}
        raise ValueError("Unknown Indexers operation.")
