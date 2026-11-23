"""Cross-seed (ADR-0024): a Reseed whose Candidate comes from another Indexer.

Every complete torrent of the Torrent Client and every Library Item is a source, searched
once on each Indexer (the backlog of a whole library is queued and paced per Indexer, by
the Indexer's own pacer and, for c411, its hourly budget). A Match is compared with the
existing rules; a Full Match, or a Partial Match covering the threshold, is Reseeded without
a review (stopped, verified, started, missing files skipped), the rest waits for the Owner.
The Reseed's own machinery does the adding and the Verification, so a failed Verification
removes the torrent (never data) and becomes a Rejection there.

Every row of the `crossseed` table is a search (no Candidate key) or one Candidate; its
state is queued, searched, review, verifying, added, failed or orphan.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from torrentlinker.client_limits import disk_renames_elsewhere, partial_refusal
from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.indexer import Candidate, KeyRefused, RateLimited
from torrentlinker.item_detection import AUDIO, EBOOK, GAME, VIDEO
from torrentlinker.matching import MatchRules
from torrentlinker.qbit import AlreadyInClient
from torrentlinker.queries import parse_name
from torrentlinker.reseed import PARTIAL, VERIFYING, start_reseed
from torrentlinker.reseed_layout import needs_disk_rename_review
from torrentlinker.review import (
    CheckedCandidate,
    candidate_key,
    compare_candidate,
    find_candidates,
    search_candidates,
)
from torrentlinker.torrent_meta import read_torrent

if TYPE_CHECKING:
    from torrentlinker.config import Settings
    from torrentlinker.web.library import Library
    from torrentlinker.web.setup import Setup

log = logging.getLogger(__name__)

TAG = "cross-seed"
STATES = ("queued", "searched", "review", "verifying", "added", "failed", "orphan")
BLOCK = 600.0  # seconds an Indexer that refused its key is left alone
NETWORK_BLOCK = 60.0
ATTEMPTS = 3  # tries of one search before it is shown as failed
ACTIVITY_LIMIT = 500
STEPS = ("found", "compared", "added", "verified", "started")
DONE_AT = {  # the steps a state has finished
    "review": 2,
    "verifying": 3,
    "added": 5,
    "orphan": 5,
    "failed": 2,
}
STOPPED = ("stopped", "paused")
MISSING = "missingFiles"
CLIENT_ERROR = "error"


def row_id(source: str, indexer_id: str, key: str) -> str:
    return hashlib.sha1(f"{source}\x1f{indexer_id}\x1f{key}".encode()).hexdigest()[:20]


def tag_for(name: str) -> str:
    """A client tag from an Indexer's name (tags are comma separated)."""
    return " ".join(name.replace(",", " ").split()) or "indexer"


def kind_of(item: LocalItem) -> ContentKind:
    """What a torrent of the client holds, from its files, so a search can pick its mode."""
    suffixes = {Path(p).suffix.lower() for p in item.files}
    if suffixes & VIDEO:
        info = parse_name(item)
        return (
            ContentKind.SERIES if info.get("season") or info.get("episode") else ContentKind.MOVIE
        )
    for kind, known in (
        (ContentKind.MUSIC, AUDIO),
        (ContentKind.EBOOK, EBOOK),
        (ContentKind.GAME, GAME),
    ):
        if suffixes & known:
            return kind
    return ContentKind.OTHER


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    item: LocalItem
    kind: ContentKind
    category: str = ""


class SourceGone(Exception):
    pass


def torrent_item(torrent: Any) -> LocalItem | None:
    """A client torrent as a Local Item: its files under its save path."""
    tops = {p.split("/")[0] for p in torrent.files}
    if not torrent.files:
        return None
    if len(torrent.files) == 1 and "/" not in next(iter(torrent.files)):
        return LocalItem(torrent.save_path / next(iter(torrent.files)), dict(torrent.files))
    if len(tops) != 1:
        return None
    return LocalItem(torrent.save_path / tops.pop(), dict(torrent.files))


class CrossSeed:
    def __init__(
        self,
        setup: Setup,
        library: Library,
        root: Setup | None = None,
        notify: Callable[[str, str, str, str, str], None] | None = None,
    ) -> None:
        self.setup, self.library = setup, library
        self.notify = notify  # (event, title, state, note, dedup): the Owner's notices
        self.root = root or setup._root or setup
        self.store = setup.store
        self._blocked: dict[str, tuple[float, str]] = {}
        self._reviews = 0
        self._lock = threading.Lock()

    def tell(self, event: str, row: dict, state: str, note: str = "", dedup: str = "") -> None:
        """Tell the Owner about a Cross-seed, once per row and event."""
        if self.notify is None:
            return
        identifier = row_id(row["source"], row["indexer_id"], row["candidate_key"])
        title = row.get("title") or row.get("name") or "Cross-seed"
        try:
            self.notify(event, title, state, note, dedup or f"{event}:{identifier}")
        except Exception:  # noqa: BLE001 - a notice must never stop the engine
            log.exception("Cross-seed notice failed")

    # Settings -------------------------------------------------------------------

    @property
    def rules(self):  # noqa: ANN201
        return self.root.settings.cross_seed

    def targets(self) -> list[Any]:
        """The Indexers searched: enabled, still listed by their service, with a key."""
        found = []
        for entry in self.root.settings.indexers:
            if not entry.enabled or entry.missing:
                continue
            from torrentlinker.config import Settings

            if self.root.secrets.get(Settings.indexer_secret(entry.id)):
                found.append(entry)
        return found

    def indexer_name(self, identifier: str) -> str:
        try:
            return self.root.settings.find_indexer(identifier).name
        except ValueError:
            return identifier

    # Sources --------------------------------------------------------------------

    def enqueue(self) -> int:
        """Queue a search on every Indexer for each source not searched yet."""
        targets = self.targets()
        if not targets:
            return 0
        known = self.store.crossseed_known()
        queued: list[tuple[str, str, dict]] = []
        sources: list[tuple[str, str, str]] = []
        for t in self.library.client().torrents(with_files=False):
            if t.progress < 1 or TAG in t.tags or VERIFYING in t.tags or t.state == MISSING:
                continue
            sources.append((f"torrent:{t.hash}", t.name, "torrent"))
        for entry in list(self.library.entries):
            if entry.state.value == "seeded":  # its torrent is a source of its own
                continue
            sources.append((f"item:{entry.item.path}", entry.item.path.name, "item"))
        for key, name, origin in sources:
            for indexer in targets:
                if (key, indexer.id) not in known:
                    queued.append((key, indexer.id, {"name": name, "origin": origin}))
        if queued:
            self.store.queue_crossseed(queued)
        return len(queued)

    def source(self, key: str, stop: threading.Event | None = None) -> Source:
        """The source as a Local Item, with its files read now; SourceGone when it left."""
        if key.startswith("torrent:"):
            client = self.library.client()
            torrent = client.torrent(key.removeprefix("torrent:"))
            if torrent is None:
                raise SourceGone("The torrent left the Torrent Client")
            item = torrent_item(torrent)
            if item is None:
                raise SourceGone("The torrent's files have no common folder")
            for path in item.files:
                if not (item.save_path / path).exists():
                    raise SourceGone("Its data is not reachable at the save path")
            return Source(key, torrent.name, item, kind_of(item), torrent.category)
        path = key.removeprefix("item:")
        entry = next((e for e in self.library.entries if str(e.item.path) == path), None)
        if entry is None:
            raise SourceGone("The Local Item left the Library")
        try:
            item = self.library.scan_entry(entry, stop or threading.Event())
        except (OSError, ValueError) as error:
            raise SourceGone(str(error) or "The Local Item cannot be read") from None
        return Source(key, item.path.name, item, entry.folder.kind)

    # Searching ------------------------------------------------------------------

    def blocked(self, identifier: str) -> tuple[float, str] | None:
        found = self._blocked.get(identifier)
        if found and found[0] > time.time():
            return found
        self._blocked.pop(identifier, None)
        return None

    def search_next(self, identifier: str, stop: threading.Event) -> bool:
        """Search the oldest queued source on one Indexer; False when there is nothing to do."""
        if self.rules.paused or self.blocked(identifier) or stop.is_set():
            return False
        rows = self.store.crossseed_rows("queued", identifier, limit=1)
        if not rows:
            return False
        row = rows[0]
        key = row["source"]
        payload = {k: row[k] for k in ("name", "origin", "attempts") if k in row}
        try:
            source = self.source(key, stop)
        except SourceGone as gone:
            self.store.save_crossseed(
                key, identifier, "", "failed", {**payload, "reason": str(gone)}
            )
            return True
        try:
            indexer = self.root.indexer_for(identifier)
            with indexer.background(stop):
                found = self._search(indexer, identifier, source, stop)
        except RateLimited as limited:
            self._blocked[identifier] = (time.time() + limited.retry_after, "Rate limited")
            return False
        except KeyRefused as refused:
            self._blocked[identifier] = (time.time() + BLOCK, str(refused))
            return False
        except InterruptedError:
            return False
        except (httpx.HTTPError, ValueError, OSError) as error:
            attempts = int(payload.get("attempts", 0)) + 1
            reason = indexer_error(error)
            self._blocked[identifier] = (time.time() + NETWORK_BLOCK, reason)
            state = "failed" if attempts >= ATTEMPTS else "queued"
            self.store.save_crossseed(
                key, identifier, "", state, {**payload, "attempts": attempts, "reason": reason}
            )
            return state == "queued"
        self.store.save_crossseed(
            key, identifier, "", "searched", {**payload, "found": found, "searched_at": time.time()}
        )
        return True

    def _search(self, indexer: Any, identifier: str, source: Source, stop: threading.Event) -> int:
        settings, store = self.root.settings, self.store
        client = self.library.client()
        rejections = dict(store.rejections(source.item.path))
        have = {t.hash.lower() for t in client.torrents(with_files=False)}
        rejections.update({h: "already in the Torrent Client" for h in have})
        categories = settings.categories(source.kind) if indexer.is_c411 else ()

        def search() -> list[Candidate]:
            if stop.is_set():
                return []
            return search_candidates(
                indexer, source.item, source.kind, categories, indexer.supported_modes()
            )

        _, checked = find_candidates(
            store,
            indexer,
            source.item,
            search,
            self.search_rules(),
            rejections,
            use_catalogue=indexer.is_c411,
        )
        found = 0
        self._reviews = 0
        for result in checked:
            if result.meta is None or result.match is None:
                continue
            if result.meta.infohash.lower() in have:
                continue
            found += 1
            self._propose(indexer, identifier, source, result)
        if self._reviews:
            count = self._reviews
            self.tell(
                "cross-review",
                {
                    "source": source.key,
                    "indexer_id": identifier,
                    "candidate_key": "",
                    "name": source.name,
                },
                f"{count} waiting for review",
                self.indexer_name(identifier),
                f"cross-review:{row_id(source.key, identifier, '')}:{time.time_ns()}",
            )
        return found

    def search_rules(self) -> MatchRules:
        """The matching rules, with a size window wide enough to hold a Partial Match down to
        the review floor: a torrent larger than the item by what that coverage forgives is
        worth its .torrent (under the threshold it waits for review), one that large is not
        otherwise fetched."""
        rules = self.root.settings.matching.rules()
        window = 1 / max(min(self.rules.threshold, rules.min_partial_coverage), 0.01) - 1
        return replace(rules, size_tolerance=max(rules.size_tolerance, window))

    def _propose(
        self, indexer: Any, identifier: str, source: Source, checked: CheckedCandidate
    ) -> None:
        assert checked.meta is not None and checked.match is not None
        key = candidate_key(checked.candidate)
        reason = self.review_reason(checked, self.library.client())
        row = {
            "name": source.name,
            "origin": "torrent" if source.key.startswith("torrent:") else "item",
            "item_path": str(source.item.path),
            "title": checked.candidate.title,
            "size": checked.candidate.size,
            "candidate": {
                **asdict(checked.candidate),
                "download_url": indexer.redact(checked.candidate.download_url),
                "categories": list(checked.candidate.categories),
            },
            "data": base64.b64encode(checked.meta.data).decode(),
            "infohash": checked.meta.infohash,
            "coverage": checked.match.coverage,
            "missing": list(checked.match.absent),
            "full": checked.match.is_full,
            "archive": checked.unpack is not None,
            "category": source.category,
        }
        if reason is None and self.rules.auto_add:
            self._add_row(source.key, identifier, key, row, source, checked)
            return
        row["reason"] = reason or "Automatic adds are off"
        self.store.save_crossseed(source.key, identifier, key, "review", row)
        self._reviews += 1

    def review_reason(self, checked: CheckedCandidate, client: Any) -> str | None:
        """Why this Match needs a review, or None when it is safe to add alone."""
        match = checked.match
        if match is None:
            return "No Match"
        if checked.unpack is not None:
            return "The Match is inside an archive"
        if not match.is_full:
            if match.coverage < self.rules.threshold:
                return (
                    f"Partial Match covering {match.coverage:.0%}, "
                    f"under the {self.rules.threshold:.0%} threshold"
                )
            if refusal := partial_refusal(client):
                return refusal
        if needs_disk_rename_review(client) and match.renames:
            return disk_renames_elsewhere(client)
        return None

    # Adding ---------------------------------------------------------------------

    def _add_row(
        self,
        source_key: str,
        identifier: str,
        key: str,
        row: dict,
        source: Source,
        checked: CheckedCandidate,
    ) -> str:
        """Reseed the Match: the same machinery as a Reseed, then our tag and category.

        Returns the row's new state: verifying, failed, or gone when the client had it."""
        assert checked.meta is not None and checked.match is not None
        client = self.library.client()
        try:
            hash = start_reseed(client, self.store, source.item, checked.meta, checked.match, key)
        except AlreadyInClient:
            self.store.delete_crossseed(source_key, identifier, key)
            return "gone"
        except Exception as error:  # noqa: BLE001 - shown on the row, retried by the Owner
            log.warning("Cross-seed could not add %s: %s", row.get("title"), error)
            reason = str(error) or type(error).__name__
            self.store.save_crossseed(
                source_key, identifier, key, "failed", {**row, "reason": reason}
            )
            self.tell(
                "cross-failed",
                {"source": source_key, "indexer_id": identifier, "candidate_key": key, **row},
                "Could not be added",
                reason,
                f"cross-failed:{row_id(source_key, identifier, key)}:{time.time_ns()}",
            )
            return "failed"
        tags = [TAG, tag_for(self.indexer_name(identifier))]
        try:
            client.add_tags(hash, tags)
            if source.category:
                client.set_category(hash, source.category)
        except Exception:  # noqa: BLE001 - the torrent is added and verified either way
            log.exception("Cross-seed could not tag %s", hash)
        row = {k: v for k, v in row.items() if k not in ("reason",)}
        self.store.save_crossseed(source_key, identifier, key, "verifying", {**row, "hash": hash})
        return "verifying"

    def _checked_from(self, row: dict, source: Source) -> CheckedCandidate:
        data = base64.b64decode(row["data"])
        meta = read_torrent(data)
        found = {**row["candidate"], "categories": tuple(row["candidate"].get("categories", ()))}
        return compare_candidate(
            source.item, Candidate(**found), meta, self.root.settings.matching.rules()
        )

    def _row(self, identifier: str) -> dict:
        for row in self.store.crossseed_rows():
            if (
                row["candidate_key"]
                and row_id(row["source"], row["indexer_id"], row["candidate_key"]) == identifier
            ):
                return row
        raise ValueError("This Cross-seed is gone.")

    def accept(self, identifier: str) -> None:
        """Add a Match waiting for review (or retry a failed one), as a Reseed."""
        row = self._row(identifier)
        if row["state"] not in ("review", "failed"):
            raise ValueError("Only a Cross-seed in review or failed can be added.")
        try:
            source = self.source(row["source"])
        except SourceGone as gone:
            raise ValueError(str(gone)) from None
        checked = self._checked_from(row, source)
        if checked.match is None or checked.meta is None:
            raise ValueError("The files no longer match this torrent.")
        if checked.unpack is not None:
            raise ValueError("This Match is inside an archive: unpack it from the Reseed board.")
        client = self.library.client()
        if not checked.match.is_full and (refusal := partial_refusal(client)):
            raise ValueError(refusal)
        if needs_disk_rename_review(client) and checked.match.renames:
            raise ValueError(disk_renames_elsewhere(client))
        key = row["candidate_key"]
        self.store.unreject(source.item.path, key)
        state = self._add_row(row["source"], row["indexer_id"], key, row, source, checked)
        if state == "gone":
            raise ValueError("This torrent is already in the Torrent Client.")
        if state == "failed":
            failed = self.store.crossseed_rows("failed", row["indexer_id"])
            reason = next((r.get("reason") for r in failed if r["candidate_key"] == key), "")
            raise ValueError(reason or "The torrent could not be added.")

    def reject(self, identifier: str) -> None:
        row = self._row(identifier)
        path = Path(row.get("item_path", ""))
        self.store.reject(path, row["candidate_key"], "Rejected in the Cross-seed review")
        self.store.delete_crossseed(row["source"], row["indexer_id"], row["candidate_key"])

    def retry(self, identifier: str) -> None:
        """Try a failed Cross-seed again: a failed search is queued, a failed add is added."""
        for row in self.store.crossseed_rows("failed"):
            if row_id(row["source"], row["indexer_id"], row["candidate_key"]) == identifier:
                if not row["candidate_key"]:
                    payload = {k: row[k] for k in ("name", "origin") if k in row}
                    self.store.save_crossseed(
                        row["source"], row["indexer_id"], "", "queued", payload
                    )
                    return
                break
        self.accept(identifier)

    def remove(self, identifier: str) -> None:
        """Remove an orphan from the Torrent Client; its data is whatever is left on disk."""
        row = self._row(identifier)
        if row["state"] != "orphan":
            raise ValueError("Only a Cross-seed whose data disappeared can be removed.")
        if row.get("hash"):
            self.library.client().remove(row["hash"], delete_files=False)
        self.store.delete_crossseed(row["source"], row["indexer_id"], row["candidate_key"])

    # Settling -------------------------------------------------------------------

    def settle(self) -> None:
        """Follow the torrents added: verifying until the client says so, then added; a
        Verification that failed (torrent removed, Rejection recorded) shows as failed."""
        wanted = [
            r
            for state in ("verifying", "added", "orphan")
            for r in self.store.crossseed_rows(state)
        ]
        if not wanted:
            return
        torrents = {t.hash.lower(): t for t in self.library.client().torrents(with_files=False)}
        for row in wanted:
            self._settle_row(row, torrents.get(str(row.get("hash", "")).lower()))

    def _settle_row(self, row: dict, torrent: Any) -> None:
        fixed = (row["source"], row["indexer_id"], row["candidate_key"])
        payload = {
            k: v
            for k, v in row.items()
            if k not in ("source", "indexer_id", "candidate_key", "state", "updated")
        }
        if torrent is None:
            if row["state"] != "verifying":
                self.store.delete_crossseed(*fixed)  # the Owner removed it
                return
            reason = self.store.rejections(Path(row.get("item_path", ""))).get(
                row["candidate_key"], "The torrent left the Torrent Client"
            )
            self.store.save_crossseed(*fixed, "failed", {**payload, "reason": reason})
            self.tell("cross-failed", row, "Failed Verification", reason)
            return
        if VERIFYING in torrent.tags:
            return
        stopped = torrent.state.startswith(STOPPED)
        if lost := self.lost(row, torrent):
            if row["state"] != "orphan" or row.get("reason") != lost:
                self.store.save_crossseed(*fixed, "orphan", {**payload, "reason": lost})
            if row["state"] != "orphan":
                self.tell("cross-orphan", row, "Its data disappeared", lost)
            return
        updated = {k: v for k, v in payload.items() if k not in ("data", "reason")}
        updated["started"] = not stopped
        if stopped and PARTIAL in torrent.tags:
            updated["reason"] = (
                "Left stopped: the client did not confirm it skips the missing files"
            )
        if row["state"] != "added" or updated != payload:
            self.store.save_crossseed(*fixed, "added", updated)
        if row["state"] == "verifying":
            self.tell("cross-added", row, "Added and verified", row.get("reason", ""))

    @staticmethod
    def lost(row: dict, torrent: Any) -> str:
        """Why a Cross-seed's data is gone (the client says so, or the files are not on disk), or
        an empty string. The data is never touched: the Owner decides what to remove."""
        if torrent.state == MISSING:
            return "Its data is missing from disk"
        if torrent.state == CLIENT_ERROR:
            return "The Torrent Client reports an error on this torrent"
        path = row.get("item_path")
        if path and not Path(path).exists():
            return "Its files are missing from disk"
        return ""

    # Reading --------------------------------------------------------------------

    def activity(self, state: str | None = None, limit: int = ACTIVITY_LIMIT) -> dict:
        rows = self.store.crossseed_rows(state, limit=limit, newest=True)
        return {
            "rows": [self.present(r) for r in rows],
            "counts": {s: self.store.crossseed_counts().get(s, 0) for s in STATES},
            "indexers": self.indexer_status(),
            "settings": asdict(self.rules),
        }

    def present(self, row: dict) -> dict:
        state = row["state"]
        done = DONE_AT.get(state, 0 if state == "queued" else 1)
        if state == "verifying" and row.get("hash"):
            done = 3
        if state == "added" and not row.get("started", True):
            done = 4
        steps = [{"name": n, "done": i < done} for i, n in enumerate(STEPS)]
        return {
            "id": row_id(row["source"], row["indexer_id"], row["candidate_key"]),
            "state": state,
            "source": row.get("name", ""),
            "origin": row.get("origin", ""),
            "indexer_id": row["indexer_id"],
            "indexer": self.indexer_name(row["indexer_id"]),
            "title": row.get("title", ""),
            "size": row.get("size", 0),
            "reason": row.get("reason", ""),
            "coverage": row.get("coverage"),
            "missing": row.get("missing", []),
            "full": row.get("full"),
            "archive": bool(row.get("archive")),
            "item_path": row.get("item_path", ""),
            "hash": row.get("hash", ""),
            "started": row.get("started"),
            "found": row.get("found"),
            "steps": steps,
            "updated": row["updated"],
        }

    def indexer_status(self) -> list[dict]:
        queued: dict[str, int] = {}
        for row in self.store.crossseed_rows("queued"):
            queued[row["indexer_id"]] = queued.get(row["indexer_id"], 0) + 1
        result = []
        for entry in self.targets():
            blocked = self.blocked(entry.id)
            result.append(
                {
                    "id": entry.id,
                    "name": entry.name,
                    "queued": queued.get(entry.id, 0),
                    "blocked_until": blocked[0] if blocked else None,
                    "blocked_reason": blocked[1] if blocked else "",
                }
            )
        return result


def indexer_error(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"The Indexer answered HTTP {error.response.status_code}"
    if isinstance(error, httpx.HTTPError):
        return "The Indexer could not be reached"
    return str(error) or type(error).__name__


class CrossSeedRunner:
    """Runs the engines: a pass every `interval` seconds and one paced worker per Indexer."""

    def __init__(self, engines, shutdown: threading.Event, interval: float = 30.0) -> None:  # noqa: ANN001
        self.engines, self.shutdown, self.interval = engines, shutdown, interval
        self._workers: dict[tuple[int, str], threading.Thread] = {}

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="cross-seed").start()

    def _loop(self) -> None:
        while not self.shutdown.is_set():
            for engine in self.engines():
                try:
                    if not engine.rules.paused:
                        engine.enqueue()
                    engine.settle()
                    self._workers_for(engine)
                except Exception:  # noqa: BLE001 - one client's trouble must not stop the rest
                    log.exception("Cross-seed pass failed")
            if self.shutdown.wait(self.interval):
                return

    def _workers_for(self, engine: CrossSeed) -> None:
        for entry in engine.targets():
            slot = (id(engine), entry.id)
            thread = self._workers.get(slot)
            if thread is None or not thread.is_alive():
                thread = threading.Thread(
                    target=self._work,
                    args=(engine, entry.id),
                    daemon=True,
                    name=f"cross-seed-{entry.id}",
                )
                self._workers[slot] = thread
                thread.start()

    def _work(self, engine: CrossSeed, identifier: str) -> None:
        while not self.shutdown.is_set():
            if identifier not in {e.id for e in engine.targets()}:
                return
            try:
                busy = engine.search_next(identifier, self.shutdown)
            except Exception:  # noqa: BLE001
                log.exception("Cross-seed search failed")
                busy = False
            if not busy:
                self.shutdown.wait(5)


def settings_of(settings: Settings) -> dict:
    return asdict(settings.cross_seed)
