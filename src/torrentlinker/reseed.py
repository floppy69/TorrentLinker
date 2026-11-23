"""Reseed: add a Match to qBittorrent against the existing data, then verify it.

The torrent is added stopped, checked, and only
started once Verification shows every piece it needs is already there. A Match with
absent files seeds only once every one of its files, present ones included, is
confirmed skipped: nothing is then wanted, so no piece it shares with an absent file
is ever fetched into the library. Otherwise it is left stopped (ADR-0018). A failed
Verification removes the torrent (never its data) and records a Rejection. µTorrent
may rename files on disk after explicit approval, with a recovery journal; other
clients leave names untouched. See ADR-0002/0013.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from torrentlinker.disk_rename import (
    RenameApproval,
    apply_disk_renames,
    journal_path,
    keep_disk_renames,
    owns_journal,
    plan_disk_renames,
    undo_disk_renames,
    verify_local_data,
)
from torrentlinker.domain import LocalItem, Torrent
from torrentlinker.matching import Match
from torrentlinker.qbit import AlreadyInClient, Qbit
from torrentlinker.reseed_layout import same_unicode_file
from torrentlinker.store import Store, Verification
from torrentlinker.torrent_meta import TorrentMeta, pieces_inside

log = logging.getLogger(__name__)

TAG = "torrentlinker"
VERIFYING = "torrentlinker:verifying"
PARTIAL = "torrentlinker:partial"
CHECKING_STATES = {"checkingUP", "checkingDL", "checkingResumeData", "queuedForChecking", "moving"}
# A stopped torrent below 100% right after a recheck request may not have started checking yet.
RECHECK_GRACE = 10.0
PIECE_VERIFIED = 2  # qBittorrent pieceStates: 0 missing, 1 downloading, 2 have

# Held for a whole Reseed set-up and for every check, so a poll never sees a half-made Reseed.
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Outcome:
    item_path: Path
    hash: str
    verified: bool
    progress: float
    started: bool = False
    problem: str | None = None  # something other than the data being wrong
    disk_renamed: bool = False


def start_reseed(
    qbit: Qbit,
    store: Store,
    item: LocalItem,
    meta: TorrentMeta,
    match: Match,
    candidate_key: str,
    sleep: Callable[[float], None] = time.sleep,
    *,
    approve_disk_renames: RenameApproval | None = None,
) -> str:
    with _LOCK:
        from torrentlinker.reseed_layout import uses_links

        if uses_links(qbit):
            return _start_link_reseed(qbit, store, item, meta, match, candidate_key)
        if getattr(qbit, "requires_disk_renames", False) and match.renames:
            if getattr(qbit, "reseed_policy", None) is not None:
                raise ValueError("This Torrent Client requires links to preserve original files.")
            return _start_disk_reseed(
                qbit, store, item, meta, match, candidate_key, sleep, approve_disk_renames
            )
        return _start_reseed(qbit, store, item, meta, match, candidate_key, sleep)


def start_board_reseed(qbit, store, item, meta, match, candidate_key, sleep=time.sleep):
    """Prepare client renames without letting the automatic verifier start the torrent."""
    if getattr(qbit, "requires_disk_renames", False):
        raise ValueError("This Torrent Client requires links to preserve original files.")
    with _LOCK:
        return _start_reseed(qbit, store, item, meta, match, candidate_key, sleep, automatic=False)


def _start_link_reseed(qbit, store, item, meta, match, candidate_key):
    from torrentlinker.reseed_layout import LINK_TAG, validate_layout

    if existing := qbit.torrent(meta.infohash):
        raise AlreadyInClient(existing)
    verify_local_data(item, meta, match)
    layout = qbit.reseed_policy.prepare(item, meta, match)
    record = {**layout, "stage": "verify", "status": "adding", "key": candidate_key}
    store.save_reseed_link_layout(meta.infohash, record)
    validate_layout(record)
    h = qbit.add(meta.data, record["destination"], [TAG, LINK_TAG, VERIFYING])
    store.start_verification(h, item.path, candidate_key, None, sorted(match.pairs.values()))
    qbit.recheck(h)
    store.mark_rechecked(h)
    record["status"] = "checking"
    store.save_reseed_link_layout(meta.infohash, record)
    return h


def _start_reseed(
    qbit: Qbit,
    store: Store,
    item: LocalItem,
    meta: TorrentMeta,
    match: Match,
    candidate_key: str,
    sleep: Callable[[float], None],
    added: Callable[[], None] = lambda: None,
    *,
    automatic: bool = True,
) -> str:
    # Some clients cannot rename or verify partial files. Let them refuse before
    # adding anything and express the Match in their reported file-path layout.
    # Ordinary clients use paths relative to the requested save folder; µTorrent
    # uses paths relative to the content root for a multifile torrent.
    prepare = getattr(qbit, "reseed_layout", None)
    client_match = prepare(meta, match) if prepare else match
    # A normalizing filesystem can expose decomposed directory names while the
    # torrent uses composed accents. Keep the torrent spelling when both names
    # already address the same regular file: asking the client to rename it could
    # move user data. Keep `match` intact for local Verification bookkeeping.
    client_match = replace(
        client_match,
        pairs={
            old: old if same_unicode_file(item.save_path, old, new) else new
            for old, new in client_match.pairs.items()
        },
    )
    if existing := qbit.torrent(meta.infohash):
        raise AlreadyInClient(existing)
    renames = rename_plan(client_match, set(meta.files))
    _require_absent_rename_sources(item.save_path, renames)
    try:
        from torrentlinker.reseed_layout import BOARD_CHECKING, BOARD_TAG

        tags = [TAG, VERIFYING] if automatic else [TAG, BOARD_TAG, BOARD_CHECKING]
        h = qbit.add(meta.data, str(item.save_path), tags)
    except AlreadyInClient as error:
        # Another process may have added it since the preflight. Reads are best
        # effort; failure to fetch details must not hide the duplicate result.
        try:
            existing = qbit.torrent(meta.infohash)
        except Exception:
            raise error from None
        raise AlreadyInClient(existing) from error
    added()
    absent = set(match.unwanted)
    required = pieces_inside(meta, absent) if absent else None
    # Where the user keeps the files, as checked below: never the client's own view.
    local_files = sorted(match.pairs.values())
    store.start_verification(h, item.path, candidate_key, required, local_files)
    # qBittorrent re-applies its own list of file paths when a new torrent settles and
    # when a check starts. A rename it has not taken in yet is then undone on disk,
    # which moves the user's file back to the torrent's original path. So: rename only
    # once the torrent has settled, and check only once qBittorrent lists the new paths.
    _wait_for(lambda: _settled(qbit.torrent(h)), sleep, h, qbit, store, "the torrent to settle")
    try:
        for old, new in renames:
            _require_absent_rename_sources(item.save_path, [(old, new)])
            qbit.rename_file(h, old, new)
        if renames:
            store.forget_torrent_files(h)  # its file list changed
    except Exception as e:  # e.g. a client that cannot rename into other folders
        qbit.remove(h)  # never deletes files
        store.end_verification(h)
        raise ReseedAborted(str(e) or type(e).__name__) from e
    # Every local file at its own path; absent files may move along with a renamed
    # folder (Transmission renames whole folders).
    expected = set(client_match.pairs.values())
    _wait_for(
        lambda: expected <= _files(qbit.torrent(h)),
        sleep,
        h,
        qbit,
        store,
        "the torrent client to take in the renamed files",
    )
    if missing := _missing(item.save_path, sorted(match.pairs.values())):
        qbit.remove(h)  # never deletes files
        store.end_verification(h)
        raise ReseedAborted(f"Local files are no longer in place: {', '.join(missing)}")
    if absent:
        indexes = [i for i, path in enumerate(meta.files) if path in absent]
        qbit.set_file_priority(h, indexes, 0)
    qbit.recheck(h)
    store.mark_rechecked(h)
    if not automatic:
        store.end_verification(h)
    return h


SETTLED_STATES = ("stopped", "paused", "missingFiles", "error")
SET_UP_TIMEOUT = 30.0
POLL_INTERVAL = 0.2


class ReseedAborted(Exception):
    """qBittorrent did not reach a safe state; the torrent was removed, data untouched."""


def _require_absent_rename_sources(save_path: Path, renames: list[tuple[str, str]]) -> None:
    # Client renames also move disk entries at the old path. In particular, staging
    # a filename swap through temporary names moves the user's original files.
    for old, _new in renames:
        try:
            (save_path / old).lstat()  # also detects dangling symlinks; unreadable is not absent
        except FileNotFoundError:
            continue
        raise ReseedAborted(
            f"Reseeding would move an existing local path: {save_path / old}. "
            "This layout cannot be reseeded safely without changing your files."
        )


def _start_disk_reseed(
    qbit: Qbit,
    store: Store,
    item: LocalItem,
    meta: TorrentMeta,
    match: Match,
    candidate_key: str,
    sleep: Callable[[float], None],
    approve: RenameApproval | None,
) -> str:
    # Only µTorrent opts into this exception to ADR-0002, with explicit per-job
    # approval. Missing files still cannot be verified through its WebUI.
    identity = Match({p: p for p in match.pairs}, absent=match.unwanted)
    prepare = getattr(qbit, "reseed_layout", None)
    assert prepare is not None
    prepare(meta, identity)
    if existing := qbit.torrent(meta.infohash):
        raise AlreadyInClient(existing)
    folder = store.torrent_dir.parent
    if journal_path(folder, meta.infohash).exists():
        raise ReseedAborted("A previous disk rename needs recovery before this torrent can retry")
    plan = plan_disk_renames(item, meta, match)
    if approve is None or not approve(plan):
        raise ReseedAborted("Disk renaming cancelled. No files were renamed.")
    verify_local_data(item, meta, match)
    created = False

    def added() -> None:
        nonlocal created
        created = True

    try:
        apply_disk_renames(folder, plan, getattr(qbit, "reseed_client_id", ""))
        return _start_reseed(qbit, store, item, meta, identity, candidate_key, sleep, added)
    except Exception:
        # Stop using the renamed files before restoring their old names. If client
        # removal fails, leave the journal for recovery rather than race the client.
        if qbit.torrent(meta.infohash) is not None:
            if not created:
                raise ReseedAborted(
                    "This torrent appeared in the Torrent Client during setup. The renamed files "
                    "and recovery journal were kept; inspect the torrent before restoring names."
                ) from None
            qbit.remove(meta.infohash)
        undo_disk_renames(folder, meta.infohash)
        store.end_verification(meta.infohash)
        raise


def _recover_disk_renames(qbit: Qbit, store: Store) -> None:
    if not getattr(qbit, "requires_disk_renames", False):
        return
    folder = store.torrent_dir.parent
    for journal in (folder / "reseed-renames").glob("*.json"):
        hash = journal.stem
        if not owns_journal(folder, hash, getattr(qbit, "reseed_client_id", "")):
            continue
        torrent = qbit.torrent(hash)
        if torrent is None:
            undo_disk_renames(folder, hash)
            store.end_verification(hash)
        elif VERIFYING not in torrent.tags and torrent.progress >= 1:
            # A crash between acceptance and journal cleanup must not undo seeding.
            keep_disk_renames(folder, hash)
            store.end_verification(hash)


def _remove_reseed(qbit: Qbit, store: Store, hash: str) -> None:
    qbit.remove(hash)
    if owns_journal(store.torrent_dir.parent, hash, getattr(qbit, "reseed_client_id", "")):
        undo_disk_renames(store.torrent_dir.parent, hash)
    store.end_verification(hash)


def _missing(save_path: Path, local_files: list[str]) -> list[str]:
    return [f for f in local_files if not (save_path / f).exists()]


def _settled(t: Torrent | None) -> bool:
    return t is not None and t.state.startswith(SETTLED_STATES)


def _files(t: Torrent | None) -> set[str]:
    return set(t.files) if t is not None else set()


def _wait_for(
    condition: Callable[[], bool],
    sleep: Callable[[float], None],
    hash: str,
    qbit: Qbit,
    store: Store,
    what: str,
) -> None:
    for _ in range(int(SET_UP_TIMEOUT / POLL_INTERVAL)):
        if condition():
            return
        sleep(POLL_INTERVAL)
    qbit.remove(hash)  # never deletes files
    store.end_verification(hash)  # keep recovery state if removal raises instead
    raise ReseedAborted(f"Timed out waiting for {what}")


def rename_plan(match: Match, torrent_paths: set[str]) -> list[tuple[str, str]]:
    """Renames that make the torrent's paths equal the local ones, safe against swaps."""
    renames = match.renames
    if not set(renames.values()) & torrent_paths:
        return list(renames.items())
    staged = {old: f"{old}.torrentlinker-tmp" for old in renames}
    return list(staged.items()) + [(staged[old], new) for old, new in renames.items()]


def check_verifications(
    qbit: Qbit, store: Store, now: Callable[[], float] = time.time
) -> list[Outcome]:
    """Settle every finished Verification."""
    from torrentlinker.achievements import observe_seeding

    observe_seeding(store.torrent_dir.parent, store.client_id, qbit)
    with _LOCK:
        _recover_disk_renames(qbit, store)
        outcomes = []
        for t in qbit.torrents(tag=VERIFYING):
            record = store.verification(t.hash)
            if record is None or record.rechecked_at is None:
                # A Reseed interrupted before its check was requested: undo it, the user
                # can retry. (The lock rules out a Reseed still being set up.)
                _remove_reseed(qbit, store, t.hash)
                continue
            if t.state in CHECKING_STATES:
                continue
            # The files where the user keeps them, beside the Local Item, exactly as the
            # Reseed checked before the hash check. The client's reported save path,
            # translated back through Path Mappings or written as a share path, may
            # name the same folder differently (#53).
            if missing := _missing(record.item_path.parent, record.local_files):
                # Never seed from files that are not where the user keeps them.
                _remove_reseed(qbit, store, t.hash)
                problem = f"Local files are no longer in place: {', '.join(missing)}"
                log.error("%s (%s)", problem, record.item_path)
                outcomes.append(Outcome(record.item_path, t.hash, False, 0.0, problem=problem))
                continue
            if "torrentlinker:links" in t.tags:
                from torrentlinker.reseed_layout import validate_layout

                layout = store.reseed_link_layout(t.hash)
                try:
                    if layout.get("hash") != t.hash or layout.get("destination") != str(
                        t.save_path
                    ):
                        raise ValueError(
                            "The prepared Reseed layout no longer belongs to this torrent."
                        )
                    validate_layout(layout)
                except (OSError, ValueError, KeyError) as error:
                    _remove_reseed(qbit, store, t.hash)
                    outcomes.append(
                        Outcome(record.item_path, t.hash, False, 0.0, problem=str(error))
                    )
                    continue
            verified, progress = _verdict(qbit, t.hash, t.progress, record)
            if verified:
                outcomes.append(_accept(qbit, store, t.hash, record, progress))
            elif now() - record.rechecked_at >= RECHECK_GRACE:
                _remove_reseed(qbit, store, t.hash)
                store.reject(
                    record.item_path,
                    record.candidate_key,
                    f"Verification failed at {progress:.1%}",
                )
                outcomes.append(Outcome(record.item_path, t.hash, False, progress))
        return outcomes


def _verdict(qbit: Qbit, hash: str, progress: float, record: Verification) -> tuple[bool, float]:
    if record.required_pieces is None:
        return progress >= 1.0, progress
    states = qbit.piece_states(hash)
    wanted = [i for start, end in record.required_pieces for i in range(start, end)]
    have = sum(1 for i in wanted if i < len(states) and states[i] == PIECE_VERIFIED)
    share = have / len(wanted) if wanted else 0.0
    return bool(wanted) and have == len(wanted), share


def _accept(qbit: Qbit, store: Store, hash: str, record: Verification, progress: float) -> Outcome:
    complete = record.required_pieces is None
    if not complete:
        qbit.add_tags(hash, [PARTIAL])
    started = complete or _skip_every_file(qbit, hash)
    if started:
        qbit.start(hash)
        if complete:
            from torrentlinker.achievements import await_seeding

            await_seeding(store.torrent_dir.parent, store.client_id, hash)
    qbit.remove_tags(hash, [VERIFYING])
    renamed = owns_journal(store.torrent_dir.parent, hash, getattr(qbit, "reseed_client_id", ""))
    if renamed:
        keep_disk_renames(store.torrent_dir.parent, hash)
    store.end_verification(hash)
    layout = store.reseed_link_layout(hash)
    if layout and layout.get("hash") == hash and layout.get("layout", "links") == "links":
        layout.update(
            stage="seeding" if started else "verify", status="seeding" if started else "verified"
        )
        store.save_reseed_link_layout(hash, layout)
    return Outcome(record.item_path, hash, True, progress, started=started, disk_renamed=renamed)


SKIP_TIMEOUT = 5.0


def _skip_every_file(qbit: Qbit, hash: str) -> bool:
    """Skip every file of a partial torrent and confirm the client took it in, so that
    starting it uploads its verified pieces and wants none. A piece shared by a present
    file and an absent one would otherwise be fetched into the present file. Clients
    apply priorities asynchronously; unconfirmed, the torrent stays stopped."""
    try:
        indexes = [f.index for f in qbit.file_listing(hash)]
        if not indexes:
            return False
        qbit.set_file_priority(hash, indexes, 0)
        for _ in range(int(SKIP_TIMEOUT / POLL_INTERVAL)):
            listing = qbit.file_listing(hash)
            if sorted(f.index for f in listing) != sorted(indexes):
                return False  # the file list changed under us
            if not any(f.wanted for f in listing):
                return True
            time.sleep(POLL_INTERVAL)
    except Exception:  # noqa: BLE001 - a stopped torrent is the safe outcome
        log.exception("Could not skip every file of %s; it stays stopped", hash)
    return False


def pending_verifications(qbit: Qbit, store: Store) -> list[Path]:
    """Local Items whose Reseed is still being verified."""
    records = (store.verification(t.hash) for t in qbit.torrents(tag=VERIFYING))
    return [r.item_path for r in records if r is not None]
