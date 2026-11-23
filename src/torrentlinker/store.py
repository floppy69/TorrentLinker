"""Local SQLite state: caches and the user's decisions."""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS reseed_link_layout (
    client_id TEXT NOT NULL, hash TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY (client_id, hash)
);
CREATE TABLE IF NOT EXISTS reseed_workspace (
    client_id TEXT NOT NULL, item_path TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY (client_id, item_path)
);
-- Cross-seed (ADR-0024): one row per source and Indexer ('' candidate: its search), and
-- one per Candidate the search found.
CREATE TABLE IF NOT EXISTS crossseed (
    client_id TEXT NOT NULL, source TEXT NOT NULL, indexer_id TEXT NOT NULL,
    candidate_key TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
    updated REAL NOT NULL,
    PRIMARY KEY (client_id, source, indexer_id, candidate_key)
);
CREATE TABLE IF NOT EXISTS local_draft (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT '{}',
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS client_plan (
    client_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_cache (
    key TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS download_queue (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    reason TEXT NOT NULL DEFAULT '',
    added_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS verification (
    hash TEXT PRIMARY KEY,
    item_path TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    rechecked_at REAL,
    required_progress REAL NOT NULL DEFAULT 1.0,
    required_pieces TEXT,
    local_files TEXT
);
CREATE TABLE IF NOT EXISTS rejection (
    item_path TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (item_path, candidate_key)
);
-- A torrent's file list, as its client last reported it: fixed for an info hash unless
-- files are renamed inside the torrent, so scans need not ask the client again.
CREATE TABLE IF NOT EXISTS torrent_files (
    client_id TEXT NOT NULL,
    infohash TEXT NOT NULL,
    files TEXT NOT NULL,
    PRIMARY KEY (client_id, infohash)
);
CREATE TABLE IF NOT EXISTS scan_cache (
    item_path TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    files TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS remembered_candidates (
    item_path TEXT PRIMARY KEY,
    candidates TEXT NOT NULL,
    searched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS item_query (
    item_path TEXT PRIMARY KEY,
    query TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS catalogue (
    infohash TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    size INTEGER NOT NULL,
    seeders INTEGER NOT NULL,
    category INTEGER,
    download_url TEXT NOT NULL,
    details_url TEXT NOT NULL,
    seen_at REAL NOT NULL
);
-- Exact sizes find Library Candidates without spending a search (catalogue_sized).
CREATE INDEX IF NOT EXISTS catalogue_by_size ON catalogue(size);
CREATE TABLE IF NOT EXISTS catalogue_crawl (
    category INTEGER PRIMARY KEY,
    next_offset INTEGER NOT NULL DEFAULT 0,
    complete INTEGER NOT NULL DEFAULT 0,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS unavailable_torrent (
    infohash TEXT PRIMARY KEY,
    seen_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS catalogue_feed (
    name TEXT PRIMARY KEY,
    next_page INTEGER NOT NULL DEFAULT 1,
    updated_at REAL,
    count INTEGER NOT NULL DEFAULT 0,
    limited INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS unpacked_archive (
    folder TEXT PRIMARY KEY,
    archive TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS upload (
    item_path TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    infohash TEXT NOT NULL,
    draft_id INTEGER,
    made_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS category_options (
    subcategory INTEGER PRIMARY KEY,
    body TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    made_at REAL NOT NULL,
    sending INTEGER NOT NULL DEFAULT 0,
    zen_added REAL
);
CREATE TABLE IF NOT EXISTS plan_item (
    position INTEGER PRIMARY KEY,
    infohash TEXT NOT NULL,
    title TEXT NOT NULL,
    size INTEGER NOT NULL,
    seeders INTEGER NOT NULL,
    category INTEGER,
    folder TEXT NOT NULL,
    zen REAL NOT NULL,
    note REAL,
    outcome TEXT,
    reason TEXT
);
-- Every file of every cached .torrent, by size: a local file finds the torrents that
-- hold it, episodes inside packs included, without a search (layouts_holding).
CREATE TABLE IF NOT EXISTS layout_file (
    cache_key TEXT NOT NULL,
    infohash TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    PRIMARY KEY (cache_key, path)
);
CREATE INDEX IF NOT EXISTS layout_file_by_size ON layout_file(size);
-- Cached .torrent files already read into layout_file, even those with no usable file.
CREATE TABLE IF NOT EXISTS layout_indexed (cache_key TEXT PRIMARY KEY);
-- Profile history: one row per local day per account binding (see profile_history).
CREATE TABLE IF NOT EXISTS profile_history (
    account TEXT NOT NULL,
    day TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (account, day)
);
"""


@dataclass(frozen=True)
class CatalogueRow:
    """A torrent of the Catalogue. `download_url` never holds the API key."""

    infohash: str
    title: str
    size: int
    seeders: int
    category: int | None
    download_url: str
    details_url: str
    seen_at: float
    source: str = "indexer"
    root: int | None = None  # c411's own category, known from its listing


@dataclass(frozen=True)
class SavedPlanItem:
    """A download of the saved Plan; `outcome` is None until it has been sent."""

    infohash: str
    title: str
    size: int
    seeders: int
    category: int | None
    folder: str
    zen: float
    note: float | None
    outcome: str | None = None  # added, refused or failed
    reason: str | None = None
    client_id: str = ""


@dataclass(frozen=True)
class SavedPlan:
    made_at: float
    sending: bool  # a send was running when the app stopped
    items: list[SavedPlanItem]
    zen_added: float | None = None  # ≈ Zen/day of the whole Plan, as it was made

    @property
    def pending(self) -> list[SavedPlanItem]:
        """Torrents still to send; a failed one is tried again, a refused one is final."""
        return [i for i in self.items if i.outcome not in ("added", "refused")]


@dataclass(frozen=True)
class FeedState:
    name: str
    next_page: int = 1
    updated_at: float | None = None
    count: int = 0
    limited: bool = False
    head_hashes: tuple[str, ...] = ()  # newest page of the last successful sync
    started_at: float | None = None  # baseline for an interrupted first latest-only update


@dataclass(frozen=True)
class CrawlState:
    category: int
    next_offset: int = 0  # where a paused full crawl resumes
    complete: bool = False  # a full crawl reached the end once
    updated_at: float | None = None
    limited: bool = False  # the Indexer stopped paging before coverage was established


@dataclass(frozen=True)
class SavedUpload:
    """An Upload the app made: its torrent and the c411 Draft it went to (ADR-0011)."""

    item_path: Path
    title: str
    infohash: str
    draft_id: int | None
    made_at: float


@dataclass(frozen=True)
class Verification:
    item_path: Path
    candidate_key: str
    rechecked_at: float | None
    # Piece ranges Verification checks when some files are absent; None means all of them.
    required_pieces: list[tuple[int, int]] | None
    # Local files that must stay in place, relative to the Local Item's folder.
    local_files: list[str] = field(default_factory=list)


_RANK = "(CASE {0}.source WHEN 'zen-lab' THEN 0 WHEN 'bundled' THEN 1 ELSE 2 END)"


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.client_id = "default"
        self.torrent_dir = path.parent / "torrents"
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(SCHEMA)
            self._migrate()
            # Older versions retained completed sends in the queue. Pending and
            # uncertain work must survive; successful handoffs need no more action.
            self._db.execute("DELETE FROM download_queue WHERE status='sent'")
            self._db.execute(
                "UPDATE download_queue SET status='uncertain', retry_safe=0, "
                "reason='Interrupted send. Check the Torrent Client "
                "before removing and queueing again.' "
                "WHERE status='sending'"
            )

    def diagnostic_counts(self) -> dict:
        """Counts across all clients, without reading paths, titles, or payloads."""
        with self._lock:
            counts = {
                table: self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("catalogue", "scan_cache", "verification")
            }
            for table in ("download_queue", "local_draft"):
                counts[table] = dict(
                    self._db.execute(f"SELECT status, COUNT(*) FROM {table} GROUP BY status")
                )
        return counts

    def change_token(self) -> tuple[object, str, int, int]:
        """An in-process token for this connection, client scope and database state.

        data_version catches other connections' commits, while total_changes
        catches this connection's writes. Read before loading a display snapshot:
        a concurrent write then causes another refresh rather than being missed.
        """
        with self._lock:
            return (
                self._db,
                self.client_id,
                self._db.total_changes,
                self._db.execute("PRAGMA data_version").fetchone()[0],
            )

    def for_client(self, identifier: str) -> Store:
        """An immutable client scope sharing caches, SQLite connection and its lock."""
        if not identifier or not identifier.replace("-", "").isalnum():
            raise ValueError("Invalid Torrent Client profile ID.")
        result = copy.copy(self)
        result.client_id = identifier
        return result

    def _verification_key(self, hash: str) -> str:
        return hash if self.client_id == "default" else f"{self.client_id}:{hash}"

    def reseed_records(self) -> dict[str, dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT item_path,payload FROM reseed_workspace WHERE client_id=?",
                (self.client_id,),
            ).fetchall()
        return {path: json.loads(payload) for path, payload in rows}

    def reseed_record(self, path: str) -> dict:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM reseed_workspace WHERE client_id=? AND item_path=?",
                (self.client_id, path),
            ).fetchone()
        return json.loads(row[0]) if row else {}

    def save_reseed_record(self, path: str, record: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO reseed_workspace VALUES (?,?,?)",
                (self.client_id, path, json.dumps(record)),
            )

    # Cross-seed activity -----------------------------------------------------

    def crossseed_rows(
        self,
        state: str | None = None,
        indexer_id: str | None = None,
        *,
        limit: int = -1,
        newest: bool = False,
    ) -> list[dict]:
        query = "SELECT source,indexer_id,candidate_key,state,payload,updated FROM crossseed"
        query += " WHERE client_id=?"
        args: list = [self.client_id]
        if state is not None:
            query += " AND state=?"
            args.append(state)
        if indexer_id is not None:
            query += " AND indexer_id=?"
            args.append(indexer_id)
        with self._lock:
            rows = self._db.execute(
                query + f" ORDER BY updated {'DESC' if newest else 'ASC'} LIMIT ?", [*args, limit]
            ).fetchall()
        return [
            {
                **json.loads(payload),
                "source": source,
                "indexer_id": indexer,
                "candidate_key": key,
                "state": st,
                "updated": updated,
            }
            for source, indexer, key, st, payload, updated in rows
        ]

    def crossseed_known(self) -> set[tuple[str, str]]:
        """Every (source, Indexer) already queued or searched."""
        with self._lock:
            rows = self._db.execute(
                "SELECT source, indexer_id FROM crossseed WHERE client_id=? AND candidate_key=''",
                (self.client_id,),
            ).fetchall()
        return {(str(a), str(b)) for a, b in rows}

    def crossseed_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute(
                "SELECT state, COUNT(*) FROM crossseed WHERE client_id=? GROUP BY state",
                (self.client_id,),
            ).fetchall()
        return {str(state): int(count) for state, count in rows}

    def queue_crossseed(self, searches: list[tuple[str, str, dict]]) -> None:
        with self._lock, self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO crossseed VALUES (?,?,?,'','queued',?,?)",
                [
                    (self.client_id, source, indexer, json.dumps(payload), time.time())
                    for source, indexer, payload in searches
                ],
            )

    def save_crossseed(
        self, source: str, indexer_id: str, candidate_key: str, state: str, payload: dict
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO crossseed VALUES (?,?,?,?,?,?,?)",
                (
                    self.client_id,
                    source,
                    indexer_id,
                    candidate_key,
                    state,
                    json.dumps(payload),
                    time.time(),
                ),
            )

    def delete_crossseed(self, source: str, indexer_id: str, candidate_key: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM crossseed WHERE client_id=? AND source=? AND indexer_id=?"
                " AND candidate_key=?",
                (self.client_id, source, indexer_id, candidate_key),
            )

    def reseed_link_layout(self, hash: str) -> dict:
        """An automatic Reseed's layout, independent of board progress."""
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM reseed_link_layout WHERE client_id=? AND hash=?",
                (self.client_id, hash),
            ).fetchone()
        return json.loads(row[0]) if row else {}

    def save_reseed_link_layout(self, hash: str, record: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO reseed_link_layout VALUES (?,?,?)",
                (self.client_id, hash, json.dumps(record)),
            )

    def local_drafts(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id,revision,status,payload,result,updated FROM local_draft "
                "WHERE client_id=? ORDER BY updated DESC",
                (self.client_id,),
            ).fetchall()
        return [
            {
                **json.loads(payload),
                "id": key,
                "client_id": self.client_id,
                "revision": revision,
                "status": status,
                "result": json.loads(result),
                "updated": updated,
            }
            for key, revision, status, payload, result, updated in rows
        ]

    def local_draft(self, identifier: str) -> dict:
        for row in self.local_drafts():
            if row["id"] == identifier:
                return row
        raise ValueError("Local Draft not found for this Torrent Client.")

    def save_local_draft(self, payload: dict, identifier: str = "", revision: int = 0) -> dict:
        key = identifier or uuid.uuid4().hex
        with self._lock, self._db:
            if identifier:
                changed = self._db.execute(
                    "UPDATE local_draft SET payload=?,revision=revision+1,updated=? "
                    "WHERE id=? AND client_id=? AND revision=? AND status='queued'",
                    (json.dumps(payload), time.time(), key, self.client_id, revision),
                ).rowcount
                if not changed:
                    raise ValueError("Local Draft changed or was sent. Reload it before editing.")
            else:
                self._db.execute(
                    "INSERT INTO local_draft(id,client_id,revision,status,payload,updated) "
                    "VALUES(?,?,1,'queued',?,?)",
                    (key, self.client_id, json.dumps(payload), time.time()),
                )
        return self.local_draft(key)

    def claim_local_draft(self, identifier: str, revision: int) -> None:
        with self._lock, self._db:
            changed = self._db.execute(
                "UPDATE local_draft SET status='sending',updated=? "
                "WHERE id=? AND client_id=? AND revision=? AND status='queued'",
                (time.time(), identifier, self.client_id, revision),
            ).rowcount
            if not changed:
                raise ValueError("Local Draft changed or is already being sent. Reload it.")

    def local_draft_outcome(self, identifier: str, status: str, result: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE local_draft SET status=?,result=?,updated=? "
                "WHERE id=? AND client_id=? AND status='sending'",
                (status, json.dumps(result), time.time(), identifier, self.client_id),
            )

    def remove_local_draft(self, identifier: str, revision: int) -> None:
        with self._lock, self._db:
            changed = self._db.execute(
                "DELETE FROM local_draft WHERE id=? AND client_id=? AND revision=? "
                "AND status!='sending'",
                (identifier, self.client_id, revision),
            ).rowcount
            if not changed:
                raise ValueError("Local Draft changed or is being sent. Reload it.")

    def reset_local_draft(self, identifier: str, revision: int) -> dict:
        """Owner confirms checking c411 after an ambiguous failed/interrupted submission."""
        with self._lock, self._db:
            changed = self._db.execute(
                "UPDATE local_draft SET status='queued',revision=revision+1,result='{}',updated=? "
                "WHERE id=? AND client_id=? AND revision=? AND status IN ('sending','uncertain')",
                (time.time(), identifier, self.client_id, revision),
            ).rowcount
            if not changed:
                raise ValueError("Local Draft changed. Reload it.")
        return self.local_draft(identifier)

    def enqueue_download(self, key: str, payload: dict[str, object]) -> bool:
        """Payload URLs must already have credentials redacted by the Indexer."""
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO download_queue(id, payload, added_at) VALUES (?, ?, ?)",
                (key, json.dumps(payload), time.time()),
            )
            return cursor.rowcount > 0

    def queued_downloads(self) -> list[tuple[str, dict[str, object], str, str]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, payload, status, reason, priority, added_at, retry_safe "
                "FROM download_queue ORDER BY priority DESC, added_at, rowid"
            ).fetchall()
        return [
            (
                key,
                {
                    **json.loads(payload),
                    "priority": priority,
                    "added_at": added_at,
                    "retry_safe": bool(retry_safe),
                },
                status,
                reason,
            )
            for key, payload, status, reason, priority, added_at, retry_safe in rows
        ]

    def download_outcome(
        self, key: str, status: str, reason: str = "", *, retry_safe: bool = False
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE download_queue SET status=?, reason=?, retry_safe=? WHERE id=?",
                (status, reason, int(retry_safe), key),
            )

    def claim_download(self, key: str) -> bool:
        """A removed/replaced or already claimed pending row can never be sent."""
        with self._lock, self._db:
            return (
                self._db.execute(
                    "UPDATE download_queue SET status='sending' WHERE id=? AND status='queued'",
                    (key,),
                ).rowcount
                == 1
            )

    def replace_pending_download(self, old_key: str, new_key: str, payload: dict) -> bool:
        with self._lock, self._db:
            # Lock across connections before reading; a sender must not claim the
            # old row between this status check and replacement.
            self._db.execute("BEGIN IMMEDIATE")
            old = self._db.execute(
                "SELECT status FROM download_queue WHERE id=?", (old_key,)
            ).fetchone()
            if old is None or old[0] != "queued":
                return False
            inserted = (
                self._db.execute(
                    "INSERT OR IGNORE INTO download_queue(id,payload,added_at) VALUES(?,?,?)",
                    (new_key, json.dumps(payload), time.time()),
                ).rowcount
                == 1
            )
            if inserted:
                self._db.execute("DELETE FROM download_queue WHERE id=?", (old_key,))
            return inserted

    def remove_downloads(self, keys: list[str]) -> None:
        with self._lock, self._db:
            self._db.executemany("DELETE FROM download_queue WHERE id=?", [(key,) for key in keys])

    def reconcile_downloads(self, keys: list[str], action: str) -> int:
        """Edit this client's local queue without racing a concurrent sender's claim."""
        if action not in {"retry", "remove", "clear-sent"}:
            raise ValueError("Unknown queue operation.")
        selected = set(keys)
        changed = 0
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            for key, payload, status, retry_safe in self._db.execute(
                "SELECT id,payload,status,retry_safe FROM download_queue"
            ).fetchall():
                if json.loads(payload).get("client_id", "default") != self.client_id:
                    continue
                if action == "clear-sent":
                    eligible = status == "sent"
                else:
                    eligible = key in selected and status != "sending"
                if not eligible:
                    continue
                if action == "retry":
                    if status != "refused" and not (status == "failed" and retry_safe):
                        continue
                    self._db.execute(
                        "UPDATE download_queue SET status='queued',reason='',retry_safe=0 "
                        "WHERE id=?",
                        (key,),
                    )
                else:
                    self._db.execute("DELETE FROM download_queue WHERE id=?", (key,))
                changed += 1
        return changed

    def edit_downloads(self, expected: list[dict], action: str, priority: int = 0) -> None:
        """Atomically edit only unchanged, definitively unsent queue rows."""
        with self._lock, self._db:
            current = {
                key: (
                    {
                        **json.loads(payload),
                        "priority": priority_value,
                        "added_at": added_at,
                        "retry_safe": bool(retry_safe),
                    },
                    status,
                )
                for key, payload, status, priority_value, added_at, retry_safe in self._db.execute(
                    "SELECT id,payload,status,priority,added_at,retry_safe FROM download_queue"
                )
            }
            for row in expected:
                payload, status = current.get(row["key"], ({}, "missing"))
                candidate = payload.get("candidate", {})
                actual = {
                    "key": row["key"],
                    "hash": candidate.get("infohash"),
                    "title": candidate.get("title"),
                    "size": candidate.get("size"),
                    "seeders": candidate.get("seeders"),
                    "categories": list(candidate.get("categories", [])),
                    "folder": payload.get("folder"),
                    "indexer_url": payload.get("indexer_url"),
                    "status": status,
                    "priority": payload.get("priority"),
                    "added_at": payload.get("added_at"),
                    "retry_safe": payload.get("retry_safe"),
                }
                if any(actual[k] != v for k, v in row.items() if k != "category"):
                    raise ValueError("Queue selection changed. Review it again.")
                safe = status in {"queued", "refused"} or (
                    status == "failed" and payload.get("retry_safe")
                )
                if (
                    not safe
                    or (
                        action == "retry" and not (status == "failed" and payload.get("retry_safe"))
                    )
                    or (action == "priority" and status != "queued")
                ):
                    raise ValueError(
                        "Only definitively unsent entries can be edited; "
                        "uncertain sends require owner investigation."
                    )
            for row in expected:
                if action == "remove":
                    self._db.execute("DELETE FROM download_queue WHERE id=?", (row["key"],))
                elif action == "retry":
                    self._db.execute(
                        "UPDATE download_queue SET status='queued',reason='',retry_safe=0 "
                        "WHERE id=?",
                        (row["key"],),
                    )
                elif action == "priority":
                    self._db.execute(
                        "UPDATE download_queue SET priority=? WHERE id=?", (priority, row["key"])
                    )
                else:
                    raise ValueError("Unknown queue edit action.")

    def _migrate(self) -> None:
        queue_columns = {r[1] for r in self._db.execute("PRAGMA table_info(download_queue)")}
        for name, definition in {
            "priority": "INTEGER NOT NULL DEFAULT 0",
            "retry_safe": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in queue_columns:
                self._db.execute(f"ALTER TABLE download_queue ADD COLUMN {name} {definition}")
        feed_columns = {r[1] for r in self._db.execute("PRAGMA table_info(catalogue_feed)")}
        if "head_hashes" not in feed_columns:
            self._db.execute(
                "ALTER TABLE catalogue_feed ADD COLUMN head_hashes TEXT NOT NULL DEFAULT '[]'"
            )
        if "started_at" not in feed_columns:
            self._db.execute("ALTER TABLE catalogue_feed ADD COLUMN started_at REAL")
        catalogue_columns = {r[1] for r in self._db.execute("PRAGMA table_info(catalogue)")}
        if "source" not in catalogue_columns:
            self._db.execute(
                "ALTER TABLE catalogue ADD COLUMN source TEXT NOT NULL DEFAULT 'indexer'"
            )
        if "root" not in catalogue_columns:
            # c411's own category: Torznab ids alone mix some of them (Jeux vidéo and
            # Emulation are both 1000), so per-category parity needs the real one.
            self._db.execute("ALTER TABLE catalogue ADD COLUMN root INTEGER")
        crawl_columns = {r[1] for r in self._db.execute("PRAGMA table_info(catalogue_crawl)")}
        if "limited" not in crawl_columns:
            self._db.execute(
                "ALTER TABLE catalogue_crawl ADD COLUMN limited INTEGER NOT NULL DEFAULT 0"
            )
            # Older versions called a repeated final page a completed crawl. Recheck
            # these categories once; their stored torrents remain available to Plans.
            self._db.execute(
                "UPDATE catalogue_crawl SET complete = 0, next_offset = 0 WHERE complete = 1"
            )
        plan_columns = {r[1] for r in self._db.execute("PRAGMA table_info(plan_state)")}
        if "zen_added" not in plan_columns:  # 0.2.3 saved Plans without it
            self._db.execute("ALTER TABLE plan_state ADD COLUMN zen_added REAL")
        item_columns = {r[1] for r in self._db.execute("PRAGMA table_info(plan_item)")}
        if "client_id" not in item_columns:
            self._db.execute("ALTER TABLE plan_item ADD COLUMN client_id TEXT NOT NULL DEFAULT ''")
        columns = {r[1] for r in self._db.execute("PRAGMA table_info(verification)")}
        if "required_progress" not in columns:
            self._db.execute(
                "ALTER TABLE verification ADD COLUMN required_progress REAL NOT NULL DEFAULT 1.0"
            )
        if "required_pieces" not in columns:
            self._db.execute("ALTER TABLE verification ADD COLUMN required_pieces TEXT")
        if "local_files" not in columns:
            self._db.execute("ALTER TABLE verification ADD COLUMN local_files TEXT")

    def cached_search(self, key: str, max_age: float) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT body, fetched_at FROM search_cache WHERE key = ?", (key,)
            ).fetchone()
        if row and time.time() - row[1] <= max_age:
            return str(row[0])
        return None

    def cache_search(self, key: str, body: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO search_cache VALUES (?, ?, ?)", (key, body, time.time())
            )

    def remember_candidates(self, item_path: Path, candidates_json: str) -> None:
        """Keep the last search's Candidates of a Local Item (already free of the API key)."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO remembered_candidates VALUES (?, ?, ?)",
                (str(item_path), candidates_json, time.time()),
            )

    def remembered_candidates(self, item_path: Path) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT candidates FROM remembered_candidates WHERE item_path = ?",
                (str(item_path),),
            ).fetchone()
        return str(row[0]) if row else None

    def item_query(self, item_path: Path) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT query FROM item_query WHERE item_path = ?", (str(item_path),)
            ).fetchone()
        return str(row[0]) if row else None

    def set_item_query(self, item_path: Path, query: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO item_query VALUES (?, ?)", (str(item_path), query)
            )

    def cached_torrent(self, key: str) -> bytes | None:
        f = self.torrent_dir / f"{key}.torrent"
        try:
            return f.read_bytes()
        except FileNotFoundError:
            return None

    def cache_torrent(self, key: str, data: bytes) -> None:
        self.torrent_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.torrent_dir / f".{key}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_bytes(data)
            temporary.replace(self.torrent_dir / f"{key}.torrent")
        finally:
            temporary.unlink(missing_ok=True)

    # Layouts of cached .torrent files ----------------------------------------

    def unindexed_torrent_keys(self) -> list[str]:
        """Cached .torrent files whose layout is not yet in `layout_file`."""
        if not self.torrent_dir.is_dir():
            return []
        cached = {f.stem for f in self.torrent_dir.glob("*.torrent")}
        with self._lock:
            done = {r[0] for r in self._db.execute("SELECT cache_key FROM layout_indexed")}
        return sorted(cached - done)

    def index_layout(self, key: str, infohash: str, files: dict[str, int]) -> None:
        """Record a cached .torrent's files; empty `files` marks one that cannot be read."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM layout_file WHERE cache_key = ?", (key,))
            self._db.executemany(
                "INSERT OR REPLACE INTO layout_file VALUES (?, ?, ?, ?)",
                [(key, infohash.lower(), path, size) for path, size in files.items()],
            )
            self._db.execute("INSERT OR REPLACE INTO layout_indexed VALUES (?)", (key,))

    def layouts_holding(self, sizes: set[int], limit: int = 20) -> list[tuple[str, str]]:
        """Cached torrents (cache key, infohash) holding files of these exact sizes, the
        most bytes in common first."""
        common: dict[tuple[str, str], int] = {}
        ordered = sorted(sizes)
        with self._lock:
            for i in range(0, len(ordered), 500):
                chunk = ordered[i : i + 500]
                marks = ",".join("?" * len(chunk))
                for key, infohash, size in self._db.execute(
                    f"SELECT cache_key, infohash, size FROM layout_file WHERE size IN ({marks})",
                    chunk,
                ):
                    common[(key, infohash)] = common.get((key, infohash), 0) + size
        ranked = sorted(common, key=lambda k: (-common[k], k))
        return ranked[:limit]

    # Verifications in flight ------------------------------------------------

    def start_verification(
        self,
        hash: str,
        item_path: Path,
        candidate_key: str,
        required_pieces: list[tuple[int, int]] | None = None,
        local_files: list[str] | None = None,
    ) -> None:
        hash = self._verification_key(hash)
        pieces = json.dumps(required_pieces) if required_pieces is not None else None
        files = json.dumps(local_files or [])
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO verification"
                " (hash, item_path, candidate_key, rechecked_at, required_pieces, local_files)"
                " VALUES (?, ?, ?, NULL, ?, ?)",
                (hash, str(item_path), candidate_key, pieces, files),
            )

    def verification_hashes(self) -> list[str]:
        """Persisted Reseeds still waiting for client verification."""
        with self._lock:
            rows = [str(row[0]) for row in self._db.execute("SELECT hash FROM verification")]
        if self.client_id == "default":
            return [h for h in rows if ":" not in h]
        prefix = self.client_id + ":"
        return [h[len(prefix) :] for h in rows if h.startswith(prefix)]

    def mark_rechecked(self, hash: str) -> None:
        hash = self._verification_key(hash)
        with self._lock, self._db:
            self._db.execute(
                "UPDATE verification SET rechecked_at = ? WHERE hash = ?", (time.time(), hash)
            )

    def verification(self, hash: str) -> Verification | None:
        hash = self._verification_key(hash)
        with self._lock:
            row = self._db.execute(
                "SELECT item_path, candidate_key, rechecked_at, required_pieces, local_files"
                " FROM verification WHERE hash = ?",
                (hash,),
            ).fetchone()
        if not row:
            return None
        rechecked = float(row[2]) if row[2] is not None else None
        pieces = [tuple(r) for r in json.loads(row[3])] if row[3] is not None else None
        files = [str(f) for f in json.loads(row[4])] if row[4] else []
        return Verification(Path(row[0]), str(row[1]), rechecked, pieces, files)  # type: ignore[arg-type]

    def end_verification(self, hash: str) -> None:
        hash = self._verification_key(hash)
        with self._lock, self._db:
            self._db.execute("DELETE FROM verification WHERE hash = ?", (hash,))

    # Rejections -------------------------------------------------------------

    def reject(self, item_path: Path, candidate_key: str, reason: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO rejection VALUES (?, ?, ?)",
                (str(item_path), candidate_key, reason),
            )

    def unreject(self, item_path: Path, candidate_key: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM rejection WHERE item_path = ? AND candidate_key = ?",
                (str(item_path), candidate_key),
            )

    def rejections(self, item_path: Path) -> dict[str, str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT candidate_key, reason FROM rejection WHERE item_path = ?",
                (str(item_path),),
            ).fetchall()
        return {str(k): str(r) for k, r in rows}

    # Scan cache -------------------------------------------------------------

    def cached_scan(self, item_path: Path, signature: str) -> dict[str, int] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT files FROM scan_cache WHERE item_path = ? AND signature = ?",
                (str(item_path), signature),
            ).fetchone()
        return {str(k): int(v) for k, v in json.loads(row[0]).items()} if row else None

    def cache_scan(self, item_path: Path, signature: str, files: dict[str, int]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO scan_cache VALUES (?, ?, ?)",
                (str(item_path), signature, json.dumps(files)),
            )

    def torrent_files(self, hashes: list[str]) -> dict[str, dict[str, int]]:
        """File lists of these torrents read in an earlier scan, by lowercase hash."""
        found: dict[str, dict[str, int]] = {}
        with self._lock:
            for i in range(0, len(hashes), 500):
                chunk = [h.lower() for h in hashes[i : i + 500]]
                marks = ",".join("?" * len(chunk))
                for h, files in self._db.execute(
                    f"SELECT infohash, files FROM torrent_files WHERE client_id = ? "
                    f"AND infohash IN ({marks})",
                    [self.client_id, *chunk],
                ):
                    found[h] = {str(k): int(v) for k, v in json.loads(files).items()}
        return found

    def cache_torrent_files(self, files: dict[str, dict[str, int]]) -> None:
        with self._lock, self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO torrent_files VALUES (?, ?, ?)",
                [(self.client_id, h.lower(), json.dumps(f)) for h, f in files.items() if f],
            )

    def forget_torrent_files(self, infohash: str) -> None:
        """After renaming files inside a torrent: its next scan asks the client again."""
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM torrent_files WHERE client_id = ? AND infohash = ?",
                (self.client_id, infohash.lower()),
            )

    # Catalogue --------------------------------------------------------------

    def catalogue_unseen_since(
        self, since: float, root: int, categories: set[int], limit: int = 500
    ) -> list[str]:
        """Torrents of a c411 category that no listing has returned since `since`,
        oldest first: those known to be of it, and those of unknown category whose
        Torznab category it uses."""
        marks = ",".join("?" * len(categories))
        with self._lock:
            return [
                row[0]
                for row in self._db.execute(
                    "SELECT infohash FROM catalogue WHERE seen_at < ? AND (root = ?"
                    f" OR (root IS NULL AND category IN ({marks}))) ORDER BY seen_at LIMIT ?",
                    (since, root, *sorted(categories), limit),
                )
            ]

    def catalogue_root_counts(self) -> tuple[dict[int, int], dict[int, int]]:
        """Torrents per c411 category where known, and per Torznab category where not."""
        known: dict[int, int] = {}
        unknown: dict[int, int] = {}
        with self._lock:
            for root, category, count in self._db.execute(
                "SELECT root, category, COUNT(*) FROM catalogue GROUP BY root, category"
            ):
                if root is not None:
                    known[root] = known.get(root, 0) + count
                elif category is not None:
                    unknown[category] = unknown.get(category, 0) + count
        return known, unknown

    def forget_feed_states(self, prefixes: tuple[str, ...]) -> None:
        with self._lock, self._db:
            for prefix in prefixes:
                self._db.execute(
                    "DELETE FROM catalogue_feed WHERE substr(name, 1, ?) = ?",
                    (len(prefix), prefix),
                )

    def mark_catalogue_seen(self, infohash: str, when: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE catalogue SET seen_at = ? WHERE infohash = ?", (when, infohash.lower())
            )

    def drop_unavailable_torrent(self, infohash: str) -> None:
        """Remove an explicitly unavailable torrent and keep refreshes from restoring it."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO unavailable_torrent VALUES (?, ?)",
                (infohash.lower(), time.time()),
            )
            self._db.execute("DELETE FROM catalogue WHERE infohash = ? COLLATE NOCASE", (infohash,))

    def save_catalogue(self, rows: list[CatalogueRow]) -> None:
        with self._lock, self._db:
            self._db.executemany(
                "INSERT INTO catalogue SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                " WHERE NOT EXISTS (SELECT 1 FROM unavailable_torrent WHERE infohash = lower(?))"
                " ON CONFLICT(infohash) DO UPDATE SET"
                " title=excluded.title, size=excluded.size, seeders=excluded.seeders,"
                " category=excluded.category, download_url=excluded.download_url,"
                " details_url=excluded.details_url, seen_at=excluded.seen_at,"
                " source=excluded.source, root=COALESCE(excluded.root, catalogue.root)"
                # Live c411 rows outrank the bundled Catalogue, which outranks Zen
                # Lab's coarser categories: a source never replaces a better one.
                f" WHERE {_RANK.format('excluded')} >= {_RANK.format('catalogue')}",
                [
                    (
                        r.infohash,
                        r.title,
                        r.size,
                        r.seeders,
                        r.category,
                        r.download_url,
                        r.details_url,
                        r.seen_at,
                        r.source,
                        r.root,
                        r.infohash,
                    )
                    for r in rows
                ],
            )

    def known_hashes(self, hashes: list[str], *, seen_before: float | None = None) -> set[str]:
        with self._lock:
            found = set()
            for i in range(0, len(hashes), 500):
                chunk = hashes[i : i + 500]
                marks = ",".join("?" * len(chunk))
                found |= {
                    str(r[0])
                    for r in self._db.execute(
                        f"SELECT infohash FROM catalogue WHERE infohash IN ({marks})"
                        + (" AND seen_at < ?" if seen_before is not None else ""),
                        [*chunk, seen_before] if seen_before is not None else chunk,
                    )
                }
                # Excluded torrents still count as seen when deciding where a crawl stops.
                found |= {
                    str(r[0])
                    for r in self._db.execute(
                        f"SELECT infohash FROM unavailable_torrent WHERE infohash IN ({marks})"
                        + (" AND seen_at < ?" if seen_before is not None else ""),
                        [*chunk, seen_before] if seen_before is not None else chunk,
                    )
                }
            return found

    def catalogue(self, hashes: list[str] | None = None) -> list[CatalogueRow]:
        with self._lock:
            if hashes is None:
                rows = self._db.execute("SELECT * FROM catalogue").fetchall()
            else:
                rows = []
                for i in range(0, len(hashes), 500):
                    chunk = hashes[i : i + 500]
                    marks = ",".join("?" * len(chunk))
                    rows.extend(
                        self._db.execute(
                            f"SELECT * FROM catalogue WHERE infohash IN ({marks})", chunk
                        ).fetchall()
                    )
        return [CatalogueRow(*r) for r in rows]

    def catalogue_titled(self, words: list[str], limit: int = 200) -> list[CatalogueRow]:
        """Catalogue torrents whose name holds every word, best seeded first."""
        if not words:
            return []
        where = " AND ".join("title LIKE ?" for _ in words)
        with self._lock:
            rows = self._db.execute(
                f"SELECT * FROM catalogue WHERE {where} ORDER BY seeders DESC LIMIT ?",
                [f"%{w}%" for w in words] + [limit],
            ).fetchall()
        return [CatalogueRow(*r) for r in rows]

    def update_catalogue_seeders(self, counts: dict[str, int]) -> None:
        """Apply swarm observations without claiming size/category metadata was refreshed."""
        with self._lock, self._db:
            self._db.executemany(
                "UPDATE catalogue SET seeders = ? WHERE infohash = ?",
                [(count, h.lower()) for h, count in counts.items() if count >= 0],
            )

    def catalogue_sized(self, size: int, limit: int = 10) -> list[CatalogueRow]:
        """Catalogue torrents of exactly this many bytes, best seeded first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM catalogue WHERE size = ? ORDER BY seeders DESC LIMIT ?",
                (size, limit),
            ).fetchall()
        return [CatalogueRow(*r) for r in rows]

    def catalogue_row(self, infohash: str) -> CatalogueRow | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM catalogue WHERE infohash = ?", (infohash.lower(),)
            ).fetchone()
        return CatalogueRow(*row) if row else None

    def catalogue_sizes(self) -> frozenset[int]:
        """Every Catalogue torrent's exact size, to recognise a release folder by size."""
        with self._lock:
            return frozenset(
                row[0] for row in self._db.execute("SELECT DISTINCT size FROM catalogue")
            )

    def catalogue_size(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM catalogue").fetchone()[0])

    def catalogue_categories(self, hashes: list[str]) -> set[int]:
        """Categories of the given torrents, as far as the Catalogue knows them."""
        with self._lock:
            found: set[int] = set()
            for i in range(0, len(hashes), 500):
                chunk = hashes[i : i + 500]
                marks = ",".join("?" * len(chunk))
                found |= {
                    int(r[0])
                    for r in self._db.execute(
                        f"SELECT DISTINCT category FROM catalogue WHERE infohash IN ({marks})"
                        " AND category IS NOT NULL",
                        chunk,
                    )
                }
            return found

    def crawl_state(self, category: int) -> CrawlState:
        with self._lock:
            row = self._db.execute(
                "SELECT next_offset, complete, updated_at, limited"
                " FROM catalogue_crawl WHERE category = ?",
                (category,),
            ).fetchone()
        if not row:
            return CrawlState(category)
        return CrawlState(category, int(row[0]), bool(row[1]), row[2], bool(row[3]))

    def save_crawl_state(self, state: CrawlState) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO catalogue_crawl"
                " (category, next_offset, complete, updated_at, limited) VALUES (?, ?, ?, ?, ?)",
                (
                    state.category,
                    state.next_offset,
                    int(state.complete),
                    state.updated_at,
                    int(state.limited),
                ),
            )

    def limited_categories(self) -> set[int]:
        """Categories where the Indexer's paging limit prevented a complete crawl."""
        with self._lock:
            return {
                int(row[0])
                for row in self._db.execute(
                    "SELECT category FROM catalogue_crawl WHERE limited = 1"
                )
            }

    def feed_state(self, name: str) -> FeedState:
        with self._lock:
            row = self._db.execute(
                "SELECT next_page, updated_at, count, limited, head_hashes, started_at"
                " FROM catalogue_feed WHERE name = ?",
                (name,),
            ).fetchone()
        return (
            FeedState(name, row[0], row[1], row[2], bool(row[3]), tuple(json.loads(row[4])), row[5])
            if row
            else FeedState(name)
        )

    def save_feed_state(self, state: FeedState) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO catalogue_feed"
                " (name, next_page, updated_at, count, limited, head_hashes, started_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    state.name,
                    state.next_page,
                    state.updated_at,
                    state.count,
                    int(state.limited),
                    json.dumps(state.head_hashes),
                    state.started_at,
                ),
            )

    def catalogue_updated_at(self) -> float | None:
        with self._lock:
            row = self._db.execute("SELECT MAX(updated_at) FROM catalogue_crawl").fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def crawl_paused(self) -> bool:
        """Whether a full crawl stopped before the end of some category."""
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM catalogue_crawl WHERE next_offset > 0 AND complete = 0 LIMIT 1"
            ).fetchone()
            feed = self._db.execute(
                "SELECT 1 FROM catalogue_feed WHERE next_page > 1"
                " AND name NOT LIKE 'c411-latest:%' LIMIT 1"
            ).fetchone()
        return row is not None or feed is not None

    # Archives unpacked to Reseed --------------------------------------------

    def remember_unpacked(self, folder: Path, archive: Path) -> None:
        """The archive `folder` was unpacked from, until its Reseed is verified."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO unpacked_archive (folder, archive) VALUES (?, ?)",
                (str(folder), str(archive)),
            )

    def take_unpacked(self, folder: Path) -> Path | None:
        """The archive `folder` was unpacked from, forgotten once read."""
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT archive FROM unpacked_archive WHERE folder = ?", (str(folder),)
            ).fetchone()
            self._db.execute("DELETE FROM unpacked_archive WHERE folder = ?", (str(folder),))
        return Path(row[0]) if row else None

    # Uploads ----------------------------------------------------------------

    def save_upload(self, upload: SavedUpload) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO upload (item_path, title, infohash, draft_id, made_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(upload.item_path),
                    upload.title,
                    upload.infohash,
                    upload.draft_id,
                    upload.made_at,
                ),
            )

    def uploads(self) -> list[SavedUpload]:
        """Every Upload made, newest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT item_path, title, infohash, draft_id, made_at FROM upload "
                "ORDER BY made_at DESC"
            ).fetchall()
        return [SavedUpload(Path(r[0]), r[1], r[2], r[3], r[4]) for r in rows]

    def cached_options(self, subcategory: int) -> tuple[str, float] | None:
        """The Category Options response kept for a subcategory, and when it was fetched."""
        with self._lock:
            row = self._db.execute(
                "SELECT body, fetched_at FROM category_options WHERE subcategory = ?",
                (subcategory,),
            ).fetchone()
        return (str(row[0]), float(row[1])) if row else None

    def cache_options(self, subcategory: int, body: str, fetched_at: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO category_options (subcategory, body, fetched_at) "
                "VALUES (?, ?, ?)",
                (subcategory, body, fetched_at),
            )

    # The saved Plan ---------------------------------------------------------

    def save_plan(
        self,
        items: list[SavedPlanItem],
        made_at: float | None = None,
        zen_added: float | None = None,
    ) -> None:
        """Replace the saved Plan, so it survives a crash or a restart."""
        if self.client_id != "default":
            plan = SavedPlan(time.time() if made_at is None else made_at, False, items, zen_added)
            self._write_client_plan(plan if items else None)
            return
        with self._lock, self._db:
            self._db.execute("DELETE FROM plan_item")
            self._db.execute("DELETE FROM plan_state")
            if not items:
                return
            self._db.execute(
                "INSERT INTO plan_state (id, made_at, sending, zen_added) VALUES (1, ?, 0, ?)",
                (time.time() if made_at is None else made_at, zen_added),
            )
            self._db.executemany(
                "INSERT INTO plan_item (position, infohash, title, size, seeders, category,"
                " folder, zen, note, outcome, reason, client_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        n,
                        i.infohash,
                        i.title,
                        i.size,
                        i.seeders,
                        i.category,
                        i.folder,
                        i.zen,
                        i.note,
                        i.outcome,
                        i.reason,
                        i.client_id,
                    )
                    for n, i in enumerate(items)
                ],
            )

    def _write_client_plan(self, plan: SavedPlan | None) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM client_plan WHERE client_id=?", (self.client_id,))
            if plan is not None:
                self._db.execute(
                    "INSERT INTO client_plan VALUES (?, ?)",
                    (self.client_id, json.dumps(asdict(plan))),
                )

    def saved_plan(self) -> SavedPlan | None:
        if self.client_id != "default":
            with self._lock:
                row = self._db.execute(
                    "SELECT payload FROM client_plan WHERE client_id=?", (self.client_id,)
                ).fetchone()
            if row is None:
                return None
            data = json.loads(row[0])
            data["items"] = [SavedPlanItem(**i) for i in data["items"]]
            return SavedPlan(**data)
        with self._lock:
            state = self._db.execute(
                "SELECT made_at, sending, zen_added FROM plan_state"
            ).fetchone()
            rows = self._db.execute(
                "SELECT infohash, title, size, seeders, category, folder, zen, note, outcome,"
                " reason, client_id FROM plan_item ORDER BY position"
            ).fetchall()
        if state is None:
            return None
        return SavedPlan(
            float(state[0]), bool(state[1]), [SavedPlanItem(*r) for r in rows], state[2]
        )

    def set_plan_sending(self, sending: bool) -> None:
        if self.client_id != "default":
            if plan := self.saved_plan():
                self._write_client_plan(replace(plan, sending=sending))
            return
        with self._lock, self._db:
            self._db.execute("UPDATE plan_state SET sending = ?", (int(sending),))

    def mark_plan_item(self, infohash: str, outcome: str, reason: str = "") -> None:
        if self.client_id != "default":
            if plan := self.saved_plan():
                items = [
                    replace(i, outcome=outcome, reason=reason or None)
                    if i.infohash == infohash
                    else i
                    for i in plan.items
                ]
                self._write_client_plan(replace(plan, items=items))
            return
        with self._lock, self._db:
            self._db.execute(
                "UPDATE plan_item SET outcome = ?, reason = ? WHERE infohash = ?",
                (outcome, reason or None, infohash),
            )

    def clear_plan(self) -> None:
        self.save_plan([])

    def profile_day(self, account: str, day: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM profile_history WHERE account = ? AND day = ?",
                (account, day),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save_profile_day(self, account: str, day: str, payload: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO profile_history VALUES (?, ?, ?)",
                (account, day, json.dumps(payload, allow_nan=False)),
            )

    def profile_days(self, account: str) -> list[tuple[str, dict]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT day, payload FROM profile_history WHERE account = ? ORDER BY day",
                (account,),
            ).fetchall()
        return [(day, json.loads(payload)) for day, payload in rows]
