# Guided reseeding workspace

The approved `reseed-prototype.html` is the visual reference. Production uses the same bundled HTML, CSS and JavaScript in Qt WebEngine and the Web UI.

The owner approved the Local Items additions on 2026-11-18. See
`local-items-preview.md` and the archived preview at `167716a`: compact folder
and seed-state filters, expandable pack episodes, and Combine in the selection
toolbar. These extend the existing list and inspector without adding another
Library landing page.

## User workflow

- Remise en seed is the Library landing page, with compact item rows and a persistent inspector. On narrow screens the inspector opens as a drawer.
- Réglages exposes client setup and the persistent symlink destination. Adding a tested client selects it.
- Disque lets the user select registered folders and start a scan. Folder creation includes a native picker on desktop and a server directory browser on the Web UI. Dossiers retains the existing folder editor.
- Each item progresses independently through finding candidates, comparison, link preparation, verification and sharing. Ambiguous or incomplete items await review without stopping unrelated items.
- The inspector follows the approved #97 extension in `candidate-inspector-preview.md`: candidate selection, file comparison, Description/NFO, measured evidence and offline provenance. The approved #98 repair and archive dialogs use the same bundled UI in both hosts; see `repair-archive-preview.md`. Originals are not renamed by this workflow.
- Run-wide and per-item pauses take effect at operation boundaries. Local hashing also observes the run-wide pause. Client hash checks may continue inside the client while paused.
- Activity and each item's history use persisted reseed records. Completed steps survive application restart; interrupted work resumes only when requested.

## Execution

The scheduler permits two search/comparison operations and one disk operation concurrently. Link preparation, scanning, verification and starting a verified torrent share the disk lane. A scan publishes completed folder groups as they become available, preserving pack detection, and new items can join an active run. Candidate decisions can requeue completed or blocked items. An item already executing must finish its current operation before its candidate can change.

The workflow retains existing link ownership, path validation, content hashing and stopped-client verification checks. Missing-content downloads and archive repair retain their separate approval flows.

## Validation boundaries

The user approved service-level tests for progression, limits and recovery; public desktop/Web interfaces for client and folder setup; and browser plus real Wayland rendering checks. Automated tests use temporary files and simulated torrent clients, with no live tracker posting or user-library changes.
