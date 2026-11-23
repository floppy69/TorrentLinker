# Interactive Web jobs

Issue: #64.

The Web job manager has one batch worker and one interactive worker. Explicitly
listed read-only actions use the interactive worker, including the shared Search
workspace's job names and single-item Library searches. Unknown actions and all
client or disk mutations use the batch worker. Deduplication, the global queue
capacity, and existing permission checks still apply.

Batch Indexer requests use background priority. Interactive requests use foreground
priority under the same API quotas. The reseed board sets background priority in
each pool worker because request contexts are thread-local. A cancellation event
interrupts quota pacing and retry waits. No additional batch worker or API quota
is introduced.

Library scans build a replacement privately and publish it when complete.
Interactive jobs pin the published entries before starting. The reseed board
receives completed-folder discoveries through an internal callback and gives each
item worker a private snapshot, preserving its scan/search pipeline without
publishing a partial Library.

The Store already serializes SQLite access. Torrent metadata cache writes now use
unique temporary files and atomic replacement. Concurrent downloads of the same
candidate share one fetch lock. A foreground request encountering a long batch
backoff reports the rate limit promptly; it does not issue a duplicate download.
Torrent Client calls sharing a Web session are serialized per API call. Agent
read completion cannot clear another job's download authorization guard.

The desktop job coordinator retains its existing scheduling policy. This change
does not add a second desktop mutation worker.

## Validation

Focused tests cover both lanes, mutation serialization, Search job aliases,
foreground request priority, scan publication, reseed discovery pipelining,
metadata fetch deduplication, atomic cache writes, session serialization,
cancellable backoff, and agent guard ownership. Existing browser, reseed,
Indexer, audit, Plan, client-profile, and job-deduplication regressions also pass.
