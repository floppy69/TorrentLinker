# Shared Search and download queue, #100

Approved on 2026-11-18: `search-queue-prototype.html`. Preserve the existing Search design from `../search-redesign.md`, with the preview's queue toolbar and category-folder dialog. Desktop and Web load one bundled panel with the shared palette and English/French strings.

The owner corrected the ticket's original per-search folder requirement: downloads use the target client's configured category folders. Prompt only for missing categories, then save those folders to the client settings and reuse them. No per-search folder override. A mixed selection retains each torrent's category. Folder selection uses a native desktop picker or the allowed server roots on Web. Previously queued entries retain their stored destination.

The queue provides Start queue, Pause, Start selected, Retry selected, Remove selected, Clear sent and row context actions. Pause stops future submissions; an in-flight client request may complete. Uncertain outcomes require checking the client and must not be automatically retried. Queue state survives panel navigation and app restart; pending sends must not replay on restart.

Torrent detail redesign belongs to #101. Preserve access to the existing details and RSS handoff while porting Search. Do not redesign the approved surrounding pages.

Confirmed test boundaries: public Search/queue services for routing, saved settings and queue control; desktop/Web public interfaces and real rendering for layout and interaction parity. Live tracker downloads and real client mutations are excluded. Confirmed by the owner on 2026-11-18.

The approved prototype is archived on `prototypes/search-queue-100` at `2cae348c2154a598f5b9614fee8935dfeb0db817`. Production assets live in `web/static/search/`; both hosts call `SearchWorkspace`. The existing details view stays native on desktop and in the existing Web dialog until #101.

Tests of the removed native Search widgets are replaced by public workspace tests, the migrated Search browser acceptance test, and a Wayland test that searches, picks a missing folder, persists it and returns from the queue without losing results. Existing indexer/filter, download queue, send, enqueue-destination and torrent-details domain tests remain. The browser test is included in CI's browser job.

Review corrections preserve completed send errors, refresh client/queue marks and estimates, persist desktop display preferences, and stop polling hidden Web panels. Poster fetching uses a shared disk-cache owner, a bounded panel cache and three concurrent requests. Queue edits check ownership and status in one transaction; retry/remove selections are processed in batches of 1,000 and refresh even after failure.

Validation includes a real Wayland panel at 1280×900 and 800×560, Chromium workflows in English/dark and French/light, a server-folder picker backed by a fake mounted client, and reuse of saved category folders. Screenshots were inspected against the approved layout. No live tracker downloads or real client mutations were used. Standards and spec reviews have no outstanding findings.

Final validation: full suite 2,144 passed / 179 skipped; Chromium acceptance 4 passed; Wayland workflow 1 passed. Ruff lint, formatting for changed Python files, mypy and diff whitespace checks pass. Two pre-existing formatting differences in unrelated files were left untouched.
