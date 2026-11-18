"""Owner-facing guided Upload workspace shared by desktop and Web UI."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from torrentlinker.domain import ItemState
from torrentlinker.upload import PROFILES, category_name, default_category
from torrentlinker.web.uploads import UploadForm, Uploads


class UploadWorkspace:
    def __init__(self, uploads: Uploads):
        self.uploads = uploads
        self.setup = uploads.setup

    def state(self):
        rows = []
        store = self.setup.store
        records = store.reseed_records()
        for entry in self.uploads.library.entries:
            if entry.state != ItemState.ORPHAN:
                continue
            cached = store.remembered_candidates(entry.item.path)
            candidates = json.loads(cached) if cached is not None else None
            reason = "unchecked"
            if candidates == []:
                reason = "none"
            elif candidates:
                from torrentlinker.indexer import Candidate
                from torrentlinker.review import candidate_key

                rejected = store.rejections(entry.item.path)
                if all(candidate_key(Candidate(**c)) in rejected for c in candidates):
                    reason = "rejected"
            checked = records.get(str(entry.item.path), {}).get("candidates", [])
            if any(c.get("match") in {"full", "partial"} for c in checked):
                continue
            if checked and all(c.get("match") == "none" for c in checked):
                reason = "rejected"
            rows.append(
                {
                    "path": str(entry.item.path),
                    "name": entry.item.path.name,
                    "size": entry.item.size,
                    "reason": reason,
                    "category": default_category(entry.folder.kind),
                }
            )
        return {
            "sources": rows,
            "drafts": store.local_drafts(),
            "categories": [{"id": k, "name": category_name(k)} for k in PROFILES],
        }

    def request(self, action: str, body: dict):
        stop = threading.Event()
        if action == "state":
            return self.state()
        if action == "browse":
            result = self.setup.browse(body.get("path", ""))
            files = []
            if result["path"]:
                for child in Path(result["path"]).iterdir():
                    if child.is_file():
                        try:
                            files.append(
                                str(self.setup.path_under_root(str(child), directory=False))
                            )
                        except ValueError:
                            continue
            return {**result, "files": sorted(files)[:1000]}
        if action == "remote":
            return self.setup.indexer().drafts()
        if action == "send":
            if body.get("reviewed_revision") != body.get("revision"):
                raise ValueError("Review the saved revision before sending.")
            return self.uploads.send(body["id"], body["revision"], stop, lambda _: None)
        if action == "remove":
            self.setup.store.remove_local_draft(body["id"], body["revision"])
            return {"ok": True}
        if action == "reset":
            from torrentlinker.upload_queue import reset_local

            return reset_local(self.setup.store, body["id"], body["revision"])
        form = UploadForm.model_validate(body.get("form", {}))
        path = body.get("path", "")
        if action == "save":
            return self.uploads.queue(path, form, stop, body.get("id", ""), body.get("revision", 0))
        if action == "prepare":
            return self.uploads.prepare(path, form, stop, stored=bool(body.get("id")))[1]
        if action == "existing":
            from torrentlinker.scan import scan_item
            from torrentlinker.upload import find_existing

            self.uploads.library.check_tree(Path(path), stop)
            item = scan_item(Path(path))
            profile = PROFILES.get(form.category or 0)
            if profile is None:
                raise ValueError("Choose an Upload Category first.")
            profile.inspect(item, self.setup.settings.matching.ignore)
            query = profile.existing_query(item, self.setup.settings.matching.ignore)
            indexer = self.setup.indexer()
            found = find_existing(indexer.search, query, profile.category, indexer.by_tmdb)
            return [{"title": c.title, "size": c.size, "link": c.details_url} for c in found]
        raise ValueError("Unknown Upload workspace action.")
