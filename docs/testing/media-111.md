# Shared compact Media chat, issue #111

The desktop and Web Media side panels load the same `assistant/view.html` as the full Assistant. Compact mode keeps the existing title, recent discussions, More menu, transcript and composer. The old compact native mode and duplicate Web renderer/cards are removed. Settings forms remain for #112.

## Verification

Public workflows use temporary libraries, a simulated Assistant provider and local test servers. They cover sending, draft retention across discussion switches and reopening, settings, opening the same discussion in Assistant, English/French, both themes, narrow layouts and Escape. Existing full Assistant tests cover inline approval and provider settings.

The desktop narrow layout preserves the saved splitter width. A Settings window replacement reconnects Media's discussion and connection actions to the new window; the retained-player regression checks discussion routing.

Delayed-response checks keep the previous composer inert while a discussion switch loads, and require a fresh playback report before submitting while another heartbeat is in flight. Both checks pass in the browser workflow. The native bridge publishes its report synchronously before acknowledging submission.

The focused run passed 7 tests covering compact chat on both hosts, retained-window routing, Torrents startup and Reseed browser workflows. CI now includes the Media video, music and compact chat browser workflows.

## Related CI fixes

Torrents ignored its ready handshake when host language/theme updates arrived before deferred view initialization. Registering its environment listener after DOMContentLoaded removes the startup exception; a browser regression injects an early environment event. The Music metadata test reads textContent because the responsive layout intentionally hides the album column below 600 pixels.

## Platform limits

Native video decoding, partial downloads and player controls remain under #89/#110. Chat widths persist per device, in native settings or browser storage. This change does not alter providers, run limits or tracker authorization. No live tracker or Torrent Client actions were performed.

The launch checkout is `/home/viet/git-perso/TorrentLinker`, used by the editable `.venv/bin/torrentlinker` launcher. Package metadata remains 1.0.0b43. The running app is not restarted, and the companion extension is unchanged.

## Final local results

The complete suite passed with 2,120 passed and 206 optional tests skipped. Ruff check/format, mypy and whitespace checks pass. The real-display compact-chat workflow passed on DP-4 using xcb with GPU rendering disabled. English/light and French/dark captures were visually inspected at 1280 × 720; the composer stays within the panel and the outer chat scrollbar is gone. Other language/theme combinations were exercised in the same workflow.

The same focused review covered standards and the issue specification. Both rechecks found no remaining actionable findings after fixing the discussion-switch race, fresh-context submission and retained-window routing.

Expanded browser acceptance: 69 tests passed; the sole failure loaded the deleted legacy chat renderer. That regression now loads the shared Assistant view and styles, with its command-summary, escaping, syntax-coloring and refresh assertions unchanged. The corrected test and final compact browser workflow passed together, 2 passed. The final browser screenshot was inspected in French/light mode; the browser workflow also checks the 390-pixel layout.

[Desktop capture](media-111-desktop-fr-dark.png) · [Web capture](media-111-web-fr-light.png)
