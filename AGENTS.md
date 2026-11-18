# TorrentLinker

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues on `Vietnoirien/TorrentLinker` via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Local application and releases

When updating the app or publishing a release:

- Prefer the canonical checkout for routine edits. Use another worktree only when the task needs branch isolation, then reconcile it with the launch checkout before completion.
- Identify the checkout, Python environment or binary, and companion extension used by the user's actual launcher.
- Audit that checkout's uncommitted feature files and local-only commits before choosing the release commit. Incorporate the requested work and preserve unrelated edits with a recoverable backup.
- Synchronize the user's launch checkout after integrating work from another worktree. Refresh editable-install version metadata and companion files when they change. Verify the expected feature and versions from that launch path.
- On this workstation, the browser loads `dist/torrentlinker-companion` as an unpacked extension. Refresh that directory from the packaged companion when its code changes; changing `src` alone does not update it. Browser Reload is still required.
- Report committed, published, locally installed, and currently running versions separately when they differ. A GitHub push or app relaunch does not update an older local checkout.
- For an authorized publication, monitor CI and release builds through completion and verify the downloadable assets before announcing availability.
