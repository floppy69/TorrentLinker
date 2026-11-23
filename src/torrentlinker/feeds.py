"""Persistent, bounded RSS discovery and conservative release rules.

Discovery never downloads torrent files or contacts a Torrent Client. A separate
explicitly authorized dispatcher is responsible for automatic downloads.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from torrentlinker.indexer import Candidate, Indexer, SearchQuery

MetadataField = Literal[
    "quality", "codec", "audio", "subtitles", "format", "bitrate", "platform", "license"
]
RankingField = Literal[MetadataField, "size", "seeders"]


def _default_priorities() -> list[RankingField]:
    return ["quality", "codec", "audio", "subtitles", "size"]


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_size: int = Field(default=0, ge=0)
    max_size: int | None = Field(default=None, ge=0)
    min_seeders: int = Field(default=0, ge=0)
    required: dict[MetadataField, list[str]] = Field(
        default_factory=dict,
        description="Hard requirements: reject releases without these verified facts.",
    )
    excluded: dict[MetadataField, list[str]] = Field(default_factory=dict)
    preferred: dict[MetadataField, list[str]] = Field(
        default_factory=dict,
        description="Soft preferences in descending order, e.g. quality: [1080p, 720p], "
        "codec: [HEVC, H264], format: [EPUB]. Do not turn preferences into required filters.",
    )
    category_scopes: dict[MetadataField, list[int]] = Field(
        default_factory=dict,
        description="Exact Torznab category IDs per criterion. Absent means global.",
    )
    priorities: list[RankingField] = Field(
        default_factory=_default_priorities,
        description="Ranking order. Include seeders to prefer more seeders. Put size after "
        "seeders and set prefer_small=true to use smaller size as a later tie-breaker. "
        "Any preferred fields omitted here are appended in their declared order.",
    )
    prefer_small: bool = Field(
        default=False,
        description="Prefer smaller releases at the size "
        "priority position. A maximum size alone is only a hard limit.",
    )

    @model_validator(mode="after")
    def valid(self):
        if self.max_size is not None and self.min_size > self.max_size:
            raise ValueError("Minimum size exceeds maximum size.")
        if any(
            not ids or len(ids) > 100 or any(i <= 0 for i in ids)
            for ids in self.category_scopes.values()
        ):
            raise ValueError("Choose positive category IDs for scoped criteria.")
        allowed = {
            "quality",
            "codec",
            "audio",
            "subtitles",
            "format",
            "bitrate",
            "platform",
            "license",
            "size",
            "seeders",
        }
        if len(set(self.priorities)) != len(self.priorities) or set(self.priorities) - allowed:
            raise ValueError("Choose distinct supported ranking priorities.")
        for values in (self.required, self.excluded, self.preferred):
            if set(values) - (allowed - {"size", "seeders"}):
                raise ValueError("Unsupported release metadata criterion.")
        # Every requested preference must affect ranking, including non-video
        # fields absent from the default priority order.
        for key in [*self.preferred, *(["size"] if self.prefer_small else [])]:
            if key not in self.priorities:
                self.priorities.append(key)
        return self


class Subscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = ""
    name: str = Field(min_length=1, max_length=100)
    query: str = Field(default="", max_length=500)
    categories: list[int] = Field(
        default_factory=list,
        max_length=100,
        description=(
            "Torznab category IDs. For c411: films 2030, TV 5000, music 3010, "
            "books/ebooks/EPUB 7020, all 3D models 8010. "
            "3010 is music, not books. Do not use native Search or Upload category IDs."
        ),
    )
    paused: bool = False
    interval_minutes: int = Field(default=30, ge=15, le=1440)
    mode: Literal["review_only", "app_queue", "automatic_download"] = "review_only"
    client_id: str = "default"
    folder: str = ""
    preferences: Preferences = Field(default_factory=Preferences)
    include_current: bool = False
    wait_minutes: int = Field(default=0, ge=0, le=10080)
    replace_pending: bool = False
    download_hours: list[int] = Field(default_factory=lambda: list(range(24)), max_length=24)
    daily_bytes: int = Field(default=10 * 1024**3, ge=0)
    daily_torrents: int = Field(default=20, ge=0, le=1000)
    reserve_bytes: int = Field(default=10 * 1024**3, ge=0)

    @model_validator(mode="after")
    def routing(self):
        if any(category <= 0 for category in self.categories):
            raise ValueError("Use positive Torznab category IDs, not native Search IDs.")
        if any(hour < 0 or hour > 23 for hour in self.download_hours):
            raise ValueError("Download hours must be UTC hours from 0 to 23.")
        if self.mode != "review_only" and not self.folder:
            raise ValueError("Choose a Download Folder for queue rules.")
        return self


def candidate(raw: dict) -> Candidate:
    return Candidate(
        **{
            **{
                key: value
                for key, value in raw.items()
                if key in {f.name for f in fields(Candidate)}
            },
            "categories": tuple(raw.get("categories", [])),
        }
    )


def work_aliases(row: Candidate) -> set[str]:
    """Reliable source IDs only; TV IDs always retain episode scope."""
    facts = row.metadata
    kind = facts.get("kind")
    if kind in {"movie", "tv"}:
        if kind == "tv" and (facts.get("season") is None or facts.get("episode") is None):
            return set()
        suffix = f":{facts['season']}:{facts['episode']}" if kind == "tv" else ""
        return {
            f"{kind}:{namespace}:{facts[key]}{suffix}"
            for namespace, key in (("imdb", "imdbid"), ("tmdb", "tmdbid"))
            if facts.get(key)
        }
    if facts.get("work_id") and facts.get("work_namespace"):
        return {f"{facts['work_namespace']}:{facts['work_id']}"}
    return set()


def work_identity(row: Candidate) -> str | None:
    return min(work_aliases(row), default=None)


def work_alias_map(rows: list[Candidate]) -> dict[str, str]:
    """Join identifiers only when a verified release explicitly carries both."""
    parents: dict[str, str] = {}

    def root(value: str) -> str:
        parents.setdefault(value, value)
        while parents[value] != value:
            parents[value] = parents[parents[value]]
            value = parents[value]
        return value

    for row in rows:
        aliases = sorted(work_aliases(row))
        for alias in aliases[1:]:
            left, right = root(aliases[0]), root(alias)
            parents[max(left, right)] = min(left, right)
        if aliases:
            root(aliases[0])
    return {value: root(value) for value in parents}


def evaluate(row: Candidate, prefs: Preferences) -> dict:
    # Unknown category must not bypass a configured requirement.
    def applicable(key):
        return (
            not prefs.category_scopes.get(key)
            or not row.categories
            or bool(set(row.categories) & set(prefs.category_scopes[key]))
        )

    blockers = []
    unknown = []
    if row.size <= 0 and (prefs.min_size or prefs.max_size is not None):
        unknown.append("size")
    elif row.size < prefs.min_size or (prefs.max_size is not None and row.size > prefs.max_size):
        blockers.append("size outside required range")
    if row.seeders < prefs.min_seeders:
        blockers.append("minimum seeders")
    for key in prefs.required.keys() | prefs.excluded.keys():
        if not applicable(key):
            continue
        values = row.metadata.get(key)
        if values is None:
            unknown.append(key)
            continue
        actual = {str(v).casefold() for v in (values if isinstance(values, list) else [values])}
        if key in prefs.required and not actual.intersection(
            v.casefold() for v in prefs.required[key]
        ):
            blockers.append(f"required {key}")
        if actual.intersection(v.casefold() for v in prefs.excluded.get(key, [])):
            blockers.append(f"excluded {key}")
        if (
            key == "quality"
            and not row.metadata.get("source")
            and any(
                value.casefold() in {"cam", "ts", "tc", "telesync", "telecine"}
                for value in prefs.excluded.get("quality", [])
            )
        ):
            unknown.append("quality.source")
    scores: dict[str, int] = {}
    for key, preferred in prefs.preferred.items():
        if not applicable(key):
            continue
        values = row.metadata.get(key)
        actual = {str(v).casefold() for v in (values if isinstance(values, list) else [values])}
        scores[key] = next(
            (i for i, value in enumerate(preferred) if value.casefold() in actual), len(preferred)
        )
    # Size is a ranking preference only in its chosen position.
    rank = [
        [int(row.size <= 0), max(row.size, 0)]
        if key == "size" and prefs.prefer_small
        else [int(row.seeders < 0), -max(row.seeders, 0)]
        if key == "seeders"
        else scores.get(key, 0)
        for key in prefs.priorities
    ]
    return {
        "eligible": not blockers and not unknown,
        "excluded": blockers,
        "unknown": unknown,
        "unknown_preferences": [
            key for key in prefs.preferred if applicable(key) and row.metadata.get(key) is None
        ]
        + (["size"] if prefs.prefer_small and row.size <= 0 else [])
        + (["seeders"] if "seeders" in prefs.priorities and row.seeders < 0 else []),
        "rank": rank,
        "work_identity": work_identity(row),
        "identity_warning": ""
        if work_identity(row)
        else "Work identity unknown; no work deduplication guarantee.",
    }


class FeedService:
    def __init__(self, path: Path, indexer: Callable[[], Indexer]):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.indexer = path, indexer
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, initialized INTEGER DEFAULT 0,
                last_attempt REAL, last_success REAL, error TEXT DEFAULT '',
                coverage TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS releases (
                infohash TEXT PRIMARY KEY, payload TEXT NOT NULL, discovered REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memberships (
                feed TEXT, infohash TEXT, discovered REAL, unread INTEGER, saved INTEGER DEFAULT 0,
                dismissed INTEGER DEFAULT 0, baseline INTEGER, PRIMARY KEY(feed,infohash)
            );
            CREATE TABLE IF NOT EXISTS decisions (
                feed TEXT, infohash TEXT, work TEXT, status TEXT, reason TEXT,
                queue_key TEXT, decided REAL, PRIMARY KEY(feed,infohash)
            );
            CREATE TABLE IF NOT EXISTS previews (signature TEXT PRIMARY KEY, created REAL);
            CREATE TABLE IF NOT EXISTS dispatch_attempts (
                queue_key TEXT PRIMARY KEY, attempt INTEGER
            );
            CREATE TABLE IF NOT EXISTS actors (feed TEXT PRIMARY KEY, actor TEXT);
            CREATE TABLE IF NOT EXISTS selections (
                id TEXT PRIMARY KEY, name TEXT, hashes TEXT, created REAL, payload TEXT DEFAULT ''
            );
            """)

        with self.db:
            if "payload" not in {
                row[1] for row in self.db.execute("PRAGMA table_info(selections)")
            }:
                self.db.execute("ALTER TABLE selections ADD COLUMN payload TEXT DEFAULT ''")

    def save(self, subscription: Subscription, *, allow_automatic: bool = False) -> Subscription:
        with self.lock, self.db:
            old = self.db.execute(
                "SELECT payload FROM subscriptions WHERE id=?", (subscription.id,)
            ).fetchone()
            if subscription.mode == "automatic_download" and not allow_automatic:
                raise ValueError("Automatic downloads require explicit approval.")
            value = subscription.model_copy(update={"id": subscription.id or uuid4().hex})
            if old:
                before = Subscription.model_validate_json(old[0])
                if before.mode != value.mode and value.mode != "review_only":
                    self.db.execute("UPDATE memberships SET baseline=1 WHERE feed=?", (value.id,))
                if before.categories != value.categories or before.query != value.query:
                    # A changed source has a new activation baseline.
                    self.db.execute("DELETE FROM memberships WHERE feed=?", (value.id,))
                    self.db.execute(
                        "UPDATE subscriptions SET initialized=0 WHERE id=?", (value.id,)
                    )
                self.db.execute(
                    "UPDATE subscriptions SET payload=? WHERE id=?",
                    (value.model_dump_json(), value.id),
                )
            else:
                self.db.execute(
                    "INSERT INTO subscriptions(id,payload) VALUES(?,?)",
                    (value.id, value.model_dump_json()),
                )
            return value

    def get(self, identifier: str) -> Subscription:
        with self.lock:
            row = self.db.execute(
                "SELECT payload FROM subscriptions WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise ValueError("Unknown subscription.")
        return Subscription.model_validate_json(row[0])

    def set_paused(self, identifier: str, paused: bool) -> None:
        with self.lock, self.db:
            feed = self.get(identifier).model_copy(update={"paused": paused})
            self.db.execute(
                "UPDATE subscriptions SET payload=? WHERE id=?",
                (feed.model_dump_json(), identifier),
            )

    def delete(self, identifier: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM subscriptions WHERE id=?", (identifier,))
            self.db.execute("DELETE FROM memberships WHERE feed=?", (identifier,))

    def subscriptions(self) -> list[dict]:
        with self.lock:
            return [
                {
                    **json.loads(row["payload"]),
                    **{
                        key: row[key]
                        for key in ("last_attempt", "last_success", "error", "coverage")
                    },
                    "unread_count": self.db.execute(
                        (
                            "SELECT COUNT(*) FROM memberships WHERE feed=? AND unread=1 AND "
                            "dismissed=0"
                        ),
                        (row["id"],),
                    ).fetchone()[0],
                }
                for row in self.db.execute("SELECT * FROM subscriptions ORDER BY rowid")
            ]

    def preview(self, subscription: Subscription, *, pages: int = 3) -> dict:
        indexer = self.indexer()
        seen_pages = set()
        rows: dict[str, Candidate] = {}
        reason = "page budget reached"
        for page in range(min(10, max(1, pages))):
            batch = indexer.search(
                SearchQuery(
                    q=subscription.query,
                    categories=tuple(subscription.categories),
                    offset=page * 100,
                    limit=100,
                    extended=True,
                ),
                cached=False,
            )
            hashes = sorted({row.infohash.lower() for row in batch if row.infohash})
            digest = hashlib.sha256("".join(hashes).encode()).hexdigest()
            if digest in seen_pages:
                reason = "repeated page"
                break
            seen_pages.add(digest)
            for row in batch:
                if row.infohash and re.fullmatch(r"[a-fA-F0-9]{40}", row.infohash):
                    clean = replace(
                        row,
                        infohash=row.infohash.lower(),
                        download_url=indexer.redact(row.download_url),
                        details_url=indexer.redact(row.details_url),
                    )
                    rows[clean.infohash] = clean  # type: ignore[index]
            if len(batch) < 100:
                reason = "end of accessible response"
                break
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO previews VALUES(?,?)",
                (self.preview_signature(subscription), time.time()),
            )
        return {
            "rows": [asdict(row) for row in rows.values()],
            "limited": True,
            "coverage": (
                f"Limited discovery: {reason}. History and gap-free updates are not guaranteed."
            ),
            "pages": len(seen_pages),
            "evaluations": {h: evaluate(row, subscription.preferences) for h, row in rows.items()},
        }

    def refresh(self, identifier: str, *, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        # Serialize in-process refreshes; SQLite serializes writes across processes.
        with self.lock:
            feed = self.get(identifier)
            if feed.paused:
                return {"status": "paused"}
            try:
                result = self.preview(feed)
            except Exception as error:
                with self.db:
                    self.db.execute(
                        "UPDATE subscriptions SET last_attempt=?,error=? WHERE id=?",
                        (now, self.indexer().redact(str(error)), identifier),
                    )
                raise
            with self.db:
                initialized = self.db.execute(
                    "SELECT initialized FROM subscriptions WHERE id=?", (identifier,)
                ).fetchone()[0]
                for raw in result["rows"]:
                    hash = raw["infohash"]
                    previous = self.db.execute(
                        "SELECT payload FROM releases WHERE infohash=?", (hash,)
                    ).fetchone()
                    if previous:
                        raw["metadata"] = {
                            **json.loads(previous[0]).get("metadata", {}),
                            **raw.get("metadata", {}),
                        }
                    self.db.execute(
                        (
                            "INSERT INTO releases VALUES(?,?,?) ON CONFLICT(infohash) DO UPDATE "
                            "SET payload=excluded.payload"
                        ),
                        (hash, json.dumps(raw), now),
                    )
                    self.db.execute(
                        (
                            "INSERT OR IGNORE INTO "
                            "memberships(feed,infohash,discovered,unread,baseline) "
                            "VALUES(?,?,?,?,?)"
                        ),
                        (identifier, hash, now, bool(initialized), not initialized),
                    )
                self.db.execute(
                    (
                        "UPDATE subscriptions SET "
                        "initialized=1,last_attempt=?,last_success=?,error='',coverage=? WHERE "
                        "id=?"
                    ),
                    (now, now, result["coverage"], identifier),
                )
            return {**result, "status": "refreshed"}

    def poll(self, *, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        results = []
        for row in self.subscriptions():
            if not row["paused"] and (
                row["last_attempt"] is None
                or now - row["last_attempt"] >= row["interval_minutes"] * 60
            ):
                try:
                    results.append(self.refresh(row["id"], now=now))
                except Exception:
                    results.append({"status": "error", "id": row["id"]})
        return results

    def inbox(
        self,
        feed_id: str = "",
        *,
        unread: bool = False,
        saved: bool = False,
        dismissed: bool = False,
    ) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                (
                    "SELECT r.payload,r.discovered AS first_discovered,m.* FROM "
                    "memberships m JOIN releases r USING(infohash) WHERE (?='' OR feed=?) "
                    "AND (?=0 OR unread=1) AND (?=0 OR saved=1) AND dismissed=? ORDER BY "
                    "m.discovered DESC,r.infohash"
                ),
                (feed_id, feed_id, unread, saved, dismissed),
            ).fetchall()
            result = {}
            for row in rows:
                hash = row["infohash"]
                if hash not in result:
                    result[hash] = {
                        **json.loads(row["payload"]),
                        "discovered_at": row["first_discovered"],
                        "unread": False,
                        "saved": False,
                        "feeds": [],
                        "baseline": bool(row["baseline"]),
                    }
                result[hash]["unread"] |= bool(row["unread"])
                result[hash]["saved"] |= bool(row["saved"])
                result[hash]["feeds"].append(row["feed"])
            return list(result.values())

    def mark(
        self,
        hashes: list[str],
        *,
        feed_id: str = "",
        action: Literal["read", "unread", "save", "unsave", "dismiss", "restore"] = "read",
    ) -> None:
        field, value = {
            "read": ("unread", 0),
            "unread": ("unread", 1),
            "save": ("saved", 1),
            "unsave": ("saved", 0),
            "dismiss": ("dismissed", 1),
            "restore": ("dismissed", 0),
        }[action]
        with self.lock, self.db:
            for hash in hashes:
                self.db.execute(
                    f"UPDATE memberships SET {field}=? WHERE infohash=? AND (?='' OR feed=?)",
                    (value, hash, feed_id, feed_id),
                )

    def select(
        self,
        hashes: list[str],
        name: str = "RSS selection",
        *,
        actor: str = "",
        client_ids: list[str] | None = None,
    ) -> dict:
        with self.lock, self.db:
            available = {row["infohash"] for row in self.inbox()}
            if set(hashes) - available:
                raise ValueError("Selection contains unavailable feed rows.")
            identifier = uuid4().hex
            hashes = sorted(set(hashes))
            rows = [
                json.loads(
                    self.db.execute(
                        "SELECT payload FROM releases WHERE infohash=?", (hash,)
                    ).fetchone()[0]
                )
                for hash in hashes
            ]
            scopes = set()
            subscription_ids = set()
            for hash in hashes:
                for row in self.db.execute(
                    (
                        "SELECT s.id,s.payload FROM memberships m "
                        "JOIN subscriptions s ON s.id=m.feed WHERE m.infohash=?"
                    ),
                    (hash,),
                ):
                    scope = json.loads(row[1])["client_id"]
                    if client_ids is None or scope in client_ids:
                        scopes.add(scope)
                        subscription_ids.add(row[0])
            payload = {
                "rows": rows,
                "indexer_url": self.indexer().url,
                "client_ids": sorted(scopes),
                "subscription_ids": sorted(subscription_ids),
                "owner": actor,
            }
            self.db.execute(
                "INSERT INTO selections(id,name,hashes,created,payload) VALUES(?,?,?,?,?)",
                (identifier, name[:100], json.dumps(hashes), time.time(), json.dumps(payload)),
            )
            return self.selection(identifier)

    def selection(
        self, identifier: str, *, actor: str | None = None, client_ids: list[str] | None = None
    ) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM selections WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise ValueError("Unknown RSS selection.")
            hashes = json.loads(row["hashes"])
            payload = (
                json.loads(row["payload"])
                if row["payload"]
                else {
                    "rows": [
                        json.loads(
                            self.db.execute(
                                "SELECT payload FROM releases WHERE infohash=?", (hash,)
                            ).fetchone()[0]
                        )
                        for hash in hashes
                    ],
                    "indexer_url": "",
                    "client_ids": [],
                    "owner": "legacy-owner-only",
                }
            )
            if actor is not None and (
                (payload["owner"] and payload["owner"] != actor)
                or not set(payload["client_ids"]).issubset(client_ids or [])
            ):
                raise ValueError("Selection is not accessible to this connection.")
            return {
                "id": identifier,
                "name": row["name"],
                "hashes": hashes,
                **{key: value for key, value in payload.items() if key != "owner"},
                "created": row["created"],
            }

    def decisions(self, feed_id: str = "") -> list[dict]:
        with self.lock:
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT * FROM decisions WHERE (?='' OR feed=?) ORDER BY decided DESC",
                    (feed_id, feed_id),
                )
            ]

    def process(
        self,
        identifier: str,
        store,
        *,
        present_hashes: set[str] | None = None,
        present_works: set[str] | None = None,
        unknown_client_works: set[str] | None = None,
        now: float | None = None,
    ) -> list[dict]:
        """Evaluate rules into the app queue only, using a supplied client snapshot.

        No Torrent Client or torrent download API is reachable from this method.
        Missing client inventories stop automatic decisions rather than claiming dedup.
        """
        from torrentlinker.download_queue import entries, queue_key

        now = time.time() if now is None else now
        with self.lock, self.db:
            # Lock before reading decisions so concurrent service instances cannot choose twice.
            self.db.execute("BEGIN IMMEDIATE")
            feed = self.get(identifier)
            if feed.paused or feed.mode == "review_only":
                return []
            indexer = self.indexer()
            queued = entries(store, all_clients=True)
            live_queue_keys = {entry.key for entry in queued}
            queued_hashes = {e.candidate.infohash for e in queued}
            known_releases = {row["infohash"]: candidate(row) for row in self.releases()}
            queue_candidates = {
                e.key: known_releases.get(e.candidate.infohash, e.candidate) for e in queued
            }
            unknown_queue_works = {
                e.key for e in queued if not work_identity(queue_candidates[e.key])
            }
            aliases = work_alias_map(
                list(known_releases.values()) + list(queue_candidates.values())
            )

            def canonical(identity):
                return aliases.get(identity, identity)

            queued_works = {canonical(work_identity(queue_candidates[e.key])) for e in queued}
            present_works = {canonical(identity) for identity in (present_works or set())}
            replacements = {}
            groups: dict[str, list[tuple[Candidate, dict, float]]] = {}
            results = []
            raw_rows = self.db.execute(
                (
                    "SELECT r.payload,m.discovered,m.baseline FROM memberships m JOIN "
                    "releases r USING(infohash) WHERE feed=? AND dismissed=0"
                ),
                (identifier,),
            ).fetchall()
            for raw in raw_rows:
                row = candidate(json.loads(raw["payload"]))
                infohash = row.infohash
                old = self.db.execute(
                    "SELECT status FROM decisions WHERE feed=? AND infohash=?",
                    (identifier, infohash),
                ).fetchone()
                if old and old[0] in {"queued", "sent", "sending", "uncertain", "replaced"}:
                    continue
                evaluation = evaluate(row, feed.preferences)
                evaluation["work_identity"] = canonical(evaluation["work_identity"])
                status, reason = "eligible", ""
                if raw["baseline"] and not feed.include_current:
                    status, reason = (
                        "baseline",
                        "Available before activation; include-current is disabled.",
                    )
                elif not evaluation["eligible"]:
                    status, reason = (
                        "blocked",
                        "; ".join(
                            evaluation["excluded"]
                            + [f"Unknown required {v}" for v in evaluation["unknown"]]
                        ),
                    )
                elif not evaluation["work_identity"]:
                    status, reason = (
                        "blocked",
                        (
                            "Unknown work identity. Review manually; automatic work deduplication "
                            "is unavailable."
                        ),
                    )
                elif present_hashes is None:
                    status, reason = (
                        "blocked",
                        "Client inventory unavailable. Compare configured Torrent Clients first.",
                    )
                elif infohash in present_hashes or infohash in queued_hashes:
                    status, reason = (
                        "duplicate",
                        "Exact release is already in a Torrent Client or the app queue.",
                    )
                elif unknown_queue_works:
                    status, reason = (
                        "blocked",
                        (
                            f"Work comparison incomplete: {len(unknown_queue_works)} "
                            "app queue torrent identities unknown. "
                            "Compare metadata before automatic selection."
                        ),
                    )
                elif unknown_client_works:
                    status, reason = (
                        "blocked",
                        f"Work comparison incomplete: {len(unknown_client_works)} "
                        "client torrent identities unknown. Review manually or complete "
                        "metadata comparison before automatic selection.",
                    )
                elif evaluation["work_identity"] in (present_works or set()):
                    status, reason = (
                        "duplicate_work",
                        "A release of this work is already in a Torrent Client.",
                    )
                elif evaluation["work_identity"] in queued_works:
                    existing = next(
                        e
                        for e in queued
                        if canonical(work_identity(queue_candidates[e.key]))
                        == evaluation["work_identity"]
                    )
                    owned = self.db.execute(
                        "SELECT 1 FROM decisions WHERE feed=? AND queue_key=? AND status='queued'",
                        (identifier, existing.key),
                    ).fetchone()
                    if (
                        feed.replace_pending
                        and existing.status == "queued"
                        and owned
                        and existing.client_id == feed.client_id
                        and evaluation["rank"]
                        < evaluate(existing.candidate, feed.preferences)["rank"]
                    ):
                        replacements[evaluation["work_identity"]] = existing
                    else:
                        status, reason = (
                            "duplicate_work",
                            "A release of this work is already in the app queue.",
                        )
                if status == "eligible":
                    groups.setdefault(evaluation["work_identity"], []).append(
                        (row, evaluation, raw["discovered"])
                    )
                else:
                    self.db.execute(
                        "INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?,?)",
                        (
                            identifier,
                            infohash,
                            evaluation["work_identity"],
                            status,
                            reason,
                            "",
                            now,
                        ),
                    )
                    results.append(
                        {"infohash": infohash, "status": status, "reason": reason, **evaluation}
                    )
            for work, alternatives in groups.items():
                alternatives.sort(key=lambda item: (item[1]["rank"], item[0].infohash))
                wait_until = min(item[2] for item in alternatives) + feed.wait_minutes * 60
                claimed = any(
                    canonical(record[0]) == work
                    and (record[1] != "queued" or record[2] in live_queue_keys)
                    for record in self.db.execute(
                        "SELECT work,status,queue_key FROM decisions WHERE status IN "
                        "('queued','sending','sent','uncertain')"
                    )
                )
                for position, (row, evaluation, _) in enumerate(alternatives):
                    key = ""
                    if claimed and work not in replacements:
                        status, reason = (
                            "duplicate_work",
                            "Another subscription already queued this work.",
                        )
                    elif now < wait_until:
                        status, reason = (
                            "waiting",
                            f"Waiting for alternatives until {wait_until:.0f}.",
                        )
                    elif position:
                        status, reason = (
                            "alternative",
                            "A higher ranked eligible release was chosen.",
                        )
                    else:
                        key = queue_key(indexer, row)
                        if feed.client_id != "default":
                            key = feed.client_id + ":" + key
                        payload = {
                            "candidate": asdict(row),
                            "folder": feed.folder,
                            "indexer_url": indexer.url,
                            "client_id": feed.client_id,
                            "origin": {
                                "source": "rss",
                                "subscription_id": identifier,
                                "work": work,
                                "mode": feed.mode,
                                "reason": evaluation,
                            },
                            "rss_automatic": feed.mode == "automatic_download",
                        }
                        previous = replacements.get(work)
                        if previous:
                            inserted = store.replace_pending_download(previous.key, key, payload)
                            if inserted:
                                self.db.execute(
                                    (
                                        "UPDATE decisions SET status='replaced',reason=? "
                                        "WHERE queue_key=?"
                                    ),
                                    (
                                        "Better eligible release selected while pending.",
                                        previous.key,
                                    ),
                                )
                        else:
                            inserted = store.for_client(feed.client_id).enqueue_download(
                                key, payload
                            )
                        status = "queued" if inserted else "duplicate"
                        reason = (
                            "Best eligible release queued in TorrentLinker. No torrent file "
                            "downloaded."
                        )
                    self.db.execute(
                        "INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?,?)",
                        (identifier, row.infohash, work, status, reason, key, now),
                    )
                    results.append(
                        {"infohash": row.infohash, "status": status, "reason": reason, **evaluation}
                    )
            return results

    def enqueue_selection(self, identifier: str, store, client_id: str, folder: str) -> dict:
        """Explicit user queue action. It may exceed disk space or daily dispatch limits."""
        from torrentlinker.download_queue import enqueue, entries

        if not folder:
            raise ValueError("Choose a Download Folder.")
        saved = self.selection(identifier)
        if saved["indexer_url"] != self.indexer().url:
            raise ValueError("Indexer changed. Preview and save a new RSS selection.")
        queued = {e.candidate.infohash for e in entries(store, all_clients=True)}
        added = 0
        for raw in saved["rows"]:
            if raw["infohash"] not in queued:
                added += enqueue(
                    store.for_client(client_id),
                    self.indexer(),
                    candidate(raw),
                    Path(folder),
                    origin={
                        "source": "rss",
                        "selection_id": identifier,
                        "subscriptions": saved.get("subscription_ids", []),
                    },
                )
                queued.add(raw["infohash"])
        return {"selection_id": identifier, "queued": added, "client_id": client_id}

    def enrich(self, infohash: str) -> dict:
        """Fetch structured metadata only. Free text and release names are never proof."""
        with self.lock:
            stored = self.db.execute(
                "SELECT payload FROM releases WHERE infohash=?", (infohash,)
            ).fetchone()
            if stored is None:
                raise ValueError("Unknown feed release.")
            row = candidate(json.loads(stored[0]))
        payload = self.indexer().torrent_json(infohash)
        facts = dict(row.metadata)
        tech = payload.get("tech") or {}
        for source, key in (
            ("resolution", "quality"),
            ("videoCodec", "codec"),
            ("audioLanguages", "audio"),
            ("subtitleLanguages", "subtitles"),
            ("season", "season"),
            ("episode", "episode"),
        ):
            if tech.get(source) is not None:
                facts[key] = tech[source]
        if tech.get("source"):
            facts["source"] = tech["source"]
            facts["quality"] = [v for v in (tech.get("resolution"), tech["source"]) if v]
        aliases = {"H.265": "HEVC", "H265": "HEVC", "H.264": "H264", "H.263": "H263"}
        if "codec" in facts:
            facts["codec"] = aliases.get(facts["codec"], facts["codec"])
        metadata = payload.get("metadata") or {}
        for source, key in (("tmdbId", "tmdbid"), ("imdbId", "imdbid")):
            if payload.get(source) or metadata.get(source):
                facts[key] = str(payload.get(source) or metadata[source])
        kind = payload.get("tmdbType") or metadata.get("tmdbType")
        if kind in {"movie", "tv"}:
            facts["kind"] = kind
        elif 2030 in row.categories:
            facts["kind"] = "movie"
        facts["metadata_checked_at"] = time.time()
        clean = asdict(replace(row, metadata=facts))
        with self.lock, self.db:
            self.db.execute(
                "UPDATE releases SET payload=? WHERE infohash=?", (json.dumps(clean), infohash)
            )
        return clean

    def selections(
        self, *, actor: str | None = None, client_ids: list[str] | None = None
    ) -> list[dict]:
        with self.lock:
            result = []
            for row in self.db.execute("SELECT * FROM selections ORDER BY created DESC"):
                try:
                    self.selection(row["id"], actor=actor, client_ids=client_ids)
                except ValueError:
                    continue
                result.append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "created": row["created"],
                        "hashes": json.loads(row["hashes"]),
                    }
                )
            return result

    def preview_signature(self, feed: Subscription) -> str:
        definition = feed.model_dump(exclude={"id"})
        return hashlib.sha256(
            (self.indexer().url + json.dumps(definition, sort_keys=True)).encode()
        ).hexdigest()

    def has_preview(self, feed: Subscription) -> bool:
        with self.lock:
            row = self.db.execute(
                "SELECT created FROM previews WHERE signature=?", (self.preview_signature(feed),)
            ).fetchone()
            return bool(row and row[0] > time.time() - 900)

    def releases(self) -> list[dict]:
        """Verified release metadata independently of inbox visibility or subscription lifetime."""
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM releases")]

    def observe_client_release(self, row: Candidate) -> None:
        """Retain identity facts for comparison without adding an inbox membership."""
        self.observe_client_releases([row])

    def observe_client_releases(self, rows: Iterable[Candidate]) -> None:
        """The same for a whole client inventory, in one transaction; known ones are skipped."""
        with self.lock:
            known = {row[0] for row in self.db.execute("SELECT infohash FROM releases")}
            now = time.time()
            new = {
                row.infohash: (row.infohash, json.dumps(asdict(row)), now)
                for row in rows
                if row.infohash
                and row.infohash not in known
                and re.fullmatch(r"[a-f0-9]{40}", row.infohash)
            }
            with self.db:
                self.db.executemany("INSERT OR IGNORE INTO releases VALUES(?,?,?)", new.values())

    def metadata_error(self, infohash: str) -> None:
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT payload FROM releases WHERE infohash=?", (infohash,)
            ).fetchone()
            if row:
                raw = json.loads(row[0])
                raw["metadata"]["metadata_checked_at"] = time.time()
                self.db.execute(
                    "UPDATE releases SET payload=? WHERE infohash=?", (json.dumps(raw), infohash)
                )
