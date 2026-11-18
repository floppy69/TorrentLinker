# Shared panel base, issue #77

The owner approved the trimmed component reference on 2026-11-18. Existing Community, guided Reseed and guided Upload layouts remain authoritative. This change extracts shared code without redesigning those pages.

## Implementation

- `web/static/panel/base.css` contains identical dark palette tokens. Panel styles retain their layout and source-specific overrides, including light palettes.
- `panel/transport.js` implements the existing per-panel Web messaging protocol with origin and parent-window validation. Desktop Community retains its callback-based request bridge; Reseed and Upload retain asynchronous response signals. The small panel entry files select their existing bridge.
- `panel/i18n.js` provides the bilingual helper. Reseed and Upload translate UI labels explicitly; file names, paths, tracker metadata, user content and API values are not translated.
- Upload forwards Web language-change events. Its editor preserves unsaved text and workflow confirmation checkboxes when rerendered. Open forms preserve input and focus while their labels change.
- `BundledView.language` resolves the automatic system-language setting consistently. The desktop interceptor allows only the three named shared files alongside existing panel files. The hidden QQuickWidget guard and Wayland workaround are unchanged.
- Package data includes the new shared directory.

## Verification boundaries

The owner confirmed browser and desktop public panel interfaces for language switching and existing interactions, plus bundled asset loading. Tests use isolated storage and simulated clients/hosts. They do not submit to c411 or touch the user's clients.

Regression coverage includes French/English controls, dirty descriptions, open-form paths, confirmation/review checkboxes, native automatic French locale, rejection of unbundled scripts, and stable native window identity. Existing panel workflows cover service responses, persistence, verification and image-host success/failure.

The TDD checks first reproduced untranslated controls, missing Web language forwarding, stale open-dialog labels and cleared confirmation state. Each passed after its corresponding fix. Tests run serially. Ruff and mypy pass.

## Review

Standards and spec reviews against pre-work commit `1a5bdcf` found automatic-language resolution, workflow checkbox preservation, remaining translated captions and a displaced strict-mode directive. These were fixed and rechecked. Neither review has a remaining blocker.

## Local launch

`~/.local/share/applications/torrentlinker.desktop` launches `/home/viet/git-perso/TorrentLinker/.venv/bin/torrentlinker`, whose editable package resolves to this checkout's `src/torrentlinker`. The running application was not restarted. No version bump, companion change, publication or tracker write is part of this change.

Final serial regression run: **88 passed** across Community interfaces/browser, Reseed service/browser, Upload workspace/view/browser and the real-display startup guard. Mypy reports no issues in 231 source files; Ruff and whitespace checks pass.

## Native and Web theme alignment, issue #78

`panel/base.css` now owns both default palettes. Qt reads its two literal token blocks; the Web shell loads the same stylesheet before `app.css`. The default light palette comes from the existing native and Upload design. Approved panel-specific light overrides and the separate Media design remain unchanged.

The duplicate Web dark palettes are removed. Web automatic mode resolves the system color scheme and follows changes, while explicit light or dark choices remain fixed. Accent-filled controls use the shared foreground token for readable contrast in both modes. No layout or navigation changes are included.

Verification: 11 tests passed across native theme selection, browser theme switching and Profile interactions, and the real-display first-panel window check. Ruff, mypy and whitespace checks passed. Tests use isolated data and do not send tracker actions.
