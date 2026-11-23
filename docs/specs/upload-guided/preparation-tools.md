# Upload preparation tools, #99

The owner approved the preparation editor preview on 2026-11-18. Reference: local branch `prototypes/upload-preparation-99`, commit `11bd1a3`, file `docs/specs/upload-guided/preparation-tools-prototype.html`.

The shared Upload page opens the approved modal with Details, Files & NFO, Description, Artwork, 3D view and Review. Desktop and Web use `upload/preparation.js` and the same styles, French/English strings and shared theme tokens. The guided page layout is unchanged.

Changes remain attached to the current Local Draft. Background refresh pauses while the modal is open. Saving checks its revision; edits invalidate review. Resetting generated text asks for confirmation. Image-host callbacks retain the existing Postimages origin, popup and request-ID checks. Description images and artwork previews use the safe image fetcher and data URLs in both hosts. No tracker publication occurs automatically.

Archive inspection shows destination, file count, extracted size and available disk space. Extraction requires confirmation against the inspected archive fingerprint, never overwrites a destination, preserves the archive and creates a separate Local Draft for extracted files. The desktop picker grants the selected destination; Web selection stays under server roots. For an archive containing a single top-level directory, that directory's name must be retained when choosing another parent. Jobs expose progress, cancellation and persisted results. Cancellation during extraction uses the existing archive cleanup behavior.

3D inspection lists real files. The live view uses bounded geometry with the approved rotation and tilt controls. These replace the retired editor’s six numeric camera fields and presets; the chosen orientation applies to the selected pieces. Rendering uses the existing CPU renderer and records private immutable presentation assets. Users can save a PNG and select it in Postimages. The renderer's existing format and size limits still apply. Live geometry is limited to 16 MB inputs and 2,000 displayed triangles; larger pieces can still use the render operation. Geometry is illustrative, not a measurement of printing units or physical scale.

Sent drafts offer explicit seeding from Tracking. The service reconstructs the saved torrent, checks its hash and the source snapshot, and submits verification. Cancellation ends before client submission. Desktop verification monitoring starts from worker completion even if the user changes panels or clients. Desktop retains its existing disk-rename consent dialog. Web retains the existing limitation for clients requiring disk renames and directs the user to desktop consent.

The native `UploadTab` and legacy Web editor are removed. `UploadEligibility` only handles Library eligibility and handoff; it constructs no widgets or secondary Upload page. Widget-specific tests for the retired implementation were replaced by shared desktop/browser workflows. Profile/category, upload rules, local revision and tracker-send tests remain at their existing public service boundaries. Library handoff, BBCode sanitization and diagnostic translation regressions are retained.

Validation covers real browser and Wayland rendering, manual sources, persisted edits, language changes within nested confirmations, actual mesh geometry and CPU rendering, archive extraction and original preservation, image-host success/failure, and seeding a persisted sent draft after restart. Clients and tracker posting are simulated; no live torrent was posted or seeded during tests.

Web Upload tabs preserve deep links and Back/Forward navigation through the shared panel.
