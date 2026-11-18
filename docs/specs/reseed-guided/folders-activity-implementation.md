# Library Folders and Activity, issue #95

The owner approved the dialog extension on 2026-11-18. The reference is archived
locally at `e5d8f962` on `prototypes/library-folder-dialog-95`, in
`docs/specs/reseed-guided/folder-dialog-prototype.html`.

The existing Reseed bundled view now owns Folders, Add/Edit Folder and Activity
on desktop and Web. The approved page structures remain. The dialog adds
content kind, Automatic/depth grouping and a live Local Item preview. Removing
a registration requires confirmation and keeps its files. The native Library
folder modal, native Add Folder dialog and old Web folder/activity forms are
removed. Settings still uses its existing folder editor pending #113.

Preview reads run off the desktop UI thread and through a read-only setup API
on Web. The form debounces changes, permits one preview request at a time and
ignores results for replaced forms or clients. It displays at most eight sample
names, with total item/episode counts. Web paths must remain under configured
storage roots. Saving returns the canonical path for a subsequent selected-folder
scan. Path edits and removal preserve pending-verification protections.

Depth 0 now keeps the selected folder whole during scanning, matching its
existing selector and the preview. This corrects the previous empty result.

## Platform limits retained

- Desktop Browse uses the system directory picker. Web Browse selects paths on
  the TorrentLinker server; it does not upload a browser-local directory.
- Both Activity pages show persisted per-item workflow events. Desktop also
  retains the last 300 session status messages, as its old log did. Web includes
  its persisted Library jobs. Known Web job kinds/statuses are translated.
- The approved shared Activity page remains a read-only event list. Web job
  Cancel and Details remain available on the existing global Activity page.
  Reseed pause/resume controls remain on the approved Reseed page.

## Verification

The pre-agreed setup, desktop/Web interface and rendering boundaries use
temporary files and simulated clients. No live tracker action is part of testing.
The API preview and missing dialog checks failed before implementation, then
passed. The targeted serial run passed 72 tests, including real Wayland rendering
and browser workflows. Review found pending-verification protection for path
edits and canonical scan paths; both were fixed and covered by regression checks.
Both review axes have no remaining blocker.

The full offscreen run completed 1,628 tests with 136 skips and no failures
before a cumulative Qt palette slowdown in `test_theme.py` made progress
impractical. It was interrupted cleanly; the remaining 60 files (including
the whole interrupted file) passed in a fresh serial process: 625 passed,
36 skipped. Together the runs cover the collected suite; display-dependent
checks were also run separately as described above. Ruff, mypy and diff checks
passed.
