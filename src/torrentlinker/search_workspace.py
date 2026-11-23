"""Shared Search and download queue boundary for desktop and Web."""

from __future__ import annotations

from typing import Any

from torrentlinker.category_tags import category_path
from torrentlinker.download_queue import entries
from torrentlinker.web.jobs import Jobs
from torrentlinker.web.operations import JobRequest, Operations


class SearchWorkspace:
    def __init__(self, operations: Operations, jobs: Jobs):
        self.operations = operations
        self.setup = operations.setup
        self.jobs = jobs
        from torrentlinker.poster_cache import shared_poster_cache

        self.posters = shared_poster_cache(self.setup.path.parent / "posters")

    def estimates(self, rows, candidates):
        from urllib.parse import urlsplit

        from torrentlinker.seeding import seeding
        from torrentlinker.zen import ZenTorrent, added_values, note

        settings = self.setup.settings
        catalogue = {
            r.infohash: r
            for r in self.setup.store.catalogue([t.hash.lower() for t in self.operations.observed])
        }
        view = seeding(
            settings.zen,
            self.operations.observed,
            settings.indexer.url,
            settings.uploads,
            catalogue=catalogue,
            categories=settings.indexer_categories,
        )
        current = {r.torrent.hash.lower(): r for r in view.rows if r.zen is not None}
        prospective = [
            ZenTorrent(c.size, c.seeders + 1, category=c.categories[-1] if c.categories else None)
            for c, origin in candidates
        ]
        values = added_values(settings.zen, prospective, view.active)
        for row, (candidate, origin), torrent, value in zip(
            rows, candidates, prospective, values, strict=True
        ):
            existing = current.get((candidate.infohash or "").lower())
            row["zen"] = existing.zen if existing else value
            row["note"] = existing.note if existing else note(settings.zen.zen_class, torrent)
            if urlsplit(origin).hostname != "c411.org":
                row["zen"] = row["note"] = None
        return rows

    def run(self, request, stop, progress):
        result = self.operations.run(request, stop, progress)
        if request.kind == "search":
            from torrentlinker.queue_selection import fingerprint

            self.estimates(
                result["rows"],
                [
                    (self.operations.candidates[row["hash"]], self.setup.indexer().url)
                    for row in result["rows"]
                ],
            )
            result["selection_fingerprint"] = fingerprint(result["rows"])
        return result

    def request(self, action: str, body: dict[str, Any]) -> Any:
        if action == "score-profile":
            from torrentlinker.release_score.preferences import Preferences
            from torrentlinker.settings_workspace import SettingsWorkspace

            with self.setup.lock:
                preferences = Preferences.model_validate(
                    self.setup.settings.release_score
                ).model_dump(by_alias=True)
                preferences["active"] = body.get("active")
                SettingsWorkspace(self.setup).save("release_score", preferences)
            return {"ok": True}
        if action in {"detail", "detail-image", "score-details"}:
            from torrentlinker.details_workspace import DetailsWorkspace

            indexer = self.setup.indexer()
            workspace = getattr(self.operations, "detail_workspace", None)
            if workspace is None or workspace.indexer is not indexer:
                workspace = DetailsWorkspace(indexer)
                self.operations.detail_workspace = workspace
            if action in {"detail", "score-details"}:
                from torrentlinker.release_score.service import details_score

                identifier = body.get("hash", "")
                if action == "score-details":
                    document = dict(workspace.documents.get(identifier, {}))
                else:
                    document = dict(workspace.load(identifier))
                candidate = self.operations.candidates.get(identifier)
                document["release_score"] = details_score(
                    document,
                    self.setup.settings.release_score,
                    title=candidate.title if candidate else "",
                    size=candidate.size if candidate else 0,
                    listing=self.operations.score_listings.get(identifier),
                )
                return document if action == "detail" else document["release_score"]
            return workspace.image(body.get("hash", ""), body.get("position", -1))
        if action == "poster":
            import base64

            data = self.posters.fetch(str(body.get("url", "")))
            if data is None:
                return {"src": None}
            image_kind = (
                "png" if data[:4] == b"\x89PNG" else "webp" if data[8:12] == b"WEBP" else "jpeg"
            )
            return {
                "src": "data:image/" + image_kind + ";base64," + base64.b64encode(data).decode()
            }
        if action == "folders":
            request = JobRequest(kind="enqueue", hashes=body.get("hashes", []))
            categories = self.operations.enqueue_categories(request)
            rows = []
            for category in dict.fromkeys(categories.values()):
                if category is None:
                    raise ValueError("Torrent category is unknown. Search again before queueing.")
                path = self.setup.download_folder(category)
                rows.append(
                    {
                        "category": category,
                        "label": " / ".join(
                            self.setup.settings.indexer_categories[c].name
                            for c in category_path(category, self.setup.settings.indexer_categories)
                            if c in self.setup.settings.indexer_categories
                        ),
                        "path": str(path) if path else "",
                    }
                )
            return {"folders": rows, "missing": [row for row in rows if not row["path"]]}
        if action == "configure-folder":
            with self.setup.lock:
                missing = self.request("folders", body)["missing"]
                category = body.get("category")
                if category not in [row["category"] for row in missing]:
                    raise ValueError(
                        "This category already has a folder or is outside the selection."
                    )
                return self.setup.configure_download_folder(body["path"], category, save=True)
        if action == "start":
            from torrentlinker.queue_selection import queue_rows

            with self.jobs.lock:
                if self.request("state", {})["active"]:
                    raise ValueError("The download queue is already running.")
                keys = set(body["keys"]) if "keys" in body else None
                rows = [
                    row
                    for row in queue_rows(self.setup)
                    if row["status"] == "queued" and (keys is None or row["key"] in keys)
                ]
                if not rows or len(rows) > 1000:
                    raise ValueError("Select between 1 and 1000 queued torrents.")
                request = JobRequest(
                    kind="send-queue", hashes=[str(row["hash"]) for row in rows], queue_binding=rows
                )
                return {
                    "job": self.jobs.submit(
                        "search-send-queue",
                        lambda stop, progress: self.run(request, stop, progress),
                        client_id=self.setup.store.client_id,
                        parameters=request.model_dump(),
                    )
                }
        if action == "pause":
            active = self.request("state", {})["active"]
            if active:
                self.jobs.cancel(active["id"])
            return {"ok": True}
        if action == "browse":
            return self.setup.browse(body.get("path", ""))
        if action == "job":
            kind = body.get("kind")
            allowed = {
                "enqueue": {"hashes"},
                "search": {
                    "query",
                    "category",
                    "page",
                    "filters",
                    "indexer_search",
                    "search_listing",
                },
                "search-options": {"category"},
            }
            if kind not in allowed or set(body) - allowed[kind] - {"kind"}:
                raise ValueError("Invalid Search job.")
            request = JobRequest(**body)
            identifier = self.jobs.submit(
                "search-" + request.kind,
                lambda stop, progress: self.run(request, stop, progress),
                client_id=self.setup.store.client_id,
                parameters=request.model_dump(),
            )
            return {"job": identifier}
        if action == "job-status":
            result = self.jobs.get(body["job"])
            if result["client_id"] != self.setup.store.client_id or not result["kind"].startswith(
                "search-"
            ):
                raise ValueError("This job belongs to another workspace.")
            return result
        if action == "state":
            sends = [
                job
                for job in self.jobs.list()
                if job["client_id"] == self.setup.store.client_id
                and job["kind"] == "search-send-queue"
            ]
            active = next((job for job in sends if job["status"] in {"queued", "running"}), None)
            queued_rows = self.operations.queue()
            snapshot = {e.key: e for e in entries(self.setup.store)}
            queued_rows = [row for row in queued_rows if row["key"] in snapshot]
            self.estimates(
                queued_rows,
                [
                    (snapshot[row["key"]].candidate, snapshot[row["key"]].indexer_url)
                    for row in queued_rows
                ],
            )
            hashes = JobRequest(kind="search", hashes=body.get("hashes", [])).hashes
            candidates = self.operations.candidates
            search_rows: list[dict[str, Any]] = [{"hash": h} for h in hashes if h in candidates]
            self.estimates(
                search_rows,
                [(candidates[row["hash"]], self.setup.settings.indexer.url) for row in search_rows],
            )
            known = {t.hash.lower(): "client" for t in self.operations.observed}
            for entry in snapshot.values():
                known.setdefault(entry.candidate.infohash or "", "queued")
            for row in search_rows:
                row["known"] = known.get(row["hash"], "")
            import hashlib
            import json

            from torrentlinker.release_score.estimate import estimate
            from torrentlinker.release_score.preferences import Preferences
            from torrentlinker.release_score.service import mark_best, score

            score_preferences = Preferences.model_validate(self.setup.settings.release_score)
            for row in search_rows:
                candidate = candidates[row["hash"]]
                row["release_score"] = score(
                    estimate(
                        candidate.title,
                        candidate.size,
                        self.operations.score_listings.get(row["hash"], {}),
                    ),
                    self.setup.settings.release_score,
                )
            mark_best(search_rows)
            return {
                "score_revision": hashlib.sha256(
                    json.dumps(self.setup.settings.release_score, sort_keys=True).encode()
                ).hexdigest(),
                "score_profiles": list(score_preferences.profiles),
                "score_active": score_preferences.active,
                "rows": queued_rows,
                "active": active,
                "last": sends[0] if sends else None,
                "search": search_rows,
            }
        if action in {"retry", "remove", "clear-sent"}:
            with self.jobs.lock:
                if self.jobs.active():
                    raise ValueError("Wait for the current operation before editing the queue.")
                self.setup.store.reconcile_downloads(body.get("keys", [])[:1000], action)
            return {"ok": True}
        raise ValueError("Unknown Search operation.")
