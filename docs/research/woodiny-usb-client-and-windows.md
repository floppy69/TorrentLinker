# Large client and Windows input reports

Woodiny reports beta.39 freezing qBittorrent while preparing a Plan with about
18,000 torrents. Both programs run on the same Windows PC; the torrents are on a
low-end USB 3 drive. He also reports a missing taskbar icon, Settings extending
below the taskbar, and numeric Plan inputs moving focus and scrolling the page.

## Reproduced causes and changes

- Editing a Plan field called `invalidate → begin → busy(True)`, disabling the
  focused spin box during its own `valueChanged` signal. Qt advanced focus and
  scrolled to another control. Invalidation now clears results without disabling
  inputs. Wheel gestures scroll the form instead of changing numbers, even when
  a numeric input is focused. Settings and per-client budgets use the same controls.
- Settings always opened at 1020 × 720 logical pixels. It now uses the available
  screen area, leaving room for the frame and taskbar. Tests include a 640-pixel
  work area and check that Save stays inside the dialog.
- The desktop kept separate connections for Plan/Library and Profile. Both could
  fetch a full qBittorrent snapshot independently. All desktop workflows now use
  the existing `Connections` cache, including distributed Plans.
- Bulk Library file-list reads had no minimum interval, used a 50% response-time
  duty cycle, and capped the pause at two seconds. They now start at no more than
  five requests per second and aim for 20% measured request time. A slow response
  reduces the rate immediately; the estimate decays by 10% per later response.
  For a 300 ms response the period is at least 1.5 seconds; for a three-second
  response it is at least 15 seconds. This is an application-side budget, not a
  measurement of CPU or disk utilization, and applies to this bulk scan only.
- Desktop and Web scans report completed file lists and the current rate. Web
  cancellation and desktop shutdown interrupt the waiting period. Read file lists
  are cached even if cancellation happens during that wait.
- The app already sets a nonempty Qt icon and embeds an executable icon. It now
  also sets an explicit Windows AppUserModelID before Qt creates windows, as
  [Microsoft documents](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-setcurrentprocessexplicitappusermodelid).
  The Windows CI job checks the OS-reported identity. A visible taskbar check on
  Woodiny's PC is still needed; this is not a confirmed taskbar-icon reproduction.

## Storage probe

The new command samples at most 64 regular files, 256 directory entries and 1 MiB
of file data, with a five-second deadline checked between OS calls. It does not
write media, follow existing symbolic links, clear the OS cache or scan the entire
library. A single stalled filesystem call can exceed that deadline.

On Windows, using the build containing these changes:

```powershell
.\TorrentLinker.exe diagnose-storage "E:\Torrents" --output "$env:USERPROFILE\Desktop\torrentlinker-storage.json"
```

Replace `E:\Torrents` with the folder on the USB drive. The JSON contains timing,
counts and errors, without file names or credentials. Run once while qBittorrent
is idle and once during its usual seeding workload, saving distinct reports.
Do not infer a sustained sequential transfer speed or a safe API rate from this
small, potentially cached sample. API pacing uses actual client response latency.

For a source checkout:

```sh
PYTHONPATH=src python -m torrentlinker.storage_probe /path/to/torrents --output /tmp/storage.json
```

## Local evidence, 2026-11-16

Linux development host, qBittorrent 5.2.4 in a throwaway container limited to two
CPUs and 2 GiB RAM. DHT, PeX and LSD disabled. 18,000 synthetic stopped torrents;
no user torrents or media were accessed. This is not a USB-HDD benchmark.

| Measurement | Result |
| --- | ---: |
| First summary, 18,000 torrents | 3.073 s |
| Incremental summary | 0.228 s |
| Mean of 20 file-list requests | 2.03 ms |
| Selected bulk-read ceiling on that fixture | 5 requests/s |
| Actual desktop Plan, 270,000 synthetic Catalogue rows | 6.008 s |
| Plan client requests | 1 summary, 0 file lists |
| Selected downloads, constrained by temporary disk space | 14 |

The storage probe sampled 64 synthetic local files, read exactly 1 MiB and
reported zero errors. Warm metadata p95 was 0.001 ms and open/read/close p95 was
0.004 ms. These cached results do not describe Woodiny's drive.

Before the fix, all three input/layout reproductions failed, as did the shared
connection check and the bulk-rate cases at 1 ms, 300 ms and three-second latency.
After the initial fixes, the focused suite passed 167 tests, with one Windows-only
check skipped on Linux. Further cancellation and progress checks are included in
the full regression run.

## Remaining evidence

The reported qBittorrent freeze itself has not been reproduced. Obtain Woodiny's
storage reports and test the new build on his USB drive. Confirm taskbar icon,
Save visibility at his Windows scaling, and typing/scrolling in the Plan fields.
Do not close #51 from this Linux evidence; its packaged-Windows rescan acceptance
is separate. #49 tracks broader performance evidence. The unrelated new issues
are #70, duplicate client profiles; #71, saved-secret hints; and #72, Zen weighting.
