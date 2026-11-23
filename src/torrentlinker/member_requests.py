"""Requests and Wishes: what a Member asks for instead of downloading (ADR-0022).

A Request names a tracker release; a Wish names only a film, for an Approver to find. Both
start `pending`. A Request goes `accepted` → `sent` → `downloading` → `available`, or ends
`refused`, `cancelled` or `expired`; `send_failed` when an accepted release could not reach
the Torrent Client. A Wish resolved to a release becomes an accepted Request.

Caps are checked at sending: accepted this week plus pending stay under the weekly count and
size, and pending under the pending cap. The week runs Monday 00:00 to Sunday 24:00, server
time. Refused, cancelled and expired ones give their slot and size back. They live in
`accounts.sqlite` with their timelines, and stay after their Member is deleted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as midnight
from uuid import uuid4

from torrentlinker.accounts import OWNER, Accounts, Caps

EXPIRY = 14 * 86400  # a Request or Wish pending this long expires
ACCEPTED = ("accepted", "sent", "send_failed", "downloading", "available")
OPEN = ("pending", *ACCEPTED)
STATES = (*OPEN, "refused", "cancelled", "expired")


def week(now: float) -> tuple[float, float]:
    """This week's Monday 00:00 and next Monday 00:00, server time."""
    day = datetime.fromtimestamp(now).date()
    monday = datetime.combine(day - timedelta(days=day.weekday()), midnight())
    return monday.timestamp(), (monday + timedelta(days=7)).timestamp()


class CapReached(ValueError):
    """A cap refuses the Request: which one (count, size or pending), and when it resets."""

    def __init__(self, message: str, cap: str, reset: float | None):
        super().__init__(message)
        self.cap, self.reset = cap, reset


@dataclass(frozen=True)
class Release:
    """The tracker release a Request names."""

    infohash: str
    name: str
    size: int
    title: str
    year: str = ""


class Requests:
    def __init__(self, accounts: Accounts):
        self.accounts = accounts
        self.db, self.lock = accounts.db, accounts.lock
        with self.lock, self.db:
            # No foreign key to accounts: a deleted Member's Requests stay in the history.
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, account TEXT NOT NULL, kind TEXT NOT NULL,
                    state TEXT NOT NULL, title TEXT NOT NULL, year TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '', infohash TEXT, release TEXT, size INTEGER,
                    created REAL NOT NULL, updated REAL NOT NULL, accepted REAL,
                    answered_by TEXT, answer TEXT NOT NULL DEFAULT '',
                    seen INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS requests_account ON requests(account, state);
                CREATE TABLE IF NOT EXISTS request_events (
                    request TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
                    at REAL NOT NULL, state TEXT NOT NULL, actor TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                );
            """)

        with self.lock, self.db:
            if "origin_kind" not in {
                row[1] for row in self.db.execute("PRAGMA table_info(requests)")
            }:
                self.db.execute(
                    "ALTER TABLE requests ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'request'"
                )
                self.db.execute("UPDATE requests SET origin_kind=kind")

    def recover_sends(self) -> None:
        """A restart cannot prove whether a claimed send reached the client; require Retry."""
        with self.lock:
            rows = self.db.execute("SELECT id FROM requests WHERE state='accepted'").fetchall()
            for row in rows:
                self.move(
                    row["id"],
                    "send_failed",
                    "",
                    "Server restarted during send. Check the client and retry.",
                )

    def quota(self, account: str, now: float | None = None) -> dict:
        """What the account may still ask for this week; None where it has no cap."""
        now = time.time() if now is None else now
        start, reset = week(now)
        caps = self.accounts.caps(account) if account != OWNER else Caps()
        with self.lock:
            pending = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(size),0) FROM requests "
                "WHERE account=? AND state='pending'",
                (account,),
            ).fetchone()
            accepted = self.db.execute(
                f"SELECT COUNT(*), COALESCE(SUM(size),0) FROM requests WHERE account=? "
                f"AND state IN ({','.join('?' * len(ACCEPTED))}) AND accepted>=?",
                (account, *ACCEPTED, start),
            ).fetchone()
        count, size = pending[0] + accepted[0], pending[1] + accepted[1]

        def left(cap: int | None, used: int) -> int | None:
            return None if cap is None else max(0, cap - used)

        return {
            "requests_left": left(caps.requests_per_week, count),
            "bytes_left": left(caps.bytes_per_week, size),
            "pending_left": left(caps.pending, pending[0]),
            "reset": reset,
        }

    def _check(self, account: str, size: int, now: float) -> None:
        quota = self.quota(account, now)
        reset = datetime.fromtimestamp(quota["reset"]).strftime("%A %d %B")
        if quota["pending_left"] == 0:
            raise CapReached(
                "Too many Requests are waiting for an answer: wait until one is answered.",
                "pending",
                None,
            )
        if quota["requests_left"] == 0:
            raise CapReached(
                f"Weekly quota reached. Next Request possible on {reset}.", "count", quota["reset"]
            )
        if quota["bytes_left"] is not None and size > quota["bytes_left"]:
            raise CapReached(
                f"This release is larger than what is left this week. More on {reset}.",
                "size",
                quota["reset"],
            )

    def ask(self, account: str, release: Release, now: float | None = None) -> dict:
        """A Request for a tracker release, refused with its reason when a cap is reached."""
        now = time.time() if now is None else now
        self.expire(now)
        with self.lock, self.db:
            if self.db.execute(
                f"SELECT 1 FROM requests WHERE account=? AND infohash=? "
                f"AND state IN ({','.join('?' * len(OPEN))})",
                (account, release.infohash, *OPEN),
            ).fetchone():
                raise ValueError("You have already asked for this release.")
            self._check(account, release.size, now)
            identifier = self._add(
                account,
                "request",
                release.title,
                release.year,
                "",
                now,
                infohash=release.infohash,
                release=release.name,
                size=release.size,
            )
        return self.get(identifier)

    def wish(self, account: str, title: str, year: str = "", note: str = "") -> dict:
        """A Wish: a film without a release, for an Approver to find."""
        now = time.time()
        title, year, note = title.strip(), year.strip(), note.strip()
        if not title or len(title) > 200:
            raise ValueError("Give the film's title.")
        if year and not (year.isdigit() and len(year) == 4):
            raise ValueError("Give the year with four digits, or leave it empty.")
        if len(note) > 500:
            raise ValueError("Keep the note under 500 characters.")
        self.expire(now)
        with self.lock, self.db:
            self._check(account, 0, now)
            identifier = self._add(account, "wish", title, year, note, now)
        return self.get(identifier)

    def _add(
        self,
        account: str,
        kind: str,
        title: str,
        year: str,
        note: str,
        now: float,
        **release,
    ) -> str:
        identifier = uuid4().hex
        self.db.execute(
            "INSERT INTO requests (id, account, kind, state, title, year, note, infohash, "
            "release, size, created, updated) VALUES (?,?,?,'pending',?,?,?,?,?,?,?,?)",
            (
                identifier,
                account,
                kind,
                title,
                year,
                note,
                release.get("infohash"),
                release.get("release"),
                release.get("size"),
                now,
                now,
            ),
        )
        self.db.execute("UPDATE requests SET origin_kind=? WHERE id=?", (kind, identifier))
        self.db.execute(
            "INSERT INTO request_events VALUES (?,?,'pending',?,?)",
            (identifier, now, account, note),
        )
        return identifier

    def move(
        self, identifier: str, state: str, actor: str, note: str = "", now: float | None = None
    ) -> None:
        """Change a Request's state and note it in its timeline. A change the Member did not
        make is new to them until they have seen it."""
        if state not in STATES:
            raise ValueError(f"Unknown Request state: {state}")
        now = time.time() if now is None else now
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT account, accepted FROM requests WHERE id=?", (identifier,)
            ).fetchone()
            if row is None:
                raise KeyError(identifier)
            answered = actor != row["account"]
            self.db.execute(
                "UPDATE requests SET state=?, updated=?, seen=?, accepted=?, "
                "answered_by=CASE WHEN ? THEN ? ELSE answered_by END, "
                "answer=CASE WHEN ? THEN ? ELSE answer END WHERE id=?",
                (
                    state,
                    now,
                    int(not answered),
                    row["accepted"] if row["accepted"] or state not in ACCEPTED else now,
                    answered and actor != "",
                    actor,
                    answered and bool(note),
                    note,
                    identifier,
                ),
            )
            self.db.execute(
                "INSERT INTO request_events VALUES (?,?,?,?,?)",
                (identifier, now, state, actor, note),
            )

    def review(self) -> list[dict]:
        """Approvers see all Requests, their requester, quotas and event history."""
        self.expire()
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM requests ORDER BY created DESC LIMIT 500"
            ).fetchall()
            return [
                {
                    **self._public(row),
                    "account": row["account"],
                    "requester": self.accounts.display_name(row["account"]),
                    "quota": self.quota(row["account"]),
                    "approval_limits": self.approval_limits(row["account"], row["id"]),
                    "events": [
                        dict(event)
                        for event in self.db.execute(
                            "SELECT at,state,actor,note FROM request_events "
                            "WHERE request=? ORDER BY at",
                            (row["id"],),
                        )
                    ],
                }
                for row in rows
            ]

    def approval_limits(self, account: str, identifier: str) -> dict:
        caps = self.accounts.caps(account) if account != OWNER else Caps()
        start, _ = week(time.time())
        with self.lock:
            used = self.db.execute(
                "SELECT COUNT(*),COALESCE(SUM(size),0) FROM requests "
                "WHERE account=? AND accepted>=? AND id<>?",
                (account, start, identifier),
            ).fetchone()
        return {
            "count_left": None
            if caps.requests_per_week is None
            else max(0, caps.requests_per_week - used[0]),
            "bytes_left": None
            if caps.bytes_per_week is None
            else max(0, caps.bytes_per_week - used[1]),
        }

    def answer(
        self,
        identifier: str,
        actor: str,
        *,
        release: Release | None = None,
        note: str = "",
        retry: bool = False,
        refuse: bool = False,
    ) -> dict:
        """Atomically claim a pending answer or failed send before any external action."""
        self.expire()
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM requests WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError(identifier)
            expected = "send_failed" if retry else "pending"
            if row["state"] != expected:
                raise ValueError("This Request has already been answered or is being sent.")
            if refuse:
                self.move(identifier, "refused", actor, note)
            else:
                if release is None:
                    if not row["infohash"]:
                        raise ValueError("Choose a release for this Wish first.")
                    release = Release(
                        row["infohash"], row["release"], row["size"], row["title"], row["year"]
                    )
                # The pending Request already reserves its original count and size.
                caps = self.accounts.caps(row["account"]) if row["account"] != OWNER else Caps()
                start, _ = week(time.time())
                used = self.db.execute(
                    "SELECT COUNT(*),COALESCE(SUM(size),0) FROM requests "
                    "WHERE account=? AND accepted>=? AND id<>?",
                    (row["account"], start, identifier),
                ).fetchone()
                over = (
                    caps.requests_per_week is not None
                    and used[0] + 1 > caps.requests_per_week
                    or caps.bytes_per_week is not None
                    and used[1] + release.size > caps.bytes_per_week
                )
                if over:
                    note = (note + "\nAccepted beyond the Member's weekly quota.").strip()
                self.db.execute(
                    "UPDATE requests SET kind='request',infohash=?,release=?,size=?,title=?,year=? "
                    "WHERE id=?",
                    (
                        release.infohash,
                        release.name,
                        release.size,
                        release.title,
                        release.year,
                        identifier,
                    ),
                )
                self.move(identifier, "accepted", actor, note)
            self.db.execute(
                "UPDATE requests SET answered_by=?,answer=?,seen=0 WHERE id=?",
                (actor, note, identifier),
            )
        return self.get(identifier)

    def cancel(self, account: str, identifier: str) -> dict:
        """The Member cancels their own Request or Wish while it is pending."""
        with self.lock:
            row = self.db.execute(
                "SELECT state FROM requests WHERE id=? AND account=?", (identifier, account)
            ).fetchone()
            if row is None:
                raise KeyError(identifier)
            if row["state"] != "pending":
                raise ValueError("Only a pending Request can be cancelled.")
            self.move(identifier, "cancelled", account)
        return self.get(identifier)

    def cancel_pending(self, account: str) -> None:
        """Before a Member is deleted: their pending Requests and Wishes are cancelled."""
        with self.lock:
            rows = self.db.execute(
                "SELECT id FROM requests WHERE account=? AND state='pending'", (account,)
            ).fetchall()
            for row in rows:
                self.move(row["id"], "cancelled", account)

    def expire(self, now: float | None = None) -> None:
        """Pending for 14 days: expired, and new to the Member."""
        now = time.time() if now is None else now
        with self.lock:
            rows = self.db.execute(
                "SELECT id FROM requests WHERE state='pending' AND created<?", (now - EXPIRY,)
            ).fetchall()
            for row in rows:
                self.move(row["id"], "expired", "", now=now)

    def get(self, identifier: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM requests WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        return self._public(row)

    def mine(self, account: str) -> list[dict]:
        """The account's Requests and Wishes, newest first."""
        self.expire()
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM requests WHERE account=? ORDER BY created DESC LIMIT 200",
                (account,),
            ).fetchall()
        return [self._public(r) for r in rows]

    def seen(self, account: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE requests SET seen=1 WHERE account=?", (account,))

    def _public(self, row) -> dict:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "state": row["state"],
            "title": row["title"],
            "year": row["year"],
            "note": row["note"],
            "infohash": row["infohash"] or "",
            "release": row["release"] or "",
            "size": row["size"],
            "created": row["created"],
            "updated": row["updated"],
            "answered_by": (
                self.accounts.display_name(row["answered_by"]) if row["answered_by"] else ""
            ),
            "answer": row["answer"],
            "unread": not row["seen"],
        }
