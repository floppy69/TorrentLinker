"""Reviewed c411 tracker changes. Private announce URLs stay inside this module."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from torrentlinker.zen import is_indexer_torrent


@dataclass(frozen=True)
class Announce:
    url: str = field(repr=False)
    tier: int = 0


def host_name(value: str) -> str:
    """Accept a DNS host, never a URL, credentials, a path or a port."""
    value = value.strip().lower().rstrip(".")
    if (
        len(value) > 253
        or any(len(label) > 63 for label in value.split("."))
        or not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", value
        )
    ):
        raise ValueError("Enter an announce host name without a scheme, port or path.")
    return value


def passkey_part(url: str) -> tuple[str, str, tuple[int, int]]:
    """Recognize explicit passkey parameters and the two c411 announce path forms."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Unsupported announce URL format.")
    matches = list(re.finditer(r"(?:^|&)passkey=([^&]+)", parsed.query))
    if len(matches) == 1:
        part, span = "query", matches[0].span(1)
    elif matches:
        raise ValueError("Ambiguous announce passkey.")
    else:
        match = re.fullmatch(r"/(?:announce/([^/]+)|([^/]+)/announce)/?", parsed.path)
        if not match:
            raise ValueError("Unsupported announce passkey format.")
        part, span = "path", match.span(1 if match.group(1) else 2)
    key = unquote(getattr(parsed, part)[slice(*span)])
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key):
        raise ValueError("Unsupported announce passkey format.")
    return key, part, span


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def replace_key(url: str, key: str) -> str:
    _, part, (start, end) = passkey_part(url)
    parsed = urlsplit(url)
    text = getattr(parsed, part)
    return urlunsplit(parsed._replace(**{part: text[:start] + quote(key, safe="") + text[end:]}))


def replace_host(url: str, host: str) -> str:
    parsed = urlsplit(url)
    # Keep the transport and explicit port, as well as every path/query byte.
    authority = host_name(host) + (f":{parsed.port}" if parsed.port else "")
    return urlunsplit(parsed._replace(netloc=authority))


def c411_host(url: str, configured: list[str]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return is_indexer_torrent(url, "https://c411.org") or host in configured


@dataclass
class TrackerChange:
    before: tuple[Announce, ...] = field(repr=False)
    after: tuple[Announce, ...] = field(repr=False)
    groups: tuple[str, ...] = ()
    hosts: tuple[str, ...] = ()
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.before != self.after


def plan_change(
    trackers: list[Announce],
    action: str,
    *,
    configured: list[str],
    source_host: str = "",
    target_host: str = "",
    groups: list[str] | None = None,
    settings_announce: str = "",
) -> TrackerChange:
    """Pure, all-or-nothing per torrent; retain unrelated trackers and their tiers."""
    if action not in {"replace-host", "add-backup", "update-passkey"}:
        raise ValueError("Unknown tracker update action.")
    configured = [host_name(host) for host in configured]
    if action in {"replace-host", "add-backup"}:
        target_host = host_name(target_host)
        if not c411_host("https://" + target_host, configured):
            raise ValueError("Save the new c411 host in Settings before using it.")
    if action == "replace-host":
        source_host = host_name(source_host)
    wanted = set(groups or [])
    if any(not re.fullmatch(r"[a-f0-9]{16}", group) for group in wanted):
        raise ValueError("Choose passkey fingerprints from the preview.")
    saved_key = ""
    if action == "update-passkey":
        if not c411_host(settings_announce, configured):
            raise ValueError("Save a c411 Announce URL in Settings first.")
        saved_key = passkey_part(settings_announce)[0]
    before = tuple(trackers)
    eligible = [entry for entry in before if c411_host(entry.url, configured)]
    if not eligible:
        return TrackerChange(before, before, reason="not_c411")
    hosts = tuple(sorted({urlsplit(entry.url).hostname or "" for entry in eligible}))
    try:
        keys = {entry.url: passkey_part(entry.url)[0] for entry in eligible}
    except ValueError:
        return TrackerChange(before, before, hosts=hosts, reason="unsupported_passkey_format")
    identities = tuple(sorted({fingerprint(key) for key in keys.values()}))
    after = list(before)
    if action == "add-backup":
        if max(e.tier for e in before) >= 255:
            return TrackerChange(before, before, identities, hosts, "tier_limit")
        if any(urlsplit(entry.url).hostname == target_host for entry in eligible):
            return TrackerChange(before, before, identities, hosts, "already_current")
        if len(identities) != 1:
            return TrackerChange(before, before, identities, hosts, "mixed_passkeys")
        after.append(
            Announce(replace_host(eligible[0].url, target_host), max(e.tier for e in before) + 1)
        )
    else:
        for index, entry in enumerate(before):
            if entry not in eligible:
                continue
            url = entry.url
            if action == "replace-host" and urlsplit(url).hostname == source_host:
                url = replace_host(url, target_host)
            if action == "update-passkey" and fingerprint(keys[url]) in wanted:
                url = replace_key(url, saved_key)
            after[index] = Announce(url, entry.tier)
        # A host move may collide with an existing backup. Refuse rather than
        # silently remove or reorder entries in the owner's tracker list.
        if len({entry.url for entry in after}) < len({entry.url for entry in before}):
            return TrackerChange(before, before, identities, hosts, "duplicate_target")
    return TrackerChange(
        before,
        tuple(after),
        identities,
        hosts,
        "update" if tuple(after) != before else "already_current",
    )


def upload_announces(announce: str, hosts: list[str]) -> list[str]:
    """Use the configured hosts in order, retaining the saved URL path and passkey."""
    if not hosts or not c411_host(announce, hosts):
        return [announce]
    passkey_part(announce)
    return list(dict.fromkeys([replace_host(announce, host) for host in hosts]))


class TrackerUpdates:
    """Short-lived private previews, consumed once before serialized execution."""

    def __init__(self, setup):
        import threading

        self.setup = setup
        self.lock = threading.RLock()
        self.previews: dict[str, tuple] = {}

    def _settings_stamp(self, setup):
        import json

        from torrentlinker.config import CLIENT_FIELDS

        credential = setup.secrets.get(
            setup.settings.secret_name(CLIENT_FIELDS[setup.settings.client] + "-password")
        )
        credential += setup.secrets.get(setup.settings.secret_name("qbit-api-key"))
        return hashlib.sha256(
            (
                json.dumps([setup.snapshot(), announce_hosts(setup)], sort_keys=True)
                + setup.secrets.get("announce-url")
                + credential
            ).encode()
        ).hexdigest()

    def preview(self, client_ids, action, source_host, target_host, groups, stop, report):
        import time
        import uuid
        from collections import Counter

        hosts = announce_hosts(self.setup)
        saved = self.setup.secrets.get("announce-url")
        # Validate the request even when the selected clients have no torrents.
        plan_change(
            [],
            action,
            configured=hosts,
            source_host=source_host,
            target_host=target_host,
            groups=groups,
            settings_announce=saved,
        )
        try:
            saved_group = fingerprint(passkey_part(saved)[0])
        except ValueError:
            saved_group = ""
        rows, changes, stamps, capabilities = [], [], {}, {}
        for identifier in dict.fromkeys(client_ids):
            if stop.is_set():
                return {"cancelled": True}
            setup = self.setup.for_client(identifier)
            if not setup.settings.profile().enabled:
                raise ValueError("A selected Torrent Client is disabled.")
            stamps[identifier] = self._settings_stamp(setup)
            client = setup.client()
            supported = all(
                hasattr(client, name)
                for name in ("announce_entries", "apply_announces", "reannounce")
            )
            try:
                if supported and hasattr(client, "tracker_updates_supported"):
                    supported = client.tracker_updates_supported()
                capabilities[identifier] = "supported" if supported else "unsupported_client"
                torrents = client.torrents(with_files=False)
            except Exception:
                capabilities[identifier] = "client_unavailable"
                rows.append(
                    {
                        "client_id": identifier,
                        "hash": "",
                        "hosts": [],
                        "groups": [],
                        "reason": "client_unavailable",
                        "update": False,
                    }
                )
                continue
            for torrent in torrents:
                if stop.is_set():
                    return {"cancelled": True}
                known = torrent.trackers or (torrent.tracker,)
                if not any(c411_host(url, hosts) for url in known if url):
                    continue
                row = {
                    "client_id": identifier,
                    "hash": torrent.hash,
                    "hosts": [],
                    "groups": [],
                    "reason": "unsupported_client",
                    "update": False,
                }
                try:
                    entries = (
                        client.announce_entries(torrent.hash)
                        if supported
                        else [Announce(url) for url in known if url]
                    )
                    change = plan_change(
                        entries,
                        action,
                        configured=hosts,
                        source_host=source_host,
                        target_host=target_host,
                        groups=groups,
                        settings_announce=saved,
                    )
                    row.update(hosts=list(change.hosts), groups=list(change.groups))
                    if supported:
                        row.update(reason=change.reason, update=change.changed)
                        if change.changed:
                            changes.append((identifier, torrent.hash, change))
                except Exception:
                    row["reason"] = "tracker_read_failed"
                rows.append(row)
                report({"done": len(rows), "phase": "preview"})
        token = uuid.uuid4().hex
        with self.lock:
            self.previews = {
                key: value
                for key, value in self.previews.items()
                if time.monotonic() - value[0] < 600
            }
            if len(self.previews) >= 20:
                self.previews.pop(next(iter(self.previews)))
            self.previews[token] = (
                time.monotonic(),
                stamps,
                changes,
                (action, source_host, target_host, sorted(set(groups))),
            )
        host_counts, group_counts = {}, {}
        for row in rows:
            for host in row["hosts"]:
                host_counts.setdefault(host, Counter())[row["reason"]] += 1
            for group in row["groups"]:
                group_counts.setdefault(group, Counter())[row["reason"]] += 1
        return {
            "hosts": {host: dict(counts) for host, counts in host_counts.items()},
            "groups": {group: dict(counts) for group, counts in group_counts.items()},
            "capabilities": capabilities,
            "preview_id": token,
            "action": action,
            "settings_group": saved_group,
            "counts": dict(Counter(row["reason"] for row in rows)),
            "rows": rows,
            "clients": {
                identifier: dict(
                    Counter(row["reason"] for row in rows if row["client_id"] == identifier)
                )
                for identifier in client_ids
            },
        }

    def apply(
        self, token, client_ids, action, stop, report, source_host="", target_host="", groups=None
    ):
        import time

        with self.lock:
            preview = self.previews.get(token)
            if preview is None or time.monotonic() - preview[0] >= 600:
                raise ValueError("Tracker preview expired. Review a new preview.")
            _, stamps, changes, expected_action = preview
            if (
                set(client_ids) != set(stamps)
                or (action, source_host, target_host, sorted(set(groups or []))) != expected_action
            ):
                raise ValueError("Tracker preview does not match this request.")
            targets = {identifier: self.setup.for_client(identifier) for identifier in stamps}
            if any(self._settings_stamp(targets[key]) != stamp for key, stamp in stamps.items()):
                raise ValueError("Settings changed. Review a new tracker preview.")
            del self.previews[token]
        rows = []
        for identifier, torrent_hash, change in changes:
            if stop.is_set():
                break
            row = {"client_id": identifier, "hash": torrent_hash, "status": "changed_since_preview"}
            client = targets[identifier].client()
            try:
                current = tuple(client.announce_entries(torrent_hash))
                if current != change.before:
                    rows.append(row)
                    continue
                client.apply_announces(torrent_hash, change.before, change.after)
                observed = tuple(client.announce_entries(torrent_hash))
                # Some clients normalize tier numbers. Preserve membership/order
                # within tiers and require backups to remain after existing tiers.
                if normalized_tiers(observed) != normalized_tiers(change.after):
                    row["status"] = "uncertain"
                else:
                    row["status"] = "updated"
                    try:
                        client.reannounce(torrent_hash)
                    except Exception:
                        row["status"] = "updated_reannounce_failed"
            except Exception:
                # A timeout may follow a committed edit. Never retry blindly or
                # expose the remote exception, which may echo private URLs.
                row["status"] = "uncertain"
            rows.append(row)
            report({"done": len(rows), "total": len(changes), "phase": "tracker-update"})
        return {"rows": rows, "cancelled": stop.is_set(), "total": len(changes)}


def normalized_tiers(entries):
    tiers = {}
    for entry in entries:
        tiers.setdefault(entry.tier, set()).add(entry.url)
    return [tiers[tier] for tier in sorted(tiers)]


def tracker_updates(setup):
    root = getattr(setup, "_root", None) or setup
    with setup.lock:
        if not hasattr(root, "_tracker_updates"):
            root._tracker_updates = TrackerUpdates(root)
        return root._tracker_updates


def announce_hosts(setup) -> list[str]:
    configured = setup.settings.announce_hosts
    if configured:
        return [host_name(host) for host in configured]
    saved = setup.secrets.get("announce-url")
    current = (
        urlsplit(saved).hostname if is_indexer_torrent(saved, "https://c411.org") else "c411.org"
    )
    return list(dict.fromkeys([current or "c411.org", "tk.c411.tw"]))
