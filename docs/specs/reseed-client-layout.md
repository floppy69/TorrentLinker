# Client-specific Reseed layouts

Issue #116 gives Settings → Connections and the Reseed board one saved choice per Torrent Client. qBittorrent and other clients that support internal path renames default to using existing files without a Link Folder. Links remain an option for retaining torrent paths, including cross-seed use. µTorrent Classic, BitTorrent Classic and rTorrent always use links to preserve original names.

The board and Local Items use the same policy through the mapped client connection. Web links must remain within configured storage roots. Prepared board records retain their original mode across preference changes; older records without a mode are treated as links. Automatic Local Items link manifests are stored separately by client and torrent hash so multiple matches cannot overwrite each other or board progress.

Source identities, local hashes, occupied-path checks, client settling and verification remain required. Client-mode board records validate the client file paths and sizes, including proven Unicode normalization aliases. An explicit board Verify step does not trigger automatic seeding. Removing client registrations never removes original data or persistent link layouts.

Validation includes 76 passing core checks, browser workflows in both modes, desktop Settings interfaces, forced-link clients, existing record recovery, changed source/layout rejection, mounted-root restrictions and multiple matches for one item. Four disposable qBittorrent checks cover board and Local Items with both client renames and links, including Path Mappings and unchanged original names, bytes and inode. Ruff and mypy pass. See ADR-0021 for the decision and superseded behavior.
