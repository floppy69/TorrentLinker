# Windows Library rescan investigation

Issue: [#51](https://github.com/Vietnoirien/TorrentLinker/issues/51).

The user reports a successful first scan followed by a freeze on subsequent scans in the Windows desktop app. On 2026-10-30 the available environment details remained "latest", probably Windows 11, probably local storage. The Windows version and storage location are unconfirmed; "latest" does not identify the installed build.

## Controlled reproduction

`tests/test_library_rescans.py` drives the native `MainWindow.scan` operation ten times in one process. It alternates cached scans with full rescans, changes fixture files between scans, and uses a simulated Torrent Client. A GUI heartbeat releases each client read, proving that the read does not block the event loop. Each pass checks the file sizes, restored scan controls and drained background jobs. Final checks compare the source bytes and close the window.

This test passed on Linux without a scan-code change. It does not reproduce the reported Windows freeze and does not establish its cause. It covers a small local fixture, not a large library, network share or the reporter's Torrent Client.

## Confirmed diagnostic defect

The existing opt-in stall monitor buffered stacks until the GUI recovered. A permanent freeze therefore produced no stack report. `test_permanent_stall_is_logged_before_the_gui_can_recover` failed while the GUI was held on a threading event, with no Qt events processed.

The monitor now writes a sample as soon as the threshold is exceeded and again as the stalled duration doubles. Each sample identifies the GUI and background threads and includes Python stacks without local-variable values. This can show a worker or lock involved in the wait. Recovery logs a short duration message. The regression passes before releasing the blocked GUI; it also verifies that a named background thread is present.

The Library scan, timeout, recovery, filesystem and stall-monitor regression set passed 45 tests on Linux. A dedicated Windows CI job runs the same-process rescan, timeout and stall-monitor checks, builds a diagnostic executable, smoke-tests its packaged media/MCP startup and shutdown, and retains the executable as `windows-library-diagnostics`. The packaged smoke test is separate from the ten-scan source test.

The [Windows job for `47e267b`](https://github.com/Vietnoirien/TorrentLinker/actions/runs/41121968333/job/124289977818) passed all 21 checks, including ten rescans in one source process, and the packaged smoke test. Its [diagnostic executable artifact](https://github.com/Vietnoirien/TorrentLinker/actions/runs/41121968333/artifacts/13008374611) contains the immediate stack logging. This is CI evidence on a clean runner, not a reproduction on the affected machine or a packaged ten-rescan walkthrough.

## Packaged rescan probe, 2026-10-31

The packaged `--smoke-test` now also runs `library_smoke_checks`. It creates a separate
window with temporary settings, 25 local files and a simulated read-only Torrent Client.
It alternates cached scans and full rescans ten times, modifies one fixture file between
rescans, verifies all displayed sizes and source bytes, and requires GUI heartbeat and
background-job completion on every pass. Worker failures are returned to the smoke
command instead of opening a modal warning. The temporary empty keyring is restored
on success and failure.

The new isolation and failure-cleanup tests passed together with the existing rescan,
timeout, stall and shutdown checks: 31 passed. A fresh Linux frozen executable and
AppImage both passed the ten scans, eight media-playback cycles, MCP startup and clean
shutdown with temporary profiles, null credentials and a loopback-only network
namespace. Total times were 5.93 and 7.43 seconds. Neither reported a traceback.

The validated local AppImage had SHA-256 `e0df91fd800977b77485f838be41eb906852fa3e4fd5dc55b84ffa50b283ef89`.
Its source is `e054892` plus the probe and smoke hook committed with this report.
It was not published or installed over the user's running app. Its temporary build,
package and raw logs were deleted at the owner's request after validation to free RAM-backed `/tmp` storage. The same AppImage
also passed controlled upgrades from archived 0.12.2 and beta.27 fixtures in 7.75 and
7.64 seconds. Persisted settings, queue and conversation state and fixture file hashes
matched the expected upgrade result; both original fixture directories stayed unchanged.

Windows CI now runs the probe from source and then inside its packaged executable.
The packaged step enables one-second stall diagnostics and retains the existing
120-second process timeout. The [Windows job at `c2965bb`](https://github.com/Vietnoirien/TorrentLinker/actions/runs/41188641793/job/124500639562)
passed 40 source checks and the frozen Library/media/MCP smoke step. Its
[diagnostic executable artifact](https://github.com/Vietnoirien/TorrentLinker/actions/runs/41188641793/artifacts/13038225855)
contains the rescan probe and immediate stall logging. This
remains controlled-fixture evidence, not the reporter's large Library, storage or
Torrent Client, and does not establish the cause of the original freeze.

## Capture on the affected Windows machine

Use a build containing this diagnostic fix. Close other TorrentLinker instances, open PowerShell in the folder containing the executable, and launch:

```powershell
$env:TORRENTLINKER_STALL_MS = '1000'
& .\TorrentLinker.exe
```

Run the first Library scan and the rescans that normally freeze. If it freezes, leave it open for at least ten seconds so the background monitor can write samples. Find the log with:

```powershell
Get-ChildItem "$env:APPDATA\TorrentLinker" -Filter torrentlinker.log -Recurse
```

Preserve the stalled-thread sections with the exact app build, Windows version, scan type, Torrent Client, approximate Library size and local/network storage details. Review the log before sharing; stacks and surrounding application logs may contain local paths. Clear the opt-in setting afterward with `Remove-Item Env:TORRENTLINKER_STALL_MS`.

The Python monitor cannot report if the interpreter itself cannot schedule its background thread. A missing sample in that case needs a Windows process dump or native stack capture.

## Remaining acceptance

The freeze is not claimed fixed. Obtain a reproduced trigger or affected-machine stacks, then verify the correction with at least ten scans in the packaged Windows executable, responsive UI, preserved results/files and clean shutdown. Keep #51 open until that evidence exists.

## Quadratic search restore after rescans, 2026-11-01

A plausible trigger was reproduced on Linux. Every scan ends by restoring each Local
Item's last search on the GUI thread. For each restored item, `_searches_restored`
checked `entry in self.library_model.entries`, and `set_status` and `set_zen` each walked
every entry to find its row. A first scan in a fresh session usually has nothing to
restore; once items have been searched, each rescan costs time quadratic in Library size.

Offscreen measurements with ten files per item and every item searched: 1,000 items took
0.54 s, 2,000 took 1.89 s and 4,000 took 7.04 s on the GUI thread. Empty candidate lists
were used, so real results cost more. The earlier rescan probes missed this because they
used 25 items and never searched before rescanning.

`LibraryModel` now indexes rows by path when entries are set; restore uses that index.
The same restore takes 0.36 s for 2,000 items, 0.72 s for 4,000 and 1.8 s for 10,000.
`tests/test_library_model.py` fails if a per-item lookup walks the whole Library.

This is not yet confirmed as the reporter's freeze. Keep #51 open until a packaged
Windows build passes ten rescans with searched items, ideally at the reporter's
Library size.
