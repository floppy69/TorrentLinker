# Archive and repair dialogs for #98

Approved by the owner on 2026-11-18. Reference: local branch
`prototypes/library-repair-archive-98`, commit `b568f97`.

The approved Library page and candidate inspector are unchanged. Archive review,
extraction progress, repair diagnosis, independent-copy preparation, verification,
separate download confirmation and history now use the same bundled dialogs in
Qt WebEngine and the Web iframe. Both use the existing archive and repair services.
Desktop selects a local destination with the native picker; Web browses server roots.

Archive review checks destination and available space before issuing a short-lived
confirmation token. Cancellation is available until client submission begins. The
original archive is retained. The dialog observes the existing verification monitor
and advances to sharing only after the client's state confirms it. Partial archives
share available pieces with every file skipped, without downloading missing content.

Repair remains experimental and qBittorrent-only. Opt-in starts unchecked. Preparing
a copy creates an independent file, adds it stopped and requests verification.
Downloading requires a second confirmation after the client's piece check agrees
with the diagnosis. History reads the persisted repair journal; interrupted or
uncertain sends are never replayed. Source/team and seeder claims are not guarantees.

Job replies are scoped to the active client. Desktop uses a dedicated persisted job
history and the same Operations dispatcher as Web. Closing a dialog does not replay
or cancel client submissions. Switching clients closes dialogs and discards stale
replies. Refreshes preserve the dialog scroll position and draft destination.

The native RepairDialog and old Web archive/repair renderers are removed. Legacy
batch archive selection routes into the shared dialog. Remaining native batch and
disk-rename workflows are outside this change.

Validation uses the pre-agreed public services, desktop/Web interfaces, browser
acceptance and actual Wayland rendering. Tests use temporary files and simulated
clients, never the user's library or live tracker actions.

## Review and visual checks

Separate Standards and Spec reviews found no remaining blockers after fixing
language changes in nested dialogs, archive progress through verified sharing,
and early refusal of unsupported repair clients. The desktop acceptance test uses
real MainWindow/DesktopSetup wiring, substituting only the external client and picker.

Inspected the implemented Web archive dialog and real Wayland repair dialog at
`/tmp/tl98-render/web-archive-confirmation-fr.png` and
`/tmp/tl98-wayland/repair-desktop.png`. Offscreen Qt pixels were unusable, so they
were not used as visual evidence. Full and partial archive workflows and repair
confirmation pass in bilingual browser acceptance.

## Final validation

- Full suite in seven serial Qt-isolated batches: 2,251 passed, 177 skipped,
  no failures. Opt-in browser/live tests remain excluded from that run.
- Bilingual browser acceptance and desktop rendering: seven checks passed,
  including partial archives, repair-history recovery, separate confirmation,
  unsupported clients and language switching. The additional desktop archive
  consent/Activity test passed separately.
- Public archive/evidence service tests pass; real Wayland rendering passed.
- Mypy passes across 231 source files. Changed Python passes Ruff, changed
  JavaScript passes syntax checks, and `git diff --check` is clean.
