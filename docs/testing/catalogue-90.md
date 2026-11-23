# Shared Catalogue, issue #90

Desktop and Web load `static/catalogue/view.html`. The old native category tiles and the Web update-only markup have been removed. Both hosts show category coverage, Fetch only, Fetch all, pause/resume, phase progress and cached-only categories. Counts and checkpoint states come from `catalogue_workspace.catalogue_cards`; fetches still use the existing resumable catalogue services.

The Web owner job API now accepts an allowlisted `catalogue_root`. A single-category request reaches `fetch_root` on c411 and the mapped Torznab categories on other indexers. It does not fetch unrelated roots. A Web fetch remains owned by the server across navigation, client switching and reload. Native fetches retain their existing desktop worker ownership. Stop fetching and plan now uses cached metadata and never sends the resulting Plan automatically.

Strings and coverage notes use the shared view's English/French labels and shared light/dark tokens. c411 category names remain the site's names. XXX remains cache-only and is hidden unless the owner enables adult content. General indexers retain their existing paging behavior; c411 parity/pruning is only available for c411.

## Verification

Public owner API and native view regressions were red against the old controls and pass after migration. Browser checks cover one-category and all-category fetching, pause/resume, reload recovery, failure/retry, client switching, English/French, both themes and 390-pixel content fit. A held idle-poll response reproduced a race that temporarily hid a newly started fetch; job identity now survives stale polls, and a terminal job cannot be revived by a late response.

A real-display xcb check rendered English/dark and French/light synthetic categories on DP-4 at 1280 × 800. The French/light capture was inspected. Tests use temporary databases, fake clients and a mocked indexer HTTP transport; no live tracker or user-library changes are involved.

The outer shell and Plan renderer are separate backlog work. The installed editable package remains 1.0.0b43; these changes do not create a release.

The focused regression run passed 106 tests and identified one remaining reference to the removed native button. After migrating that controller test to its public request signal, the test and browser capture workflow both passed. Ruff, formatting, mypy and whitespace checks pass. [Desktop rendering](catalogue-90-desktop.png) and [Web rendering](catalogue-90-web.png) captures were inspected.

Review regressions: all 7 passed after fixing native-root progress for overlapping Torznab IDs, desktop non-c411 Fetch-only scope, delayed cancellation ownership/completion and competing Catalogue submissions. Identical pending requests reuse their job; a different request is rejected while the shared cache is fetching. Plan-now intent is recorded before cancellation, pinned to its client, and rolled back if cancellation fails.
