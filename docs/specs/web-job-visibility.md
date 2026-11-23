# Web job visibility

Issue: #65. Builds on the two execution lanes in #64.

Jobs persist an allowlisted subject: paths, torrent hashes, draft/repair/Plan/feed
identifiers and workflow action names. Request bodies, torrent data, Candidate
URLs and confirmation credentials are excluded. Diagnostics still query only
kind, status and client. Existing databases gain an empty subject column without
replaying work.

The jobs endpoint includes every pending job plus the latest 100 finished jobs.
Queue position and predecessor are calculated within each execution lane, across
clients, because those clients share the lane's worker. Long batch jobs remain
visible after many newer interactive completions.

The Web header badge opens Jobs. Jobs has an explicit refresh button. Each page
shows its current and most recent jobs, with subject, progress and cancellation
when permitted. Polling detects terminal transitions without depending on a
page's callback map, then refreshes the affected active page.

Library uses its existing shared panel polling. Its job strip, Local Item badges,
Candidate action buttons and Activity show persisted status and progress.
Pending per-item work takes precedence over newer finished inspections. Terminal
Candidate changes invalidate the selected inspector's cached result; read-only
refresh jobs do not invalidate themselves. Manual Refresh also reloads Candidate
results. The Download queue has an explicit Refresh control; RSS retains its
existing Refresh all control.

The desktop panel retains its existing host data contract. Web-only job controls
appear when the host supplies the jobs snapshot.

## Validation

Backend tests cover subject persistence and exclusions, diagnostics, lane-local
queue order, and active jobs surviving more than 100 later completions. Browser
checks cover an API caller updating an open Candidate inspector, queued/running
progress, reload during a job, live Activity, terminal status, and header
navigation. Existing Library workflows and Search/queue navigation are checked
alongside the new cases.
