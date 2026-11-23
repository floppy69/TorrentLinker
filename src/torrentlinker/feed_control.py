"""RSS adapters shared by owner UI and MCP, with budgeted automatic dispatch."""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from torrentlinker.feeds import (
    FeedService,
    Subscription,
    candidate,
    evaluate,
    work_alias_map,
    work_identity,
)
from torrentlinker.indexer import Candidate

if TYPE_CHECKING:
    from torrentlinker.agent.service import AgentService


class FeedControl:
    def __init__(self, service: AgentService):
        self.service = service
        self.feeds = FeedService(service.setup.path.parent / "feeds.sqlite", service.setup.indexer)
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.loop, daemon=True, name="rss-monitor")
            self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)

    def loop(self):
        while not self.stop.wait(30):
            if self.service.suspended or not self.service.setup.configured:
                continue
            try:
                self.tick()
            except Exception:
                # Per-feed errors are persisted. Never log source URLs or keys.
                continue

    def inventory(self, *, refresh: bool = False, client_ids: list[str] | None = None) -> dict:
        hashes, clients, unknown, queue_hashes = self._observe(refresh, client_ids)
        known = {row["infohash"]: row for row in self.feeds.releases()}
        if refresh:
            missing = [
                hash
                for hash in sorted(hashes | queue_hashes)
                if hash in known
                and not work_identity(candidate(known[hash]))
                and known[hash].get("metadata", {}).get("metadata_checked_at", 0)
                < time.time() - 900
            ]
            for hash in missing[:10]:
                try:
                    known[hash] = self.feeds.enrich(hash)
                except Exception:
                    self.feeds.metadata_error(hash)
        identities = {
            hash: work_identity(candidate(known[hash])) if hash in known else None
            for hash in hashes
        }
        unresolved = sorted(hash for hash, identity in identities.items() if not identity)
        works = {identity for identity in identities.values() if identity is not None}
        return {
            "hashes": sorted(hashes),
            "clients": clients,
            "unavailable_clients": unknown,
            "works": sorted(works),
            "unknown_work_hashes": unresolved,
            "work_identity_coverage": (
                "Only verified identifiers from known feed releases. Other client "
                "torrents may have unknown work identity."
            ),
        }

    def _observe(
        self, refresh: bool, client_ids: list[str] | None
    ) -> tuple[set[str], dict[str, list[str]], list[str], set[str]]:
        """Each client's torrent hashes, refreshed when asked, and the queued hashes."""
        if client_ids is not None:
            for client_id in client_ids:
                self.service.setup.settings.profile(client_id)
        hashes = set()
        clients = {}
        unknown = []
        for profile in self.service.setup.settings.client_profiles:
            if not profile.enabled or (client_ids is not None and profile.id not in client_ids):
                continue
            target = self.service.for_client(profile.id)
            if refresh:
                try:
                    target.observed = target.setup.client().torrents(with_files=False)
                    target.connection_error = ""
                    target.feed_observed_at = time.time()
                except Exception:
                    target.connection_error = "Client inventory unavailable."
            fresh = getattr(target, "feed_observed_at", 0) > time.time() - 1800
            if not fresh or target.connection_error:
                unknown.append(profile.id)
            present = {torrent.hash.lower() for torrent in target.observed}
            clients[profile.id] = sorted(present)
            hashes.update(present)
            self.feeds.observe_client_releases(
                Candidate(torrent.name, torrent.size, "", infohash=torrent.hash.lower())
                for torrent in target.observed
            )
        from torrentlinker.download_queue import entries

        queued = [
            entry.candidate
            for entry in entries(self.service.setup.store, all_clients=True)
            if entry.candidate.infohash
        ]
        self.feeds.observe_client_releases(queued)
        queue_hashes = {c.infohash for c in queued if c.infohash}
        return hashes, clients, unknown, queue_hashes

    def inbox(self, *, client_ids: list[str] | None = None, **filters) -> list[dict]:
        from torrentlinker.download_queue import entries

        _, clients, unavailable, _ = self._observe(False, client_ids)
        present = {client: set(hashes) for client, hashes in clients.items()}
        queued = {
            e.candidate.infohash: e
            for e in entries(self.service.setup.store, all_clients=True)
            if client_ids is None or e.client_id in client_ids
        }
        result = self.feeds.inbox(**filters)
        for row in result:
            row["in_clients"] = [
                client for client, hashes in present.items() if row["infohash"] in hashes
            ]
            row["client_inventory_unknown"] = unavailable
            entry = queued.get(row["infohash"])
            row["queue_status"] = entry.status if entry else ""
            row["queued"] = bool(entry)
        return result

    def save(self, feed: Subscription, *, approved: bool = False, actor: str = "") -> dict:
        self.service.setup.settings.profile(feed.client_id)
        old = self.feeds.get(feed.id) if feed.id else None
        if (
            old is None or old.query != feed.query or old.categories != feed.categories
        ) and not self.feeds.has_preview(feed):
            raise ValueError("Preview this definition before saving.")
        if feed.folder:
            target = self.service.for_client(feed.client_id)
            target.setup.path_under_root(feed.folder)
            # Validate the configured per-client destination without changing global folders.
            if feed.folder not in target.download_destinations():
                raise ValueError("Choose a configured Download Folder for this Torrent Client.")
        if feed.mode == "automatic_download" and not approved:
            raise ValueError("Automatic downloads need explicit owner approval of this rule.")
        saved = self.feeds.save(feed, allow_automatic=approved)
        if saved.mode == "automatic_download":
            from torrentlinker.agent.access import Grant

            grant = Grant(
                name=f"RSS: {saved.name}",
                clients=[saved.client_id],
                mode="execute",
                permissions=["downloads"],
                daily_bytes=saved.daily_bytes,
                daily_torrents=saved.daily_torrents,
                reserve_bytes=saved.reserve_bytes,
            )
            with self.feeds.lock, self.feeds.db:
                old = self.feeds.db.execute(
                    "SELECT actor FROM actors WHERE feed=?", (saved.id,)
                ).fetchone()
                if old:
                    self.service.revoke(old[0])
                    self.service.access.set_internal_active(old[0], True)
                    self.service.access.update_internal(old[0], grant)
                else:
                    bound = self.service.access.create(grant, internal=True)
                    self.feeds.db.execute("INSERT INTO actors VALUES(?,?)", (saved.id, bound["id"]))
        if saved.mode != "automatic_download" or saved.paused:
            self._revoke(saved.id)
        if self.feeds.has_preview(saved):
            from torrentlinker.achievements import record_completion

            record_completion(self.service.setup.path.parent, "rss", saved.id)
        return saved.model_dump()

    def _revoke(self, identifier: str) -> None:
        with self.feeds.lock:
            actor = self.feeds.db.execute(
                "SELECT actor FROM actors WHERE feed=?", (identifier,)
            ).fetchone()
        if actor:
            self.service.revoke(actor[0])

    def set_paused(self, identifier: str, paused: bool) -> None:
        with self.feeds.lock:
            self.feeds.set_paused(identifier, paused)
            if paused:
                self._revoke(identifier)
            else:
                feed = self.feeds.get(identifier)
                if feed.mode == "automatic_download":
                    actor = self.feeds.db.execute(
                        "SELECT actor FROM actors WHERE feed=?", (identifier,)
                    ).fetchone()
                    if actor:
                        self.service.access.set_internal_active(actor[0], True)

    def delete(self, identifier: str) -> None:
        with self.feeds.lock:
            self._revoke(identifier)
            self.feeds.delete(identifier)

    def decisions(self, identifier: str = "") -> list[dict]:
        from torrentlinker.download_queue import entries

        current = {
            entry.key: entry for entry in entries(self.service.setup.store, all_clients=True)
        }
        result = self.feeds.decisions(identifier)
        for row in result:
            entry = current.get(row["queue_key"])
            if entry:
                row["queue_status"] = entry.status
                if row["status"] == "queued" and entry.status != "queued":
                    row["status"] = entry.status
                    row["reason"] = entry.reason or f"App queue outcome: {entry.status}."
                    with self.feeds.lock, self.feeds.db:
                        self.feeds.db.execute(
                            "UPDATE decisions SET status=?,reason=? WHERE feed=? AND infohash=?",
                            (row["status"], row["reason"], row["feed"], row["infohash"]),
                        )
        return result

    def process(self, identifier: str, *, refresh_clients: bool = False) -> dict:
        self.decisions(identifier)
        inventory = self.inventory(refresh=refresh_clients)
        rows = self.feeds.process(
            identifier,
            self.service.setup.store,
            present_hashes=None if inventory["unavailable_clients"] else set(inventory["hashes"]),
            present_works=set(inventory["works"]),
            unknown_client_works=set(inventory["unknown_work_hashes"]),
        )
        return {"rows": rows, "inventory": inventory}

    def tick(self):
        self.feeds.poll()
        for value in self.feeds.subscriptions():
            feed = self.feeds.get(value["id"])
            if feed.paused or feed.mode == "review_only":
                continue
            for row in [
                r
                for r in self.feeds.inbox(feed_id=feed.id)
                if not r["metadata"].get("metadata_checked_at")
            ][:10]:
                if not row["metadata"].get("metadata_checked_at"):
                    try:
                        self.feeds.enrich(row["infohash"])
                    except Exception:
                        pass
            # App-queue rules use cached inventory only. They never contact any client.
            self.process(feed.id, refresh_clients=feed.mode == "automatic_download")
            if feed.mode == "automatic_download":
                self.dispatch(feed)

    def dispatch(self, feed: Subscription) -> list[dict]:
        from torrentlinker.agent.service import AgentRequest
        from torrentlinker.download_queue import entries

        try:
            current = self.feeds.get(feed.id)
        except ValueError:
            return [{"status": "stopped", "reason": "Subscription deleted."}]
        if current.paused or current.mode != "automatic_download":
            return [
                {
                    "status": "stopped",
                    "reason": "Subscription paused or automatic downloads disabled.",
                }
            ]
        feed = current
        if datetime.now(UTC).hour not in feed.download_hours:
            return [{"status": "waiting", "reason": "Outside configured UTC download hours."}]
        with self.feeds.lock:
            actor = self.feeds.db.execute(
                "SELECT actor FROM actors WHERE feed=?", (feed.id,)
            ).fetchone()
        if actor is None:
            return [{"status": "blocked", "reason": "No approved download authority."}]
        eligible = {
            row["infohash"]
            for row in self.feeds.inbox(feed_id=feed.id)
            if feed.include_current or not row["baseline"]
        }
        keys = {
            row["queue_key"]
            for row in self.decisions(feed.id)
            if row["status"] == "queued" and row["infohash"] in eligible
        }
        outcomes = []
        inventory = self.inventory()
        for entry in entries(self.service.setup.store.for_client(feed.client_id)):
            if entry.key not in keys or entry.status != "queued":
                continue
            try:
                blockers = self.pending_blockers(feed, entry, inventory)
                if blockers:
                    reason = "; ".join(blockers)
                    with self.feeds.lock, self.feeds.db:
                        self.feeds.db.execute(
                            "UPDATE decisions SET reason=? WHERE feed=? AND queue_key=?",
                            (reason, feed.id, entry.key),
                        )
                    outcomes.append({"status": "waiting", "reason": reason})
                    continue
                # The existing request path reserves daily bytes/count and mounted-disk space,
                # rechecks each send, and journals uncertain sends. No LLM is involved.
                request_id = self.dispatch_request_id(feed, entry.key, actor[0])
                # Recheck lifecycle after inventory/network work and before reserving a send.
                latest = self.feeds.get(feed.id)
                if latest.paused or latest.mode != "automatic_download":
                    break
                outcome = self.service.request(
                    actor[0],
                    request_id,
                    AgentRequest(
                        kind="send-queue",
                        client_id=feed.client_id,
                        hashes=[entry.candidate.infohash or ""],
                    ),
                )
                if outcome.get("status") == "pending":
                    outcome = self.service.execute(outcome["id"], approved=False)
                outcomes.append(outcome)
                with self.feeds.lock, self.feeds.db:
                    self.feeds.db.execute(
                        "UPDATE decisions SET reason=? WHERE feed=? AND queue_key=?",
                        (
                            (
                                f"Download request {outcome.get('status', 'submitted')}; "
                                f"proposal {outcome.get('id', '')}"
                            ),
                            feed.id,
                            entry.key,
                        ),
                    )
            except Exception as error:
                with self.feeds.lock, self.feeds.db:
                    self.feeds.db.execute(
                        "UPDATE decisions SET reason=? WHERE feed=? AND queue_key=?",
                        (self.service.setup.secrets.redact(str(error)), feed.id, entry.key),
                    )
                outcomes.append(
                    {"status": "waiting", "reason": self.service.setup.secrets.redact(str(error))}
                )
        return outcomes

    def dispatch_request_id(self, feed: Subscription, key: str, actor: str) -> str:
        """Renew only a definitively unsubmitted expired proposal, never an uncertain send."""
        prefix = f"rss-{feed.id}-{hashlib.sha256(key.encode()).hexdigest()[:24]}"
        with self.feeds.lock, self.feeds.db, self.service.access.lock:
            row = self.feeds.db.execute(
                "SELECT attempt FROM dispatch_attempts WHERE queue_key=?", (key,)
            ).fetchone()
            attempt = row[0] if row else 0
            request_id = f"{prefix}-{attempt}"
            proposal = self.service.access.db.execute(
                (
                    "SELECT id,status,created,fingerprint FROM proposals WHERE grant_id=? "
                    "AND request_id=?"
                ),
                (actor, request_id),
            ).fetchone()
            if (
                proposal
                and proposal["status"] == "pending"
                and (
                    time.time() - proposal["created"] > 900
                    or proposal["fingerprint"] != self.service.fingerprint()
                )
            ):
                self.service.reject(proposal["id"])
                attempt += 1
                request_id = f"{prefix}-{attempt}"
            self.feeds.db.execute(
                "INSERT OR REPLACE INTO dispatch_attempts VALUES(?,?)", (key, attempt)
            )
            return request_id

    def check_download_authority(
        self, actor: str, client_id: str, folder: str, infohash: str = ""
    ) -> None:
        """Called again by the existing send guard immediately before client addition."""
        with self.feeds.lock:
            row = self.feeds.db.execute(
                "SELECT feed FROM actors WHERE actor=?", (actor,)
            ).fetchone()
            if row is None:
                return
            feed = self.feeds.get(row[0])
            if (
                feed.paused
                or feed.mode != "automatic_download"
                or feed.client_id != client_id
                or feed.folder != folder
                or datetime.now(UTC).hour not in feed.download_hours
            ):
                raise ValueError("RSS download authority changed. Review the subscription.")
        if infohash:
            from torrentlinker.download_queue import entries

            entry = next(
                (
                    value
                    for value in entries(self.service.setup.store.for_client(client_id))
                    if value.candidate.infohash == infohash
                ),
                None,
            )
            if entry is None:
                raise ValueError("RSS queue entry is no longer available.")
            blockers = self.pending_blockers(feed, entry, self.inventory(refresh=True))
            if blockers:
                raise ValueError("; ".join(blockers))

    def pending_blockers(self, feed: Subscription, entry, inventory: dict) -> list[str]:
        """Recheck current hard criteria and comparisons, excluding this entry itself."""
        from torrentlinker.download_queue import entries

        known = {raw["infohash"]: candidate(raw) for raw in self.feeds.releases()}
        row = known.get(entry.candidate.infohash, entry.candidate)
        decision = evaluate(row, feed.preferences)
        blockers = decision["excluded"] + [
            f"Unknown required {value}" for value in decision["unknown"]
        ]
        if row.size != entry.candidate.size:
            blockers.append("Queued release size changed; review the entry again.")
        other_entries = [
            value
            for value in entries(self.service.setup.store, all_clients=True)
            if value.key != entry.key
        ]
        others = [known.get(value.candidate.infohash, value.candidate) for value in other_entries]
        aliases = work_alias_map(list(known.values()) + others + [row])

        def canonical(value: Candidate) -> str | None:
            identity = work_identity(value)
            return aliases.get(identity, identity) if identity else None

        work = canonical(row)
        if work is None:
            blockers.append("Unknown work identity.")
        if inventory["unavailable_clients"]:
            blockers.append("Client inventory unavailable or stale.")
        if row.infohash in inventory["hashes"]:
            blockers.append("Exact release already in a Torrent Client.")
        elif work in {aliases.get(value, value) for value in inventory["works"]}:
            blockers.append("A release of this work is already in a Torrent Client.")
        if inventory["unknown_work_hashes"]:
            blockers.append("Client work comparison incomplete: unknown identities.")
        if any(work_identity(value) is None for value in others):
            blockers.append("App queue work comparison incomplete: unknown identities.")
        if work is not None and work in {canonical(value) for value in others}:
            blockers.append("Another release of this work is already in the app queue.")
        return blockers
