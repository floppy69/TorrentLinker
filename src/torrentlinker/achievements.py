"""Private, durable app-reported achievements; never a source of member permissions."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from uuid import uuid4

SEEDING_STATES = frozenset({"uploading", "stalledUP", "forcedUP"})
DEFINITION_VERSION = 1
FIRSTS = {
    "playlist": "playlist-first",
    "studio": "studio-first",
    "rss": "rss-first",
    "community-import": "community-import-first",
    "already-seeding": "already-seeding",
}
CODES = frozenset(
    {
        "already-seeding",
        "reseed-1",
        "reseed-10",
        "reseed-100",
        "playlist-first",
        "studio-first",
        "rss-first",
        "community-import-first",
    }
)


def torrent_identity(infohash: str) -> str:
    """Canonical client identity, kept local and shared only with paired installations."""
    value = infohash.lower()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise ValueError("Unsupported torrent identity.")
    return hashlib.sha256(
        ("btih:" if len(value) == 40 else "btmh:").encode() + value.encode()
    ).hexdigest()


def seeding(state: str, progress: float) -> bool:
    return state in SEEDING_STATES and math.isfinite(progress) and progress == 1


class Ledger:
    def __init__(self, path: Path, *, clock=time.time):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        path.chmod(0o600)
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        if self.db.execute("PRAGMA user_version").fetchone()[0] > 1:
            self.db.close()
            raise ValueError("This ledger requires a newer TorrentLinker version.")
        with self.db:
            self.db.executescript("""
                PRAGMA user_version=1;
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS actors(
                    actor TEXT PRIMARY KEY, account TEXT NOT NULL DEFAULT '',
                    sharing INTEGER NOT NULL DEFAULT 0, epoch TEXT NOT NULL DEFAULT '',
                    partition TEXT NOT NULL, consent_at REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS partitions(
                    actor TEXT NOT NULL, account TEXT NOT NULL, partition TEXT NOT NULL,
                    PRIMARY KEY(actor,account));
                CREATE TABLE IF NOT EXISTS pending(
                    actor TEXT NOT NULL, code TEXT NOT NULL, version INTEGER NOT NULL,
                    account TEXT NOT NULL, epoch TEXT NOT NULL, PRIMARY KEY(actor,code,version));
                CREATE TABLE IF NOT EXISTS reseed_pending(
                    actor TEXT NOT NULL, partition TEXT NOT NULL, client TEXT NOT NULL,
                    infohash TEXT NOT NULL, verified REAL NOT NULL,
                    PRIMARY KEY(actor,client,infohash));
                CREATE TABLE IF NOT EXISTS events(
                    actor TEXT NOT NULL, family TEXT NOT NULL, identity TEXT NOT NULL,
                    version INTEGER NOT NULL, evidence TEXT NOT NULL, earned REAL NOT NULL,
                    PRIMARY KEY(actor,family,identity,version));
                CREATE TABLE IF NOT EXISTS awards(
                    actor TEXT NOT NULL, code TEXT NOT NULL, version INTEGER NOT NULL,
                    earned REAL NOT NULL, PRIMARY KEY(actor,code,version));
            """)
            self.db.execute("BEGIN IMMEDIATE")
            # Additive migration for early local ledgers created during preview.
            for table, column, declaration in (
                ("pending", "explicit", "INTEGER NOT NULL DEFAULT 0"),
                ("reseed_pending", "checked", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if column not in {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('started',?)", (self.clock(),))

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _actor(actor: str) -> None:
        if (
            not isinstance(actor, str)
            or not 0 < len(actor) <= 160
            or any(ord(c) < 32 for c in actor)
        ):
            raise ValueError("An authenticated local actor is required.")

    def reseed(
        self,
        actor: str,
        infohash: str,
        *,
        verified_at: float,
        observed_at: float,
        state: str,
        progress: float,
        full: bool,
    ) -> bool:
        self._actor(actor)
        identity = torrent_identity(infohash)
        if (
            full is not True
            or not seeding(state, progress)
            or not all(math.isfinite(t) and t > 0 for t in (verified_at, observed_at))
            or observed_at <= verified_at
        ):
            return False
        evidence = {
            "full": True,
            "verified_at": verified_at,
            "observed_at": observed_at,
            "state": state,
            "progress": 1,
        }
        with self.lock, self.db:
            added = self.db.execute(
                "INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)",
                (
                    self._partition(actor),
                    "reseed",
                    identity,
                    DEFINITION_VERSION,
                    json.dumps(evidence),
                    observed_at,
                ),
            ).rowcount
            self._derive(actor)
            return bool(added)

    def _derive(self, actor: str) -> None:
        partition = self._partition(actor)
        times = [
            r[0]
            for r in self.db.execute(
                "SELECT earned FROM events WHERE actor=? AND family='reseed' "
                "AND version=1 ORDER BY earned,identity",
                (partition,),
            )
        ]
        for threshold in (1, 10, 100):
            if len(times) >= threshold:
                self._award(actor, f"reseed-{threshold}", times[threshold - 1])
        for family, code in FIRSTS.items():
            row = self.db.execute(
                "SELECT earned,evidence FROM events WHERE actor=? AND family=? AND version=1 "
                "ORDER BY earned,identity LIMIT 1",
                (partition, family),
            ).fetchone()
            if row:
                self._award(actor, code, row[0], eligible=not json.loads(row[1]).get("recovered"))

    def state(self, actor: str) -> dict:
        self._actor(actor)
        with self.lock:
            owner = self.db.execute(
                "SELECT account,sharing,epoch,partition FROM actors WHERE actor=?", (actor,)
            ).fetchone()
            return {
                "trackingStarted": self.db.execute(
                    "SELECT value FROM metadata WHERE key='started'"
                ).fetchone()[0],
                "account": owner["account"] if owner else "",
                "sharing": bool(owner and owner["sharing"]),
                "consentEpoch": owner["epoch"] if owner else "",
                "reseeds": self.db.execute(
                    "SELECT count(*) FROM events WHERE actor=? AND family='reseed' AND version=1",
                    (owner["partition"] if owner else "",),
                ).fetchone()[0],
                "achievements": [
                    dict(row)
                    for row in self.db.execute(
                        "SELECT code,version,earned FROM awards WHERE actor=? ORDER BY code",
                        (owner["partition"] if owner else "",),
                    )
                ],
            }

    def _award(self, actor: str, code: str, earned: float, *, eligible: bool = True) -> None:
        added = self.db.execute(
            "INSERT OR IGNORE INTO awards VALUES(?,?,?,?)",
            (self._partition(actor), code, DEFINITION_VERSION, earned),
        ).rowcount
        consent = self.db.execute(
            "SELECT consent_at FROM actors WHERE actor=?", (actor,)
        ).fetchone()
        self.db.execute(
            "UPDATE awards SET earned=min(earned,?) WHERE actor=? AND code=? AND version=?",
            (earned, self._partition(actor), code, DEFINITION_VERSION),
        )
        if not eligible or (consent and earned < consent[0]):
            self.db.execute(
                "DELETE FROM pending WHERE actor=? AND code=? AND version=? AND explicit=0",
                (actor, code, DEFINITION_VERSION),
            )
        elif added and consent and earned >= consent[0]:
            self._queue(actor, code, DEFINITION_VERSION)

    def _queue(self, actor: str, code: str, version: int, *, explicit=False) -> None:
        self.db.execute(
            "INSERT INTO pending(actor,code,version,account,epoch,explicit) "
            "SELECT actor,?,?,account,epoch,? FROM actors "
            "WHERE actor=? AND sharing=1 AND account<>'' AND epoch<>'' "
            "ON CONFLICT(actor,code,version) DO UPDATE "
            "SET explicit=max(explicit,excluded.explicit)",
            (code, version, int(explicit), actor),
        )

    def complete(self, actor: str, family: str, identity: str, *, recovered: bool = False) -> bool:
        """Called only after a trusted operation has durably completed, never from claim JSON."""
        self._actor(actor)
        if family not in FIRSTS or not isinstance(identity, str) or not 0 < len(identity) <= 512:
            raise ValueError("Unsupported completion evidence.")
        key = hashlib.sha256((family + ":" + identity).encode()).hexdigest()
        with self.lock, self.db:
            added = self.db.execute(
                "INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)",
                (
                    self._partition(actor),
                    family,
                    key,
                    DEFINITION_VERSION,
                    json.dumps({"completed": True, **({"recovered": True} if recovered else {})}),
                    self.clock(),
                ),
            ).rowcount
            self._derive(actor)
            return bool(added)

    def _partition(self, actor: str) -> str:
        if not self.db.in_transaction:
            self.db.execute("BEGIN IMMEDIATE")
        row = self.db.execute("SELECT partition FROM actors WHERE actor=?", (actor,)).fetchone()
        if row:
            return row[0]
        self.db.execute(
            "INSERT OR IGNORE INTO actors(actor,partition) VALUES(?,?)", (actor, uuid4().hex)
        )
        return self.db.execute("SELECT partition FROM actors WHERE actor=?", (actor,)).fetchone()[0]

    def bind(self, actor: str, account: str) -> None:
        self._actor(actor)
        if account:
            self._actor(account)
        with self.lock, self.db:
            partition = self._partition(actor)
            previous = self.db.execute(
                "SELECT account FROM actors WHERE actor=?", (actor,)
            ).fetchone()[0]
            if previous == account:
                return
            if not account:
                # Detached activity is private and unattributed. Never leave the
                # prior account's collection visible or write new events into it.
                partition = uuid4().hex
            if account:
                target = self.db.execute(
                    "SELECT partition FROM partitions WHERE actor=? AND account=?", (actor, account)
                ).fetchone()
                if target:
                    partition = target[0]
                elif self.db.execute(
                    "SELECT 1 FROM partitions WHERE actor=? LIMIT 1", (actor,)
                ).fetchone():
                    partition = uuid4().hex
                self.db.execute(
                    "INSERT OR IGNORE INTO partitions VALUES(?,?,?)", (actor, account, partition)
                )
            self.db.execute(
                "UPDATE actors SET account=?,partition=?,sharing=0,epoch='' WHERE actor=?",
                (account, partition, actor),
            )
            self.db.execute("DELETE FROM pending WHERE actor=?", (actor,))

    def sharing(self, actor: str, enabled: bool, epoch: str = "") -> None:
        self._actor(actor)
        with self.lock, self.db:
            self._partition(actor)
            owner = self.db.execute("SELECT account FROM actors WHERE actor=?", (actor,)).fetchone()
            if enabled and (not owner or not owner[0] or not epoch or len(epoch) > 160):
                raise ValueError("Link an account and confirm current sharing consent first.")
            self.db.execute(
                "UPDATE actors SET sharing=?,epoch=?,consent_at=? WHERE actor=?",
                (int(enabled), epoch if enabled else "", self.clock(), actor),
            )
            # Enabling sharing never submits awards already earned.
            self.db.execute("DELETE FROM pending WHERE actor=?", (actor,))

    def share_existing(self, actor: str) -> None:
        self._actor(actor)
        with self.lock, self.db:
            self._partition(actor)
            if not self.state(actor)["sharing"]:
                raise ValueError("Enable sharing first.")
            for award in self.db.execute(
                "SELECT code,version FROM awards WHERE actor=?", (self._partition(actor),)
            ):
                self._queue(actor, award["code"], award["version"], explicit=True)

    def pending(self, actor: str) -> list[dict]:
        self._actor(actor)
        with self.lock:
            return [
                {"code": r["code"], "definitionVersion": r["version"]}
                for r in self.db.execute(
                    "SELECT p.code,p.version FROM pending p JOIN actors a ON a.actor=p.actor "
                    "WHERE p.actor=? AND a.sharing=1 AND a.account=p.account "
                    "AND a.epoch=p.epoch ORDER BY p.code",
                    (actor,),
                )
            ]

    def acknowledge(self, actor: str, account: str, epoch: str, awards: list[dict]) -> None:
        with self.lock, self.db:
            for award in awards:
                self.db.execute(
                    "DELETE FROM pending WHERE actor=? AND account=? AND epoch=? "
                    "AND code=? AND version=?",
                    (actor, account, epoch, award["code"], award["definitionVersion"]),
                )

    def export(self, actor: str, *, after: str = "", limit: int = 500) -> dict:
        """Private peer/backup data. This document must never be sent to the Site API."""
        self._actor(actor)
        if not 1 <= limit <= 500:
            raise ValueError("Invalid ledger page size.")
        with self.lock:
            account = self.state(actor)["account"]
            if not account:
                raise ValueError("Link an account before merging ledgers.")
            rows = self.db.execute(
                "SELECT family,identity,version,evidence,earned FROM events WHERE actor=? "
                "AND family||':'||identity>? ORDER BY family,identity LIMIT ?",
                (
                    self.db.execute(
                        "SELECT partition FROM actors WHERE actor=?", (actor,)
                    ).fetchone()[0],
                    after,
                    limit,
                ),
            )
            return {
                "schemaVersion": 1,
                "accountId": account,
                "events": [{**dict(row), "evidence": json.loads(row["evidence"])} for row in rows],
            }

    def merge(self, actor: str, authenticated_account: str, payload: dict) -> int:
        """Import a validated page only after the transport has authenticated the peer account."""
        self._actor(actor)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schemaVersion", "accountId", "events"}
            or type(payload["schemaVersion"]) is not int
            or payload["schemaVersion"] != 1
            or payload["accountId"] != authenticated_account
            or not isinstance(payload["events"], list)
            or len(payload["events"]) > 500
        ):
            raise ValueError("Unsupported ledger page.")
        for event in payload["events"]:
            self._validate_event(event)
        with self.lock, self.db:
            self._partition(actor)
            if not authenticated_account or self.state(actor)["account"] != authenticated_account:
                raise ValueError("The paired account does not match.")
            added = 0
            for event in payload["events"]:
                partition = self._partition(actor)
                incoming = (event["earned"], json.dumps(event["evidence"], sort_keys=True))
                previous = self.db.execute(
                    "SELECT earned,evidence FROM events "
                    "WHERE actor=? AND family=? AND identity=? AND version=?",
                    (partition, event["family"], event["identity"], event["version"]),
                ).fetchone()
                if previous is None:
                    self.db.execute(
                        "INSERT INTO events VALUES(?,?,?,?,?,?)",
                        (
                            partition,
                            event["family"],
                            event["identity"],
                            event["version"],
                            incoming[1],
                            incoming[0],
                        ),
                    )
                    added += 1
                elif incoming < (previous[0], json.dumps(json.loads(previous[1]), sort_keys=True)):
                    # Earliest qualified evidence wins; canonical JSON breaks ties.
                    # Recovery evidence sorts before live evidence on equal dates,
                    # conservatively excluding implicit historical submissions.
                    self.db.execute(
                        "UPDATE events SET earned=?,evidence=? "
                        "WHERE actor=? AND family=? AND identity=? AND version=?",
                        (
                            *incoming,
                            partition,
                            event["family"],
                            event["identity"],
                            event["version"],
                        ),
                    )
            self._derive(actor)
            return added

    @staticmethod
    def _validate_event(event: dict) -> None:
        if (
            not isinstance(event, dict)
            or set(event) != {"family", "identity", "version", "evidence", "earned"}
            or not isinstance(event["family"], str)
            or event["family"] not in {*FIRSTS, "reseed"}
            or type(event["version"]) is not int
            or event["version"] != DEFINITION_VERSION
            or not isinstance(event["identity"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", event["identity"])
            or type(event["earned"]) not in (int, float)
            or not math.isfinite(event["earned"])
            or event["earned"] <= 0
            or not isinstance(event["evidence"], dict)
        ):
            raise ValueError("Unsupported achievement evidence.")
        evidence = event["evidence"]
        if event["family"] != "reseed":
            if (
                set(evidence) not in ({"completed"}, {"completed", "recovered"})
                or evidence.get("completed") is not True
                or ("recovered" in evidence and evidence["recovered"] is not True)
            ):
                raise ValueError("Incomplete achievement evidence.")
            return
        if (
            set(evidence) != {"full", "verified_at", "observed_at", "state", "progress"}
            or evidence["full"] is not True
            or type(evidence["progress"]) not in (int, float)
            or not isinstance(evidence["state"], str)
            or not seeding(evidence["state"], evidence["progress"])
            or any(
                type(evidence[k]) not in (int, float) or not math.isfinite(evidence[k])
                for k in ("verified_at", "observed_at")
            )
            or not 0 < evidence["verified_at"] < evidence["observed_at"]
            or event["earned"] != evidence["observed_at"]
        ):
            raise ValueError("A full recheck and later seeding observation are required.")

    def history_recovery_allowed(self, actor: str) -> bool:
        """Unattributed legacy assets may only join the first linked account."""
        with self.lock:
            accounts = [
                r[0]
                for r in self.db.execute("SELECT account FROM partitions WHERE actor=?", (actor,))
            ]
            return not accounts or accounts == [self.state(actor)["account"]]

    def reset(self, actor: str) -> None:
        """Explicit local reset. Does not remove published badges or enable sharing."""
        with self.lock, self.db:
            partition = self._partition(actor)
            for table in ("events", "awards"):
                self.db.execute(f"DELETE FROM {table} WHERE actor=?", (partition,))
            self.db.execute("DELETE FROM pending WHERE actor=?", (actor,))
            self.db.execute("DELETE FROM reseed_pending WHERE actor=?", (actor,))
            self.db.execute("UPDATE actors SET sharing=0,epoch='' WHERE actor=?", (actor,))

    def await_seeding(self, actor: str, client: str, infohash: str) -> None:
        self._actor(actor)
        torrent_identity(infohash)
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO reseed_pending "
                "(actor,partition,client,infohash,verified) VALUES(?,?,?,?,?)",
                (actor, self._partition(actor), client, infohash.lower(), self.clock()),
            )

    def observe(self, client_id: str, client) -> None:
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            pending = list(
                self.db.execute(
                    "SELECT * FROM reseed_pending WHERE client=? "
                    "ORDER BY checked,verified LIMIT 32",
                    (client_id,),
                )
            )
            sequence = self.db.execute(
                "SELECT coalesce(max(checked),0) FROM reseed_pending"
            ).fetchone()[0]
            for offset, row in enumerate(pending, 1):
                self.db.execute(
                    "UPDATE reseed_pending SET checked=? WHERE actor=? AND client=? AND infohash=?",
                    (sequence + offset, row["actor"], client_id, row["infohash"]),
                )
        for row in pending:
            with self.lock, self.db:
                valid = (
                    self._partition(row["actor"]) == row["partition"]
                    and self.clock() - row["verified"] < 604800
                )
            if not valid:
                torrent = None
            else:
                try:
                    torrent = client.torrent(row["infohash"], with_files=False)
                except Exception:
                    continue  # unavailable evidence never qualifies, and never leaks into logs
            completed = bool(torrent and seeding(torrent.state, torrent.progress))
            if completed and torrent is not None:
                with self.lock, self.db:
                    if self._partition(row["actor"]) == row["partition"]:
                        self.reseed(
                            row["actor"],
                            row["infohash"],
                            verified_at=row["verified"],
                            observed_at=self.clock(),
                            state=torrent.state,
                            progress=torrent.progress,
                            full=True,
                        )
            if (
                completed
                or torrent is None
                or torrent.state.startswith("checking")
                or torrent.state in {"error", "missingFiles"}
            ):
                with self.lock, self.db:
                    self.db.execute(
                        "DELETE FROM reseed_pending WHERE actor=? AND client=? AND infohash=? "
                        "AND partition=? AND verified=?",
                        (
                            row["actor"],
                            client_id,
                            row["infohash"],
                            row["partition"],
                            row["verified"],
                        ),
                    )


def record_completion(
    directory: Path, family: str, identity: str, *, account: str = "owner", viewer: str = ""
) -> None:
    actor = account if not viewer else json.dumps([account, viewer], separators=(",", ":"))
    _record(directory, lambda ledger: ledger.complete(actor, family, identity))


def await_seeding(directory: Path, client: str, infohash: str) -> None:
    _record(directory, lambda ledger: ledger.await_seeding("owner", client, infohash))


def observe_seeding(directory: Path, client_id: str, client) -> None:
    _record(directory, lambda ledger: ledger.observe(client_id, client))


def _record(directory: Path, operation) -> None:
    try:
        ledger = Ledger(directory / "achievements.sqlite")
        try:
            operation(ledger)
        finally:
            ledger.close()
    except (OSError, sqlite3.Error, ValueError):
        logging.getLogger(__name__).warning("Local achievement recording is unavailable.")
