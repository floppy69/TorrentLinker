# Desktop and web polish assessment after ReleaseScore

Issue: [#48](https://github.com/Vietnoirien/TorrentLinker/issues/48). Assessed on 2026-11-20 against source revision `8c0286891e691cf0eed2a432c0ea5be8fb05ebf6`, plus the job-language correction accompanying this report.

## Decision

Keep #48 open. The exercised workflows pass after repairing an obsolete acceptance test and a visible language-switch defect. This is useful source-level evidence, but it does not complete the issue's paired state, accessibility and deployment matrix. No release-readiness claim follows from this run.

The canonical checkout and its `.venv` supplied the application. Chromium exercised temporary WebUI servers; Qt used `QT_QPA_PLATFORM=offscreen` with GPU disabled. Tests used isolated configuration directories, local files, simulated Torrent Clients and mocked services. They did not publish tracker content or use the operator's library. Installed metadata remained `1.0.0b43`; the operator's running application was not restarted or upgraded.

## Results

- Initial walkthrough: 53 passed, one failed, in 248.91 seconds. The failure was an obsolete Library selector, not a missing current capability.
- Extended Library, Torrents, Seeding, setup/queue and Assistant run: 17 passed, one audit-harness error. The error came from a string predicate rejected by the page's Content Security Policy. Replacing it with a CSS expectation made the isolated mobile scenario pass.
- Job-language regression: failed before the correction with `Refresh clientRunningCancelRefresh clientDone` still visible after selecting French while polling was delayed.
- Final focused Torrents, Settings, tool Activity and Assistant Activity run: 23 passed in 39.83 seconds. The corrected Library test and Seeding translation assertions passed in the extended run.
- Python lint/format, JavaScript syntax and whitespace checks passed for the changed files.

These runs overlap; their counts must not be added as unique coverage.

## Findings and corrections

### Task labels did not change language until the next successful poll

Reproduction: open Torrents with a refresh job displayed, delay `GET /api/jobs`, then switch from English to French. The shared shell and Torrents panel translated, but the task title, status and cancellation button remained English. Activity cards used the same delayed rendering path.

The shell now retains the last displayed job rows and translates them immediately when the language changes. This uses the existing data and does not retry work or request another update. Logout clears the retained rows. A browser regression delays polling and verifies translation before allowing the requests to finish.

The inspected [French mobile capture](../testing/polish-48-2026-11-20/torrents-mobile.png), at 390 × 844, shows the corrected title and completed status.

### Library acceptance still targeted the replaced review dialog

The test tried to open `Review files and repairs` and inspect the old outer-page candidate table. The current UI uses the inline candidate inspector. The migrated test checks file comparison, metadata evidence, historical `.torrent` import, verified provenance, French translation, candidate rejection and folder setup through that inspector. It now runs in the browser CI job, so this workflow cannot silently age outside that job again.

The inspected [French evidence capture](../testing/polish-48-2026-11-20/library-features-web-fr.png) uses a 1600 × 1000 viewport. It is taken after scrolling the inspector; it is not a full view of all provenance content.

### Early mobile captures were misleading

A Torrents capture taken immediately after resizing showed a large blank navigation area. Waiting for the compact navigation height succeeded without changing production layout. Likewise, waiting for the actual French Seeding filter placeholder produced translated controls. Neither initial screenshot establishes a persistent layout or translation defect.

The narrow Plan and RSS captures still warrant a manual scrolling and keyboard pass: the outer shell occupies much of the initial viewport, while panel content scrolls within an iframe. Existing click tests establish reachable controls, not comfortable use at increased text size.

## Coverage and limits

| Area | Exercised in this assessment | Remaining evidence |
| --- | --- | --- |
| Shell and Settings | Client scope, bilingual navigation, small desktop sizing, drafts, failed saves, secret handling, shared controls, ReleaseScore persistence | Full keyboard and text-scaling walkthrough across all sections; installed desktop appearance |
| Zen | Profile pairing/disconnect, Plan limits and units, review/send/stop, destination scope, errors, selection preservation, Seeding search/filter/sort/paging with 10,001 torrents | Every state in both hosts, complete Catalogue/Community walkthrough, narrow Plan scroll usability |
| Library | Scan/folder management, inline candidate review, provenance, rejection, pause/reload, long paths and original-file preservation | Paired desktop screenshots for every inspected web state; installed remote/path-mapping walkthrough |
| Search and queue | Listing/details, ReleaseScore, profile changes, row selection, queue review, sent/uncertain entries, keyboard context menu | Paired empty/loading/failure/recovery captures and text scaling |
| Torrents | Filters/sort/columns, refresh selection, audit/export, desktop-width and narrow web layouts, French job labels | Complete native/web state matrix and long-name keyboard pass |
| Upload and RSS | Isolated guided upload/host-failure scenarios, rules/categories, cancel/save locking, language/theme cases | Complete album and multi-piece 3D walkthrough; paired desktop states |
| Media | Shared video browse/details, native host handoff, resume removal, web light/dark and French rendering | Actual packaged playback/codec work remains separate in #122; full music and failure-state walkthrough |
| Assistant and Activity | Simulated provider, conversations, composer, questions/approvals, safe tables, scheduled-task editor, tool-error details, chronological updates and long summaries | Current full-window paired visual evidence, every global Activity state, real model observation |

The source tests include English/French, light/dark, 390-pixel web layouts and smaller Qt windows, but not every combination for every workflow. MCP capability parity was not independently re-audited in this pass. Windows installed executable, Linux AppImage and reverse-proxy Docker checks were not performed here.

## Preserved evidence

The Search fixtures use the same listing data in the two hosts. The inspected [desktop capture](../testing/polish-48-2026-11-20/search-desktop.png) and [web capture](../testing/polish-48-2026-11-20/search-web-en-US-dark.png) are both 1280 × 900. They show different selected profiles and queue states, so their numeric scores are not a parity comparison. Numeric parity is established separately by #117's upstream reference cases.

Additional local screenshots and logs are in `/tmp/tl48-20261120`. Those temporary files are not durable release evidence. The offscreen native Assistant grab did not paint its transcript sufficiently for visual review; its passing interaction assertions must not be presented as a successful screenshot review.

Next closure work should use the current launch build for the missing paired states, keyboard/zoom checks and deployment matrix. Preserve the distinction between a demonstrated defect and a missing observation.
