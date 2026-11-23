"""Plan downloads across selected clients without spending a shared disk twice."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from torrentlinker.config import Settings
from torrentlinker.domain import LibraryFolder, Torrent
from torrentlinker.plan import (
    Plan,
    PlanCandidate,
    PlanGoal,
    catalogue_candidates,
    disk_of,
    disk_space,
    explain_inputs,
    make_plan,
    note_priority,
    on_disk,
)
from torrentlinker.plan_diagnostics import PlanIssue
from torrentlinker.qbit import Qbit
from torrentlinker.scan import scan
from torrentlinker.seeding import combined_seeding
from torrentlinker.store import Store
from torrentlinker.zen import note


def distributed_plan(
    settings: Settings,
    store: Store,
    clients: Mapping[str, Qbit],
    budgets: Mapping[str, int],
    validate_folder: Callable[[str, Path], None] = lambda identifier, folder: None,
) -> Plan:
    """Round-robin placement within client budgets, followed by the Zen selection engine.

    Paths resolve to physical disks on the application host. A disk mounted for two
    clients has one free-space budget. Every infohash gets at most one destination.
    """
    if not clients:
        raise ValueError("Choose at least one Torrent Client.")
    if any(value < 0 for value in budgets.values()):
        raise ValueError("Client budgets cannot be negative.")
    observed: list[Torrent] = []
    for client in clients.values():
        observed.extend(client.torrents(with_files=False))
    hashes = {t.hash.lower() for t in observed}
    rows = store.catalogue()
    current = combined_seeding(
        settings.zen,
        observed,
        settings.indexer.url,
        catalogue={r.infohash: r for r in rows},
    )
    options = settings.plan_options
    available: dict[str, list[PlanCandidate]] = {}
    folders: set[Path] = set()
    scanned = {}
    excluded = {}
    input_issues: dict[str, int] = {}
    for identifier in clients:
        scoped = settings.for_client(identifier)
        issues: list[PlanIssue] = []
        candidates = catalogue_candidates(
            rows,
            scoped.download_folders,
            settings.indexer_categories,
            hashes,
            disk_of,
            set(settings.plan_categories) if settings.plan_categories is not None else None,
            settings.plan_exclusions,
            issues=issues,
            adult=settings.adult_content,
        )
        for folder in {c.folder for c in candidates if c.folder is not None}:
            validate_folder(identifier, folder)
            if not folder.is_dir():
                raise ValueError(f"Download Folder is unavailable for {scoped.profile().name}.")
            folders.add(folder)
            if folder not in scanned:
                scanned[folder] = scan(LibraryFolder(folder), store).require_complete()
        existing = on_disk(
            candidates,
            [
                item
                for folder in {c.folder for c in candidates}
                if folder is not None
                for item in scanned[folder]
            ],
        )
        excluded.update({item.infohash: item for item in existing})
        if candidates and not any(options.admits(c.size, c.seeders) for c in candidates):
            issues.append(PlanIssue("filters", len(candidates)))
        for issue in issues:
            input_issues[issue.code] = max(input_issues.get(issue.code, 0), issue.count)
        available[identifier] = [
            replace(c, client_id=identifier)
            for c in candidates
            if c.infohash not in excluded and options.admits(c.size, c.seeders)
        ]
    spaces = disk_space(sorted(folders), settings.free_space_margin)
    physical = {space.disk: space.available for space in spaces}
    by_hash: dict[str, dict[str, PlanCandidate]] = {}
    for identifier, candidates in available.items():
        for item in candidates:
            by_hash.setdefault(item.infohash, {})[identifier] = item

    def placement_priority(choices: dict[str, PlanCandidate]) -> tuple[float, int, str]:
        candidate = next(iter(choices.values()))
        score = note(settings.zen.zen_class, candidate.as_zen())
        if options.goal is PlanGoal.NOTE:
            return note_priority(candidate, score)
        return -score / max(1, candidate.size), 0, ""

    # Reserve space in goal order so placement cannot discard a higher-note download.
    ordered = sorted(by_hash.values(), key=placement_priority)
    identifiers = list(clients)

    def place(ordering: list[dict[str, PlanCandidate]]) -> list[PlanCandidate]:
        remaining = dict(physical)
        client_remaining = {
            identifier: budgets.get(identifier, 0) or sum(physical.values())
            for identifier in clients
        }
        assigned: list[PlanCandidate] = []
        cursor = 0
        for choices in ordering:
            for offset in range(len(identifiers)):
                index = (cursor + offset) % len(identifiers)
                identifier = identifiers[index]
                candidate = choices.get(identifier)
                if (
                    candidate is not None
                    and candidate.infohash not in excluded
                    and candidate.size <= client_remaining[identifier]
                    and candidate.size <= remaining.get(candidate.disk, 0)
                ):
                    assigned.append(candidate)
                    client_remaining[identifier] -= candidate.size
                    remaining[candidate.disk] -= candidate.size
                    cursor = (index + 1) % len(identifiers)
                    break
        return assigned

    assigned = place(ordered)
    slots = max(0, settings.zen.torrent_cap - current.count) if settings.zen.torrent_cap else None
    result = make_plan(
        settings.zen, assigned, physical, current.active, slots, options=options, disk_spaces=spaces
    )
    if len(result.items) < options.min_torrents:
        smaller_first = sorted(
            by_hash.values(),
            key=lambda choices: (
                next(iter(choices.values())).download_size,
                next(iter(choices.values())).infohash,
            ),
        )
        alternative = make_plan(
            settings.zen,
            place(smaller_first),
            physical,
            current.active,
            slots,
            options=options,
            disk_spaces=spaces,
        )
        if len(alternative.items) > len(result.items):
            result = alternative
    issues = [PlanIssue(code, count) for code, count in input_issues.items()]
    if not assigned and by_hash:
        candidates = [c for choices in by_hash.values() for c in choices.values()]
        if all(c.size > physical.get(c.disk, 0) for c in candidates):
            issues = [PlanIssue("disk_space", len(by_hash))]
        else:
            issues = [PlanIssue("client_budget")]
    return explain_inputs(result, issues, list(excluded.values()))
