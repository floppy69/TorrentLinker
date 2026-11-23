"""Review, persistence and explicit sending of the desktop Plan through HTTP jobs."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import Any

from torrentlinker.catalogue import candidate
from torrentlinker.disk_rename import DiskRenamePlan, plan_disk_renames
from torrentlinker.plan import Plan, PlanCandidate, ReseedSource, restore_plan, saved_items
from torrentlinker.reseed_layout import needs_disk_rename_review
from torrentlinker.send import Refused, send_plan
from torrentlinker.store import CatalogueRow
from torrentlinker.web.library import Library
from torrentlinker.web.planning import plan_result
from torrentlinker.web.setup import Setup
from torrentlinker.web.storage import DownloadClient


@dataclass(frozen=True)
class RenameConsent:
    token: str
    expires: float
    plan_id: str
    selection: frozenset[str]
    setup_identity: str
    renames: tuple[DiskRenamePlan, ...]


class PlanSession:
    def __init__(self, setup: Setup, library: Library):
        self.setup, self.library = setup, library
        self.current: Plan | None = None
        self.identifier = ""
        self.interrupted = False
        self.approval: RenameConsent | None = None

    def accept(self, plan: Plan) -> None:
        made_at = time.time()
        self.setup.store.save_plan(saved_items(plan), made_at, plan.zen_added)
        self.current, self.identifier = plan, str(made_at)
        self.interrupted = False
        self.approval = None

    def clear(self) -> None:
        self.setup.store.clear_plan()
        self.current, self.identifier = Plan(), ""
        self.interrupted = False
        self.approval = None

    def restore(self) -> None:
        if self.current is None:
            saved = self.setup.store.saved_plan()
            if saved is not None:
                rows = {r.infohash: r for r in self.setup.store.catalogue()}
                self.current = restore_plan(saved, rows)
                self.identifier = str(saved.made_at)
                self.interrupted = saved.sending
            else:
                self.current = Plan()

    def read(self) -> dict:
        self.restore()
        assert self.current is not None
        return {
            **plan_result(self.setup, self.current),
            "plan_id": self.identifier,
            "interrupted": self.interrupted,
        }

    def validate(self, identifier: str, hashes: list[str]) -> Plan:
        self.restore()
        if not identifier or identifier != self.identifier or self.current is None:
            raise ValueError("This Plan changed. Review the current Plan before sending.")
        known = {i.candidate.infohash for i in self.current.items}
        selected = set(hashes)
        if selected - known:
            raise ValueError("The selection contains torrents outside the current Plan.")
        items = [i for i in self.current.items if not selected or i.candidate.infohash in selected]
        if not items:
            raise ValueError("Select torrents still waiting in the current Plan.")
        return replace(self.current, items=items)

    def review(self, identifier: str, hashes: list[str]) -> dict:
        plan = self.validate(identifier, hashes)
        renames = self.disk_renames(plan)
        token = secrets.token_urlsafe(32)
        self.approval = RenameConsent(
            token,
            time.monotonic() + 300,
            identifier,
            frozenset(i.candidate.infohash for i in plan.items),
            str(self.setup.snapshot()),
            tuple(renames),
        )
        return {
            "token": token,
            "renames": [
                {"title": p.title, "source": str(move.source), "target": str(move.target)}
                for p in renames
                for move in p.moves
            ],
        }

    def disk_renames(self, plan: Plan) -> list[DiskRenamePlan]:
        if not any(i.candidate.reseed for i in plan.items):
            return []
        if not needs_disk_rename_review(self.library.client()):
            return []
        result = []
        for item in plan.items:
            source = item.candidate.source
            if isinstance(source, ReseedSource):
                checked = source.checked
                if checked.meta and checked.match and checked.match.renames:
                    result.append(plan_disk_renames(source.entry.item, checked.meta, checked.match))
        return result

    def approved_renames(self, plan: Plan, confirmation: str) -> list[DiskRenamePlan]:
        renames = self.disk_renames(plan)
        if not renames:
            return []
        approval = self.approval
        if (
            approval is None
            or not secrets.compare_digest(confirmation, approval.token)
            or time.monotonic() > approval.expires
            or self.identifier != approval.plan_id
            or {i.candidate.infohash for i in plan.items} != approval.selection
            or str(self.setup.snapshot()) != approval.setup_identity
            or tuple(renames) != approval.renames
        ):
            raise ValueError(
                "Review and explicitly approve the current disk renames before sending."
            )
        return renames

    def send(
        self,
        identifier: str,
        hashes: list[str],
        stop: threading.Event,
        progress: Callable[[Any], None],
        confirmation: str = "",
    ) -> dict:
        plan = self.validate(identifier, hashes)
        approved = self.approved_renames(plan, confirmation)
        self.approval = None  # one use, including a failed or interrupted send
        identifiers = {
            i.candidate.client_id or self.setup.settings.active_client_id for i in plan.items
        }
        targets = {key: self.setup.for_client(key) for key in identifiers}
        clients = {key: DownloadClient(target) for key, target in targets.items()}
        verified = set()
        for item in plan.items:
            c = item.candidate
            target = targets[c.client_id or self.setup.settings.active_client_id]
            if not c.reseed:
                if c.folder != target.download_folder(c.category):
                    raise ValueError("A Download Folder changed. Build and review a new Plan.")
                destination = (target.settings.active_client_id, c.folder)
                if destination not in verified:
                    target.configure_download_folder(str(c.folder))
                    verified.add(destination)
        indexer = self.setup.indexer()
        handled: set[str] = set()
        committed: set[str] = set()

        def fetch(c: PlanCandidate) -> bytes:
            if not isinstance(c.source, CatalogueRow):
                raise Refused("This torrent is no longer in the Catalogue. Build a new Plan.")
            return indexer.fetch_torrent(candidate(indexer, c.source), retry=False)

        def reseed(c: PlanCandidate) -> None:
            if not isinstance(c.source, ReseedSource):
                raise Refused("Review this Reseed in the Library again.")
            self.library.reseed(
                str(c.source.entry.item.path),
                c.infohash,
                stop,
                approve_disk_renames=lambda proposed: proposed in approved,
            )

        def record(c: PlanCandidate, outcome: str, reason: str) -> None:
            self.setup.store.mark_plan_item(c.infohash, outcome, self.setup.secrets.redact(reason))
            if outcome in {"added", "reseeded", "refused"}:
                handled.add(c.infohash)
            if outcome == "added":
                committed.add(c.infohash)

        self.setup.store.set_plan_sending(True)
        started_at = time.time()

        def sending_progress(value) -> None:
            elapsed = max(0, time.time() - started_at)
            progress(
                {
                    **asdict(value),
                    "started_at": started_at,
                    "elapsed": elapsed,
                    "remaining_seconds": elapsed / value.done * (value.total - value.done)
                    if value.done
                    else None,
                }
            )

        def ahead(candidates: list[PlanCandidate]) -> None:
            if not hasattr(indexer, "prefetch"):  # test stubs have none
                return
            indexer.prefetch(
                [
                    candidate(indexer, c.source)
                    for c in candidates
                    if isinstance(c.source, CatalogueRow)
                ]
            )

        try:
            with indexer.background():
                report = send_plan(
                    plan,
                    next(iter(clients.values())),
                    fetch,
                    reseed,
                    on_progress=sending_progress,
                    on_outcome=record,
                    stop=stop,
                    client_for=lambda key: clients[key or self.setup.settings.active_client_id],
                    ahead=ahead,
                )
            result = asdict(report)
            result["failed"] = [
                (title, self.setup.secrets.redact(reason)) for title, reason in report.failed
            ]
            result["refused"] = [
                (title, self.setup.secrets.redact(reason)) for title, reason in report.refused
            ]
            return result
        finally:
            if hasattr(indexer, "drop_prefetch"):
                indexer.drop_prefetch()
            self.setup.store.set_plan_sending(False)
            if self.current is not None:
                remaining = [i for i in self.current.items if i.candidate.infohash not in handled]
                total = sum(i.zen for i in self.current.items)
                gain = (
                    self.current.zen_added * sum(i.zen for i in remaining) / total if total else 0
                )
                spaces = tuple(
                    replace(
                        space,
                        free=max(
                            0,
                            space.free
                            - sum(
                                i.candidate.download_size
                                for i in self.current.items
                                if i.candidate.disk == space.disk
                                and i.candidate.infohash in committed
                            ),
                        ),
                        download=sum(
                            i.candidate.download_size
                            for i in remaining
                            if i.candidate.disk == space.disk
                        ),
                    )
                    for space in self.current.disk_spaces
                )
                self.current = replace(
                    self.current, items=remaining, zen_added=gain, disk_spaces=spaces
                )
            self.interrupted = False
