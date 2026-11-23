"""Application jobs using the same domain operations as the desktop UI."""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from torrentlinker.catalogue_selection import CatalogueCriteria, select_catalogue_rows
from torrentlinker.details_workspace import DetailsWorkspace
from torrentlinker.domain import Torrent
from torrentlinker.download_queue import enqueue, entries, run_queue
from torrentlinker.indexer import Candidate, SearchQuery
from torrentlinker.plan import PlanGoal, PlanOptions
from torrentlinker.queue_selection import QueueCriteria
from torrentlinker.seeding import observe_swarm, seeding
from torrentlinker.store import CatalogueRow
from torrentlinker.torrent_details import website_url
from torrentlinker.torrent_management import (
    category_labels,
    manage,
    status,
    torrent_categories,
    tracker_hosts,
)
from torrentlinker.torrent_search import native_search
from torrentlinker.torrent_selection import SelectionCriteria, select_rows
from torrentlinker.upload_queue import reset_local
from torrentlinker.web.archives import ArchiveReseeds
from torrentlinker.web.library import Library
from torrentlinker.web.setup import Setup
from torrentlinker.web.storage import DownloadClient
from torrentlinker.web.uploads import UploadForm, Uploads
from torrentlinker.zen import ZenTorrent, note, torrent_zen


class DownloadFolderRequired(ValueError):
    def __init__(self, client_id: str, category: int | None):
        super().__init__(
            "Configure and verify a mounted Download Folder in Settings first. "
            "A seedbox API connection alone cannot check existing files."
        )
        self.client_id, self.category = client_id, category


class JobRequest(BaseModel):
    client_id: str = Field(default="", max_length=64)
    client_ids: list[str] = Field(default_factory=list, max_length=32)
    client_budgets: dict[str, int] = Field(default_factory=dict, max_length=32)
    kind: Literal[
        "manage",
        "tracker-preview",
        "tracker-update",
        "feed-action",
        "refresh",
        "select-torrents",
        "select-catalogue",
        "select-queue",
        "prepare-download-batch",
        "refine-selection",
        "edit-queue-selection",
        "search",
        "enqueue",
        "send-queue",
        "scan",
        "check",
        "candidate-inspector",
        "library-review",
        "library-evidence",
        "find-compatible",
        "combine-library",
        "diagnose-repair",
        "prepare-repair",
        "refresh-repair",
        "start-repair",
        "import-provenance",
        "library-reject",
        "check-candidate",
        "search-library",
        "reseed",
        "reseed-workspace",
        "preview-unpack",
        "refresh-unpack",
        "unpack-reseed",
        "check-all",
        "reseed-all",
        "catalogue",
        "plan",
        "send-plan",
        "speed-test",
        "details",
        "search-options",
        "upload-preview",
        "model-inspect",
        "model-render",
        "upload-draft",
        "upload-queue",
        "upload-send",
        "upload-remove",
        "upload-reset",
        "upload-seed",
        "profile",
        "verify",
        "configure-download-folder",
    ]
    feed_operation: Literal["save", "delete", "mark", "process", "enqueue"] = "save"
    feed_definition: dict = Field(default_factory=dict)
    feed_id: str = ""
    feed_selection_id: str = ""
    feed_mark: Literal["read", "unread", "save", "unsave", "dismiss", "restore"] = "read"
    tracker_action: Literal["replace-host", "add-backup", "update-passkey"] = "add-backup"
    tracker_source_host: str = Field(default="", max_length=253)
    tracker_target_host: str = Field(default="tk.c411.tw", max_length=253)
    tracker_groups: list[str] = Field(default_factory=list, max_length=1000)
    tracker_preview_id: str = Field(default="", max_length=64)
    action: Literal["pause", "resume", "recheck", "remove", "delete"] = "pause"
    hashes: list[str] = Field(default_factory=list, max_length=1000)
    selection_name: str = Field(default="", max_length=200)
    confirmation: str = ""
    experimental: bool = False
    upload: UploadForm = Field(default_factory=UploadForm)
    model_files: list[str] = Field(default_factory=list, max_length=108)
    model_cameras: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=108)
    draft_id: str = Field(default="", max_length=64)
    revision: int = Field(default=0, ge=0)
    maximum_bytes: int = Field(default=0, ge=0)
    maximum_torrents: int = Field(default=20, ge=1, le=1_000_000)
    minimum_torrents: int = Field(default=0, ge=0, le=1_000_000)
    min_seeders: int = Field(default=0, ge=0)
    limit_torrents: bool = True
    plan_goal: PlanGoal = PlanGoal.NOTE
    max_seeders: int | None = Field(default=None, ge=0)
    min_size: int = Field(default=0, ge=0)
    max_size: int = Field(default=0, ge=0)
    cached_only: bool = False
    plan_id: str = Field(default="", max_length=64)
    plan_selection: list[str] = Field(default_factory=list, max_length=1_000_000)
    selection: SelectionCriteria = Field(default_factory=SelectionCriteria)
    selection_id: str = Field(default="", max_length=64)
    catalogue_selection: CatalogueCriteria = Field(default_factory=CatalogueCriteria)
    selection_source: Literal["catalogue", "queue", "saved-catalogue"] = "catalogue"
    selection_rows: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    queue_binding: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    queue_action: Literal["remove", "retry", "priority"] = "remove"
    priority: int = Field(default=0, ge=-1000, le=1000)
    queue_selection: QueueCriteria = Field(default_factory=QueueCriteria)
    selection_fingerprint: str = Field(default="", max_length=64)
    path: str = Field(default="", max_length=4096)
    repair_id: str = Field(default="", max_length=64)
    torrent_data: str = Field(default="", max_length=12_000_000)
    inspector_action: Literal[
        "review",
        "check",
        "reject",
        "search",
        "provenance",
        "evidence",
        "import",
        "details",
        "repairs",
    ] = "review"
    candidate_key: str = Field(default="", max_length=4096)
    paths: list[str] = Field(default_factory=list, max_length=10000)
    reseed_action: Literal["all", "find", "compare", "prepare", "verify", "seed", "refresh"] = "all"
    link_root: str = Field(default="", max_length=4096)
    client_path: str = Field(default="", max_length=4096)
    query: str = Field(default="", max_length=500)
    page: int = Field(default=1, ge=1, le=10000)
    category: int | None = None
    catalogue_root: Literal[1, 2, 3, 4, 5, 6, 7, 9, 10] | None = None
    categories: list[int] | None = Field(default=None, max_length=1000)
    filters: dict[str, str] = Field(default_factory=dict, max_length=30)
    indexer_search: bool = False
    search_exclude_seeded: bool = False
    search_listing: bool = False  # also return the listing's display fields, for the Search page

    @field_validator("tracker_source_host", "tracker_target_host")
    @classmethod
    def valid_tracker_host(cls, value):
        from torrentlinker.tracker_updates import host_name

        return host_name(value) if value else ""

    @field_validator("tracker_groups")
    @classmethod
    def valid_tracker_groups(cls, groups):
        if any(
            len(group) != 16 or any(c not in "0123456789abcdef" for c in group) for group in groups
        ):
            raise ValueError("Choose passkey fingerprints from the preview.")
        return list(dict.fromkeys(groups))

    @field_validator("hashes", "plan_selection")
    @classmethod
    def hashes_valid(cls, hashes: list[str]) -> list[str]:
        if any(len(h) != 40 or any(c not in "0123456789abcdefABCDEF" for c in h) for h in hashes):
            raise ValueError("Invalid torrent hash.")
        return list(dict.fromkeys(h.lower() for h in hashes))

    @model_validator(mode="after")
    def valid_plan_range(self) -> JobRequest:
        if self.kind != "reseed-workspace" and len(self.paths) > 1000:
            raise ValueError("Select at most 1000 paths for this operation.")
        if self.kind == "plan" and self.max_size and self.min_size > self.max_size:
            raise ValueError("Minimum torrent size must not exceed maximum torrent size.")
        if self.kind == "plan":
            if self.limit_torrents and self.minimum_torrents > self.maximum_torrents:
                raise ValueError("Minimum torrent count must not exceed maximum torrent count.")
            if self.max_seeders is not None and self.min_seeders > self.max_seeders:
                raise ValueError("Minimum seeders must not exceed maximum seeders.")
        return self

    def planning_options(self) -> PlanOptions:
        return PlanOptions(
            goal=self.plan_goal,
            max_download_bytes=self.maximum_bytes,
            max_torrents=self.maximum_torrents if self.limit_torrents else None,
            max_seeders=self.max_seeders,
            min_seeders=self.min_seeders,
            min_torrents=self.minimum_torrents,
            min_size=self.min_size,
            max_size=self.max_size,
        )

    def planning_categories(self) -> list[int] | None:
        if self.categories is not None:
            return list(dict.fromkeys(self.categories)) or None
        return [self.category] if self.category is not None else None


class Operations:
    def __init__(self, setup: Setup):
        self.setup = setup
        self.library = Library(setup)
        from torrentlinker.reseed_workspace import ReseedWorkspace

        self.reseed_workspace = ReseedWorkspace(self.library)
        from torrentlinker.web.plan_session import PlanSession

        self.planner = PlanSession(setup, self.library)
        self.archives = ArchiveReseeds(self.library)
        self.uploads = Uploads(setup, self.library)
        self.candidates: dict[str, Candidate] = {}
        self.score_listings: dict[str, dict] = {}
        self.detail_workspace: DetailsWorkspace | None = None
        self.rows: list[dict[str, Any]] = []
        self.observed: list[Torrent] = []
        self.feed_observed_at: float = 0
        self.connection_error = ""
        self.zen: dict[str, Any] = {}

    def validate(self, request: JobRequest) -> None:
        if request.kind == "send-plan":
            reviewed_plan = self.planner.validate(
                request.plan_id, request.plan_selection or request.hashes
            )
            self.planner.approved_renames(reviewed_plan, request.confirmation)
        if request.kind in {"upload-send", "upload-remove", "upload-reset"} or (
            request.kind in {"upload-queue", "upload-preview"} and request.draft_id
        ):
            record = self.setup.store.local_draft(request.draft_id)
            if record["revision"] != request.revision:
                raise ValueError("Local Draft changed. Reload and review the current revision.")
        if (
            request.kind in {"scan", "check", "reseed", "check-all", "reseed-all"}
            and not self.setup.settings.library_folders
        ):
            raise ValueError("Add a mounted Library Folder in Settings first.")
        if request.kind == "reseed" and len(request.hashes) != 1:
            raise ValueError("Select one checked Candidate.")
        if request.kind in {"enqueue", "send-queue", "edit-queue-selection"}:
            if request.selection_id and request.selection_source == "queue":
                from torrentlinker.queue_selection import validate_snapshot

                validate_snapshot(self.setup, request.selection_rows, request.selection_fingerprint)
            if request.selection_id and request.selection_source == "saved-catalogue":
                from torrentlinker.queue_selection import validate_catalogue_subset

                validate_catalogue_subset(self.setup, request.selection_rows)
                if request.kind == "send-queue":
                    queued_subset = {
                        e.candidate.infohash: e
                        for e in entries(self.setup.store)
                        if e.status == "queued"
                    }
                    if any(
                        r["hash"] not in queued_subset
                        or queued_subset[r["hash"]].candidate.size != r["size"]
                        or queued_subset[r["hash"]].candidate.title != r["title"]
                        or (
                            r["category"] is not None
                            and r["category"] not in queued_subset[r["hash"]].candidate.categories
                        )
                        for r in request.selection_rows
                    ):
                        raise ValueError(
                            "Queued entries do not match the catalogue selection. "
                            "Review and queue it again."
                        )
            if request.selection_id and request.selection_source == "catalogue":
                selected = self.select_catalogue(request.catalogue_selection)
                if (
                    selected["selection_fingerprint"] != request.selection_fingerprint
                    or [r["hash"] for r in selected["rows"]] != request.hashes
                ):
                    raise ValueError("Catalogue selection changed. Select and review it again.")
                if request.kind == "send-queue":
                    queued = {
                        e.candidate.infohash: e.candidate
                        for e in entries(self.setup.store)
                        if e.status == "queued"
                    }
                    for row in selected["rows"]:
                        candidate = queued.get(row["hash"])
                        if (
                            candidate is None
                            or candidate.size != row["size"]
                            or candidate.title != row["title"]
                            or (
                                row["category"] is not None
                                and row["category"] not in candidate.categories
                            )
                        ):
                            raise ValueError(
                                "Queued entries do not match the catalogue selection. "
                                "Review and queue the selection again."
                            )
            if request.kind == "enqueue":
                self.enqueue_folders(request)
        if request.kind == "send-queue" and request.queue_binding:
            from torrentlinker.queue_selection import fingerprint, validate_snapshot

            validate_snapshot(self.setup, request.queue_binding, fingerprint(request.queue_binding))
        if request.kind in {"send-queue", "plan"}:
            targets = (
                [self.setup.for_client(identifier) for identifier in request.client_ids]
                if request.kind == "plan" and request.client_ids
                else [self.setup]
            )
            for target in targets:
                if request.kind == "plan" and request.planning_categories():
                    from torrentlinker.catalogue import plan_categories

                    for cid in request.planning_categories() or []:
                        if not plan_categories(
                            [cid],
                            target.settings.download_folders,
                            target.settings.indexer_categories,
                        ):
                            raise DownloadFolderRequired(target.settings.active_client_id, cid)
                folder = target.download_folder(request.category)
                if not folder and request.kind == "plan" and request.category is None:
                    folder = next(
                        (
                            Path(value)
                            for value in target.settings.download_folders.by_category.values()
                        ),
                        None,
                    )
                if request.kind == "send-queue":
                    hashes = set(request.hashes)
                    folder = next(
                        (
                            e.folder
                            for e in entries(target.store)
                            if e.status == "queued"
                            and (not hashes or e.candidate.infohash in hashes)
                        ),
                        folder,
                    )
                if not folder:
                    raise DownloadFolderRequired(target.settings.active_client_id, request.category)
                target.path_under_root(str(folder))
        if request.kind == "manage" and not request.hashes:
            raise ValueError("Select at least one torrent.")

    def select_catalogue(self, criteria: CatalogueCriteria) -> dict[str, Any]:
        from torrentlinker.web.planning import catalogue_status

        excluded = set(criteria.exclude_hashes)
        if criteria.exclude_queued:
            excluded.update(
                e.candidate.infohash for e in entries(self.setup.store) if e.candidate.infohash
            )
        if criteria.exclude_seeded:
            excluded.update(
                t.hash.lower()
                for t in self.setup.client().torrents(with_files=False)
                if t.progress >= 1
            )
        return {
            **select_catalogue_rows(
                (r for r in self.setup.store.catalogue() if r.infohash not in excluded),
                self.setup.settings.indexer_categories,
                criteria,
            ),
            "catalogue": catalogue_status(self.setup),
            "indexer_url": getattr(getattr(self.setup, "_indexer", None), "url", None)
            or self.setup.settings.indexer.url,
        }

    def enqueue_categories(self, request: JobRequest) -> dict[str, int | None]:
        """Keep each torrent's category; a mixed batch does not mean the default."""
        from torrentlinker.category_tags import category_path

        rows = {r.infohash: r for r in self.setup.store.catalogue(request.hashes)}
        categories: dict[str, int | None] = {}
        for h in request.hashes:
            if h not in rows and h not in self.candidates:
                raise ValueError("Search again before queueing this torrent.")
            if request.category is not None:
                categories[h] = request.category
            elif h in rows:
                categories[h] = rows[h].category
            else:
                categories[h] = max(
                    self.candidates[h].categories,
                    key=lambda cid: len(category_path(cid, self.setup.settings.indexer_categories)),
                    default=None,
                )
        return categories

    def enqueue_folders(self, request: JobRequest, *, verify: bool = False) -> dict[str, Path]:
        """Resolve the entire batch before queueing, asking only for missing categories."""
        resolved: dict[int | None, Path] = {}
        folders: dict[str, Path] = {}
        for h, category in self.enqueue_categories(request).items():
            if category not in resolved:
                folder = self.setup.download_folder(category)
                if folder is None:
                    if category is None:
                        raise ValueError(
                            "Torrent category is unknown. Search again or choose an explicit "
                            "category before queueing; no default Download Folder was changed."
                        )
                    raise DownloadFolderRequired(self.setup.settings.active_client_id, category)
                resolved[category] = (
                    self.setup.verified_download_folder(category)
                    if verify
                    else self.setup.path_under_root(str(folder))
                )
            folders[h] = resolved[category]
        return folders

    def download_destinations(self) -> set[str]:
        folders = self.setup.settings.download_folders
        result = set()
        for value in [folders.default, *folders.by_category.values()]:
            if not value:
                continue
            try:
                result.add(str(self.setup.path_under_root(value)))
            except (ValueError, OSError):
                # An unrelated disconnected destination does not invalidate this one.
                continue
        return result

    def queue(self) -> list[dict[str, Any]]:
        return [
            {
                "client_id": e.client_id,
                "client_name": self.setup.settings.profile(e.client_id).name,
                "key": e.key,
                "title": e.candidate.title,
                "hash": e.candidate.infohash,
                "size": e.candidate.size,
                "folder": str(e.folder),
                "status": e.status,
                "reason": (
                    "Check the Torrent Client before removing and queueing this entry again."
                    if e.status == "uncertain"
                    else "Check the last job and client state."
                    if e.reason
                    else ""
                ),
                "origin": e.origin,
                "priority": e.priority,
                "added_at": e.added_at,
                "retry_safe": e.retry_safe,
                "zen": torrent_zen(
                    self.setup.settings.zen, ZenTorrent(e.candidate.size, e.candidate.seeders + 1)
                ),
                "note": note(
                    self.setup.settings.zen.zen_class,
                    ZenTorrent(e.candidate.size, e.candidate.seeders + 1),
                ),
            }
            for e in entries(self.setup.store)
        ]

    def search_listing(self, indexer, page, rows) -> dict[str, Any]:
        """What the Search page paints beyond a result row: poster, rating, tags, counts, and
        which results the client or the queue already has. Kept out of the rows themselves,
        which agents and saved selections fingerprint."""
        from dataclasses import asdict

        from torrentlinker.download_queue import entries

        shown = {r["hash"] for r in rows}
        known = {t.hash.lower(): "client" for t in self.observed if t.hash.lower() in shown}
        for entry in entries(self.setup.store):
            key = (entry.candidate.infohash or "").lower()
            if key in shown and entry.status in {"queued", "sending"}:
                known.setdefault(key, "queued")
        if page is None:
            return {"listing": {}, "known": known, "root_counts": {}, "total_size": None}
        return {
            "listing": {h: asdict(d) for h, d in page.details.items() if h in shown},
            "known": known,
            "root_counts": {str(k): v for k, v in page.root_counts.items()},
            "total_size": page.total_size,
        }

    def search_options(self, category=None):
        from torrentlinker.indexer_search import search_options

        settings = self.setup.settings
        visible = settings.visible_categories(settings.indexer_categories)
        return search_options(
            self.setup.indexer(),
            category,
            {str(k): asdict(settings.indexer_categories[k]) for k in visible},
            adult=settings.adult_content,
        )

    def run(
        self, request: JobRequest, stop: threading.Event, progress: Callable[[Any], None]
    ) -> Any:
        from contextlib import nullcontext

        from torrentlinker.job_lanes import BACKGROUND, job_lane

        self.validate(request)
        interactive = job_lane(request.kind, request.model_dump()) == "interactive"
        access = (
            self.setup.indexer().background(stop)
            if request.kind in BACKGROUND
            and not interactive
            and not (request.kind == "plan" and request.cached_only)
            else nullcontext()
        )
        if interactive and (
            request.kind not in {"library-evidence", "candidate-inspector"}
            or request.kind == "candidate-inspector"
            and request.inspector_action in {"review", "check", "search", "details"}
        ):
            access = self.setup.indexer().foreground(stop)
        with access:
            return self._run(request, stop, progress, interactive=interactive)

    def _run(self, request, stop, progress, *, interactive=False):
        library = self.library.snapshot() if interactive else self.library
        if request.kind in {"tracker-preview", "tracker-update"}:
            from torrentlinker.tracker_updates import tracker_updates

            service = tracker_updates(self.setup)
            clients = request.client_ids or [self.setup.settings.active_client_id]
            if request.kind == "tracker-preview":
                return service.preview(
                    clients,
                    request.tracker_action,
                    request.tracker_source_host,
                    request.tracker_target_host,
                    request.tracker_groups,
                    stop,
                    progress,
                )
            return service.apply(
                request.tracker_preview_id,
                clients,
                request.tracker_action,
                stop,
                progress,
                request.tracker_source_host,
                request.tracker_target_host,
                request.tracker_groups,
            )
        if request.kind == "reseed-workspace":
            return self.reseed_workspace.run(
                request.paths,
                request.reseed_action,
                request.link_root,
                stop,
                progress,
                request.candidate_key,
            )
        if request.kind == "edit-queue-selection":
            if request.queue_action == "retry":
                destinations = self.download_destinations()
                # Probe each distinct folder once, not once per selected entry.
                for folder in dict.fromkeys(row["folder"] for row in request.selection_rows):
                    self.setup.path_under_root(folder)
                    self.setup.configure_download_folder(folder)
                    if folder not in destinations:
                        raise ValueError("The queued destination changed. Review it again.")
            self.setup.store.edit_downloads(
                request.selection_rows, request.queue_action, request.priority
            )
            return {
                "rows": [
                    {"hash": row["hash"], "outcome": request.queue_action}
                    for row in request.selection_rows
                ],
                "removed" if request.queue_action == "remove" else "updated": len(
                    request.selection_rows
                ),
                "downloads_started": False,
            }
        if request.kind == "select-queue":
            from torrentlinker.queue_selection import select_queue

            return select_queue(self.setup, request.queue_selection)
        if request.kind == "select-catalogue":
            return self.select_catalogue(request.catalogue_selection)
        if request.kind == "configure-download-folder":
            return self.setup.configure_download_folder(
                request.path, request.category, request.client_path, save=True
            )
        if request.kind in {"model-inspect", "model-render"}:
            from torrentlinker import upload_models

            if request.kind == "model-inspect":
                return upload_models.inspect(self.uploads, request.path, stop)
            return upload_models.render(
                self.uploads,
                request.path,
                request.model_files,
                request.model_cameras,
                stop,
                progress,
            )
        if request.kind == "upload-preview":
            if request.draft_id:
                record = self.setup.store.local_draft(request.draft_id)
                if record["path"] != request.path:
                    raise ValueError("A Local Draft cannot be moved to another Local Item.")
            return self.uploads.prepare(
                request.path, request.upload, stop, stored=bool(request.draft_id)
            )[1]
        if request.kind == "upload-queue":
            return self.uploads.queue(
                request.path, request.upload, stop, request.draft_id, request.revision
            )
        if request.kind == "upload-send":
            return self.uploads.send(request.draft_id, request.revision, stop, progress)
        if request.kind == "upload-remove":
            self.setup.store.remove_local_draft(request.draft_id, request.revision)
            return {"removed": request.draft_id}
        if request.kind == "upload-reset":
            return reset_local(self.setup.store, request.draft_id, request.revision)
        if request.kind == "upload-draft":
            return self.uploads.draft(request.path, request.upload, stop, progress)
        if request.kind == "upload-seed":
            if len(request.hashes) != 1:
                raise ValueError("Select one prepared Upload.")
            return self.uploads.seed(request.hashes[0], stop)
        if request.kind == "profile":
            profile = self.setup.profile_workspace().refresh(
                self.setup.settings.indexer.url, self.setup.secrets.get("indexer-api-key")
            )
            self.setup.settings.zen = profile.apply(self.setup.settings.zen)
            self.setup.save()
            return {"balance": profile.balance, "class": profile.class_slug}
        if request.kind == "verify":
            from torrentlinker.reseed import check_verifications

            outcomes = check_verifications(library.client(), self.setup.store)
            return [
                {
                    "hash": o.hash,
                    "verified": o.verified,
                    "progress": o.progress,
                    "started": o.started,
                }
                for o in outcomes
            ]
        if request.kind == "catalogue":
            from torrentlinker.web.planning import catalogue as update_catalogue

            return update_catalogue(self.setup, stop, progress, root=request.catalogue_root)
        if request.kind == "plan":
            root = self.setup._root or self.setup
            for settings in (root.settings, self.setup.settings):
                settings.plan_options = request.planning_options()
                settings.plan_categories = request.planning_categories()
            root.save()
            self.planner.clear()
            from torrentlinker.web.planning import (
                catalogue_status,
                plan,
                plan_result,
                refresh_for_plan,
            )

            if request.client_ids and not (
                set(request.client_ids) == {self.setup.settings.active_client_id}
                and not request.client_budgets.get(self.setup.settings.active_client_id, 0)
            ):
                from dataclasses import replace

                from torrentlinker.multi_plan import distributed_plan

                targets = {
                    identifier: self.setup.for_client(identifier)
                    for identifier in dict.fromkeys(request.client_ids)
                }
                notice = ""
                if not request.cached_only:
                    notice = refresh_for_plan(
                        self.setup,
                        stop,
                        progress,
                        request.planning_categories(),
                    )
                if stop.is_set():
                    return {
                        "cancelled": True,
                        "rows": [],
                        "catalogue": catalogue_status(self.setup),
                        "indexer_url": getattr(getattr(self.setup, "_indexer", None), "url", None)
                        or self.setup.settings.indexer.url,
                    }
                settings = replace(
                    self.setup.settings,
                    plan_categories=request.planning_categories(),
                    plan_options=request.planning_options(),
                )
                progress({"phase": "planning"})

                def validate(identifier, folder):
                    target = targets[identifier]
                    target.configure_download_folder(str(folder))
                    Library(target).check_tree(folder, stop)

                proposed = distributed_plan(
                    settings,
                    self.setup.store,
                    {identifier: target.client() for identifier, target in targets.items()},
                    request.client_budgets,
                    validate,
                )
                self.planner.accept(proposed)
                return {
                    **plan_result(self.setup, proposed),
                    "notice": notice,
                    "plan_id": self.planner.identifier,
                    "indexer_url": getattr(getattr(self.setup, "_indexer", None), "url", None)
                    or self.setup.settings.indexer.url,
                }
            planned_result = plan(
                self.setup,
                library,
                request.maximum_bytes,
                request.maximum_torrents,
                stop,
                progress,
                cached_only=request.cached_only,
                category=request.category,
                categories=request.planning_categories(),
                options=request.planning_options(),
                on_plan=self.planner.accept,
            )
            return {**planned_result, "plan_id": self.planner.identifier}
        if request.kind == "send-plan":
            return self.planner.send(
                request.plan_id,
                request.plan_selection or request.hashes,
                stop,
                progress,
                request.confirmation,
            )
        if request.kind == "speed-test":
            from torrentlinker.web.zen_preferences import measure

            return measure(self.setup)
        if request.kind == "details":
            from torrentlinker.torrent_details import parse_details, preview_html

            if len(request.hashes) != 1:
                raise ValueError("Select one torrent.")
            raw_detail = self.setup.indexer().torrent_json(request.hashes[0])
            detail = parse_details(raw_detail)
            markup, images = preview_html(detail.description, detail.poster)
            facts = asdict(detail)
            for key in ("description", "nfo", "files", "has_nfo"):
                facts.pop(key)
            document = {
                "title": str(raw_detail.get("name") or ""),
                "size": raw_detail.get("size") if isinstance(raw_detail.get("size"), int) else 0,
                "description": markup,
                "images": images,
                "nfo": detail.nfo,
                "files": detail.files,
                "info": facts,
            }
            from torrentlinker.release_score.service import details_score

            candidate = self.candidates.get(request.hashes[0])
            document["release_score"] = details_score(
                document,
                self.setup.settings.release_score,
                title=candidate.title if candidate else "",
                size=candidate.size if candidate else 0,
                listing=self.score_listings.get(request.hashes[0]),
            )
            return document
        if request.kind == "search-options":
            return self.search_options(request.category)
        if request.kind == "scan":
            return library.scan(stop, progress, request.paths or None)
        if request.kind == "diagnose-repair":
            from torrentlinker.domain import TorrentClient

            if self.setup.settings.client != TorrentClient.QBITTORRENT:
                raise ValueError("Experimental repair currently requires qBittorrent.")
            from torrentlinker.review import candidate_key, remembered_candidates

            indexer = self.setup.indexer()
            found = remembered_candidates(self.setup.store, indexer, Path(request.path)) or []
            candidate = next((c for c in found if candidate_key(c) == request.candidate_key), None)
            if candidate is None:
                raise ValueError("Select a current Candidate first.")
            return library.diagnose(request.path, candidate, indexer.fetch_torrent(candidate), stop)
        if request.kind == "prepare-repair":
            return library.prepare_repair(
                request.repair_id, request.client_path, stop, experimental=request.experimental
            )
        if request.kind == "refresh-repair":
            return library.refresh_repair(request.repair_id)
        if request.kind == "start-repair":
            return library.start_repair(request.repair_id, request.confirmation)
        if request.kind == "combine-library":
            return library.combine(request.paths, stop, request.selection_name)
        if request.kind == "find-compatible":
            return library.compatible(request.path, stop, progress)
        if request.kind == "candidate-inspector":
            return library.inspector(
                request.path,
                request.inspector_action,
                stop,
                key=request.candidate_key,
                torrent_data=request.torrent_data,
                progress=progress,
            )
        if request.kind == "library-evidence":
            return {
                **library.evidence(request.path, stop),
                "provenance": library.provenance(request.path),
                "repairs": library.repairs().rows(),
            }
        if request.kind == "import-provenance":
            import base64

            try:
                data = base64.b64decode(request.torrent_data, validate=True)
            except ValueError as error:
                raise ValueError("Invalid torrent upload.") from error
            return library.import_provenance(request.path, data, stop)
        if request.kind == "check":
            return library.check(request.path, stop, progress)
        if request.kind in {"library-review", "library-reject", "check-candidate"}:
            return library.review(
                request.path,
                stop,
                key=request.candidate_key,
                action={
                    "library-review": "",
                    "library-reject": "reject",
                    "check-candidate": "check",
                }[request.kind],
            )
        if request.kind == "search-library":
            return library.search_items(request.paths, stop, progress)
        if request.kind == "refresh-unpack":
            if len(request.hashes) != 1:
                raise ValueError("Select one archive torrent.")
            return self.archives.status(request.hashes[0])
        if request.kind == "preview-unpack":
            return self.archives.preview(request.path, request.candidate_key, stop)
        if request.kind == "unpack-reseed":
            return self.archives.start(
                request.path, request.candidate_key, request.confirmation, stop, progress
            )
        if request.kind == "reseed":
            return library.reseed(request.path, request.hashes[0], stop)
        if request.kind == "check-all":
            return library.check_all(stop, progress)
        if request.kind == "reseed-all":
            return library.reseed_all(stop, progress)
        if request.kind == "search":
            indexer = self.setup.indexer()
            seeded = set()
            if request.search_exclude_seeded:
                seeded = {
                    t.hash.lower()
                    for t in self.setup.client().torrents(with_files=False)
                    if t.progress >= 1
                }
            native_params = None
            if request.indexer_search:
                from torrentlinker.indexer_search import IndexerFilters

                typed_filters = IndexerFilters.model_validate(request.filters)
                if indexer.is_c411:
                    native_params = typed_filters.validate_native(
                        indexer, request.category, request.query
                    )
                elif typed_filters != IndexerFilters():
                    raise ValueError(
                        "Advanced native filters are unavailable on this Indexer; "
                        "no filters were ignored."
                    )
            if indexer.is_c411:
                allowed = {
                    k: v
                    for k, v in request.filters.items()
                    if k not in {"page", "perPage", "viewMode", "apikey", "api_key"}
                    and len(v) < 500
                }
                params = {
                    "sortBy": "createdAt",
                    "sortOrder": "desc",
                    **(native_params if native_params is not None else allowed),
                    "name": request.query,
                }
                if request.category is not None and native_params is None:
                    if request.category < 0:
                        from torrentlinker.torrent_search import parse_tree

                        parent = parse_tree(indexer.search_categories()).root(request.category)
                        if parent is None:
                            raise ValueError("This subcategory is unavailable. Refresh categories.")
                        params["category"] = str(parent)
                    params["category" if request.category > 0 else "subcat"] = str(
                        abs(request.category)
                    )
                page = native_search(indexer, params, request.page)
                found, total_pages = page.rows, page.total_pages
            else:
                found = indexer.search(
                    SearchQuery(
                        q=request.query,
                        categories=(request.category,) if request.category else (),
                        limit=100,
                        offset=(request.page - 1) * 100,
                    )
                )
                total_pages = request.page + int(len(found) == 100)
            found = [c for c in found if not self.setup.settings.hides(c.categories)]
            metadata: dict[str, Any] = {
                "backend": "c411-native" if indexer.is_c411 else "torznab",
                "page": page.page if indexer.is_c411 else request.page,
                "pages": total_pages,
                "total": page.total if indexer.is_c411 else None,
                "per_page": page.per_page if indexer.is_c411 else 100,
                "has_more": page.has_more if indexer.is_c411 else len(found) == 100,
                "window_limited": page.limited if indexer.is_c411 else None,
                "pagination_is_estimate": not indexer.is_c411,
                "palliative_matches": page.palliative_matches if indexer.is_c411 else None,
                "palliative_fallback": page.palliative_fallback if indexer.is_c411 else None,
                "palliative_count": page.palliative_count if indexer.is_c411 else None,
                "returned_count_before_exclusions": len(found),
                "excluded_seeded_count": sum(c.infohash in seeded for c in found),
                "seeded_exclusion_scope": "returned page only; completed includes paused"
                if request.search_exclude_seeded
                else None,
                "observed_at": time.time(),
                "search": {
                    "query": request.query,
                    "category": request.category,
                    "filters": request.filters,
                },
            }
            result = []
            catalogue = []
            for c in found:
                if c.infohash in seeded:
                    continue
                if not c.infohash:
                    continue
                self.candidates[c.infohash] = c
                zt = ZenTorrent(c.size, c.seeders + 1)
                result.append(
                    {
                        "hash": c.infohash,
                        "title": c.title,
                        "size": c.size,
                        "seeders": c.seeders,
                        "published_at": c.published_at,
                        "native_category_label": page.labels.get(c.infohash)
                        if indexer.is_c411
                        else None,
                        "revival": c.infohash in page.palliative if indexer.is_c411 else None,
                        "website": indexer.redact(website_url(c, indexer)),
                        "zen": torrent_zen(self.setup.settings.zen, zt),
                        "note": note(self.setup.settings.zen.zen_class, zt),
                        "categories": c.categories,
                        "category": c.categories[-1] if c.categories else None,
                        "source": "indexer",
                        "seen_at": metadata["observed_at"],
                    }
                )
                catalogue.append(
                    CatalogueRow(
                        c.infohash,
                        c.title,
                        c.size,
                        c.seeders,
                        c.categories[-1] if c.categories else None,
                        indexer.redact(c.download_url),
                        indexer.redact(c.details_url),
                        time.time(),
                    )
                )
            from torrentlinker.release_score.estimate import estimate as release_estimate
            from torrentlinker.release_score.service import mark_best, score

            for row in result:
                listing = (
                    asdict(page.details[row["hash"]])
                    if indexer.is_c411 and row["hash"] in page.details
                    else {}
                )
                self.score_listings[row["hash"]] = listing
                row["release_score"] = score(
                    release_estimate(row["title"], row["size"], listing),
                    self.setup.settings.release_score,
                )
            # Only retain bounded listing facts for local re-scoring of recent pages.
            while len(self.score_listings) > 2000:
                self.score_listings.pop(next(iter(self.score_listings)))
            mark_best(result)
            self.setup.store.save_catalogue(catalogue)
            from torrentlinker.queue_selection import snapshot

            extras = (
                self.search_listing(indexer, page if indexer.is_c411 else None, result)
                if request.search_listing
                else {}
            )
            return {
                **snapshot(result, "catalogue", metadata["search"]),
                **metadata,
                **extras,
                "selection_kind": "live-search",
                "indexer_url": indexer.url,
                "coverage": "Exact returned page after exclusions; "
                "not the whole tracker or all matching pages.",
            }
        if request.kind == "enqueue":
            folders = self.enqueue_folders(request, verify=True)
            indexer = self.setup.indexer()
            candidates = []
            for h in request.hashes:
                candidate = None if request.selection_id else self.candidates.get(h)
                if candidate is None:
                    cached = self.setup.store.catalogue([h])
                    if not cached:
                        raise ValueError("Search again before queueing this torrent.")
                    r = cached[0]
                    candidate = Candidate(
                        r.title,
                        r.size,
                        indexer.unredact(r.download_url),
                        r.seeders,
                        r.infohash,
                        r.details_url,
                        categories=(r.category,) if r.category is not None else (),
                    )
                if not candidate.download_url:
                    raise ValueError("This torrent has no download link.")
                candidates.append((h, candidate))
            count = 0
            queue_outcomes = []
            for h, candidate in candidates:
                added = enqueue(
                    self.setup.store,
                    indexer,
                    candidate,
                    folders[h],
                )
                count += added
                queue_outcomes.append(
                    {
                        "hash": h,
                        "title": candidate.title,
                        "outcome": "queued" if added else "already_present",
                    }
                )
            return {
                "rows": queue_outcomes,
                "queued": count,
                "already_present": len(candidates) - count,
                "location": "TorrentLinker Search > Download queue",
                "sent_to_client": False,
                "downloads_started": False,
                "next_step": "Use send-queue only if the user asks to start downloads.",
            }
        if request.kind == "send-queue":
            selected_keys = (
                {r["key"] for r in request.queue_binding}
                if request.queue_binding
                else {r["key"] for r in request.selection_rows}
                if request.selection_source == "queue"
                else None
            )
            hashes = set(request.hashes)
            queued_entries = [
                e
                for e in entries(self.setup.store)
                if e.status == "queued"
                and (not hashes or e.candidate.infohash in hashes)
                and (selected_keys is None or e.key in selected_keys)
            ]
            if not queued_entries and self.setup.download_folder(request.category):
                self.setup.verified_download_folder(request.category)
            # Recheck selected folders, including entries saved before settings changed.
            # Each probe lists the client's torrents, so check each folder once.
            destinations = self.download_destinations()
            for folder in dict.fromkeys(str(entry.folder) for entry in queued_entries):
                self.setup.path_under_root(folder)
                self.setup.configure_download_folder(folder)
                if folder not in destinations:
                    raise ValueError(
                        "A queued destination changed. Remove that entry and queue it again."
                    )
            client = DownloadClient(self.setup)
            send_options: dict[str, Any] = (
                {"order": [r["key"] for r in request.selection_rows]}
                if request.selection_source == "queue"
                else {}
            )
            report = run_queue(
                self.setup.store,
                self.setup.indexer(),
                client,
                self.setup.settings.indexer_categories,
                stop,
                lambda p: progress(asdict(p)),
                only={e.key for e in queued_entries} if request.hashes else None,
                **send_options,
            )
            after = {e.key: e for e in entries(self.setup.store)}
            return {
                "rows": [
                    {
                        "key": e.key,
                        "hash": e.candidate.infohash,
                        "title": e.candidate.title,
                        "outcome": (
                            "sent"
                            if e.key in report.sent_keys
                            else after[e.key].status
                            if e.key in after
                            else "removed"
                        ),
                        "reason": after[e.key].reason if e.key in after else "",
                    }
                    for e in queued_entries
                ],
                "selected_count": len(queued_entries),
                "total_size_bytes": sum(e.candidate.size for e in queued_entries),
                "attempted_count": report.handled,
                "added": len(report.added),
                "refused": [title for title, _ in report.refused],
                "failed": [title for title, _ in report.failed],
                "stopped": report.stopped,
            }
        if request.kind in {"refresh", "select-torrents"}:
            torrents = self.setup.client().torrents(with_files=False)
            settings = self.setup.settings
            cached_rows = {
                r.infohash: r
                for r in self.setup.store.catalogue([t.hash.lower() for t in torrents])
            }
            cached_rows.update(observe_swarm(self.setup.store, torrents, settings.indexer.url))
            view = seeding(
                settings.zen,
                torrents,
                settings.indexer.url,
                settings.uploads,
                catalogue=cached_rows,
                categories=settings.indexer_categories,
            )
            estimates = {r.torrent.hash: r for r in view.rows}
            labels = category_labels(settings.indexer_categories)
            rows = []
            for t in torrents:
                estimate = estimates.get(t.hash)
                rows.append(
                    {
                        "client_id": settings.active_client_id,
                        "client_name": settings.profile().name,
                        "hash": t.hash,
                        "name": t.name,
                        "status": status(t),
                        "progress": t.progress,
                        "size": t.total_size,
                        "download": t.download_rate,
                        "upload": t.upload_rate,
                        "ratio": t.ratio,
                        "eta": t.eta,
                        "seeds": t.connected_seeds,
                        "peers": t.connected_peers,
                        "total_seeds": t.swarm_seeders,
                        "total_peers": t.swarm_peers,
                        "folder": str(t.save_path),
                        "trackers": tracker_hosts(t),
                        "categories": torrent_categories(t, labels),
                        "tags": sorted(t.tags),
                        "zen": estimate.zen if estimate else None,
                        "note": estimate.note if estimate else None,
                        "provisional": estimate.provisional_category if estimate else False,
                        "ranking_metrics_known": estimate is not None
                        and (t.swarm_seeders >= 0 or t.hash.lower() in cached_rows),
                    }
                )
            self.rows = rows
            self.observed = torrents
            self.connection_error = ""
            self.zen = {"count": view.count, "daily": view.day.total, "paid": view.day.paid}
            if request.kind == "select-torrents":
                return select_rows(rows, request.selection)
            return {"count": len(rows), "zen": self.zen}
        if request.kind == "manage":
            if request.selection_id:
                # Refresh and check the ranking inside the same desktop coordination scope.
                # Never replace a missing or changed selection with different torrents.
                Operations.run(
                    self, JobRequest(kind="refresh", client_id=request.client_id), stop, progress
                )
                selected = select_rows(self.rows, request.selection)
                if [row["hash"] for row in selected["rows"]] != request.hashes:
                    raise ValueError("Torrent selection changed. Select and review it again.")
            result = []
            for hash in request.hashes:
                if stop.is_set():
                    break
                results = manage(self.setup.client(), [hash], request.action)
                # Raw adapter failures may contain secrets. Expose only safe outcomes.
                result += [
                    {
                        **asdict(r),
                        "detail": "See connection settings." if r.outcome == "failed" else r.detail,
                    }
                    for r in results
                ]
                progress({"done": len(result), "total": len(request.hashes)})
            if request.selection_id:
                return {
                    "rows": result,
                    "requested_count": len(request.hashes),
                    "attempted_count": len(result),
                    "outcomes": dict(Counter(row["outcome"] for row in result)),
                    "cancelled": stop.is_set(),
                }
            return result
        raise ValueError("Unknown job.")
