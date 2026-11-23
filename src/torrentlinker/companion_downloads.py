"""Ephemeral, account-bound descriptor tests. No file or Torrent Client writes."""

from __future__ import annotations

import base64
import json
import re
import secrets
from collections.abc import Callable
from typing import Any

from torrentlinker.torrent_meta import read_torrent

MAX_TORRENT = 8 * 1024 * 1024
MAX_RESULT = (MAX_TORRENT * 4 // 3) + 4096
MAX_QUEUE = 100
MAX_HISTORY = 4000
FINISHED_KEEP = 600
MAX_READ = 4 * 1024 * 1024
MAX_BATCH = 25
# The only pages a read may ask for; c411 hides adult content from the API key, so
# these are read through the owner's signed-in tab, as the website itself would.
READ_ROUTES = (
    re.compile(r"/api/categories"),
    re.compile(r"/api/categories/8/filter-options"),
    re.compile(
        r"/api/torrents\?(?=(?:[A-Za-z0-9_=%.,+~-]+&)*category=8(?:&|$))[A-Za-z0-9_=&%.,+~-]{1,1500}"
    ),
)
MAX_CONCURRENCY = 16
DEFAULT_CONCURRENCY = 4  # measured: 2,000 files in 561 s, no refusal


REASONS = frozenset(
    {
        "origin",
        "account",
        "integrity",
        "type",
        "size",
        "empty",
        "timeout",
        "network",
        "stopped",
        "profile",
        "watchdog",
    }
)


class SessionFetchError(Exception):
    """A descriptor the browser session could not deliver."""

    def __init__(
        self, message: str, status: int = 0, retry_after: int = 0, fatal: bool = True
    ) -> None:
        super().__init__(message)
        self.fatal = fatal  # every later torrent would fail the same way
        self.status = status
        self.retry_after = retry_after


class CompanionDownloads:
    """Called under the ProfileWorkspace lock; raw descriptors are never retained."""

    def __init__(self, clock: Callable[[], float]):
        self.clock = clock
        self.jobs: dict[str, dict[str, Any]] = {}
        self.last_poll = 0.0
        self.retry_at = 0.0
        self.blocked = False
        self.concurrency = DEFAULT_CONCURRENCY

    def clear(self) -> None:
        self.jobs.clear()
        self.last_poll = 0.0
        self.blocked = False
        self.concurrency = DEFAULT_CONCURRENCY
        # Re-pairing must not remove a server-requested cooldown.

    def _expire(self) -> None:
        now = self.clock()
        for key, job in list(self.jobs.items()):
            finished = job["status"] not in ("pending", "running")
            if finished and job.get("raw") and now - job["created"] > 120:
                job.pop("raw")  # an abandoned request must not hold a descriptor
            if finished and job.get("json") and now - job["created"] > 120:
                job.pop("json")
            if now - job["created"] > (FINISHED_KEEP if finished else 600):
                del self.jobs[key]
            elif job["status"] in ("pending", "running") and now > job["expires"]:
                job.update(status="failed", error="Companion timed out. No automatic retry.")

    def state(self) -> dict[str, Any]:
        self._expire()
        return {
            "available": self.last_poll > 0 and self.clock() - self.last_poll < 70,
            "retry_after": max(0, int(self.retry_at - self.clock() + 0.999)),
            "blocked": self.blocked,
            "concurrency": self.concurrency,
        }

    @staticmethod
    def _public(job: dict[str, Any]) -> dict[str, Any]:
        return {
            k: v
            for k, v in job.items()
            if k not in ("actor", "request_id", "created", "expires", "raw", "keep", "json")
        }

    def set_concurrency(self, value: int) -> int:
        if type(value) is not int or not 1 <= value <= MAX_CONCURRENCY:
            raise ValueError(f"Use a concurrency from 1 to {MAX_CONCURRENCY}.")
        self.concurrency = value
        return value

    def get(self, identifier: str, actor: str) -> dict[str, Any]:
        self._expire()
        job = self.jobs.get(identifier)
        if job is None or job["actor"] != actor:
            raise ValueError("Download test unavailable or expired.")
        return self._public(job)

    def take(self, identifier: str) -> bytes | None:
        """Hand over a kept descriptor once; it is never retained after this."""
        job = self.jobs.get(identifier)
        return job.pop("raw", None) if job else None

    def submit(
        self, infohash: str, request_id: str, actor: str, keep: bool = False
    ) -> dict[str, Any]:
        self._expire()
        if not re.fullmatch(r"[a-fA-F0-9]{40}", infohash):
            raise ValueError("Use a torrent info hash, not a URL.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id):
            raise ValueError(
                "Use a stable request ID of 1–100 letters, digits, underscores or dashes."
            )
        infohash = infohash.lower()
        for job in self.jobs.values():
            if job["actor"] == actor and job["request_id"] == request_id:
                if job["infohash"] != infohash:
                    raise ValueError("Request ID already used for another torrent.")
                return self._public(job)
        state = self.state()
        if not state["available"]:
            raise ValueError("Connect the updated companion and keep a signed-in c411 tab open.")
        if self.blocked:
            raise ValueError("c411 refused the session. Check the account and reconnect.")
        if state["retry_after"]:
            raise ValueError(f"c411 requested a wait. Retry after {state['retry_after']} seconds.")
        if sum(j["status"] in ("pending", "running") for j in self.jobs.values()) >= MAX_QUEUE:
            raise ValueError("The companion download queue is full.")
        if len(self.jobs) >= MAX_HISTORY:
            raise ValueError("Recent test history is full. Wait for older results to expire.")
        now = self.clock()
        identifier = secrets.token_hex(16)
        job = dict(
            id=identifier,
            infohash=infohash,
            request_id=request_id,
            actor=actor,
            created=now,
            expires=now + 500,
            status="pending",
            keep=keep,
        )
        self.jobs[identifier] = job
        return self._public(job)

    def submit_read(self, path: str) -> dict[str, Any]:
        """Queue one fixed read-only page for the browser session (see READ_ROUTES)."""
        self._expire()
        if not any(route.fullmatch(path) for route in READ_ROUTES):
            raise ValueError("This page cannot be read through the session.")
        state = self.state()
        if not state["available"]:
            raise ValueError("Connect the updated companion and keep a signed-in c411 tab open.")
        if self.blocked:
            raise ValueError("c411 refused the session. Check the account and reconnect.")
        if state["retry_after"]:
            raise ValueError(f"c411 requested a wait. Retry after {state['retry_after']} seconds.")
        if sum(j["status"] in ("pending", "running") for j in self.jobs.values()) >= MAX_QUEUE:
            raise ValueError("The companion queue is full.")
        now = self.clock()
        identifier = secrets.token_hex(16)
        job = dict(
            id=identifier,
            kind="read",
            path=path,
            actor="app",
            request_id=identifier,
            infohash="",
            created=now,
            expires=now + 100,
            status="pending",
        )
        self.jobs[identifier] = job
        return self._public(job)

    def take_json(self, identifier: str) -> Any:
        job = self.jobs.get(identifier)
        return job.pop("json", None) if job else None

    def _receive_read(self, job: dict[str, Any], body: dict[str, Any]) -> dict[str, bool]:
        status = body.get("status")
        if type(status) is not int or not 0 <= status <= 599:
            raise ValueError("Invalid HTTP status.")
        job.update(status="failed", http_status=status)
        if status == 200:
            try:
                text = body.get("data")
                if not isinstance(text, str) or not 0 < len(text) <= MAX_READ:
                    raise ValueError()
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ValueError()
                job.update(status="complete", json=data)
            except ValueError:
                job["error"] = "Unexpected answer from c411."
            return {"accepted": True}
        job["error"] = "The session read was refused or unavailable."
        if status == 429:
            wait = body.get("retryAfter", 60)
            if type(wait) is not int or not 0 <= wait <= 2147483647:
                wait = 60
            self.retry_at = max(self.retry_at, self.clock() + max(60, wait))
            job["retry_after"] = max(60, wait)
        if status in (401, 403):
            self.blocked = True
        return {"accepted": True}

    def poll(self, account: str, limit: int = 1, reads_only: bool = False) -> dict[str, Any]:
        self._expire()
        now = self.clock()
        self.last_poll = now
        batch: list[dict[str, str]] = []
        if self.blocked or now < self.retry_at:
            return {"command": None, "commands": batch, "concurrency": self.concurrency}
        ordered = sorted(self.jobs.values(), key=lambda j: j.get("kind") != "read")
        for job in ordered:
            if job["status"] != "pending" or len(batch) >= max(1, min(limit, MAX_BATCH)):
                continue
            if job.get("kind") == "read":
                job.update(status="running", expires=now + 100)
                batch.append({"id": job["id"], "path": job["path"], "accountId": account})
            elif not reads_only:
                job.update(status="running", expires=now + 240)
                batch.append({"id": job["id"], "infohash": job["infohash"], "accountId": account})
        return {
            "command": batch[0] if batch else None,
            "commands": batch,
            "concurrency": self.concurrency,
        }

    def receive(self, body: dict[str, Any]) -> dict[str, bool]:
        self._expire()
        identifier = body.get("id")
        if not isinstance(identifier, str):
            raise ValueError("Invalid download test ID.")
        job = self.jobs.get(identifier)
        if job is None or job["status"] != "running":
            raise ValueError("No active download test matches this result.")
        if job.get("kind") == "read":
            return self._receive_read(job, body)
        status = body.get("status")
        if type(status) is not int or not 0 <= status <= 599:
            raise ValueError("Invalid HTTP status.")
        job.update(status="failed", http_status=status, discarded=True)
        elapsed = body.get("ms")
        if type(elapsed) is int and 0 <= elapsed <= 600000:
            job["ms"] = elapsed
        if status != 200:
            job["error"] = "The session download was refused or unavailable."
            reason = body.get("reason")
            if reason in REASONS:
                job["reason"] = reason
            if status == 429:
                wait = body.get("retryAfter", 60)
                if type(wait) is not int or not 0 <= wait <= 2147483647:
                    wait = 60
                self.retry_at = max(self.retry_at, self.clock() + max(60, wait))
                job["retry_after"] = max(60, wait)
            if status in (401, 403):
                self.blocked = True
            if status != 404 and job.get("reason") != "timeout":
                for other in self.jobs.values():
                    if other["status"] == "pending":
                        other.update(
                            status="failed",
                            http_status=0,
                            discarded=True,
                            error="Cancelled after an earlier failure.",
                        )
            return {"accepted": True}
        try:
            encoded = body.get("data")
            if not isinstance(encoded, str) or len(encoded) > MAX_RESULT:
                raise ValueError()
            raw = base64.b64decode(encoded, validate=True)
            if not 0 < len(raw) <= MAX_TORRENT:
                raise ValueError()
            meta = read_torrent(raw)
            if meta.infohash.lower() != job["infohash"] or not meta.files:
                raise ValueError()
            job.update(status="complete", bytes=len(raw), files=len(meta.files))
            if job.get("keep"):
                job["raw"] = raw
        except Exception:
            # Never expose parser errors, announce URLs or arbitrary tracker bodies.
            job["error"] = "Invalid torrent metadata or unexpected info hash."
        return {"accepted": True}
