"""Owner Torrents panel service shared by desktop and Web."""

from __future__ import annotations

import secrets
import threading
import time
from contextlib import nullcontext
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, Field

from torrentlinker.seeding import indexer_torrents
from torrentlinker.torrent_management import manage, peer_count_order, safe_error, tracker_group
from torrentlinker.web.operations import JobRequest, Operations
from torrentlinker.zen import weight


class TorrentQuery(BaseModel):
    client_id: str = ""
    q: str = ""
    sort: Literal[
        "name",
        "client_name",
        "status",
        "size",
        "progress",
        "download",
        "upload",
        "ratio",
        "eta",
        "note",
        "zen",
        "weight",
        "seeds",
        "peers",
        "seedtime",
    ] = "name"
    descending: bool = False
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=200)
    tracker: str = ""
    state: str = ""
    category: str = ""
    tag: str = ""
    scope: Literal["", "c411", "other"] = ""
    size_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    size_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    note_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    zen_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    weight_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    seed_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    days_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class TorrentInstance(BaseModel):
    client_id: str = Field(min_length=1)
    hash: str = Field(pattern=r"^[a-fA-F0-9]{40}$")


class TorrentAction(BaseModel):
    action: Literal[
        "pause",
        "resume",
        "recheck",
        "remove",
        "delete",
        "skip_files",
        "want_files",
        "reannounce",
        "limits",
        "category",
        "location",
    ]
    items: list[TorrentInstance] = Field(min_length=1, max_length=1000)
    file_indexes: list[int] = Field(default_factory=list, max_length=10000)
    download_limit: int = Field(default=0, ge=0)
    upload_limit: int = Field(default=0, ge=0)
    category: str = Field(default="", max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=50)
    path: str = Field(default="", max_length=4096)
    token: str = ""


class TorrentWorkspace:
    def __init__(self, setup, for_client, jobs=None):
        self.setup, self.for_client = setup, for_client
        self.jobs = jobs
        self.lock = threading.RLock()
        self.updated: dict[str, float] = {}
        self.observed_at: dict[str, float] = {}
        self.pending: dict[str, tuple] = {}
        from torrentlinker.remote_access import RemoteAccess
        from torrentlinker.transfers import Transfers

        root = getattr(setup, "_root", None) or setup
        with setup.lock:
            from torrentlinker.torrent_audit import TorrentAudit

            if not hasattr(root, "_torrent_audit"):
                root._torrent_audit = TorrentAudit(
                    setup.path.parent / "torrent-audits", self.audit_collect, setup.indexer
                )
            self.audit = root._torrent_audit
            existing = getattr(root, "_client_transfers", None)
            if existing is not None:
                self.transfers = existing
                self.remote = root._transfer_remote
                return
            self.remote = RemoteAccess(setup.path.parent / "transfer-access", setup.secrets)
            root._transfer_remote = self.remote
            self.transfers = Transfers(
                setup.path.parent / "client-transfers",
                self.transfer_client,
                self.transfer_metadata,
                lambda: [p.id for p in self.setup.settings.client_profiles if p.enabled],
                self.transfer_fingerprint,
                self.transfer_accessible,
                self.remote.path_for,
            )
            root._client_transfers = self.transfers

    def close(self):
        self.audit.close()
        for identifier in list(self.transfers.running):
            self.transfers.stop(identifier)
        deadline = time.monotonic() + 5
        while self.transfers.running and time.monotonic() < deadline:
            time.sleep(0.05)
        self.remote.close()

    def target(self, identifier):
        identifier = identifier or self.setup.settings.active_client_id
        profile = self.setup.settings.profile(identifier)
        if not profile.enabled:
            raise ValueError("This Torrent Client is disabled.")
        return self.for_client(identifier)

    def request(self, action, body=None):
        body = body or {}
        from torrentlinker.agent.coordination import coordinator
        from torrentlinker.agent.desktop import DesktopSetup

        # Job polling only reads Jobs' synchronized state. It must stay available
        # while a desktop worker holds the application coordinator.
        if action == "tracker-job":
            return self.tracker_request(action, body)

        # Acquire application access before our own lock. Desktop refresh must not
        # nest DesktopOperations' agent context while this request holds it.
        access = (
            coordinator.agent(threading.Event())
            if isinstance(self.setup, DesktopSetup)
            else nullcontext()
        )
        with access, self.lock:
            if action.startswith("tracker-"):
                return self.tracker_request(action, body)
            if action.startswith("audit-"):
                return self.audit_request(action, body)
            if action.startswith("transfer-"):
                # Client removal and access persistence share the setup lock,
                # including validation that the owning client still exists.
                mutation = action in {"transfer-access-save", "transfer-access-remove"}
                with self.setup.lock if mutation else nullcontext():
                    return self.transfer_request(action, body)
            if action == "list":
                return self.list(TorrentQuery.model_validate(body))
            if action in {"review", "apply"}:
                return self.action(action, TorrentAction.model_validate(body))
            if action == "files":
                item = TorrentInstance.model_validate(body)
                return {
                    "files": [
                        asdict(f)
                        for f in self.target(item.client_id).setup.client().file_listing(item.hash)
                    ]
                }
            raise ValueError("Unknown torrent operation.")

    def tracker_request(self, action, body):
        if self.jobs is None:
            raise ValueError("Tracker jobs are unavailable in this workspace.")
        if action == "tracker-job":
            job = self.jobs.get(body.get("id", ""))
            if job["kind"] not in {"tracker-preview", "tracker-update"}:
                raise ValueError("Unknown tracker job.")
            return job
        if action == "tracker-settings":
            from torrentlinker.tracker_updates import announce_hosts

            return {
                "hosts": announce_hosts(self.setup),
                "clients": [
                    {"id": p.id, "name": p.name}
                    for p in self.setup.settings.client_profiles
                    if p.enabled
                ],
            }
        if action not in {"tracker-preview", "tracker-update"}:
            raise ValueError("Unknown tracker action.")
        request = JobRequest.model_validate({**body, "kind": action})
        identifiers = request.client_ids or [request.client_id]
        for identifier in identifiers:
            self.target(identifier)
        target = self.target(identifiers[0])
        return {
            "id": self.jobs.submit(
                action,
                lambda stop, report: target.run(request, stop, report),
                client_id=identifiers[0],
                parameters=request.model_dump(),
            )
        }

    def audit_collect(self, identifier):
        from torrentlinker.agent.coordination import coordinator
        from torrentlinker.agent.desktop import DesktopSetup

        access = (
            coordinator.agent(threading.Event())
            if isinstance(self.setup, DesktopSetup)
            else nullcontext()
        )
        with access:
            target = self.target(identifier).setup
            return target.settings.profile().name, target.client().torrents(with_files=False)

    def audit_request(self, action, body):
        if action == "audit-start":
            selected = body.get("client_ids") or [
                body.get("client_id") or self.setup.settings.active_client_id
            ]
            if selected == ["all"]:
                selected = [p.id for p in self.setup.settings.client_profiles if p.enabled]
            if (
                not isinstance(selected, list)
                or not selected
                or len(selected) > 100
                or any(not isinstance(value, str) for value in selected)
            ):
                raise ValueError("Choose one or more Torrent Clients.")
            selected = list(dict.fromkeys(selected))
            for identifier in selected:
                self.target(identifier)
            tag = body.get("tag", "")
            if not isinstance(tag, str) or len(tag) > 200:
                raise ValueError("Invalid tag filter.")
            return self.audit.start(selected, tag)
        if action == "audit-list":
            return {"reports": self.audit.history()}
        identifier = body.get("id", "")
        if action == "audit-stop":
            return self.audit.stop(identifier)
        if action == "audit-report":
            return self.audit.read(
                identifier, int(body.get("offset", 0)), int(body.get("limit", 100))
            )
        if action == "audit-export":
            return self.audit.export(identifier, body.get("format", "json"))
        raise ValueError("Unknown audit operation.")

    def transfer_fingerprint(self, identifier):
        import hashlib

        return hashlib.sha256(
            (
                str(self.target(identifier).setup.snapshot()) + self.remote.fingerprint(identifier)
            ).encode()
        ).hexdigest()

    def transfer_accessible(self, identifier, path):
        from pathlib import Path
        from urllib.parse import urlsplit

        if identifier in self.remote.profiles:
            if not self.remote.snapshot(identifier)["checked"]:
                raise ValueError("Check SFTP access before preparing the transfer")
            self.remote.mapped(identifier, path)
            return
        self.setup.path_under_root(str(path))
        settings = self.target(identifier).setup.settings
        host = urlsplit(settings.profile().host).hostname
        if host in {"localhost", "127.0.0.1", "::1"}:
            return
        if not any(
            Path(path).is_relative_to(Path(mapping.local)) for mapping in settings.path_mappings
        ):
            raise ValueError("Remote storage needs a configured accessible path mapping")

    def transfer_client(self, identifier):
        from torrentlinker.paths import MappedQbit, PathMapper

        target = self.target(identifier).setup
        if identifier in self.remote.profiles:
            return target.client()
        return MappedQbit(target.client(), PathMapper(target.settings.path_mappings))

    def transfer_metadata(self, identifier, key):
        target = self.target(identifier)
        data = target.setup.store.cached_torrent(key)
        if data is not None:
            return data
        export = getattr(target.setup.client(), "export_torrent", None)
        if export is None:
            raise ValueError(
                "Original .torrent metadata is unavailable; "
                "use a torrent already cached in TorrentLinker"
            )
        data = export(key)
        target.setup.store.cache_torrent(key, data)
        return data

    def transfer_request(self, action, body):
        if action.startswith("transfer-access-") or action == "transfer-remote-browse":
            identifier = body["client_id"]
            profile = self.setup.settings.profile(identifier)
            if action not in {"transfer-access-snapshot", "transfer-access-remove"}:
                self.target(identifier)  # Reject unknown or disabled clients before connecting.
            try:
                if action == "transfer-access-snapshot":
                    return {
                        **self.remote.snapshot(identifier),
                        "client_id": identifier,
                        "enabled": profile.enabled,
                        "busy": bool(self.transfers.running),
                    }
                if action == "transfer-access-remove":
                    if body.get("confirmed") is not True:
                        raise ValueError("Confirm file-access removal first")
                    if self.transfers.running:
                        raise ValueError("Interrupt active transfers before changing file access")
                    return self.remote.remove(identifier)
                if action == "transfer-access-discover":
                    return self.remote.discover(body["config"])
                if action == "transfer-access-save":
                    if self.transfers.running:
                        raise ValueError("Interrupt active transfers before changing file access")
                    return self.remote.save(
                        identifier,
                        body["config"],
                        body.get("credential", ""),
                        body.get("host_key", ""),
                    )
                if action == "transfer-access-check":
                    return self.remote.check(identifier)
                if action == "transfer-remote-browse":
                    return self.remote.browse(identifier, body.get("path", ""))
                raise ValueError("Unknown file-access operation")
            except Exception as error:
                import asyncssh

                if isinstance(error, asyncssh.HostKeyNotVerifiable):
                    message = (
                        "Server identity changed. Review its fingerprint in file-access settings."
                    )
                elif isinstance(error, asyncssh.PermissionDenied):
                    message = "SFTP sign-in denied. Check the username and file-access credential."
                elif isinstance(error, asyncssh.SFTPPermissionDenied):
                    message = (
                        "SFTP permission denied. Check this account's access to the mapped folder."
                    )
                elif isinstance(error, (ConnectionError, TimeoutError, asyncssh.ConnectionLost)):
                    message = (
                        "SFTP server unavailable. Check its address, port and network connection."
                    )
                else:
                    message = str(error)
                raise ValueError(self.setup.secrets.redact(message)) from None
        if action == "transfer-options":
            items = [TorrentInstance.model_validate(i) for i in body.get("items", [])]
            sources, clients = [], []
            for item in items:
                torrent = self.transfer_client(item.client_id).torrent(item.hash)
                if torrent is None:
                    raise ValueError("Source torrent disappeared")
                from torrentlinker.category_tags import category_tag

                categories = self.setup.settings.indexer_categories
                catalogue = self.setup.store.catalogue([item.hash])
                category_id = catalogue[0].category if catalogue else None
                if category_id is None:
                    category_id = next(
                        (
                            cid
                            for cid, cat in categories.items()
                            if cat.name == torrent.category
                            or category_tag(cid, categories) in torrent.tags
                        ),
                        None,
                    )
                category = (
                    categories[category_id].name if category_id in categories else torrent.category
                )
                sources.append(
                    {
                        "client_id": item.client_id,
                        "hash": item.hash,
                        "name": torrent.name,
                        "category": category,
                        "category_id": category_id,
                        "source": str(torrent.save_path),
                        "total": torrent.total_size,
                    }
                )
            for profile in self.setup.settings.client_profiles:
                if not profile.enabled:
                    continue
                target = self.target(profile.id)
                settings = target.setup.settings
                from torrentlinker.downloads import DownloadFolders
                from torrentlinker.paths import PathMapper

                folders = {}
                try:
                    native = {
                        f.name: f.path
                        if profile.id in self.remote.profiles
                        else PathMapper(settings.path_mappings).to_local(f.path)
                        for f in target.setup.client().folder_settings()
                        if f.kind == "category"
                    }
                except Exception:
                    native = {}
                for row in sources:
                    category = row["category"]
                    category_id = row["category_id"] or next(
                        (
                            cid
                            for cid, cat in settings.indexer_categories.items()
                            if cat.name == category
                        ),
                        0,
                    )
                    explicit = DownloadFolders(settings.download_folders.by_category).resolve(
                        category_id, settings.indexer_categories
                    )
                    resolved = (
                        explicit
                        or native.get(category)
                        or settings.download_folders.resolve(
                            category_id, settings.indexer_categories
                        )
                    )
                    if (
                        resolved
                        and profile.id in self.remote.profiles
                        and (explicit or category not in native)
                    ):
                        resolved = PathMapper(settings.path_mappings).to_qbit(str(resolved))
                    folders[category] = str(resolved) if resolved else ""
                clients.append(
                    {
                        "id": profile.id,
                        "name": profile.name,
                        "folders": folders,
                        "access": self.remote.snapshot(profile.id),
                    }
                )
            return {"sources": sources, "clients": clients}
        if action == "transfer-prepare":
            for item in body["items"]:
                if item.get("folder") and body["destination"] not in self.remote.profiles:
                    self.setup.path_under_root(item["folder"])
            return self.transfers.prepare(
                body["items"],
                body["destination"],
                remove_torrent=body.get("remove_torrent", False),
                remove_files=body.get("remove_files", False),
            )
        if action == "transfer-list":
            return {"plans": self.transfers.list()}
        if action == "transfer-get":
            return self.transfers.get(body["id"])
        if action == "transfer-start":
            return self.transfers.start(body["id"])
        if action == "transfer-stop":
            return self.transfers.stop(body["id"])
        if action == "transfer-review-cleanup":
            return self.transfers.review_cleanup(body["id"], body["index"])
        if action == "transfer-cleanup":
            return self.transfers.cleanup(body["id"], body["index"], body["token"])
        if action == "transfer-browse":
            return self.setup.browse(body.get("path", ""))
        raise ValueError("Unknown transfer operation")

    def list(self, query: TorrentQuery):
        profiles = [p for p in self.setup.settings.client_profiles if p.enabled]
        identifiers = (
            [p.id for p in profiles]
            if query.client_id == "all"
            else [query.client_id or self.setup.settings.active_client_id]
        )
        rows, errors = [], []
        for identifier in identifiers:
            target = self.target(identifier)
            try:
                if time.monotonic() - self.updated.get(identifier, 0) >= 4:
                    Operations.run(
                        target,
                        JobRequest(kind="refresh", client_id=identifier),
                        threading.Event(),
                        lambda _: None,
                    )
                    self.updated[identifier] = time.monotonic()
                    self.observed_at[identifier] = time.time()
                observed = {t.hash: t for t in target.observed}
                eligible_hashes = {
                    t.hash
                    for t in indexer_torrents(
                        target.observed,
                        target.setup.settings.indexer.url,
                        {r.infohash for r in target.setup.store.catalogue(list(observed))},
                    )
                }
                capabilities = self.capabilities(target.setup.client())
                for original in target.rows:
                    row = dict(original)
                    torrent = observed[row["hash"]]
                    # Weight uses the existing estimator, never a separate UI formula.
                    eligible = row["hash"] in eligible_hashes
                    if not row.get("ranking_metrics_known"):
                        row["note"] = row["zen"] = None
                    row.update(
                        weight=weight(row["size"]) if eligible else None,
                        c411=eligible,
                        seedtime=torrent.seeding_time / 86400,
                        key=identifier + ":" + row["hash"],
                        capabilities=capabilities,
                        observed_at=self.observed_at.get(identifier),
                    )
                    rows.append(row)
            except Exception as error:
                errors.append(
                    {"name": target.setup.settings.profile().name, "message": safe_error(error)}
                )
        all_rows = rows

        def value(row, key):
            v = (
                peer_count_order(row[key], row["total_" + key])
                if key in {"seeds", "peers"}
                else row.get(key)
            )
            return None if isinstance(v, (int, float)) and v < 0 else v

        ranges = [
            ("size_min", "size", True),
            ("size_max", "size", False),
            ("note_min", "note", True),
            ("zen_min", "zen", True),
            ("weight_min", "weight", True),
            ("seed_max", "seeds", False),
            ("days_min", "seedtime", True),
        ]

        def matches(row):
            if query.q.casefold() not in row["name"].casefold() and query.q.lower() != row["hash"]:
                return False
            if query.state and row["status"] != query.state:
                return False
            if query.tracker and query.tracker not in [tracker_group(h) for h in row["trackers"]]:
                return False
            if query.category and query.category not in [" / ".join(c) for c in row["categories"]]:
                return False
            if query.tag and query.tag not in row["tags"]:
                return False
            if query.scope and row["c411"] != (query.scope == "c411"):
                return False
            for field, key, minimum in ranges:
                threshold = getattr(query, field)
                if threshold is not None:
                    v = value(row, key)
                    if v is None or (v < threshold if minimum else v > threshold):
                        return False
            return True

        rows = [r for r in rows if matches(r)]
        known = [r for r in rows if value(r, query.sort) is not None]
        unknown = [r for r in rows if value(r, query.sort) is None]
        known.sort(
            key=lambda r: (
                str(value(r, query.sort)).casefold()
                if isinstance(value(r, query.sort), str)
                else value(r, query.sort)
            ),
            reverse=query.descending,
        )
        rows = known + unknown
        offset = min(query.offset, max(0, (len(rows) - 1) // query.limit) * query.limit)
        return {
            "rows": rows[offset : offset + query.limit],
            "total": len(rows),
            "offset": offset,
            "client_errors": errors,
            "clients": [{"id": p.id, "name": p.name} for p in profiles],
            "trackers": sorted({tracker_group(h) for r in all_rows for h in r["trackers"] if h}),
            "categories": sorted({" / ".join(c) for r in all_rows for c in r["categories"] if c}),
            "tags": sorted({t for r in all_rows for t in r["tags"]}),
            "summary": {
                "count": len(all_rows),
                "download": sum(r["download"] for r in all_rows),
                "upload": sum(r["upload"] for r in all_rows),
            },
            "observed_at": min(
                (self.observed_at[i] for i in identifiers if i in self.observed_at), default=None
            ),
        }

    @staticmethod
    def capabilities(client):
        actions = ["pause", "resume", "recheck", "remove", "delete", "skip_files", "want_files"]
        return actions + list(getattr(client, "management_controls", ()))

    def action(self, operation, body):
        payload = body.model_dump_json(exclude={"token"})
        identities, rows = [], []
        for item in body.items:
            target = self.target(item.client_id)
            identities.append(str(target.setup.snapshot()))
            torrent = target.setup.client().torrent(item.hash, with_files=False)
            if torrent is None:
                raise ValueError("A selected torrent no longer exists. Refresh the list.")
            if body.action not in self.capabilities(target.setup.client()):
                raise ValueError("This operation is not supported by this Torrent Client.")
            rows.append(
                {
                    "client_id": item.client_id,
                    "hash": item.hash,
                    "name": torrent.name,
                    "client_name": target.setup.settings.profile().name,
                    "folder": str(torrent.save_path),
                }
            )
            if body.action.endswith("_files"):
                listing = target.setup.client().file_listing(item.hash)
                indexes = {f.index for f in listing}
                if not body.file_indexes or not set(body.file_indexes) <= indexes:
                    raise ValueError("Choose existing file indexes.")
                rows[-1]["files"] = [asdict(f) for f in listing if f.index in body.file_indexes]
        identity = (payload, identities, rows)
        if operation == "review":
            now = time.monotonic()
            self.pending = {k: v for k, v in self.pending.items() if v[0] > now}
            if len(self.pending) >= 100:
                self.pending.clear()
            token = secrets.token_urlsafe(32)
            self.pending[token] = (now + 300, identity)
            return {"token": token, "rows": rows}
        record = self.pending.pop(body.token, None)
        if record is None or record[0] < time.monotonic() or record[1] != identity:
            raise ValueError("Review and confirm this exact action first.")
        results, seen = [], set()
        for item in body.items:
            key = (item.client_id, item.hash)
            if key in seen:
                continue
            seen.add(key)
            target = self.target(item.client_id)
            client = target.setup.client()
            if body.action in {"reannounce", "limits", "category", "location"}:
                # Share the existing Reseed setup lock; never relocate or relabel protected links.
                from torrentlinker import reseed

                try:
                    with reseed._LOCK:
                        torrent = client.torrent(item.hash, with_files=False)
                        if torrent is None or any(
                            t.startswith("torrentlinker:link") or t == reseed.VERIFYING
                            for t in torrent.tags
                        ):
                            raise ValueError(
                                "Protected or missing torrent. Use its Reseed workflow."
                            )
                        client.manage_control(item.hash, body.action, body.model_dump())
                    result = {"hash": item.hash, "outcome": "sent", "detail": ""}
                except Exception as error:
                    result = {"hash": item.hash, "outcome": "failed", "detail": safe_error(error)}
            else:
                if body.action.endswith("_files"):
                    indexes = {f.index for f in client.file_listing(item.hash)}
                    if not body.file_indexes or not set(body.file_indexes) <= indexes:
                        raise ValueError("Choose existing file indexes.")
                result = asdict(
                    manage(client, [item.hash], body.action, file_indexes=body.file_indexes)[0]
                )
            results.append({**result, "client_id": item.client_id})
            self.updated.pop(item.client_id, None)
        return {"rows": results}
