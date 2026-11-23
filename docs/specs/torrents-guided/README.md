# Torrents design preview, #84

Status: approved by the owner on 2026-11-19 for implementation in #103.
Uses the current shared panel palette and existing table/inspector components.
One layout, desktop/Web mode switch; no redesign alternatives because the owner
requires coherence with the approved Community, Reseed and Upload components.

Run: python -m http.server 18780 --bind 127.0.0.1 --directory /tmp/torrentlinker-torrents84
Open http://127.0.0.1:18780/?mode=desktop or ?mode=web.

Review paths:
- Switch between one client and All clients; select rows from both and pause/resume.
- Choose visible columns; filter by state, category, tracker or tag.
- Tracker tree dialog drills into tracker + client.
- Select a row, open Files, switch Download/Skip.
- Remove selected rows, with a separate second confirmation when removing files.
- Use the bottom bar for French/English, light/dark, empty/loading/error states.
- At 390 px the inspector stacks below the table; the table has its own horizontal
  scroll rather than squeezing columns. The header filters wrap.

Performance proposal: server-filtered pages of 100 rows, stable selection by
client+hash, saved columns/widths per host, patch visible rows on refresh without
replacing focused controls or resetting scroll. The preview uses 5,200 in-memory
fixtures and pagination; it is not evidence of backend performance. Refresh is a
labelled design expectation, not a running network poll.

Approved parity decisions:
- Shared toolbar provides contextual actions on both platforms; native right-click
  is not required to access any action.
- Tracker hierarchy is available in a compact dialog on either host.
- Cross-client actions identify affected clients before submission.
- Columns and widths will persist in implementation; this preview retains only
  column choices in memory. Width-resizing interaction is not demonstrated yet.

Confirmed verification boundaries: public
Torrent management service for filtering, batch client routing and file priority;
shared desktop/Web panel workflows for selection, refresh, column persistence and
responsive rendering. Fake clients only, no live file deletion/downloads.

Owner-requested additions, 2026-11-19:
- c411 Note and estimated Zen/day columns; optional weight, seeders/peers and seed duration columns. Inspector includes all these values. Non-c411 rewards show unavailable, not zero. Values are fictional; production must show source/freshness and retain documented uncertainty in Zen rules.
- More actions: recheck, reannounce, speed limits, category/tags and current-client location. These are simulated controls, not backend implementations.
- Follow-up #105 transfer proposal: reuse shared storage or copy data to another client's storage. Check path mappings, permissions, available space and duplicate hashes first. Items already on the destination are skipped and reported. Add paused, hash-check, then start and confirm seed before separately offering source removal. Shared storage must never be deleted by source removal. A durable per-item transfer journal should support retry/recovery and retain the source after any failure. Remote copy transport and incomplete-download handling still need capability design; client APIs alone may not provide a copy transport.

The transfer dialog previews the sequence only. It does not validate paths or move files. Speed/location controls simulate confirmation; only category edits change the in-memory rows. Production must disable unsupported actions with a reason for each client.

Sorting/filtering correction:
- Every data column header toggles ascending/descending order with a visible arrow and aria-sort. Numeric values sort numerically; unavailable c411 metrics remain last in both directions. Sorting covers the full filtered dataset before pagination.
- Seed/c411 filters combine network, min/max size, minimum Note/Zen/weight, maximum seeders and minimum seed days with the existing filters. Numeric c411 filters exclude unknown/non-c411 values. Clear filters and an empty-results message are included.
- Direct JavaScript checks passed for numeric order, unavailable values, combined filters and empty results. Browser visual recheck was blocked by the browser connection in this turn.


Implementation #103
-------------------
The bundled `web/static/torrents/` panel is shared by Qt WebEngine and the WebUI.
`TorrentWorkspace` filters and sorts all observed rows before returning pages of
100. Selection uses client ID plus infohash; columns and widths persist per host.
Refresh retains scroll and focused controls. The inspector shows the last successful
client observation time. Zen/Note retain the existing estimator and uncertainty.

Pause, resume, verification, removal and file priorities use the existing protected
management service. Every operation requires a payload-bound review token. Removing
files has a separate confirmation. qBittorrent additionally supports reannounce,
speed limits, category/tag additions and changing the current-client location.
Other adapters show unsupported controls disabled with an explanation. Client
transfers remain exclusively in #105. The archived preview's transfer dialog is
not part of this implementation.

Tests exercise public services with simulated clients, browser workflows and the
production DesktopOperations integration in Qt WebEngine. No live torrents or
files are changed by these tests.

Owner follow-up: minimum and maximum size each have a small MiB/GiB toggle. Switching converts the value and preserves the size threshold, independently for each bound.

Inspector completion #104
-------------------------
The retained Summary/Files/Trackers layout is unchanged. A file's Download/Skip
choice continues to show the observed setting while its command awaits review;
cancelling leaves that setting intact. Confirmation lists the selected filenames
and sizes. The service binds the client's original file indexes and listing to the
review, rejecting changed files until reviewed again. Browser and Wayland checks
cover cancellation and applied priorities; service tests include non-contiguous
indexes and changed-file rejection. Live files and torrent clients remain excluded
from these tests.
