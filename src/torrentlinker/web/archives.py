"""Individual archive consent and server extraction through the shared Reseed workflow."""

from __future__ import annotations

import hashlib
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from typing import Any

from torrentlinker.archives import ArchiveError
from torrentlinker.client_limits import disk_renames_elsewhere
from torrentlinker.reseed_layout import needs_disk_rename_review
from torrentlinker.review import (
    CheckedCandidate,
    candidate_key,
    check_candidate,
    remembered_candidates,
    unpack_and_reseed,
)
from torrentlinker.scan import scan_item
from torrentlinker.web.library import Library


class ExtractionCancelled(ValueError):
    pass


class ArchiveReseeds:
    def __init__(self, library: Library):
        self.library = library
        self.setup = library.setup
        self.pending: dict[str, tuple[float, str]] = {}

    def _plan(
        self, path: str, key: str, stop: threading.Event
    ) -> tuple[CheckedCandidate, dict, str]:
        if stop.is_set():
            raise ExtractionCancelled("Archive extraction cancelled.")
        entry = self.library.entry(path)
        self.library.check_tree(entry.item.path, stop)
        # Use a canonical path for both the archive and its new sibling folder.
        archive = self.setup.path_under_root(path, directory=False)
        item = scan_item(archive)
        indexer = self.setup.indexer()
        candidates = remembered_candidates(self.setup.store, indexer, entry.item.path) or []
        rejected = self.setup.store.rejections(entry.item.path)
        candidate = next(
            (c for c in candidates if candidate_key(c) == key and key not in rejected), None
        )
        if candidate is None:
            raise ValueError("Select a current Candidate for this Local Item.")
        checked = check_candidate(indexer, item, candidate, self.setup.settings.matching.rules())
        unpacked, match, meta = checked.unpack, checked.match, checked.meta
        if unpacked is None or match is None or meta is None:
            raise ValueError("This Candidate does not match the archive's contents.")
        self.setup.path_under_root(str(unpacked.item.path.parent))
        if unpacked.item.path.exists() or unpacked.item.path.is_symlink():
            raise ValueError(
                "The extraction destination already exists. Scan and review that folder instead."
            )
        free = shutil.disk_usage(archive.parent).free
        if free < unpacked.size:
            raise ValueError(
                f"Not enough free space: extraction needs {unpacked.size} bytes; "
                f"{free} bytes are available."
            )
        client = self.library.client()
        if needs_disk_rename_review(client) and match.renames:
            raise ValueError(disk_renames_elsewhere(client))
        if client.torrent(meta.infohash) is not None:
            raise ValueError("This torrent already exists in the Torrent Client.")
        stat = archive.stat()
        preview = {
            "archive": str(archive),
            "destination": str(unpacked.item.path),
            "size": unpacked.size,
            "files": len(unpacked.item.files),
            "free": free,
            "match": "full" if match.is_full else "partial",
            "missing": len(match.absent),
            "coverage": match.coverage,
            "title": candidate.title,
        }
        # Changing the input, comparison, client configuration or destination requires a new review.
        identity = repr(
            (
                path,
                key,
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
                unpacked,
                match,
                hashlib.sha256(meta.data).hexdigest(),
                self.setup.snapshot(),
            )
        )
        return checked, preview, identity

    def preview(self, path: str, key: str, stop: threading.Event) -> dict:
        _, preview, identity = self._plan(path, key, stop)
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if v[0] > now}
        if len(self.pending) >= 100:
            self.pending.clear()
        token = secrets.token_urlsafe(32)
        self.pending[token] = (now + 300, identity)
        return {**preview, "token": token}

    def status(self, infohash: str) -> dict:
        """Observe verification owned by the existing monitor; never start or retry here."""
        from torrentlinker.reseed import CHECKING_STATES, PARTIAL, TAG, VERIFYING

        torrent = self.library.client().torrent(infohash)
        if torrent is None:
            return {"hash": infohash, "status": "needs-review"}
        pending = self.setup.store.verification(infohash)
        verified = TAG in torrent.tags and (torrent.progress >= 1 or PARTIAL in torrent.tags)
        if pending or VERIFYING in torrent.tags or torrent.state in CHECKING_STATES:
            state = "verifying"
        elif verified and torrent.state in {"uploading", "stalledUP", "forcedUP", "queuedUP"}:
            state = "seeding"
        elif verified:
            state = "verified-stopped"
        else:
            state = "needs-review"
        return {"hash": infohash, "status": state, "partial": PARTIAL in torrent.tags}

    def start(
        self,
        path: str,
        key: str,
        token: str,
        stop: threading.Event,
        progress: Callable[[Any], None],
    ) -> dict:
        record = self.pending.pop(token, None)
        if record is None or record[0] <= time.monotonic():
            raise ValueError("Review and confirm this archive before extracting it.")
        checked, preview, identity = self._plan(path, key, stop)
        if record[1] != identity:
            raise ValueError("The archive or its settings changed. Review and confirm it again.")

        def report(done: int, total: int) -> None:
            if stop.is_set():
                raise ExtractionCancelled("Archive extraction cancelled.")
            progress(
                {
                    "stage": "extracting",
                    "done": done,
                    "total": total,
                    "destination": preview["destination"],
                }
            )

        def begin_reseed() -> None:
            # The job lock serializes this progress transition with cancel requests.
            # A cancellation accepted before the transition still prevents submission.
            progress(
                {
                    "stage": "verifying",
                    "cancellable": False,
                    "done": preview["size"],
                    "total": preview["size"],
                }
            )
            if stop.is_set():
                raise ExtractionCancelled("Archive extraction cancelled.")

        try:
            infohash, local = unpack_and_reseed(
                self.library.client(),
                self.setup.store,
                checked,
                self.setup.settings.matching.rules(),
                report,
                before_reseed=begin_reseed,
            )
        except ExtractionCancelled:
            return {"cancelled": True}
        except ArchiveError as error:
            raise ValueError(str(error)) from error
        return {
            "hash": infohash,
            "path": str(local.path),
            "archive": preview["archive"],
            "status": "verifying",
        }
