"""Prowlarr and Jackett as a source of Indexers (ADR-0024): list theirs, with Torznab endpoints.

The service's API key is also the key of every Torznab endpoint it serves.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from torrentlinker import net

SERVICES = ("prowlarr", "jackett")


@dataclass(frozen=True)
class HubIndexer:
    source_id: str
    name: str
    url: str
    enabled: bool = True


def list_indexers(service: str, base_url: str, api_key: str) -> list[HubIndexer]:
    """The torrent indexers a Prowlarr or Jackett instance offers; raises on any failure."""
    base = base_url.rstrip("/")
    with net.client(timeout=30, follow_redirects=True) as http:
        if service == "prowlarr":
            response = http.get(f"{base}/api/v1/indexer", headers={"X-Api-Key": api_key})
            rows = response.raise_for_status().json()
            return [
                HubIndexer(
                    str(r["id"]),
                    str(r["name"]),
                    f"{base}/{r['id']}/api",
                    bool(r.get("enable", True)),
                )
                for r in rows
                if r.get("protocol", "torrent") == "torrent"
            ]
        if service == "jackett":
            response = http.get(
                f"{base}/api/v2.0/indexers", params={"configured": "true", "apikey": api_key}
            )
            rows = response.raise_for_status().json()
            return [
                HubIndexer(
                    str(r["id"]),
                    str(r.get("name") or r["id"]),
                    f"{base}/api/v2.0/indexers/{r['id']}/results/torznab/",
                )
                for r in rows
                if r.get("configured", True)
            ]
    raise ValueError("Choose Prowlarr or Jackett.")


def refused(error: Exception) -> str:
    """A reason for the Owner, never the key."""
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (401, 403):
        return "The service refused the API key."
    return "Could not read the indexers. Check the address and API key."
