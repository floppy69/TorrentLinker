"""Read-only c411 availability reports, shared by owner interfaces and agents."""

from __future__ import annotations

import copy
import csv
import io
import json
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from torrentlinker.indexer import KeyRefused, RateLimited
from torrentlinker.zen import is_indexer_torrent

CONFIRM_AFTER = 60.0
CLASSES = ("present", "deleted", "suspect", "unknown")


class TorrentAudit:
    def __init__(self, directory: Path, collect, indexer, *, confirm_after=CONFIRM_AFTER):
        self.directory, self.collect, self.indexer = directory, collect, indexer
        self.confirm_after = confirm_after
        self.lock = threading.RLock()
        self.running: dict[str, threading.Event] = {}
        self._live: dict[str, dict] = {}
        self._published: dict[str, float] = {}
        self._persisted: dict[str, float] = {}

    def _path(self, identifier):
        if (
            not isinstance(identifier, str)
            or len(identifier) != 32
            or any(c not in "0123456789abcdef" for c in identifier)
        ):
            raise ValueError("Unknown audit report.")
        return self.directory / (identifier + ".json")

    def _save(self, report, *, force=False):
        identifier = report["id"]
        now = time.monotonic()
        final = report["status"] != "running"
        with self.lock:
            if not force and not final and now - self._published.get(identifier, -1e9) < 0.25:
                return
            self._live[identifier] = copy.deepcopy(report)
            self._published[identifier] = now
            if not force and not final and now - self._persisted.get(identifier, -1e9) < 30:
                return
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self._path(identifier)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
            self._persisted[identifier] = now
            if final:
                self._live.pop(identifier, None)
                self._published.pop(identifier, None)
                self._persisted.pop(identifier, None)

    def _read(self, identifier):
        with self.lock:
            try:
                report = (
                    copy.deepcopy(self._live[identifier])
                    if identifier in self._live
                    else json.loads(self._path(identifier).read_text(encoding="utf-8"))
                )
            except FileNotFoundError:
                raise ValueError("Unknown audit report.") from None
            if report["status"] == "running" and identifier not in self.running:
                report["status"] = "interrupted"
                for row in report["rows"]:
                    if row["reason"] == "not_checked":
                        row["reason"] = "interrupted"
        return report

    def read(self, identifier, offset=0, limit=100):
        report = self._read(identifier)
        rows = report.pop("rows")
        report["counts"] = {key: sum(r["classification"] == key for r in rows) for key in CLASSES}
        report["clients"] = {
            client: dict(Counter(r["classification"] for r in rows if r["client_id"] == client))
            for client in sorted({r["client_id"] for r in rows})
        }
        report["total"] = len(rows)
        report["rows"] = rows[max(0, offset) : max(0, offset) + min(max(1, limit), 200)]
        return report

    def history(self):
        if not self.directory.exists():
            return []
        reports = []
        for path in sorted(
            self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )[:100]:
            report = self.read(path.stem, limit=1)
            report.pop("rows")
            reports.append(report)
        return reports

    def start(self, clients: list[str], tag: str = ""):
        identifier = uuid.uuid4().hex
        stop = threading.Event()
        report = {
            "id": identifier,
            "created_at": time.time(),
            "status": "running",
            "tag": tag,
            "selected_clients": clients,
            "rows": [],
            "errors": [],
            "checked_hashes": 0,
        }
        with self.lock:
            if self.running:
                raise ValueError("An audit is already running. Read or stop it first.")
            self.running[identifier] = stop
            try:
                self._save(report)
            except Exception:
                self.running.pop(identifier, None)
                self._live.pop(identifier, None)
                self._published.pop(identifier, None)
                self._persisted.pop(identifier, None)
                raise ValueError("The audit report could not be saved.") from None
        threading.Thread(target=self._run, args=(report, stop), daemon=True).start()
        return self.read(identifier)

    def stop(self, identifier):
        with self.lock:
            if event := self.running.get(identifier):
                event.set()
        return self.read(identifier)

    def close(self):
        with self.lock:
            for event in self.running.values():
                event.set()

    @staticmethod
    def _lookup(indexer, infohash, stop):
        try:
            indexer.torrent_json(infohash, retry=False, stop=stop)
            return "present", ""
        except InterruptedError:
            return "unknown", "stopped_before_checking"
        except RateLimited:
            return "unknown", "rate_limited"
        except KeyRefused:
            return "unknown", "key_refused"
        except httpx.TimeoutException:
            return "unknown", "timeout"
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 404:
                return "suspect", "single_404"
            return "unknown", {429: "rate_limited", 401: "key_refused", 403: "key_refused"}.get(
                status, "server_error"
            )
        except httpx.RequestError:
            return "unknown", "network_error"
        except Exception:
            return "unknown", "lookup_failed"

    def _run(self, report, stop):
        try:
            by_hash = {}
            for identifier in report["selected_clients"]:
                if stop.is_set():
                    report["errors"].append(
                        {"client_id": identifier, "reason": "stopped_before_listing"}
                    )
                    continue
                try:
                    name, torrents = self.collect(identifier)
                except Exception:
                    report["errors"].append(
                        {"client_id": identifier, "reason": "client_unavailable"}
                    )
                    continue
                for torrent in torrents:
                    if report["tag"] and report["tag"] not in torrent.tags:
                        continue
                    urls = [torrent.tracker, *torrent.trackers]
                    hosts = sorted(
                        {
                            urlsplit(u if "//" in u else "//" + u).hostname or ""
                            for u in urls
                            if is_indexer_torrent(u, "https://c411.org")
                        }
                    )
                    if not hosts:
                        continue
                    infohash = torrent.hash.lower()
                    row = {
                        "hash": infohash,
                        "name": torrent.name,
                        "client_id": identifier,
                        "client_name": name,
                        "tags": sorted(torrent.tags),
                        "hosts": hosts,
                        "classification": "unknown",
                        "reason": "not_checked",
                        "checked_at": None,
                    }
                    report["rows"].append(row)
                    by_hash.setdefault(infohash, []).append(row)
                self._save(report)
            self._save(report, force=True)  # keep the selected rows even if the process stops
            indexer = self.indexer()
            missing = []
            with indexer.background():
                for infohash, rows in by_hash.items():
                    if stop.is_set():
                        break
                    state, reason = self._lookup(indexer, infohash, stop)
                    if reason == "stopped_before_checking":
                        break
                    stamp = time.time()
                    for row in rows:
                        row.update(classification=state, reason=reason, checked_at=stamp)
                    if state == "suspect":
                        missing.append((infohash, time.monotonic()))
                    report["checked_hashes"] += 1
                    self._save(report)
                for infohash, first in missing:
                    if stop.wait(max(0, self.confirm_after - (time.monotonic() - first))):
                        break
                    state, reason = self._lookup(indexer, infohash, stop)
                    if reason == "stopped_before_checking":
                        break
                    if state == "suspect":
                        state, reason = "deleted", "two_404"
                    for row in by_hash[infohash]:
                        row.update(classification=state, reason=reason, checked_at=time.time())
                    self._save(report)
            report["status"] = "stopped" if stop.is_set() else "complete"
        except Exception:
            report["status"] = "failed"
            report["errors"].append({"reason": "audit_unavailable"})
        finally:
            for row in report["rows"]:
                if row["reason"] == "not_checked":
                    row["reason"] = (
                        "stopped_before_checking" if stop.is_set() else "audit_unavailable"
                    )
            report["finished_at"] = time.time()
            try:
                self._save(report)
            except OSError:
                report["status"] = "failed"
                report["errors"].append({"reason": "report_not_saved"})
                with self.lock:
                    self._live[report["id"]] = copy.deepcopy(report)
            finally:
                with self.lock:
                    self.running.pop(report["id"], None)

    def export(self, identifier, format="json"):
        with self.lock:
            report = self.read(identifier)
            rows = self._read(identifier)["rows"]
        if format == "json":
            return {
                "filename": f"c411-audit-{identifier}.json",
                "content": json.dumps({**report, "rows": rows}, ensure_ascii=False, indent=2),
            }
        if format != "csv":
            raise ValueError("Choose CSV or JSON.")
        output = io.StringIO()
        fields = [
            "client_id",
            "client_name",
            "name",
            "hash",
            "classification",
            "reason",
            "tags",
            "hosts",
            "checked_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            values = {
                key: "; ".join(row[key]) if isinstance(row[key], list) else row[key]
                for key in fields
            }
            # Spreadsheet applications must not execute torrent names as formulas.
            values = {
                key: "'" + value
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                else value
                for key, value in values.items()
            }
            writer.writerow(values)
        return {"filename": f"c411-audit-{identifier}.csv", "content": output.getvalue()}
