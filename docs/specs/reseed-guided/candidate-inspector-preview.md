# Candidate inspector for #97

Approved by the owner on 2026-11-18. Reference: local branch
`prototypes/library-candidate-inspector-97`, commit `6d5de5e`.

The inspector extends the approved Reseed page with a candidate selector and
Summary, Files, Description, NFO and Evidence tabs. Candidate comparison checks
names and sizes; the existing guided Reseed workflow verifies hashes before sharing.
Historical torrent imports stay offline and show association confidence, including
stale evidence after files change. Measurements and processing clues are not proof
of authorship.

Desktop and Web use the same bundled inspector. Candidate review, decisions,
metadata inspection and provenance use `Library.inspector`. UI replies are scoped
to the selected Local Item and client. Background candidate changes update the
inspector without losing its tab or scroll position. Description markup uses the
existing sanitized renderer; external artwork is represented by placeholders.

The duplicate Web candidate/evidence page and native review-dialog entry are
removed. The native ReviewPanel controller remains private for existing batch and
archive operations. Protected repair and archive dialogs now use the approved shared #98 extension
documented in `repair-archive-preview.md`; they do not reopen candidate inspection.

Validation uses the pre-agreed public Library and desktop/Web interfaces. No live
tracker actions or real library mutations are performed by automated tests.

## Implementation validation

- Full suite run in seven serial Qt-isolated batches: 2,248 passed, 174 skipped,
  two failures. Fixed the desktop inspector callback replacing an active run's
  item list and updated the old review-route assertion to the shared Reseed route.
  Both failing tests passed on targeted reruns.
- All five desktop workspace tests pass, including reading candidate details
  while reseeding; all three browser acceptance tests pass.
- Real Wayland rendering passed for the inspector, Description and NFO.
  Inspected `/tmp/tl97-render/candidate-inspector-desktop.png`.
- Mypy passed across 223 source files; changed Python files pass Ruff, changed
  JavaScript passes syntax checks, and `git diff --check` is clean.
- Separate Standards and Spec reviews found no remaining blockers after fixes
  for asset loading, external links, stale replies/candidates, scroll preservation
  and standalone repair-history access.
