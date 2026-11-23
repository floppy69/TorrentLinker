# Client transfers (#105)

The owner approved the retained preview, including the final source-client exclusion.
`approved-prototype.html` is the design reference for the shared desktop/Web panel.

- Exclude every source client from the destination choices.
- Default folders from destination client/category configuration; allow per-transfer overrides without changing settings.
- Derive copy/reuse from accessible storage, not host names. Seedbox file transports remain in #118.
- Block the whole selected batch until every item validates; highlight blockers and provide correction actions.
- Keep source data until copy, content verification and destination seeding succeed. Show per-item copy/hash progress and recover saved transfers.
- Choose source torrent/files cleanup independently during preparation. Require explicit final cleanup confirmation. Files-only leaves the source torrent paused. Shared files cannot be deleted.
- Use one bundled view, with French/English and light/dark support.

Transfers are tested with generated files and disposable clients on an internal Docker network, as requested by the owner. No configured user clients or library data are test targets.

## Supported storage and metadata

File copies run through storage mounted and accessible to TorrentLinker. Remote clients require explicit Path Mappings, including identity mappings when both sides use the same path. Unmounted remote paths require the explicit SFTP access approved for #118; see [the seedbox workflow](seedbox-workflow.md).

Original metainfo comes from TorrentLinker's cache or qBittorrent's export API. Other source clients need cached original metainfo; a missing original produces a blocker rather than reconstructing a torrent with different hashes or tracker settings. Renamed layouts and protected Reseed files are also blocked.

Transfers preserve the source until explicit post-verification cleanup. Partial copying resumes from journaled byte offsets after validating identities; a crash between a write and journal update is reconciled by comparing the copied prefix. Cleanup deletion intents are saved before each unlink. No folder is recursively removed.

## Validation

Run `TL_MULTI_DOCKER=1 .venv/bin/pytest -q tests/test_transfer_docker.py` for the disposable internal Docker network. This exercises qBittorrent, Transmission and Deluge with generated files, including cached-metadata return transfers, copy interruption/recovery, explicit cleanup and the Web workflow. Containers and network are removed by the fixture.

Run `QT_QPA_PLATFORM=wayland .venv/bin/pytest -q tests/test_torrents_desktop.py` on a Wayland desktop for the real-display bundled asset/dialog check. It uses temporary settings and UI fixtures rather than configured clients.
