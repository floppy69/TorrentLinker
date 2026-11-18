"""Headless Library workflows, with mounted-root checks before reading user data."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from torrentlinker.batch import MAX_WAITS
from torrentlinker.client_limits import disk_renames_elsewhere, partial_refusal
from torrentlinker.domain import ItemState
from torrentlinker.indexer import Candidate, RateLimited
from torrentlinker.library import LibraryEntry, LibraryResult, build_library, indexer_contents
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.reseed import start_reseed
from torrentlinker.review import (
    CheckedCandidate,
    candidate_key,
    check_candidate,
    find_candidates,
    remember_candidates,
    remembered_candidates,
    restore_checked,
)
from torrentlinker.scan import ScanError, scan_item
from torrentlinker.torrent_details import website_url
from torrentlinker.web.setup import Setup, StorageUnavailableError


class Library:
    def __init__(self, setup: Setup):
        self.setup = setup
        self.entries: list[LibraryEntry] = []
        self.selections: dict[str, list[str]] = {}
        self.folder_errors: list[ScanError] = []

    def client(self) -> MappedQbit:
        settings = self.setup.settings
        return MappedQbit(
            self.setup.client(),
            PathMapper(settings.path_mappings),
            sequential_video=settings.sequential_video,
        )

    def check_tree(self, path: Path, stop: threading.Event) -> None:
        self.setup.path_under_root(str(path), directory=path.is_dir())
        if not path.is_dir():
            return

        # Reject links in traversed trees, including in-root cycles, before the existing
        # desktop scanner follows a directory at its configured depth.
        def walk_failed(error: OSError) -> None:
            raise error

        for base, dirs, files in os.walk(path, onerror=walk_failed):
            if stop.is_set():
                raise ValueError("Scan cancelled.")
            for name in (*dirs, *files):
                child = Path(base) / name
                if child.is_symlink():
                    raise ValueError(
                        "The Library Folder contains symbolic links. Choose a directory "
                        "without links."
                    )
                self.setup.path_under_root(str(child), directory=False)

    def scan(
        self,
        stop: threading.Event,
        progress: Callable[[Any], None],
        folders: list[str] | None = None,
    ) -> dict:
        selected = self.setup.settings.library_folders
        if folders is not None:
            registered = {str(f.path) for f in selected}
            if not folders or not set(folders) <= registered:
                raise ValueError("Choose registered Library Folders to scan.")
            selected = [f for f in selected if str(f.path) in folders]
        selected_paths = {f.path for f in selected}
        previous = list(self.entries)
        unavailable = {}
        for folder in selected:
            if stop.is_set():
                return {"cancelled": True}
            try:
                self.check_tree(folder.path, stop)
            except (OSError, StorageUnavailableError) as error:
                unavailable[folder.path] = error
            except ValueError:
                if stop.is_set():
                    return {"cancelled": True}
                raise
        if stop.is_set():
            return {"cancelled": True}
        client_unavailable = False
        try:
            torrents = indexer_contents(
                self.client(),
                self.setup.store,
                self.setup.settings.indexer.url,
                stop=stop,
                progress=lambda done, total, rate: progress(
                    {
                        "stage": "client-files",
                        "done": done,
                        "total": total,
                        "requests_per_second": round(rate, 2),
                    }
                ),
            )
        except Exception:
            torrents = []
            client_unavailable = True
        result = LibraryResult()
        retained_paths = {f.path for f in self.setup.settings.library_folders} - selected_paths
        result.extend(e for e in previous if e.folder.path in retained_paths)
        scanned_paths: set[Path] = set()
        for folder in selected:
            if stop.is_set():
                return {"cancelled": True}
            if folder.path in unavailable:
                result.errors.append(ScanError(folder.path, str(unavailable[folder.path])))
                result.extend(entry for entry in self.entries if entry.folder == folder)
            else:
                scanned = build_library(
                    [folder],
                    torrents,
                    self.setup.settings.matching.ignore,
                    self.setup.store,
                    previous=self.entries,
                )
                result.extend(scanned)
                result.errors.extend(scanned.errors)
            scanned_paths.add(folder.path)
            published = (
                [replace(e, state=ItemState.UNKNOWN) for e in result]
                if client_unavailable
                else list(result)
            )
            self.entries = published + [
                e for e in previous if e.folder.path in selected_paths - scanned_paths
            ]
            progress(
                {
                    "items": len(result),
                    "folder": str(folder.path),
                    "discovered": [str(e.item.path) for e in published if e.folder == folder],
                }
            )
        if stop.is_set():
            return {"cancelled": True}
        if client_unavailable:
            result[:] = [replace(entry, state=ItemState.UNKNOWN) for entry in result]
        self.entries = result
        self.folder_errors = list(result.errors)
        return {
            "count": len(result),
            "client_unavailable": client_unavailable,
            "partial": bool(result.errors),
            "errors": [
                {"path": str(error.path), "message": error.message} for error in result.errors
            ],
        }

    def rows(self) -> list[dict[str, Any]]:
        return [
            {
                "path": str(e.item.path),
                "name": e.item.path.name,
                "within": str(e.item.within) if e.item.within else "",
                "size": e.item.size,
                "state": e.state,
                "kind": e.folder.kind,
                "folder": str(e.folder.path),
            }
            for e in self.entries
        ]

    def combine(self, paths: list[str], stop: threading.Event) -> dict:
        from torrentlinker.compatible import combine_items
        from torrentlinker.domain import TorrentClient

        if self.setup.settings.client != TorrentClient.QBITTORRENT:
            raise ValueError("Combining folders currently requires qBittorrent.")
        entries = [self.entry(p) for p in dict.fromkeys(paths)]
        if any(p in self.selections for p in paths):
            raise ValueError("Select real Local Items, not another combined selection.")
        if len({e.folder.kind for e in entries}) != 1:
            raise ValueError("Select items with the same Content Kind.")
        items = [self.scan_entry(e, stop) for e in entries]
        item = combine_items(items, self.setup.settings.path_mappings)
        self.selections[str(item.path)] = list(dict.fromkeys(paths))
        return {
            "path": str(item.path),
            "name": "Selected Local Items",
            "size": item.size,
            "folder": str(item.save_path),
            "kind": entries[0].folder.kind,
        }

    def scan_entry(self, entry: LibraryEntry, stop: threading.Event):
        from torrentlinker.compatible import combine_items

        paths = self.selections.get(str(entry.item.path))
        if paths:
            return combine_items(
                [self.scan_entry(self.entry(p), stop) for p in paths],
                self.setup.settings.path_mappings,
            )
        self.check_tree(entry.item.path, stop)
        return scan_item(entry.item.path)

    def entry(self, path: str) -> LibraryEntry:
        if path in self.selections:
            from torrentlinker.compatible import combine_items

            entries = [self.entry(p) for p in self.selections[path]]
            return LibraryEntry(
                entries[0].folder,
                combine_items([e.item for e in entries], self.setup.settings.path_mappings),
                ItemState.ORPHAN,
            )
        for entry in self.entries:
            if str(entry.item.path) == path:
                return entry
        raise ValueError("Scan the Library and select a Local Item first.")

    def repairs(self):
        from torrentlinker.repair import Repairs

        return Repairs(self.setup.store.torrent_dir.parent, self.setup.settings.active_client_id)

    def diagnose(self, path: str, candidate, data: bytes, stop: threading.Event) -> dict:
        entry = self.entry(path)
        self.check_tree(entry.item.path, stop)
        return self.repairs().diagnose(scan_item(entry.item.path), candidate, data, stop)

    def repair_client(self):
        from torrentlinker.domain import TorrentClient

        if self.setup.settings.client != TorrentClient.QBITTORRENT:
            raise ValueError("Experimental repair currently requires qBittorrent.")
        return self.client()

    def prepare_repair(
        self,
        identifier: str,
        destination: str,
        stop: threading.Event,
        *,
        client=None,
        experimental: bool = False,
    ) -> dict:
        root = self.setup.path_under_root(destination)
        return self.repairs().prepare(
            identifier, root, client or self.repair_client(), stop, experimental=experimental
        )

    def refresh_repair(self, identifier: str, *, client=None) -> dict:
        return self.repairs().refresh(identifier, client or self.repair_client())

    def start_repair(self, identifier: str, confirmation: str, *, client=None) -> dict:
        return self.repairs().start(identifier, confirmation, client or self.repair_client())

    def import_provenance(self, path: str, data: bytes, stop: threading.Event) -> dict:
        from torrentlinker.provenance import Provenance

        entry = self.entry(path)
        return Provenance(self.setup.store.torrent_dir.parent).inspect(
            self.scan_entry(entry, stop), data, stop
        )

    def provenance(self, path: str) -> list[dict]:
        from torrentlinker.provenance import Provenance

        entry = self.entry(path)
        return Provenance(self.setup.store.torrent_dir.parent).rows(
            self.scan_entry(entry, threading.Event())
        )

    def compatible(self, path: str, stop: threading.Event, progress) -> list[dict]:
        from torrentlinker.compatible import discover

        entry = self.entry(path)
        item = self.scan_entry(entry, stop)
        indexer = self.setup.indexer()
        checked = discover(
            indexer,
            self.setup.store,
            item,
            entry.folder.kind,
            self.setup.settings.categories(entry.folder.kind),
            self.setup.settings.matching.rules(),
            stop,
            progress,
        )
        return [self.candidate_row(row, indexer) for row in checked]

    def evidence(self, path: str, stop: threading.Event, **kwargs) -> dict:
        from torrentlinker.library_evidence import inspect_item

        entry = self.entry(path)
        return inspect_item(self.scan_entry(entry, stop), stop, **kwargs)

    def check(
        self,
        path: str,
        stop: threading.Event,
        progress: Callable[[Any], None],
        *,
        indexer_search: bool = True,
    ) -> list:
        """Check one Local Item; without `indexer_search`, only against the Catalogue and
        cached torrents, which costs no search."""
        from torrentlinker.review import search_candidates

        entry = self.entry(path)
        item = self.scan_entry(entry, stop)
        indexer, store = self.setup.indexer(), self.setup.store

        def search() -> list[Candidate]:
            if stop.is_set() or not indexer_search:
                return []
            return search_candidates(
                indexer,
                item,
                entry.folder.kind,
                self.setup.settings.categories(entry.folder.kind),
                indexer.supported_modes(),
            )

        found, checked = find_candidates(
            store,
            indexer,
            item,
            search,
            self.setup.settings.matching.rules(),
            store.rejections(item.path),
        )
        remember_candidates(store, indexer, item.path, found)
        result = [self.candidate_row(v, indexer) for v in checked]
        progress({"done": len(result), "total": len(found)})
        return result

    def candidate_row(self, checked: CheckedCandidate, indexer) -> dict:
        c, comparison = checked.candidate, checked.comparison
        files = []
        if comparison is not None:
            for torrent, local in comparison.pairs.items():
                files.append(
                    {
                        "torrent": torrent,
                        "local": local,
                        "status": "renamed" if torrent != local else "matched",
                    }
                )
            files.extend(
                {"torrent": path, "local": "", "status": "missing"} for path in comparison.absent
            )
            files.extend(
                {"torrent": path, "local": "", "status": "ignored"} for path in comparison.skipped
            )
        return {
            "key": candidate_key(c),
            "hash": c.infohash,
            "title": c.title,
            "size": c.size,
            "seeders": c.seeders,
            "match": "unchecked"
            if not checked.compared
            else "full"
            if checked.match and checked.match.is_full
            else "partial"
            if checked.match
            else "none",
            "archive": checked.unpack is not None,
            "files": files,
            "coverage": comparison.coverage if comparison else None,
            "website": website_url(c, indexer),
            "evidence": c.metadata,
        }

    def review(self, path: str, stop: threading.Event, *, key: str = "", action: str = "") -> list:
        entry = self.entry(path)
        item = self.scan_entry(entry, stop)
        indexer, store = self.setup.indexer(), self.setup.store
        found = remembered_candidates(store, indexer, item.path) or []
        rejected = store.rejections(item.path)
        found = [c for c in found if candidate_key(c) not in rejected]
        if action:
            candidate = next((c for c in found if candidate_key(c) == key), None)
            if candidate is None:
                raise ValueError("Select a current Candidate for this Local Item.")
            if action == "reject":
                store.reject(item.path, key, "Rejected by user")
                found.remove(candidate)
            elif action == "check":
                check_candidate(indexer, item, candidate, self.setup.settings.matching.rules())
        checked = restore_checked(indexer, item, found, self.setup.settings.matching.rules())
        return [self.candidate_row(v, indexer) for v in checked]

    def search_items(self, paths: list[str], stop: threading.Event, progress) -> dict:

        from torrentlinker.library import auto_searchable, pack_episodes

        chosen = [self.entry(path) for path in paths] if paths else list(self.entries)
        episodes = pack_episodes(chosen)  # checked without searching, after their packs
        selected = auto_searchable(chosen) + episodes
        results, errors = [], []
        for entry in selected:
            if stop.is_set():
                break
            for attempt in range(MAX_WAITS + 1):
                try:
                    rows = self.check(
                        str(entry.item.path),
                        stop,
                        progress,
                        indexer_search=entry not in episodes,
                    )
                    results.append({"path": str(entry.item.path), "rows": rows})
                except RateLimited as error:
                    # c411 asks to wait: resume this item then, unless cancelled meanwhile.
                    if attempt < MAX_WAITS:
                        progress({"waiting_until": time.time() + error.retry_after})
                        if not stop.wait(error.retry_after):
                            continue
                    errors.append({"path": str(entry.item.path), "message": "RateLimited"})
                except Exception as error:
                    errors.append({"path": str(entry.item.path), "message": type(error).__name__})
                break
            progress({"done": len(results), "total": len(selected)})
        return {"results": results, "errors": errors}

    def planning_matches(self, stop: threading.Event):
        """Restore checked Full Matches from this Library, without fetching torrents."""
        if not self.entries:
            return []
        found = []
        for entry, indexer, candidates in self._remembered(stop):
            if entry.state is not ItemState.ORPHAN:
                continue
            item = self.scan_entry(entry, stop)
            checked = restore_checked(
                indexer, item, candidates, self.setup.settings.matching.rules()
            )
            found.append((replace(entry, item=item), checked))
        return found

    def _remembered(self, stop: threading.Event):
        """Each not fully seeded Local Item with the Candidates its last search found,
        without rejected ones, as the desktop's Library batch actions use them."""
        from torrentlinker.domain import ItemState
        from torrentlinker.review import candidate_key

        indexer = self.setup.indexer()
        store = self.setup.store
        for entry in list(self.entries):
            if stop.is_set():
                return
            if entry.state is ItemState.SEEDED:
                continue
            rejected = store.rejections(entry.item.path)
            candidates = [
                c
                for c in remembered_candidates(store, indexer, entry.item.path) or []
                if candidate_key(c) not in rejected
            ]
            if candidates:
                yield entry, indexer, candidates

    def check_all(self, stop: threading.Event, progress: Callable[[Any], None]) -> dict:
        """Check every remembered Candidate across the Library, like the desktop's
        "Check all Candidates"; items never searched are left for "Find candidates"."""
        rules = self.setup.settings.matching.rules()
        items, counts, errors = [], {"full": 0, "partial": 0, "none": 0, "archive": 0}, []
        for entry, indexer, candidates in self._remembered(stop):
            self.check_tree(entry.item.path, stop)
            item = scan_item(entry.item.path)
            rows = []
            for candidate in candidates:
                if stop.is_set():
                    break
                try:
                    checked = check_candidate(indexer, item, candidate, rules)
                except Exception as error:
                    errors.append(f"{candidate.title}: {type(error).__name__}")
                    continue
                match = (
                    "full"
                    if checked.match and checked.match.is_full
                    else "partial"
                    if checked.match
                    else "none"
                )
                counts["archive" if checked.unpack else match] += 1
                rows.append({"hash": candidate.infohash, "title": candidate.title, "match": match})
            items.append({"path": str(entry.item.path), "name": entry.item.path.name, "rows": rows})
            progress({"done": len(items), "full": counts["full"]})
        return {"items": len(items), **counts, "errors": errors[:20], "results": items}

    def reseed_all(self, stop: threading.Event, progress: Callable[[Any], None]) -> dict:
        """Reseed every confirmed Full Match across the Library, like the desktop's
        "Reseed all Full Matches". Archives and disk renames need the item's own review."""
        from torrentlinker.qbit import AlreadyInClient
        from torrentlinker.review import candidate_key

        rules = self.setup.settings.matching.rules()
        client = self.client()
        started, present, skipped, errors = 0, 0, 0, []
        seen: set[str] = set()
        for entry, indexer, candidates in self._remembered(stop):
            self.check_tree(entry.item.path, stop)
            item = scan_item(entry.item.path)
            for candidate in candidates:
                if stop.is_set():
                    break
                try:
                    checked = check_candidate(indexer, item, candidate, rules)
                    if not checked.meta or not checked.match or not checked.match.is_full:
                        continue
                    if checked.unpack or (client.requires_disk_renames and checked.match.renames):
                        skipped += 1
                        continue
                    infohash = checked.meta.infohash.lower()
                    if infohash in seen:
                        continue
                    start_reseed(
                        client,
                        self.setup.store,
                        item,
                        checked.meta,
                        checked.match,
                        candidate_key(candidate),
                    )
                    seen.add(infohash)
                    started += 1
                except AlreadyInClient:
                    present += 1
                except Exception as error:
                    errors.append(f"{candidate.title}: {type(error).__name__}")
            progress({"reseeding": started})
        return {
            "started": started,
            "already_present": present,
            "skipped": skipped,
            "errors": errors[:20],
        }

    def reseed(
        self, path: str, hash: str, stop: threading.Event, *, approve_disk_renames=None
    ) -> dict:
        entry = self.entry(path)
        item = self.scan_entry(entry, stop)
        indexer = self.setup.indexer()
        candidates = remembered_candidates(self.setup.store, indexer, item.path) or []
        rejected = self.setup.store.rejections(item.path)
        candidate = next(
            (c for c in candidates if c.infohash == hash and candidate_key(c) not in rejected), None
        )
        if candidate is None:
            raise ValueError("Check this Local Item's Candidates first.")
        checked = check_candidate(indexer, item, candidate, self.setup.settings.matching.rules())
        if checked.unpack or not checked.match or not checked.meta:
            raise ValueError(
                "This Candidate requires extraction or has no Match. Prepare it in"
                " the desktop application."
            )
        client = self.client()
        if refusal := (None if checked.match.is_full else partial_refusal(client)):
            raise ValueError(refusal)
        if client.requires_disk_renames and checked.match.renames and approve_disk_renames is None:
            raise ValueError(disk_renames_elsewhere(client))
        hash = start_reseed(
            client,
            self.setup.store,
            item,
            checked.meta,
            checked.match,
            hash,
            approve_disk_renames=approve_disk_renames,
        )
        return {"hash": hash, "status": "verifying"}
