"""Durable owner-authored community actions, shared by desktop and WebUI.

Only the paired browser executes c411 writes. A transaction reserves each attempt
before dispatch; ambiguous results are never automatically sent a second time.
"""

from __future__ import annotations

import copy
import html
import json
import math
import os
import re
import secrets
import sqlite3
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from torrentlinker.community_schedule import (
    AUTOMATION,
    in_window,
    next_slot,
    site_day,
    validate_automation,
)

KINDS = {"comment": "comment_post", "vote": "trust_vote", "chat": "shout_message"}
EDITABLE = {"draft", "queued", "paused", "refused", "cancelled"}
DEFAULTS = {
    "automation": AUTOMATION,
    "enabled": False,
    "limits": {"comment": 5, "vote": 5, "chat": 5},
    "intervals": {"comment": 60, "vote": 60, "chat": 600},
    "templates": {"comment": "", "chat": ""},
}
MAX_ITEMS = 500


def normalized(text: str) -> str:
    plain = html.unescape(re.sub(r"<[^>]*>", " ", text))
    plain = "".join(c for c in unicodedata.normalize("NFKD", plain) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", plain.casefold()))


def bounded(value: Any, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"Use a whole number from {low} to {high}.")
    return value


def message_library() -> list[dict[str, Any]]:
    path = Path(__file__).parent / "assets" / "community_messages_fr.json"
    return json.loads(path.read_text(encoding="utf-8"))["entries"] if path.exists() else []


class CommunityActions:
    def __init__(self, directory: Path, clock: Callable[[], float] = time.time):
        self.path = directory / "community.sqlite3"
        self.clock = clock
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account TEXT PRIMARY KEY, settings TEXT NOT NULL,
                    snapshot TEXT NOT NULL DEFAULT '{}', synced REAL NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0, page INTEGER NOT NULL DEFAULT 1,
                    refresh INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, account TEXT NOT NULL, kind TEXT NOT NULL,
                    subject TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                    due REAL NOT NULL, created REAL NOT NULL, position REAL NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, attempt TEXT, started REAL,
                    posted REAL, remote_id TEXT, note TEXT NOT NULL DEFAULT '',
                    reward TEXT NOT NULL DEFAULT 'unknown');
                CREATE INDEX IF NOT EXISTS action_account ON actions(account, state, due);
                CREATE TABLE IF NOT EXISTS candidates (
                    account TEXT NOT NULL, hash TEXT NOT NULL, title TEXT NOT NULL,
                    seen REAL NOT NULL, PRIMARY KEY(account,hash));
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL,
                    action_id TEXT NOT NULL, time REAL NOT NULL, state TEXT NOT NULL,
                    content TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS event_account ON events(account, action_id, time);
            """)
            columns = {r["name"] for r in db.execute("PRAGMA table_info(actions)")}
            if "source" not in columns:
                db.execute("ALTER TABLE actions ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
            columns = {r["name"] for r in db.execute("PRAGMA table_info(accounts)")}
            if "discovered" not in columns:
                db.execute("ALTER TABLE accounts ADD COLUMN discovered REAL NOT NULL DEFAULT 0")
            if "scan" not in columns:
                db.execute("ALTER TABLE accounts ADD COLUMN scan TEXT NOT NULL DEFAULT ''")
            if "scan_started" not in columns:
                db.execute("ALTER TABLE accounts ADD COLUMN scan_started REAL NOT NULL DEFAULT 0")

    @staticmethod
    def _settings(row: sqlite3.Row) -> dict[str, Any]:
        return {**copy.deepcopy(DEFAULTS), **json.loads(row["settings"])}

    def _event(self, db: sqlite3.Connection, account: str, identifier: str, note: str = "") -> None:
        row = db.execute(
            "SELECT * FROM actions WHERE id=? AND account=?", (identifier, account)
        ).fetchone()
        if row:
            db.execute(
                "INSERT INTO events(account,action_id,time,state,content,note) "
                "VALUES (?,?,?,?,?,?)",
                (account, identifier, self.clock(), row["state"], row["payload"], note),
            )

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _account(self, db: sqlite3.Connection, account: str) -> sqlite3.Row:
        if not account or len(account) > 160:
            raise ValueError("Refresh the c411 profile first.")
        db.execute(
            "INSERT OR IGNORE INTO accounts(account,settings) VALUES (?,?)",
            (account, json.dumps(DEFAULTS)),
        )
        row = db.execute("SELECT * FROM accounts WHERE account=?", (account,)).fetchone()
        assert row is not None
        return row

    def _expire(self, db: sqlite3.Connection, account: str) -> None:
        expired = [
            r["id"]
            for r in db.execute(
                "SELECT id FROM actions WHERE account=? AND state='sending' AND started<?",
                (account, self.clock() - 180),
            )
        ]
        db.execute(
            """UPDATE actions SET state='uncertain', note='No receipt. Check c411; no retry.'
                      WHERE account=? AND state='sending' AND started<?""",
            (account, self.clock() - 180),
        )

        for identifier in expired:
            self._event(db, account, identifier, "receipt_timeout")

    @staticmethod
    def _item(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result.pop("account")
        result.update(json.loads(result.pop("payload")))
        if result["reward"] == "pending_24h" and result["posted"]:
            result["reward_due"] = result["posted"] + 86400
        return result

    def daily_contribution(self, account: str) -> dict[str, Any]:
        """Profile counters without loading the library, history or scheduling work."""
        with self._db() as db:
            return self._daily_contribution(db, account, self._account(db, account))

    def _daily_contribution(
        self, db: sqlite3.Connection, account: str, row: sqlite3.Row
    ) -> dict[str, Any]:
        today_start, _ = site_day(self.clock())
        snapshot = json.loads(row["snapshot"])
        if row["synced"] < today_start:
            for rule in snapshot.get("rules", {}).values():
                rule["today"] = 0
        limits = self._settings(row)["limits"]
        counts = dict(
            db.execute(
                "SELECT kind, COUNT(*) FROM actions WHERE account=? "
                "AND state IN ('sending','uncertain','posted') AND started>=? GROUP BY kind",
                (account, today_start),
            ).fetchall()
        )
        return {
            kind: {
                "local_used": counts.get(kind, 0),
                "site_used": snapshot.get("rules", {}).get(kind, {}).get("today"),
                "limit": limits[kind],
            }
            for kind in KINDS
        }

    def state(self, account: str) -> dict[str, Any]:
        with self._db() as db:
            row = self._account(db, account)
            self._expire(db, account)
            items = [
                self._item(r)
                for r in db.execute(
                    "SELECT * FROM actions WHERE account=? ORDER BY position,created", (account,)
                )
            ]
            events: dict[str, list[dict[str, Any]]] = {}
            for event in db.execute(
                "SELECT * FROM events WHERE account=? ORDER BY sequence", (account,)
            ):
                events.setdefault(event["action_id"], []).append(
                    {
                        "time": event["time"],
                        "state": event["state"],
                        "note": event["note"],
                        **json.loads(event["content"]),
                    }
                )
            for item in items:
                item["events"] = events.get(item["id"], [])
                item["updated"] = (
                    item["events"][-1]["time"]
                    if item["events"]
                    else item["posted"] or item["created"]
                )
            snapshot = json.loads(row["snapshot"])
            today_start, _ = site_day(self.clock())
            if row["synced"] < today_start:
                for rule in snapshot.get("rules", {}).values():
                    rule["today"] = 0
            settings = self._settings(row)
            quotas = self._daily_contribution(db, account, row)
            reservations = {
                k: [
                    i["started"]
                    for i in items
                    if i["kind"] == k
                    and i["state"] in ("sending", "uncertain", "posted")
                    and (i["started"] or 0) >= min(today_start, self.clock() - 86400)
                ]
                for k in KINDS
            }
            for k in KINDS:
                rule = snapshot.get("rules", {}).get(k, {})
                reservations[k].extend(
                    [self.clock()]
                    * max(0, rule.get("today", 0) - sum(t >= today_start for t in reservations[k]))
                )
            for item in items:
                if item["state"] not in ("queued", "paused"):
                    continue
                kind = item["kind"]
                rule = snapshot.get("rules", {}).get(kind, {})
                cap = min(settings["limits"][kind], rule.get("limit", 0))
                recent = sorted(
                    i["started"]
                    for i in items
                    if i["kind"] == kind
                    and i["state"] in ("sending", "uncertain", "posted")
                    and (i["started"] or 0) >= min(today_start, self.clock() - 86400)
                )
                next_at = max(item["due"], row["retry_at"])
                if recent:
                    next_at = max(
                        next_at,
                        recent[-1] + max(settings["intervals"][kind], rule.get("cooldown", 0)),
                    )
                slot = next_slot(
                    max(next_at, self.clock()),
                    reservations[kind],
                    cap,
                    max(30, settings["intervals"][kind], rule.get("cooldown", 0)),
                    settings["automation"] if item["source"] == "automatic" else None,
                )
                item["next_at"] = slot if slot is not None else next_at
                if slot is not None:
                    reservations[kind].append(slot)
                item["wait_reason"] = (
                    "Queue paused"
                    if not settings["enabled"]
                    else "Action disabled"
                    if not settings["limits"][kind]
                    else "Waiting for fresh site limits"
                    if self.clock() - row["synced"] > 90 or row["synced"] < today_start
                    else "Site permission required"
                    if rule.get("locked", True)
                    else "Site daily limit reached"
                    if rule.get("today", 0) >= cap
                    else ""
                )
            return {
                "account_id": account,
                "settings": settings,
                "items": items,
                "candidates": [
                    dict(r)
                    for r in db.execute(
                        "SELECT hash,title,seen FROM candidates WHERE account=? "
                        "ORDER BY seen DESC,title",
                        (account,),
                    )
                ],
                "channels": snapshot.get("channels", []),
                "quotas": quotas,
                "synced_at": row["synced"],
                "discovered_at": row["discovered"],
                "retry_at": row["retry_at"],
                "page": row["page"],
                "refresh_pending": bool(row["refresh"]),
                "now": self.clock(),
            }

    def settings(self, account: str, values: dict[str, Any]) -> None:
        values = copy.deepcopy(values)
        with self._db() as db:
            previous = self._settings(self._account(db, account))
        values.setdefault("automation", previous["automation"])
        if set(values) != set(DEFAULTS) or type(values["enabled"]) is not bool:
            raise ValueError("Invalid community settings.")
        for field in ("limits", "intervals"):
            if not isinstance(values[field], dict) or set(values[field]) != set(KINDS):
                raise ValueError("Set a separate limit and interval for each action.")
            for value in values[field].values():
                bounded(value, 0 if field == "limits" else 30, 5 if field == "limits" else 86400)
        if not isinstance(values["templates"], dict) or set(values["templates"]) != {
            "comment",
            "chat",
        }:
            raise ValueError("Invalid templates.")
        if any(not isinstance(t, str) or len(t) > 500 for t in values["templates"].values()):
            raise ValueError("Templates must contain at most 500 characters.")
        validate_automation(values["automation"])
        if (
            values["automation"]["enabled"]
            and values["automation"]["kinds"]["comment"]
            and len(values["templates"]["comment"].strip()) < 3
        ):
            raise ValueError("Write a comment template before enabling automatic comments.")
        if values["automation"]["enabled"] and not previous["automation"]["enabled"]:
            # Planning slots the queue would never send looks like a broken schedule.
            values["enabled"] = True
        with self._db() as db:
            self._account(db, account)
            db.execute(
                "UPDATE accounts SET settings=? WHERE account=?", (json.dumps(values), account)
            )
            config = values["automation"]
            snapshot = json.loads(self._account(db, account)["snapshot"])
            channels = {
                c["id"] for c in snapshot.get("channels", []) if c["kind"] in config["channels"]
            }
            messages = {normalized(m) for m in config["messages"]}
            for item in db.execute(
                "SELECT * FROM actions WHERE account=? AND source='automatic' "
                "AND state IN ('queued','paused')",
                (account,),
            ).fetchall():
                payload = json.loads(item["payload"])
                removed = item["kind"] == "chat" and (
                    item["subject"] not in channels
                    or normalized(payload["content"]) not in messages
                )
                if not config["enabled"] or not config["kinds"][item["kind"]] or removed:
                    db.execute(
                        "UPDATE actions SET "
                        "state='cancelled',revision=revision+1,note='automation_disabled' "
                        "WHERE id=?",
                        (item["id"],),
                    )
                    self._event(db, account, item["id"], "automation_disabled")
                elif item["kind"] == "comment":
                    content = (
                        values["templates"]["comment"]
                        .replace("{titre}", payload["title"])
                        .replace("{title}", payload["title"])
                    )
                    if not 3 <= len(content.strip()) <= 500:
                        raise ValueError(
                            "The rendered comment template must contain 3 to 500 characters."
                        )
                    if content != payload["content"]:
                        payload["content"] = content
                        db.execute(
                            "UPDATE actions SET payload=?,revision=revision+1 WHERE id=?",
                            (json.dumps(payload), item["id"]),
                        )
                        self._event(db, account, item["id"], "template_updated")
            self._plan(db, account)

    def refresh(self, account: str, page: int = 1) -> None:
        bounded(page, 1, 100000)
        with self._db() as db:
            self._account(db, account)
            db.execute(
                "UPDATE accounts SET page=?,refresh=1,scan_started=?,scan=? WHERE account=?",
                (page, self.clock(), secrets.token_hex(16), account),
            )

    def demand(self, account: str) -> dict[str, Any]:
        with self._db() as db:
            row = self._account(db, account)
            settings = self._settings(row)
            return {
                "collect": bool(row["refresh"]) or settings["enabled"],
                "seeds": bool(row["refresh"]),
                "scan": row["scan"],
                "page": row["page"],
                "retry_at": row["retry_at"],
            }

    def observe(self, account: str, data: dict[str, Any]) -> None:
        # Data returned by the extension is deliberately much narrower than c411's bodies.
        if set(data) - {
            "rules",
            "channels",
            "candidates",
            "page",
            "has_more",
            "seeds",
            "scan",
        } or not {
            "rules",
            "channels",
            "candidates",
            "page",
        } <= set(data):
            raise ValueError("Invalid community snapshot.")
        rules = data["rules"]
        if not isinstance(rules, dict) or set(rules) != set(KINDS):
            raise ValueError("Missing action rules.")
        clean_rules = {}
        for kind, rule in rules.items():
            if not isinstance(rule, dict):
                raise ValueError("Invalid action rule.")
            clean_rules[kind] = {
                "today": bounded(rule.get("today"), 0, 1000000),
                "limit": bounded(rule.get("limit"), 0, 5),
                "cooldown": bounded(rule.get("cooldown"), 0, 86400),
                "locked": rule.get("locked") is not False,
            }
        channels = data["channels"]
        candidates = data["candidates"]
        if not isinstance(channels, list) or len(channels) > 20:
            raise ValueError("Invalid channels.")
        clean_channels = []
        for c in channels:
            if not isinstance(c, dict) or c.get("kind") not in ("general", "class"):
                raise ValueError("Only general and class channels are supported.")
            clean_channels.append(
                {
                    "id": str(bounded(c.get("id"), 1, 2147483647)),
                    "name": str(c.get("name", ""))[:160],
                    "kind": c["kind"],
                }
            )
        if not isinstance(candidates, list) or len(candidates) > 50:
            raise ValueError("Read at most 50 seeds at a time.")
        clean_candidates = []
        for c in candidates:
            if not isinstance(c, dict) or not re.fullmatch(r"[a-f0-9]{40}", c.get("hash", "")):
                raise ValueError("Invalid torrent hash.")
            clean_candidates.append(
                (account, c["hash"], str(c.get("title", ""))[:300], self.clock())
            )
        page = bounded(data["page"], 1, 100000)
        if "seeds" in data and type(data["seeds"]) is not bool:
            raise ValueError("Invalid seed collection flag.")
        if "scan" in data and (
            not isinstance(data["scan"], str) or not re.fullmatch(r"[a-f0-9]{32}|", data["scan"])
        ):
            raise ValueError("Invalid discovery scan.")
        if "has_more" in data and type(data["has_more"]) is not bool:
            raise ValueError("Invalid page status.")
        with self._db() as db:
            row = self._account(db, account)
            db.execute(
                "UPDATE accounts SET snapshot=?,synced=?,refresh=? WHERE account=?",
                (
                    json.dumps({"rules": clean_rules, "channels": clean_channels}),
                    self.clock(),
                    row["refresh"],
                    account,
                ),
            )
            matching_scan = "scan" not in data or data["scan"] == row["scan"]
            collected_seeds = data.get("seeds", True) and matching_scan
            if not collected_seeds:
                clean_candidates = []
            if row["refresh"] and page == row["page"] and collected_seeds:
                more = data.get("has_more", False) and page < 100000
                db.execute(
                    "UPDATE accounts SET page=?,refresh=?,discovered=? WHERE account=?",
                    (
                        page + 1 if more else page,
                        int(more),
                        row["discovered"] if more else self.clock(),
                        account,
                    ),
                )
                if not more and row["scan_started"]:
                    db.execute(
                        "DELETE FROM candidates WHERE account=? AND seen<?",
                        (account, row["scan_started"]),
                    )
            db.executemany(
                "INSERT INTO candidates VALUES (?,?,?,?) ON CONFLICT(account,hash) "
                "DO UPDATE SET title=excluded.title,seen=excluded.seen",
                clean_candidates,
            )
            self._plan(db, account)

    def save(self, account: str, data: dict[str, Any]) -> str:
        kind = data.get("kind")
        if kind not in KINDS:
            raise ValueError("Choose a comment, vote or chat message.")
        subject = data.get("subject", "")
        if not isinstance(subject, str) or not re.fullmatch(
            r"[1-9][0-9]{0,9}" if kind == "chat" else r"[a-fA-F0-9]{40}", subject
        ):
            raise ValueError("Choose a channel or enter a torrent's 40-character info hash.")
        subject = subject.lower()
        content = data.get("content", "")
        vote = data.get("vote", "")
        if not isinstance(content, str) or len(content) > 500:
            raise ValueError("Use at most 500 characters.")
        content = content.strip()
        if kind != "vote" and len(content) < 3:
            raise ValueError("Write the message before saving.")
        if kind == "chat" and len(content.split()) < 5:
            raise ValueError("Chat messages require at least five words.")
        if kind == "vote" and (
            vote not in ("approve", "disapprove") or (vote == "disapprove" and len(content) < 5)
        ):
            raise ValueError(
                "Choose your vote; disapproval needs a reason of at least five characters."
            )
        due = data.get("due", self.clock())
        if type(due) not in (int, float) or not math.isfinite(due) or not 0 <= due <= 32503680000:
            raise ValueError("Invalid scheduled time.")
        identifier = data.get("id") or secrets.token_hex(16)
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Invalid draft ID.")
        with self._db() as db:
            self._account(db, account)
            old = db.execute(
                "SELECT * FROM actions WHERE id=? AND account=?", (identifier, account)
            ).fetchone()
            if data.get("id") and old is None:
                raise ValueError("Draft not found.")
            if old and (old["state"] not in EDITABLE or data.get("revision") != old["revision"]):
                raise ValueError("Draft changed or already sent. Reload it before editing.")
            for other in db.execute(
                "SELECT * FROM actions WHERE account=? AND id<>? AND state<>'cancelled'",
                (account, identifier),
            ):
                if other["kind"] == kind and (
                    (kind != "chat" and other["subject"] == subject)
                    or (
                        kind == "chat"
                        and normalized(json.loads(other["payload"])["content"])
                        == normalized(content)
                    )
                ):
                    raise ValueError(
                        "This torrent action or chat message is already in the journal."
                    )
            payload = json.dumps(
                {
                    "content": content,
                    "vote": vote if kind == "vote" else "",
                    "title": str(data.get("title", subject))[:300],
                }
            )
            if old:
                # Editing always returns the item to draft, requiring Queue again.
                db.execute(
                    "UPDATE actions SET "
                    "kind=?,subject=?,payload=?,due=?,state='draft',source='manual',"
                    "revision=revision+1,note='' WHERE id=?",
                    (kind, subject, payload, due, identifier),
                )
            else:
                count = db.execute(
                    "SELECT count(*) FROM actions WHERE account=? AND state IN "
                    "('draft','queued','paused','sending')",
                    (account,),
                ).fetchone()[0]
                if count >= MAX_ITEMS:
                    raise ValueError("The waitlist is full. Cancel or finish older drafts first.")
                db.execute(
                    "INSERT INTO actions(id,account,kind,subject,payload,state,"
                    "due,created,position) "
                    "VALUES (?,?,?,?,?,'draft',?,?,?)",
                    (identifier, account, kind, subject, payload, due, self.clock(), self.clock()),
                )
            self._event(db, account, identifier)
        return identifier

    def control(self, account: str, identifier: str, action: str, revision: int) -> None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM actions WHERE id=? AND account=?", (identifier, account)
            ).fetchone()
            if row is None or row["revision"] != revision:
                raise ValueError("Item changed. Reload the waitlist.")
            if row["state"] not in EDITABLE:
                raise ValueError("Already sending or sent. Check c411 for uncertain results.")
            states = {"queue": "queued", "pause": "paused", "cancel": "cancelled"}
            if action == "queue":
                for other in db.execute(
                    "SELECT * FROM actions WHERE account=? AND kind=? "
                    "AND id<>? AND state<>'cancelled'",
                    (account, row["kind"], identifier),
                ):
                    same = (
                        other["subject"] == row["subject"]
                        if row["kind"] != "chat"
                        else normalized(json.loads(other["payload"])["content"])
                        == normalized(json.loads(row["payload"])["content"])
                    )
                    if same:
                        raise ValueError("This action is already in the journal.")
            if action in states:
                db.execute(
                    "UPDATE actions SET state=?,revision=revision+1,note='' WHERE id=?",
                    (states[action], identifier),
                )
            elif action == "first":
                first = db.execute(
                    "SELECT min(position) FROM actions WHERE account=?", (account,)
                ).fetchone()[0]
                db.execute(
                    "UPDATE actions SET position=?,revision=revision+1 WHERE id=?",
                    (first - 1, identifier),
                )
            else:
                raise ValueError("Unknown queue action.")
            self._event(db, account, identifier, action)

    def claim(self, account: str) -> dict[str, Any] | None:
        now = self.clock()
        with self._db() as db:
            row = self._account(db, account)
            self._expire(db, account)
            settings = self._settings(row)
            today_start, _ = site_day(now)
            if (
                not settings["enabled"]
                or now < row["retry_at"]
                or now - row["synced"] > 90
                or row["synced"] < today_start
            ):
                return None
            if db.execute(
                "SELECT 1 FROM actions WHERE account=? AND state='sending'", (account,)
            ).fetchone():
                return None
            self._plan(db, account)
            rules = json.loads(row["snapshot"]).get("rules", {})
            for job in db.execute(
                "SELECT * FROM actions WHERE account=? AND state='queued' AND due<=? "
                "ORDER BY position,created",
                (account, now),
            ).fetchall():
                kind = job["kind"]
                if job["source"] == "automatic":
                    config = settings["automation"]
                    if (
                        not config["enabled"]
                        or not config["kinds"][kind]
                        or in_window(now, config) > now
                    ):
                        continue
                rule = rules.get(kind)
                if not rule or rule["locked"]:
                    continue
                cap = min(settings["limits"][kind], rule["limit"])
                recent = db.execute(
                    "SELECT started FROM actions WHERE account=? AND kind=? "
                    "AND state IN ('sending','uncertain','posted') AND started>=? "
                    "ORDER BY started",
                    (account, kind, min(today_start, now - 86400)),
                ).fetchall()
                interval = max(30, settings["intervals"][kind], rule["cooldown"])
                # Daily quota resets at Paris midnight; cooldown still crosses midnight.
                if (
                    sum(r["started"] >= today_start for r in recent) >= cap
                    or rule["today"] + sum(r["started"] >= row["synced"] for r in recent) >= cap
                ):
                    continue
                if recent and now < recent[-1]["started"] + interval:
                    continue
                attempt = secrets.token_hex(16)
                db.execute(
                    "UPDATE actions SET state='sending',attempt=?,started=?,revision=revision+1 "
                    "WHERE id=?",
                    (attempt, now, job["id"]),
                )
                self._event(db, account, job["id"])
                return {
                    "id": job["id"],
                    "attempt": attempt,
                    "accountId": account,
                    "kind": kind,
                    "subject": job["subject"],
                    "limit": cap,
                    "expires": now + 90,
                    **json.loads(job["payload"]),
                }
        return None

    def receipt(self, account: str, data: dict[str, Any]) -> None:
        result = data.get("outcome")
        if result not in ("posted", "refused", "uncertain", "deferred"):
            raise ValueError("Invalid action receipt.")
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM actions WHERE account=? AND id=? AND attempt=?",
                (account, data.get("id"), data.get("attempt")),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown posting attempt.")
            if row["state"] not in ("sending", "uncertain"):
                return  # Receipt acknowledgement retry, never another send.
            remote = data.get("remoteId")
            if result == "posted" and (not isinstance(remote, str) or not 0 < len(remote) <= 160):
                result = "uncertain"
            note = data.get("reason", "")
            # Never accept arbitrary site errors, HTML, credentials or traceback text.
            allowed = {
                "account",
                "auth",
                "permission",
                "duplicate",
                "quota",
                "cooldown",
                "network",
                "schema",
                "expired",
                "token",
                "unavailable",
                "receipt",
                "rate",
                "channel",
            }
            note = note if note in allowed else ""
            wait = data.get("retryAfter", 60)
            wait = wait if type(wait) is int and 0 <= wait <= 86400 else 60
            if result == "deferred":
                db.execute(
                    "UPDATE accounts SET retry_at=max(retry_at,?) WHERE account=?",
                    (self.clock() + max(30, wait), account),
                )
            if note in ("auth", "account", "token"):
                settings = self._settings(self._account(db, account))
                settings["enabled"] = False
                db.execute(
                    "UPDATE accounts SET settings=? WHERE account=?",
                    (json.dumps(settings), account),
                )
            db.execute(
                "UPDATE actions SET state=?,posted=?,remote_id=?,note=?,reward=? WHERE id=?",
                (
                    "queued" if result == "deferred" else result,
                    self.clock() if result == "posted" else None,
                    remote if result == "posted" else None,
                    note,
                    "pending_24h" if result == "posted" and row["kind"] == "comment" else "unknown",
                    row["id"],
                ),
            )

            self._event(db, account, row["id"], note)

    def discover(self, account: str) -> None:
        """Request a bounded background scan when the Community view is opened."""
        with self._db() as db:
            row = self._account(db, account)
            if not row["refresh"] and (
                not row["discovered"] or self.clock() - row["discovered"] > 21600
            ):
                db.execute(
                    "UPDATE accounts SET refresh=1,page=1,scan_started=?,scan=? WHERE account=?",
                    (self.clock(), secrets.token_hex(16), account),
                )

    def _plan(self, db: sqlite3.Connection, account: str) -> None:
        row = self._account(db, account)
        settings = self._settings(row)
        config = settings["automation"]
        if not config["enabled"]:
            return
        now = self.clock()
        items = [dict(r) for r in db.execute("SELECT * FROM actions WHERE account=?", (account,))]
        active = sum(i["state"] in ("draft", "queued", "paused", "sending") for i in items)
        snapshot = json.loads(row["snapshot"])
        if row["synced"] < site_day(now)[0]:
            for rule in snapshot.get("rules", {}).values():
                rule["today"] = 0
        rules = snapshot.get("rules", {})
        for kind in KINDS:
            if not config["kinds"][kind]:
                continue
            rule = rules.get(kind, {})
            cap = min(settings["limits"][kind], rule.get("limit", 0))
            if not cap or rule.get("locked", True):
                continue
            reservations = [
                i["started"]
                for i in items
                if i["kind"] == kind
                and i["state"] in ("sending", "uncertain", "posted")
                and (i["started"] or 0) >= min(site_day(now)[0], now - 86400)
            ]
            # External sends reserve capacity conservatively until a later snapshot.
            reservations.extend(
                [now]
                * max(0, rule.get("today", 0) - sum(t >= site_day(now)[0] for t in reservations))
            )
            reservations.extend(
                max(now, i["due"])
                for i in items
                if i["kind"] == kind and i["state"] in ("queued", "paused")
            )
            interval = max(30, settings["intervals"][kind], rule.get("cooldown", 0))
            proposals = []
            known = {
                i["subject"]
                for i in items
                if i["kind"] == kind
                and not (i["state"] == "cancelled" and i["note"] == "automation_disabled")
            }
            if kind == "comment":
                for candidate in db.execute(
                    "SELECT * FROM candidates WHERE account=? ORDER BY seen DESC,title", (account,)
                ):
                    if candidate["hash"] not in known:
                        content = (
                            settings["templates"]["comment"]
                            .replace("{titre}", candidate["title"])
                            .replace("{title}", candidate["title"])
                        )
                        if 3 <= len(content.strip()) <= 500:
                            proposals.append(
                                (
                                    None,
                                    candidate["hash"],
                                    {"title": candidate["title"], "content": content, "vote": ""},
                                )
                            )
            elif kind == "vote":
                proposed = set()
                for item in sorted(items, key=lambda i: i["created"], reverse=True):
                    if item["kind"] != "vote" or item["subject"] in proposed:
                        continue
                    recover = item["state"] == "cancelled" and item["note"] == "automation_disabled"
                    if item["state"] != "draft" and not recover:
                        continue
                    if recover and any(
                        other["kind"] == "vote"
                        and other["subject"] == item["subject"]
                        and other["state"] != "cancelled"
                        for other in items
                    ):
                        continue
                    proposals.append((item["id"], item["subject"], json.loads(item["payload"])))
                    proposed.add(item["subject"])
            else:
                channels = [
                    c for c in snapshot.get("channels", []) if c["kind"] in config["channels"]
                ]
                seen = {
                    normalized(json.loads(i["payload"])["content"])
                    for i in items
                    if i["kind"] == "chat"
                    and not (i["state"] == "cancelled" and i["note"] == "automation_disabled")
                }
                if channels:
                    for message in config["messages"]:
                        if normalized(message) not in seen:
                            channel = channels[len(proposals) % len(channels)]
                            proposals.append(
                                (
                                    None,
                                    channel["id"],
                                    {
                                        "title": channel["name"],
                                        "content": message.strip(),
                                        "vote": "",
                                    },
                                )
                            )
                            seen.add(normalized(message))
            # New proposals all start now against the same reservations: once one finds no
            # slot this week, none will. Trying thousands of candidates froze video playback.
            full = False
            for identifier, subject, payload in proposals:
                if (active >= MAX_ITEMS or full) and not identifier:
                    break
                earliest = (
                    max(now, next(i["due"] for i in items if i["id"] == identifier))
                    if identifier
                    else now
                )
                slot = next_slot(earliest, reservations, cap, interval, config)
                if slot is None or slot >= now + 7 * 86400:
                    full = full or not identifier
                    continue
                if identifier:
                    db.execute(
                        "UPDATE actions SET "
                        "state='queued',source='automatic',due=?,revision=revision+1,note='' "
                        "WHERE id=?",
                        (slot, identifier),
                    )
                else:
                    identifier = secrets.token_hex(16)
                    db.execute(
                        "INSERT INTO "
                        "actions(id,account,kind,subject,payload,state,due,"
                        "created,position,source) "
                        "VALUES (?,?,?,?,?,'queued',?,?,?,'automatic')",
                        (identifier, account, kind, subject, json.dumps(payload), slot, now, slot),
                    )
                    active += 1
                reservations.append(slot)
                self._event(db, account, identifier, "automatic")
