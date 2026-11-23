# Shared Torrents performance baseline

Measured for #49 on 2026-11-20, from application commit `85c690f` before the parsing cache, then with the cache in this change. This supersedes the retired native table for current app measurements. [Raw samples](shared-torrents-performance-2026-11-20.json) include every refresh.

The environment is the same Intel Core i9-9900KF workstation, 125.7 GiB RAM, now Linux 7.2.13, Python 3.13.11 and Qt 6.12.0. Each count runs in a separate process with temporary settings, an empty catalogue and an immediate synthetic client. No real client, tracker, keyring or user configuration is used.

The benchmark renders the actual shared Torrents panel through its Qt host and desktop operations. It waits for the complete asynchronous load, including pending reloads. The fixture has four trackers, 24 category paths, 33 tags, long names and changing rates/ratios. It checks the 100-row page limit, filtering to one result, clearing the filter and selection retention after a fresh client snapshot. The shared backend is used by Web as well, but these are desktop-host measurements, not browser-network or packaged-platform measurements.

Run one size at a time:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark_shared_torrents.py --count 1000 --output /tmp/shared-1000.json
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark_shared_torrents.py --count 12000 --output /tmp/shared-12000.json
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark_shared_torrents.py --count 50000 --output /tmp/shared-50000.json
```

The former `benchmark_torrents.py` entry point delegates to this current benchmark.

## Results

Milliseconds, before → after bounded tracker-host parsing caches. Refresh values are medians of three samples. Timings include a 20 ms event drain; filter changes exclude the typing debounce.

| Torrents | First useful content | Changing refresh | Clear filter |
| ---: | ---: | ---: | ---: |
| 1,000 | 527 → 497 | 90 → 86 | 75 → 76 |
| 12,000 | 870 → 771 | 349 → 262 | 181 → 169 |
| 50,000 | 2,201 → 1,707 | 1,342 → 1,007 | 510 → 404 |

Profiling the 50,000-row initial load counted 300,000 calls to tracker classification and 700,000 hostname property reads. Pure URL-to-host parsing is now cached in memory, with each cache bounded to 1,024 entries. This changes no classification rules. URLs never enter exports or persistent caches. Existing tests cover changed announce lists, unrelated domains, c411's backup domain and distinct Indexer hosts.

The first display includes WebEngine initialization. Qt's event heartbeat measures the application thread; renderer timer callbacks did not produce samples in the offscreen environment and are reported as null. App peak RSS excludes renderer subprocesses, so it is not a total application-memory figure and cannot be compared directly with the old native table's RSS. The rendered 50,000-row page was inspected.

## Remaining work

The 50,000-row filter expansion target of one second is met by the shared panel. First display remains above one second, and the 12,000-row changing-refresh target of 250 ms is narrowly missed. The benchmark does not establish cancellation latency, installed Windows performance, remote client latency, large populated-catalogue cost or Woodiny's USB-drive behavior. #49 remains open for those targets and measurements.

Validation: the benchmark completed at all three sizes before and after the change; 82 tracker, Zen, seeding and workspace tests passed. No machine-dependent timing threshold is asserted in CI.
