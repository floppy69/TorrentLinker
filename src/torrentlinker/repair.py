"""Opt-in repair of an independent copy; ordinary Reseeds never use this service.

No recovery path starts a torrent. Ambiguous sends require checking the client.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path

from torrentlinker.domain import LocalItem
from torrentlinker.indexer import Candidate
from torrentlinker.provenance import identity, safe_torrent, verify_pieces
from torrentlinker.qbit import Qbit

MIB = 1024 * 1024
_LOCK = threading.RLock()
STOPPED = {"pausedDL", "pausedUP", "stoppedDL", "stoppedUP"}
CHECKING = {"checkingDL", "checkingUP", "checkingResumeData", "queuedForChecking"}


class Repairs:
    def __init__(self, directory: Path, client_id: str):
        self.directory = directory / "repairs"
        self.client_id = client_id

    def _db(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.directory / "state.sqlite"
        db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        db.execute("CREATE TABLE IF NOT EXISTS repair (id TEXT PRIMARY KEY, body TEXT)")
        return db

    def _save(self, row):
        with closing(self._db()) as db, db:
            db.execute("INSERT OR REPLACE INTO repair VALUES (?, ?)", (row["id"], json.dumps(row)))

    def _get(self, identifier):
        with closing(self._db()) as db:
            record = db.execute("SELECT body FROM repair WHERE id=?", (identifier,)).fetchone()
        if record is None:
            raise ValueError("Repair preview expired. Diagnose the Candidate again.")
        row = json.loads(record[0])
        if row["client_id"] != self.client_id:
            raise ValueError("Select the Torrent Client used for this repair.")
        return row

    def _public(self, row):
        return {
            k: v
            for k, v in row.items()
            if k
            not in {
                "data",
                "identities",
                "piece_states",
                "copy_identity",
                "claim",
            }
        }

    def diagnose(
        self, item: LocalItem, candidate: Candidate, data: bytes, stop: threading.Event
    ) -> dict:
        meta = safe_torrent(data)
        if not item.path.is_file() or len(meta.files) != 1:
            raise ValueError("Experimental repair supports one local file and one target file.")
        if candidate.infohash and candidate.infohash.lower() != meta.infohash:
            raise ValueError("Candidate identity differs from its torrent metadata.")
        name, size = next(iter(meta.files.items()))
        source = identity(item.path)
        if abs(size - source[2]) > min(size * 0.01, 50 * MIB):
            raise ValueError("File size differs by more than 1% or 50 MiB.")
        result = verify_pieces(meta, {name: item.path}, stop)
        eligible = (
            result["verified_bytes"] >= 0.9 * size
            and 0 < result["missing_bytes"] <= 500 * MIB
            and candidate.seeders >= 2
        )
        row = {
            "id": uuid.uuid4().hex,
            "client_id": self.client_id,
            "hash": meta.infohash,
            "source": str(item.path),
            "name": meta.name,
            "target_file": name,
            "seeders": candidate.seeders,
            "size_difference": abs(size - source[2]),
            "eligible": eligible,
            "status": "awaiting-confirmation" if eligible else "ineligible",
            "data": base64.b64encode(data).decode(),
            **result,
        }
        self._save(row)
        return self._public(row)

    def prepare(
        self,
        identifier: str,
        destination: Path,
        client: Qbit,
        stop: threading.Event,
        *,
        experimental: bool = False,
    ) -> dict:
        if not experimental:
            raise ValueError("Opt in to experimental repair before preparing a copy.")
        with _LOCK:
            row = self._get(identifier)
            if row["status"] != "awaiting-confirmation" or not row["eligible"]:
                raise ValueError("Diagnose again before preparing a repair copy.")
            source = Path(row["source"])
            if identity(source) != row["identities"][str(source)]:
                raise ValueError("Source changed. Diagnose again.")
            if client.torrent(row["hash"]) is not None:
                raise ValueError("This torrent already exists in the Torrent Client.")
            if not destination.is_dir() or any(
                p.is_symlink() for p in (destination, *destination.parents)
            ):
                raise ValueError("Choose an accessible destination without symbolic links.")
            if shutil.disk_usage(destination).free < row["target_bytes"]:
                raise ValueError("Not enough space for an independent repair copy.")
            root = destination / ("torrentlinker-repair-" + row["id"])
            root.mkdir(mode=0o700)  # exclusive, never reuse a user directory
            target = root / row["target_file"]
            row.update(status="preparing", destination=str(root), copy=str(target))
            self._save(row)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open("rb") as reader, target.open("xb") as writer:
                    remaining = row["target_bytes"]
                    while remaining:
                        if stop.is_set():
                            raise ValueError("Copy cancelled. The original is unchanged.")
                        chunk = reader.read(min(remaining, MIB))
                        if not chunk:
                            break
                        writer.write(chunk)
                        remaining -= len(chunk)
                    writer.truncate(row["target_bytes"])
                    writer.flush()
                    os.fsync(writer.fileno())
                if identity(source) != row["identities"][str(source)]:
                    raise ValueError("Source changed while copying. Diagnose again.")
                data = base64.b64decode(row["data"])
                result = verify_pieces(safe_torrent(data), {row["target_file"]: target}, stop)
                if result["piece_states"] != row["piece_states"]:
                    raise ValueError("Copy verification differs from the preview.")
                row["copy_identity"] = identity(target)
                # Journal before the external add. An uncertain result is never retried.
                row["check_requested_at"] = time.time()
                row["status"] = "adding"
                self._save(row)
                client.add(data, str(root), ["torrentlinker-repair"])
                client.recheck(row["hash"])
                row["status"] = "checking"
                self._save(row)
            except Exception:
                row["status"] = "needs-review"
                self._save(row)
                raise
            return self._public(row)

    def refresh(self, identifier: str, client: Qbit) -> dict:
        with _LOCK:
            row = self._get(identifier)
            torrent = client.torrent(row["hash"]) if row.get("copy") else None
            if row["status"] in {"checking", "ready"}:
                if torrent is None:
                    row["status"] = "needs-review"
                elif torrent.state in CHECKING:
                    row["check_seen"] = True
                    row["status"] = "checking"
                elif torrent.state not in STOPPED:
                    client.pause(row["hash"])
                    row["status"] = "needs-review"
                elif client.piece_states(row["hash"]) == row["piece_states"]:
                    row["status"] = "ready"
                else:
                    # A newly submitted recheck may not have started yet. Readiness is
                    # revoked immediately; pending checks get a bounded grace period.
                    failed = (
                        row["status"] == "ready"
                        or row.get("check_seen")
                        or time.time() - row.get("check_requested_at", 0) >= 60
                    )
                    row["status"] = "needs-review" if failed else "checking"
                self._save(row)
            elif row["status"] == "downloading" and torrent and torrent.progress >= 1:
                row["status"] = "completed"
                self._save(row)
            return self._public(row)

    def start(self, identifier: str, confirmation: str, client: Qbit) -> dict:
        with _LOCK:
            row = self._get(identifier)
            if confirmation != identifier or row["status"] != "ready":
                raise ValueError("Refresh the completed check and confirm this repair first.")
            if self.refresh(identifier, client)["status"] != "ready":
                raise ValueError("The Torrent Client has not completed verification.")
            if identity(Path(row["copy"])) != row["copy_identity"]:
                raise ValueError("Repair copy changed. Do not start; inspect the Torrent Client.")
            # The original may be shared. Only the new exclusive copy is ever downloaded into.
            torrent = client.torrent(row["hash"])
            if (
                torrent is None
                or Path(torrent.save_path) != Path(row["destination"])
                or torrent.files != {row["target_file"]: row["target_bytes"]}
            ):
                raise ValueError("Torrent destination changed. Do not start this repair.")
            row["status"] = "starting"
            self._save(row)
            try:
                client.start(row["hash"])
            except Exception:
                row["status"] = "needs-review"
                self._save(row)
                raise
            row["status"] = "downloading"
            self._save(row)
            return self._public(row)

    def rows(self) -> list[dict]:
        with closing(self._db()) as db:
            rows = [
                json.loads(r[0]) for r in db.execute("SELECT body FROM repair ORDER BY rowid DESC")
            ]
        return [self._public(row) for row in rows if row["client_id"] == self.client_id]
