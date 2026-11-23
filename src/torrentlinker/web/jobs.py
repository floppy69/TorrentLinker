"""Persistent job history with separate batch and read-only interactive workers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from torrentlinker.job_lanes import job_lane


class JobStop(threading.Event):
    """Cancellation and an independent request to finish a Plan with cached metadata."""

    def __init__(self):
        super().__init__()
        self.plan_now = threading.Event()
        self.paused = threading.Event()


class Jobs:
    def __init__(self, directory: Path, error_message: Callable[[Exception], str] | None = None):
        self.error_message = error_message or (lambda error: type(error).__name__)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(directory / "jobs.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="torrentlinker-batch")
        self.interactive_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="torrentlinker-interactive"
        )
        self.stops: dict[str, JobStop] = {}
        # Pending work never survives restart. Keep only digests in memory, not
        # request bodies that may contain paths, confirmation tokens or credentials.
        self._request_keys: dict[str, str] = {}
        self.closed = False
        with self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT, "
                "status TEXT, created REAL, progress TEXT, result TEXT, error "
                "TEXT)"
            )
            if "client_id" not in {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}:
                self.db.execute(
                    "ALTER TABLE jobs ADD COLUMN client_id TEXT NOT NULL DEFAULT 'default'"
                )
            if "lane" not in {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}:
                self.db.execute("ALTER TABLE jobs ADD COLUMN lane TEXT NOT NULL DEFAULT 'batch'")
            if "subject" not in {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}:
                self.db.execute("ALTER TABLE jobs ADD COLUMN subject TEXT NOT NULL DEFAULT '{}'")
            self.db.execute(
                "UPDATE jobs SET status='interrupted', error='Server restarted. "
                "Check the Torrent Client before retrying; no action was "
                "replayed.' WHERE status IN ('queued','running')"
            )

    def active(self) -> bool:
        with self.lock:
            return bool(
                self.db.execute(
                    "SELECT 1 FROM jobs WHERE status IN ('queued','running') LIMIT 1"
                ).fetchone()
            )

    def check_capacity(
        self,
        kind: str,
        client_id: str = "default",
        *,
        parameters: dict[str, Any] | None = None,
        deduplicate: bool = True,
    ) -> str | None:
        """Return identical pending work, otherwise check capacity before reservations.

        Callers that reserve before submit must hold this lock across both operations.
        """
        with self.lock:
            if self.closed:
                raise ValueError("Server is shutting down.")
            if deduplicate:
                key = _request_key(parameters)
                pending = self.db.execute(
                    "SELECT id FROM jobs WHERE kind=? AND status IN ('queued','running') "
                    "AND client_id=? ORDER BY created",
                    (kind, client_id),
                ).fetchall()
                for row in pending:
                    if self._request_keys.get(row[0]) == key:
                        return str(row[0])
            count = self.db.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            if count >= 20:
                raise ValueError("Too many pending jobs. Wait for the current work to finish.")
            return None

    def submit(
        self,
        kind: str,
        work: Callable[[threading.Event, Callable[[Any], None]], Any],
        *,
        client_id: str = "default",
        parameters: dict[str, Any] | None = None,
        deduplicate: bool = True,
    ) -> str:
        with self.lock:
            existing = self.check_capacity(
                kind, client_id, parameters=parameters, deduplicate=deduplicate
            )
            if existing is not None:
                return existing
            identifier = uuid.uuid4().hex
            if deduplicate:
                self._request_keys[identifier] = _request_key(parameters)
            stop = self.stops[identifier] = JobStop()
            lane = job_lane(kind, parameters)
            with self.db:
                self.db.execute(
                    "INSERT INTO jobs "
                    "(id,kind,status,created,progress,result,error,client_id,lane,subject) "
                    "VALUES (?,?,'queued',?,'null','null','',?,?,?)",
                    (
                        identifier,
                        kind,
                        time.time(),
                        client_id,
                        lane,
                        json.dumps(job_subject(kind, parameters)),
                    ),
                )
            with self.db:
                self.db.execute(
                    "DELETE FROM jobs WHERE status NOT IN ('queued','running') AND id "
                    "NOT IN (SELECT id FROM jobs ORDER BY created DESC LIMIT 200)"
                )
            executor = self.interactive_executor if lane == "interactive" else self.executor
            executor.submit(self._run, identifier, stop, work)
            return identifier

    def _run(self, identifier: str, stop: threading.Event, work: Callable) -> None:
        if stop.is_set():
            self._update(identifier, status="cancelled")
            with self.lock:
                self.stops.pop(identifier, None)
                self._request_keys.pop(identifier, None)
            return
        self._update(identifier, status="running")
        reseed_job = self.get(identifier)["kind"] == "reseed-workspace"
        paused = getattr(stop, "paused", None)

        def report(progress):
            with self.lock:
                if reseed_job:
                    progress = {**progress, "paused": bool(paused and paused.is_set())}
                self._update(identifier, progress=json.dumps(progress))

        try:
            result = work(stop, report)
        except Exception as error:
            # Never persist raw network exception text, which may include credentials.
            self._update(
                identifier,
                status="cancelled" if stop.is_set() else "failed",
                error="" if stop.is_set() else self.error_message(error),
            )
        else:
            status = (
                "partial"
                if self.get(identifier)["kind"] == "scan"
                and isinstance(result, dict)
                and result.get("partial")
                else "completed"
            )
            self._update(
                identifier,
                status="cancelled" if stop.is_set() else status,
                result=json.dumps(result),
            )
        finally:
            with self.lock:
                self.stops.pop(identifier, None)
                self._request_keys.pop(identifier, None)

    def _update(self, identifier: str, **values: Any) -> None:
        with self.lock, self.db:
            self.db.execute(
                "UPDATE jobs SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?",
                (*values.values(), identifier),
            )

    def get(self, identifier: str) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        result = dict(row)
        for key in ("progress", "result", "subject"):
            result[key] = json.loads(result[key])
        return result

    def diagnostic_rows(self) -> list[dict[str, Any]]:
        """Bounded metadata only; never read errors, progress or results for export."""
        with self.lock:
            rows = self.db.execute(
                "SELECT kind,status,client_id FROM jobs ORDER BY created DESC LIMIT 20"
            ).fetchall()
        return [dict(row) for row in rows]

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT id,kind,status,created,progress,error,client_id,lane,subject "
                "FROM jobs WHERE status IN ('queued','running') OR id IN "
                "(SELECT id FROM jobs WHERE status NOT IN ('queued','running') "
                "ORDER BY created DESC LIMIT 100) ORDER BY created DESC"
            ).fetchall()
        result = [
            {**dict(r), "progress": json.loads(r["progress"]), "subject": json.loads(r["subject"])}
            for r in rows
        ]
        lanes: dict[str, list[dict]] = {}
        for row in reversed(result):
            if row["status"] not in {"running", "queued"}:
                continue
            ahead = lanes.setdefault(row["lane"], [])
            row["queue_position"] = len(ahead) if row["status"] == "queued" else 0
            row["waiting_for"] = (
                {key: ahead[-1][key] for key in ("id", "kind", "client_id")}
                if ahead and row["status"] == "queued"
                else None
            )
            ahead.append(row)
        return result

    def cancel(self, identifier: str) -> None:
        with self.lock:
            row = self.get(identifier)
            if (row["progress"] or {}).get("cancellable") is False:
                raise ValueError(
                    "This job cannot be cancelled after Torrent Client submission begins."
                )
            if identifier in self.stops:
                self.stops[identifier].set()

    def plan_now(self, identifier: str) -> None:
        with self.lock:
            row = self.get(identifier)
            if row["kind"] != "plan" or row["status"] not in {"queued", "running"}:
                raise ValueError("This Plan is no longer fetching its Catalogue.")
            if (row["progress"] or {}).get("phase") == "planning":
                raise ValueError("This Plan is already being calculated.")
            self.stops[identifier].plan_now.set()

    def pause_reseed(self, identifier: str, paused: bool) -> None:
        with self.lock:
            row = self.get(identifier)
            if row["kind"] != "reseed-workspace" or identifier not in self.stops:
                raise ValueError("This reseed run is no longer active.")
            event = self.stops[identifier].paused
            event.set() if paused else event.clear()
            progress = row["progress"] or {}
            self._update(identifier, progress=json.dumps({**progress, "paused": paused}))

    def close(self) -> None:
        with self.lock:
            self.closed = True
            for identifier, stop in self.stops.items():
                if (self.get(identifier)["progress"] or {}).get("cancellable") is not False:
                    stop.set()
        self.executor.shutdown(wait=True)
        self.interactive_executor.shutdown(wait=True)
        self.db.close()


def _request_key(parameters: dict[str, Any] | None) -> str:
    encoded = json.dumps(parameters or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def job_subject(kind: str, parameters: dict[str, Any] | None) -> dict[str, Any]:
    """Persist identifiers for UI matching, never arbitrary request bodies or tokens."""
    parameters = parameters or {}
    subject: dict[str, Any] = {"kind": kind}
    for key in ("path", "draft_id", "repair_id", "plan_id", "feed_id"):
        value = parameters.get(key)
        if isinstance(value, str) and value:
            subject[key] = value
    for key in ("paths", "hashes"):
        value = parameters.get(key)
        if isinstance(value, list):
            subject[key] = [item for item in value if isinstance(item, str)]
    for key in ("inspector_action", "reseed_action", "queue_action", "feed_operation"):
        value = parameters.get(key)
        if isinstance(value, str) and value:
            subject[key] = value
    return subject
