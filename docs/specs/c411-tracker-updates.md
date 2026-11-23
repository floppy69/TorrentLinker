# Reviewed c411 tracker updates

Issue #120 adds the shared Torrents dialog, Web jobs and MCP `update_c411_trackers` tool. A preview covers all c411 torrents on selected clients, including torrents added outside TorrentLinker. It reports counts by client, host and passkey fingerprint, plus paginated per-torrent reasons. Unsupported clients are identified even when they contain no matching torrents.

Replace host retains the original transport, port, path and passkey. Add backup appends a later tier using the torrent's own key, and skips an existing backup or ambiguous mixed-key torrent. Update passkey changes only explicitly selected fingerprint groups to the saved Settings key. Unrelated tracker entries remain intact. A replacement that would duplicate an existing URL is skipped.

Previews expire after ten minutes and live only in memory. Applying requires the same client set, action, hosts, fingerprint groups, settings and credentials. Each torrent's tracker list is read again before writing. The token is consumed before the first edit; timeouts return an uncertain result and require a fresh preview. Successful edits are read back, checked for tier membership and order, then reannounced. Remote exceptions never enter public results. Public previews, proposals and job results contain host names and SHA-256 fingerprints, never announce URLs or keys.

The agent needs controls permission to preview. Replace host and Update passkey always need owner approval. Add backup follows the connection's controls policy. Queued work rechecks client scope and current permissions. A target must be a recognized c411 host or a host the owner saved in Settings, so automatic backups cannot direct credentials to an arbitrary host supplied by an agent.

Settings holds the ordered host list, current host first. New Uploads put the first URL in `announce` and each configured URL in a separate `announce-list` tier. Only metadata outside the info dictionary changes, so the infohash stays the same.

## Client support

- qBittorrent edits existing URLs and adds the backup at its explicit later tier. Leading empty lines preserve the requested tier on 4.6 and newer APIs.
- Transmission 4.x uses `trackerList`, preserving groups separated by blank lines. Older RPC versions are reported unsupported.
- Deluge replaces the tracker list with explicit tier values.
- µTorrent, BitTorrent and rTorrent adapters currently report unsupported for these reviewed edit-and-reannounce operations. No partial update is attempted through those adapters.

Path Mappings forwards these capabilities. Desktop and Web use the same operations; desktop progress polling reads Jobs without waiting for the application's exclusive job coordinator.

## Validation

Generated private torrents on an isolated Docker network exercise all three actions against two qBittorrent 5.2.4 instances, Transmission 4.1.3 and Deluge 2.2.0. Existing CI integration suites also exercise qBittorrent 4.6 and 5.2.4, Transmission 4.1.3 and Deluge 2.1.1. Tests verify unrelated URLs, tier order, passkey preservation/replacement and backup idempotence. Unit and MCP tests cover redaction, settings/intent changes, expiry, single-use previews, owner approvals and controls permission. Real-browser tests cover preview, apply, repeated preview and reuse of the shared dialog. Upload tests compare infohashes before and after adding backups.

## API references

- [qBittorrent Web API](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29)
- [qBittorrent 4.6 tracker tier parser](https://github.com/qbittorrent/qBittorrent/blob/release-4.6.7/src/base/bittorrent/trackerentry.cpp)
- [Transmission 4.1.3 RPC specification](https://github.com/transmission/transmission/blob/4.1.3/docs/rpc-spec.md)
- [Deluge core tracker operations](https://github.com/deluge-torrent/deluge/blob/develop/deluge/core/core.py)
