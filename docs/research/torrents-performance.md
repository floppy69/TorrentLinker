# Native Torrents performance baseline

Historical measurement of the retired native table. The current shared panel is
measured in [the November 20 report](shared-torrents-performance.md). The benchmark
command now runs that panel; check out the dated baseline revision to reproduce the
native table measurements below.

Recorded on 2026-10-31 for [#49](https://github.com/Vietnoirien/TorrentLinker/issues/49).
The baseline is `f1cbef1`; the follow-up is the implementation committed with this report.
[Raw measurements](torrents-performance-2026-10-31.json) retain all three refresh samples.

## Method and environment

Intel Core i9-9900KF at 3.60 GHz, 16 logical CPUs, 125.7 GiB RAM; Linux 7.2.11,
Python 3.13.11, Qt 6.12.0, offscreen platform. Each size ran in a separate process
with fresh temporary settings/data directories. The fake Torrent Client returns
synthetic torrents immediately; no Indexer or real Torrent Client is contacted.

The fixture has four trackers, 24 category paths and 33 personal tags, including
one tag shared by every torrent. It includes long names, downloading and seeding
states, changing rates/ratios, and a selected torrent. Each process measures first
display, three unchanged refreshes, three changing refreshes, selection preservation,
filtering to one row and clearing that filter. A 10 ms Qt heartbeat measures gaps
while the UI thread is busy. Timings include a 20 ms heartbeat drain after each
operation; peak RSS includes imports, fixture construction and the whole view.

Reproduce from the repository root, one size at a time:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark_torrents.py --count 1000 --output /tmp/tl-perf-1000.json
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark_torrents.py --count 12000 --output /tmp/tl-perf-12000.json
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark_torrents.py --count 50000 --output /tmp/tl-perf-50000.json
```

This is a workstation baseline, not a supported-hardware speed guarantee. Real RPC,
disk/network latency, Windows packaging, chat histories, large mutation selections
and cancellation delays are not measured here.

## Results

Elapsed milliseconds; refresh columns are medians of three samples.

| Torrents | First display before → after | Unchanged refresh before → after | Changing refresh before → after | Peak RSS before → after |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 199 → 117 | 33 → 30 | 76 → 46 | 119 → 119 MiB |
| 12,000 | 1,925 → 765 | 116 → 91 | 472 → 152 | 147 → 147 MiB |
| 50,000 | 8,273 → 3,220 | 454 → 319 | 1,876 → 563 | 244 → 244 MiB |

The maximum heartbeat gap during changing refreshes fell from 519 to 192 ms at
12,000 torrents and from 2,062 to 715 ms at 50,000. First display still blocks for
about 3.17 seconds at 50,000. Clearing a one-row search still takes about 2.65 seconds
at 50,000; this path must sort the newly visible rows. Those remaining stalls are
recorded rather than treated as resolved.

## Confirmed costs and fixes

Profiling the 12,000 fixture showed full sorting invalidations during grouping,
tag rebuilding and filtering, plus repeated filter checks for rate/ratio changes.
Two deterministic regressions reproduced 684 unnecessary sort comparisons after
an unchanged filter and 256 filter checks for two irrelevant columns on 128 rows.

The view now preserves the sorted proxy for unchanged filters and uses row-filter
updates for changed predicates. It explicitly recomputes sort/filter results when
the changed data affects them. Status dependencies include progress, not just the
raw client state. State/tag counts are collected in one pass rather than rescanning
all torrents per tag. This retains existing Qt sorting behavior and exact selected
hashes. Qt's [proxy documentation](https://doc.qt.io/qt-6/qsortfilterproxymodel.html)
distinguishes full sort/filter invalidation from row-filter changes; the implementation
keeps a fallback for Qt versions before `endFilterChange` was introduced.

Older saved 12-column headers need one reconciliation after their first populated
refresh when migrating to the 14-column table. The existing header migration test
caught invalid serialized state when that formerly incidental full invalidation was
removed. The explicit one-time reconciliation preserves hidden columns and widths;
it is not part of the fresh-profile timings above.

Screenshot inspection also found that every tag received a permanently visible
sidebar row. Just 100 tags forced the window to 2,043 pixels high. Lists now show
at most eight rows and scroll, preserving access to the tracker tree. A separate
12,000-torrent/1,001-tag fixture opens in 705 ms, has a 149 ms median changing refresh
and peaks at 151 MiB. This is a follow-up observation, not a matched before/after
comparison for that tag count.

## Validation and next targets

The native Torrents tests cover sorting, exact selection retention, changed
name/tag/category membership with unchanged group counts, progress-driven status,
column preferences, connection changes, file priorities and explicit destructive-action
confirmation. The broader native/client/seeding/shutdown/browser suite passed 129 tests
before the final sidebar cap; all 37 native Torrents tests then passed with that cap.
The 50,000-row and many-tag screenshots were inspected. Lint, formatting and typechecking
passed before committing this batch.

For this same fixture and workstation, retain a sub-second first display and a median
changing refresh below 250 ms at 12,000 torrents. At 50,000, target a first display and
filter expansion below one second and changing-refresh heartbeat gaps below 250 ms;
these are follow-up targets, currently unmet. Do not turn machine-dependent timings
into universal CI assertions. Extend the baseline to queues, chat histories,
cancellation and installed Windows before claiming the performance audit complete.
