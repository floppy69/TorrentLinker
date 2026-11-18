"""Independent, resource-limited reseed pipelines shared by Qt and Web UI."""

from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import TYPE_CHECKING

from torrentlinker.disk_rename import verify_local_data
from torrentlinker.paths import PathMapper
from torrentlinker.qbit import AlreadyInClient
from torrentlinker.reseed import CHECKING_STATES, TAG
from torrentlinker.reseed_links import prepare_links, validate_links
from torrentlinker.review import candidate_key, check_candidate, remembered_candidates

if TYPE_CHECKING:
    from torrentlinker.web.library import Library

LINK_TAG = "torrentlinker:links"
_WORKSPACE_LOCK = threading.Lock()
STAGES = ("find", "candidates", "links", "verify", "incomplete", "seeding")


class RunStopped(Exception):
    pass


def checkpoint(stop: threading.Event) -> None:
    paused = getattr(stop, "paused", None)
    while paused is not None and paused.is_set() and not stop.wait(0.1):
        pass
    if stop.is_set():
        raise RunStopped()


class ReseedWorkspace:
    def __init__(self, library: Library):
        self.library = library
        self.setup = library.setup
        self._control_lock = threading.RLock()
        self._paused_paths: set[str] = set()
        self._added_paths: list[str] = []
        self._choices: dict[str, str] = {}
        self._active_paths: set[str] = set()
        self._scan_folders: list[str] | None = None
        self._running = False
        self._scan_requested = False

    def rows(self) -> list[dict]:
        records = self.setup.store.reseed_records()
        return [
            {
                **row,
                "stage": "seeding" if row["state"] == "seeded" else "find",
                **records.get(row["path"], {}),
            }
            for row in self.library.rows()
        ]

    def control(self, paths: list[str], *, paused: bool) -> None:
        """Pause/resume individual items at operation boundaries."""
        with self._control_lock:
            if paused:
                self._paused_paths.update(paths)
            else:
                self._paused_paths.difference_update(paths)

    def paused_paths(self) -> set[str]:
        with self._control_lock:
            return set(self._paused_paths)

    def enqueue(self, paths: list[str], key: str = "") -> None:
        """Let newly discovered items join an owner's active run."""
        with self._control_lock:
            if not self._running:
                raise ValueError("Start the reseed workflow first.")
            if key:
                if len(paths) != 1:
                    raise ValueError("Choose a candidate for one item at a time.")
                if paths[0] in self._active_paths:
                    raise ValueError("Wait for this item to finish its current operation.")
                self._choices[paths[0]] = key
            self._added_paths.extend(paths)

    def request_scan(self, folders: list[str] | None = None) -> None:
        """Scan in the disk lane and admit discoveries to the current run."""
        with self._control_lock:
            if not self._running:
                raise ValueError("Start the reseed workflow first.")
            self._scan_requested = True
            self._scan_folders = folders

    def run(self, paths: list[str], action: str, root: str, stop, report, key: str = "") -> dict:
        if action not in {"all", "find", "compare", "prepare", "verify", "seed", "refresh"}:
            raise ValueError("Unknown reseed action.")
        if action == "refresh":
            return self.refresh_client()
        if not paths:
            raise ValueError("Select Local Items first.")
        if not _WORKSPACE_LOCK.acquire(blocking=False):
            raise ValueError("Another reseed workspace run is active.")
        pending = deque(dict.fromkeys(paths))
        known = set(pending)
        resources = {"search": threading.Semaphore(2), "disk": threading.Semaphore(1)}
        lock = threading.RLock()
        active: dict[str, dict] = {}
        result: dict = {"done": 0, "total": len(pending), "errors": [], "seeded": 0}
        self._running = True
        if key and len(paths) == 1:
            self._choices[paths[0]] = key

        def emit(progress):
            with lock:
                path, phase = progress["path"], progress["phase"]
                if phase != "item-complete":
                    active[path] = {"phase": phase, "fraction": progress.get("fraction")}
                value = {
                    **progress,
                    **result,
                    "active": dict(active),
                    "paused_paths": sorted(self.paused_paths()),
                }
            report(value)

        def emit_scan(progress):
            if progress.get("discovered"):
                with self._control_lock:
                    self._added_paths.extend(p for p in progress["discovered"] if p not in known)
            emit({"path": "", "phase": "scan", "scan": progress, "rows": self.rows()})

        records = self.setup.store.reseed_records()
        seeded_paths = {r["path"] for r in self.library.rows() if r["state"] == "seeded"}
        futures: dict[Future, tuple[str, str]] = {}
        try:
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix="reseed-step") as pool:
                while True:
                    with self._control_lock:
                        for path in self._added_paths:
                            if path not in pending and path not in {p for p, _ in futures.values()}:
                                pending.append(path)
                                if path in known:
                                    result["done"] = max(0, result["done"] - 1)
                                else:
                                    known.add(path)
                                    result["total"] += 1
                        self._added_paths.clear()
                        if not pending and not futures and not self._scan_requested:
                            self._running = False
                            break
                    if stop.is_set():
                        result["cancelled"] = True
                        pending.clear()
                        self._scan_requested = False
                    used = {"search": 0, "disk": 0}
                    for _, resource in futures.values():
                        used[resource] += 1
                    with self._control_lock:
                        if (
                            self._scan_requested
                            and used["disk"] == 0
                            and not getattr(stop, "paused", threading.Event()).is_set()
                        ):
                            self._scan_requested = False
                            used["disk"] += 1
                            future = pool.submit(
                                self.library.scan,
                                stop,
                                lambda p: emit_scan(p),
                                self._scan_folders,
                            )
                            futures[future] = ("", "disk")
                    for _ in range(len(pending)):
                        path = pending.popleft()
                        if (
                            getattr(stop, "paused", threading.Event()).is_set()
                            or path in self._paused_paths
                        ):
                            pending.append(path)
                            continue
                        if used["search"] == 2 and used["disk"] == 1:
                            pending.appendleft(path)
                            break
                        record = records.get(path) or {
                            "stage": "seeding" if path in seeded_paths else "find"
                        }
                        choice = self._choices.get(path, "")
                        if (
                            action == "all"
                            and not choice
                            and record.get("stage") in {"incomplete", "seeding"}
                        ):
                            result["done"] += 1
                            continue
                        step = (
                            "compare"
                            if choice
                            else (self._remaining(record)[0] if action == "all" else action)
                        )
                        resource = "search" if step in {"find", "compare"} else "disk"
                        if used[resource] >= (2 if resource == "search" else 1):
                            pending.append(path)
                            continue
                        used[resource] += 1
                        with self._control_lock:
                            self._active_paths.add(path)
                        future = pool.submit(
                            self._run_item, [path], step, root, stop, emit, choice, resources
                        )
                        self._choices.pop(path, None)
                        futures[future] = (path, resource)
                    if not futures:
                        if pending:
                            stop.wait(0.1)
                        continue
                    completed, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                    for future in completed:
                        path, _ = futures.pop(future)
                        with self._control_lock:
                            self._active_paths.discard(path)
                        try:
                            value = future.result()
                        except Exception as error:
                            message = self.setup.secrets.redact(str(error))
                            value = {"seeded": 0, "errors": [{"path": path, "message": message}]}
                            if not path:
                                result["errors"].extend(value["errors"])
                                emit({"path": "", "phase": "scan-error", "error": message})
                        if not path:
                            active.pop("", None)
                            for row in self.library.rows():
                                if row["path"] not in known and row["state"] != "seeded":
                                    known.add(row["path"])
                                    pending.append(row["path"])
                                    result["total"] += 1
                            emit(
                                {
                                    "path": "",
                                    "phase": "item-complete",
                                    "rows": self.rows(),
                                    "scan_complete": True,
                                }
                            )
                            continue
                        with lock:
                            active.pop(path, None)
                            result["seeded"] += value["seeded"]
                            result["errors"].extend(value["errors"])
                            record = self.setup.store.reseed_record(path)
                            records[path] = record
                            if (
                                action == "all"
                                and not value["errors"]
                                and not stop.is_set()
                                and record.get("stage") not in {"incomplete", "seeding"}
                            ):
                                pending.append(path)
                            else:
                                result["done"] += 1
                        emit({"path": path, "phase": "item-complete", "rows": self.rows()})
        finally:
            self._running = False
            self._scan_requested = False
            self._paused_paths.clear()
            self._added_paths.clear()
            self._choices.clear()
            self._active_paths.clear()
            _WORKSPACE_LOCK.release()
        if stop.is_set():
            result["cancelled"] = True
        return {**result, "rows": self.rows()}

    def _run_item(self, paths, action, root, stop, report, key, resources) -> dict:
        if action not in {"all", "find", "compare", "prepare", "verify", "seed", "refresh"}:
            raise ValueError("Unknown reseed action.")
        if action == "refresh":
            return self.refresh_client()
        if not paths:
            raise ValueError("Select Local Items from the reseed board first.")
        result: dict = {"done": 0, "total": len(paths), "errors": [], "seeded": 0}
        try:
            for path in dict.fromkeys(paths):
                checkpoint(stop)
                row = next((r for r in self.rows() if r["path"] == path), None)
                if row is None:
                    raise ValueError("Scan the Library and select a current Local Item.")
                if row["stage"] == "seeding":
                    result["done"] += 1
                    continue
                record = self.setup.store.reseed_record(path) or {"stage": "find"}

                def save(path=path, record=record):
                    event = {
                        "phase": record.get("status") or record["stage"],
                        "error": record.get("error", ""),
                    }
                    events = record.setdefault("events", [])
                    if not events or any(events[-1].get(k) != v for k, v in event.items()):
                        events.append({**event, "at": time.time()})
                        del events[:-200]
                    self.setup.store.save_reseed_record(path, record)

                def progress(phase: str, path=path, **extra):
                    report({**result, "path": path, "phase": phase, **extra})

                try:
                    steps = [action] if action != "all" else self._remaining(record)
                    for step in steps:
                        checkpoint(stop)
                        resource = resources["search" if step in {"find", "compare"} else "disk"]
                        while not resource.acquire(timeout=0.1):
                            checkpoint(stop)
                        try:
                            progress(step)
                            record.pop("error", None)
                            if step == "find":
                                candidates = self.library.review(path, stop)
                                if not candidates:
                                    candidates = self.library.check(path, stop, lambda _: None)
                                record.update(stage="candidates", candidates=candidates)
                                if not candidates:
                                    record.update(
                                        stage="find",
                                        error="No candidate found. Try another search.",
                                    )
                                    result["errors"].append(
                                        {"path": path, "message": record["error"]}
                                    )
                                    save()
                                    break
                            elif step == "compare":
                                if record.get("destination") and self.library.client().torrent(
                                    record["hash"]
                                ):
                                    raise ValueError(
                                        "Remove the existing torrent without deleting data before "
                                        "changing its prepared layout."
                                    )
                                candidates = self.library.review(path, stop)
                                for candidate in candidates:
                                    checkpoint(stop)
                                    candidates = self.library.review(
                                        path, stop, key=candidate["key"], action="check"
                                    )
                                eligible = [
                                    c
                                    for c in candidates
                                    if c["match"] == "full"
                                    and not c["archive"]
                                    and all(f["local"] for f in c["files"])
                                ]
                                if key:
                                    eligible = [c for c in eligible if c["key"] == key]
                                record["candidates"] = candidates
                                if len(eligible) != 1:
                                    record.update(
                                        stage="candidates" if eligible else "incomplete",
                                        error="Choose one full Candidate."
                                        if eligible
                                        else (
                                            "Incomplete or archived content "
                                            "needs a separate review."
                                        ),
                                    )
                                    result["errors"].append(
                                        {"path": path, "message": record["error"]}
                                    )
                                    save()
                                    break
                                record.update(stage="links", key=eligible[0]["key"])
                                # Old link folders remain untouched; a new comparison can
                                # select a different torrent after the previous one is removed.
                                for old in ("destination", "files", "hash", "status"):
                                    record.pop(old, None)
                            elif step == "prepare":
                                if record.get("stage") != "links":
                                    raise ValueError("Compare and choose a full Candidate first.")
                                entry, checked = self._checked(path, record, stop)
                                destination = self.setup.path_under_root(root)
                                assert checked.meta and checked.match
                                layout = prepare_links(
                                    destination,
                                    entry,
                                    checked.meta,
                                    checked.match,
                                    PathMapper(self.setup.settings.path_mappings),
                                    [f.path for f in self.setup.settings.library_folders],
                                )
                                record.update(layout, stage="verify", status="prepared")
                            elif step == "verify":
                                self._verify(path, record, stop, progress, save)
                            elif step == "seed":
                                if record.get("status") != "verified":
                                    raise ValueError("Verify every file before seeding.")
                                validate_links(record)
                                client = self.library.client()
                                torrent = self._owned(client, record)
                                if torrent.progress < 1 or torrent.state in CHECKING_STATES:
                                    raise ValueError(
                                        "The Torrent Client no longer reports complete data. "
                                        "Verify again."
                                    )
                                checkpoint(stop)
                                client.remove_tags(record["hash"], ["torrentlinker:link-checking"])
                                client.start(record["hash"])
                                record.update(stage="seeding", status="seeding")
                                result["seeded"] += 1
                            save()
                            progress(step, rows=self.rows())
                        finally:
                            resource.release()
                except RunStopped:
                    save()
                    raise
                except Exception as error:
                    # Use the same credential redaction as other UI operations.
                    record["error"] = self.setup.secrets.redact(str(error))
                    save()
                    result["errors"].append({"path": path, "message": record["error"]})
                result["done"] += 1
        except RunStopped:
            result["cancelled"] = True
        return {**result, "rows": self.rows()}

    def refresh_client(self) -> dict:
        """Reconcile saved progress after an external client removal or file change."""
        with _WORKSPACE_LOCK:
            client = self.library.client()
            torrents = {t.hash: t for t in client.torrents(with_files=False)}
            for path, record in self.setup.store.reseed_records().items():
                if record.get("status") not in {"verified", "seeding", "checking", "adding"}:
                    continue
                torrent = torrents.get(record.get("hash", ""))
                try:
                    validate_links(record)
                    if torrent is None:
                        raise ValueError(
                            "Torrent removed from the client. Verify again to continue."
                        )
                    if (
                        LINK_TAG not in torrent.tags
                        or str(torrent.save_path) != record["destination"]
                    ):
                        raise ValueError(
                            "The torrent uses another location. Review it in the client."
                        )
                    if torrent.progress < 1:
                        raise ValueError(
                            "The client no longer reports complete data. Verify again."
                        )
                except (OSError, ValueError) as error:
                    record.update(stage="verify", status="prepared", error=str(error))
                    self.setup.store.save_reseed_record(path, record)
            return {"done": 0, "total": 0, "seeded": 0, "errors": [], "rows": self.rows()}

    @staticmethod
    def _remaining(record: dict) -> list[str]:
        if record.get("stage") == "incomplete":
            return []
        steps = ["find", "compare", "prepare", "verify", "seed"]
        first = {
            "find": "find",
            "candidates": "compare",
            "links": "prepare",
            "verify": "seed" if record.get("status") == "verified" else "verify",
            "seeding": "seed",
        }[record["stage"]]
        return steps[steps.index(first) :]

    def _checked(self, path, record, stop):
        entry = self.library.scan_entry(self.library.entry(path), stop)
        indexer = self.setup.indexer()
        candidates = remembered_candidates(self.setup.store, indexer, entry.path) or []
        rejected = self.setup.store.rejections(entry.path)
        candidate = next(
            (
                c
                for c in candidates
                if candidate_key(c) == record.get("key") and candidate_key(c) not in rejected
            ),
            None,
        )
        if candidate is None:
            raise ValueError("The Candidate changed. Search and compare this item again.")
        checked = check_candidate(indexer, entry, candidate, self.setup.settings.matching.rules())
        if not checked.meta or not checked.match or checked.match.unwanted or checked.unpack:
            raise ValueError("Every torrent file must be present before preparing links.")
        if record.get("hash") and record["hash"] != checked.meta.infohash:
            raise ValueError("The torrent metadata changed. Compare this item again.")
        return entry, checked

    @staticmethod
    def _owned(client, record):
        torrent = client.torrent(record["hash"])
        if (
            torrent is None
            or LINK_TAG not in torrent.tags
            or torrent.save_path != Path(record["destination"])
        ):
            raise ValueError(
                "This torrent is absent or uses another location. Check the Torrent Client."
            )
        return torrent

    def _verify(self, path, record, stop, progress, save):
        if record.get("stage") != "verify":
            raise ValueError("Prepare links before verification.")
        validate_links(record)
        item, checked = self._checked(path, record, stop)
        assert checked.meta and checked.match
        last_report = [0.0]

        def local_progress(done, total):
            if time.monotonic() - last_report[0] > 0.2 or done == total:
                progress("local-hash", fraction=done / max(total, 1))
                last_report[0] = time.monotonic()

        verify_local_data(
            item,
            checked.meta,
            checked.match,
            checkpoint=lambda: checkpoint(stop),
            progress=local_progress,
        )
        validate_links(record)
        checkpoint(stop)
        client = self.library.client()
        resume_check = record.get("status") == "checking"
        if client.torrent(record["hash"]) is None:
            resume_check = False
            record["status"] = "adding"
            save()  # interruption never loses the chosen destination
            try:
                client.add(
                    checked.meta.data,
                    record["destination"],
                    [TAG, LINK_TAG, "torrentlinker:link-checking"],
                )
            except AlreadyInClient:
                self._owned(client, record)  # refuse adopting an unrelated torrent
        start = time.monotonic()
        while True:
            checkpoint(stop)
            torrent = self._owned(client, record)
            if torrent.state.startswith(("paused", "stopped")) or (
                resume_check and torrent.state in CHECKING_STATES
            ):
                break
            if time.monotonic() - start > 30:
                raise ValueError(
                    "The Torrent Client did not settle stopped. Check it before retrying."
                )
            stop.wait(0.2)
        already_checking = torrent.state in CHECKING_STATES
        if not already_checking:
            client.recheck(record["hash"])
        record["status"] = "checking"
        save()
        start = time.monotonic()
        saw_checking = already_checking
        while True:
            checkpoint(stop)
            torrent = self._owned(client, record)
            checking = torrent.state in CHECKING_STATES
            saw_checking |= checking
            progress("client-hash", fraction=torrent.progress)
            if not checking and (saw_checking or time.monotonic() - start >= 10):
                if torrent.progress < 1:
                    client.remove(record["hash"])  # never delete data through symlinks
                    record.update(stage="incomplete", status="failed")
                    raise ValueError(
                        "Client verification failed. Check Path Mappings "
                        "and client access to the link targets."
                    )
                validate_links(record)
                record["status"] = "verified"
                return
            if time.monotonic() - start > 3600:
                raise ValueError(
                    "Verification is still pending in the client. Retry to inspect it."
                )
            stop.wait(0.5)
