"""Tracker grouping and explicit management of existing Torrent Client torrents."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

from torrentlinker import reseed
from torrentlinker.category_tags import CATEGORY_TAG_PREFIX, category_path, category_tag
from torrentlinker.client_limits import delete_refusal
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.qbit import Qbit


def tracker_hosts(torrent: Torrent) -> tuple[str, ...]:
    """Never expose announce paths, query strings or embedded credentials in the UI."""
    hosts = set()
    for url in (*torrent.trackers, torrent.tracker):
        try:
            if host := _tracker_host(url):
                hosts.add(host)
        except ValueError:
            continue
    return tuple(sorted(hosts)) or ("",)


@lru_cache(maxsize=1024)
def _tracker_host(url: str) -> str:
    """Bounded in-memory parsing, shared by torrents using the same private URL."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() in {"http", "https", "udp", "ws", "wss"} and parsed.hostname:
        return parsed.hostname.lower().rstrip(".")
    return ""


def tracker_group(host: str) -> str:
    """Group the known c411 mirror without merging unrelated tracker domains."""
    return "c411.org" if host == "tk.c411.tw" else host


def peer_count_text(connected: int, total: int) -> str:
    return f"{connected if connected >= 0 else '?'} ({total if total >= 0 else '?'})"


def peer_count_order(connected: int, total: int) -> int:
    return total if total >= 0 else connected


def tracker_groups(torrent: Torrent) -> tuple[str, ...]:
    return tuple(sorted({tracker_group(host) for host in tracker_hosts(torrent)}))


def category_labels(categories: Mapping[int, IndexerCategory]) -> dict[str, tuple[str, ...]]:
    # Category names themselves contain slashes. Resolve known paths as whole names.
    result = {}
    for cid in categories:
        tag = category_tag(cid, categories)
        if tag:
            result[tag] = tuple(categories[p].name for p in category_path(cid, categories))
    return result


def torrent_categories(
    torrent: Torrent, known: Mapping[str, tuple[str, ...]]
) -> tuple[tuple[str, ...], ...]:
    paths = set()
    for tag in torrent.tags:
        if tag.startswith(CATEGORY_TAG_PREFIX):
            # Unknown taxonomy: retain the full label rather than inventing subcategories.
            path = known.get(tag, (tag[len(CATEGORY_TAG_PREFIX) :].strip(),))
            if any(path):
                paths.add(path)
    if not paths and torrent.category and not torrent.category.startswith("torrentlinker"):
        paths.add(tuple(p.strip() for p in torrent.category.split("/") if p.strip()))
    return tuple(sorted(paths)) or ((),)


def status(torrent: Torrent) -> str:
    state = torrent.state.lower()
    if state in {"error", "missingfiles", "unknown"}:
        return "error"
    if "checking" in state:
        return "checking"
    if state.startswith(("paused", "stopped")):
        return "paused"
    if torrent.is_seeding:
        return "seeding"
    if torrent.progress < 1:
        return "downloading"
    return "other"


def comparison_status(torrent: Torrent | None) -> str:
    """Classify an exact client instance for read-only cross-client comparison."""
    if torrent is None:
        return "absent"
    if torrent.progress < 1:
        return "incomplete"
    if torrent.state.casefold().startswith(("paused", "stopped")):
        return "completed_paused"
    if torrent.state.casefold() in {"uploading", "stalledup", "forcedup", "seeding"}:
        return "actively_seeding"
    return "completed_other"


def safe_error(error: Exception) -> str:
    # HTTP exceptions often include a full request URL, including private announce keys.
    return re.sub(r"(?:https?|udp|wss?)://[^\s<>\"']+", "[URL]", str(error)) or type(error).__name__


@dataclass(frozen=True)
class ActionResult:
    hash: str
    name: str
    outcome: str  # sent, verifying, missing, failed
    detail: str = ""


def manage(
    client: Qbit,
    hashes: Sequence[str],
    action: str,
    progress: Callable[[ActionResult], None] = lambda _: None,
    *,
    file_indexes: Sequence[int] = (),
) -> list[ActionResult]:
    """Apply once per hash, rechecking Verification under the Reseed setup lock.

    Only the explicit delete action removes data. File selection is never an empty API list
    (which some clients interpret as every file).
    """
    if action not in {"resume", "pause", "recheck", "remove", "delete", "skip_files", "want_files"}:
        raise ValueError("Unknown torrent action")
    if action.endswith("_files") and not file_indexes:
        return []
    if action == "delete" and (refusal := delete_refusal(client)):
        refused = [ActionResult(hash, hash, "failed", refusal) for hash in dict.fromkeys(hashes)]
        for result in refused:
            progress(result)
        return refused
    results = []
    for hash in dict.fromkeys(hashes):
        name = hash
        try:
            with reseed._LOCK:
                torrent = client.torrent(hash, with_files=False)
                if torrent is None:
                    result = ActionResult(hash, name, "missing")
                elif reseed.VERIFYING in torrent.tags or (
                    "torrentlinker:link-checking" in torrent.tags and action != "remove"
                ):
                    result = ActionResult(hash, torrent.name, "verifying")
                elif "torrentlinker:links" in torrent.tags and action in {"delete", "want_files"}:
                    result = ActionResult(
                        hash,
                        torrent.name,
                        "failed",
                        "This torrent uses links to original files. "
                        "Remove it without deleting data.",
                    )
                elif (
                    "torrentlinker:links" in torrent.tags
                    and action == "resume"
                    and (torrent.progress < 1 or torrent.state in reseed.CHECKING_STATES)
                ):
                    result = ActionResult(hash, torrent.name, "verifying")
                else:
                    name = torrent.name
                    if action.endswith("_files"):
                        client.set_file_priority(
                            hash, list(file_indexes), 0 if action == "skip_files" else 1
                        )
                    elif action == "delete":
                        client.remove(hash, delete_files=True)
                    else:
                        getattr(client, action)(hash)
                    result = ActionResult(hash, name, "sent")
        except Exception as error:
            result = ActionResult(hash, name, "failed", safe_error(error))
        results.append(result)
        progress(result)
    return results
