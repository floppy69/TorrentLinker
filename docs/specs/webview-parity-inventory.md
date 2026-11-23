# Shared-WebView design: surface inventory and desktop/Web parity gaps

Snapshot of `main` at `2ad7523` (2026-11-18). Read-only survey; nothing implemented yet.
Paths are relative to `src/torrentlinker/` unless they start with `docs/`.

Legend: **BV** = already a `BundledView` (`gui/community_view.py`). **Native** = Qt widgets.
Status: **Done**, **NU** (needs update), **DO** (desktop-only), **WO** (Web-only).

How the three BV panels work: desktop loads `view.html` in a QWebEngineView with a QWebChannel
bridge; the Web hosts the same `view.html` in an iframe with postMessage. Only `transport.js` differs.

## 1. Inventory

### Zen

| # | Surface | Desktop | Web | Status | Spec | Blockers |
|---|---|---|---|---|---|---|
| 1 | Profile / Profil | **BV** `ProfileView` (`gui/profile_view.py`) | `profile.js` iframe, shared `static/profile/` SVG renderer | **Done** (#91) | `profile-redesign.md` + mockup | None; period, history and charts shared |
| 2 | Seeding / Seed | Native `SeedingView` (`zen_view.py:89`), `seeding_tree.py`, `ClassComparison` | `zen.js`, `index.html:563-587` | NU | none | Large sortable grouped tree, 30 s refresh |
| 3 | Plan | Native `PlanView` (`zen_view.py:496`) + plan dialogs in `main_window.py` | `plan.js`, `index.html:588-647` | NU | none | Native folder pickers, speed test, send progress |
| 4 | Catalogue | **BV** `CatalogueBox` (`gui/catalogue_view.py`) | `catalogue.js` iframe, same `static/catalogue/` view | **Implemented #90** | Approved `interface-backlog/` prototype | Shared coverage, per-category/all fetch, pause/resume and progress |
| 5 | Community / Communauté | **BV** `CommunityView` | `community.js` iframe | **Done** | `community-redesign/` (WebView) | reference implementation |
| 6 | Zen band (footer) | **BV** shell band in status bar | Same bundled shell band | **Done** (#115) | `shell-shared-implementation.md` | Host status messages remain separate |

### Library / Bibliothèque

| # | Surface | Desktop | Web | Status | Spec | Blockers |
|---|---|---|---|---|---|---|
| 7 | Reseed landing | **BV** `ReseedBoard` | `reseed.js` iframe | **Done** | `reseed-guided/` (WebView) | folder picker vs server browser (deliberate) |
| 8 | Local Items + candidate review | **BV** shared Local Items and candidate/evidence inspector | Same bundled list and candidate/evidence inspector | **Done** (#96/#97/#98) | `reseed-guided/local-items-preview.md`, `reseed-guided/candidate-inspector-preview.md` | shared filters, packs, Combine, decisions, details and offline provenance; shared approved archive/repair confirmations |
| 9 | Library Folders | **BV** `ReseedBoard` Folders page | Same bundled Folders page | **Done** (#95) | `reseed-guided/folders-activity-implementation.md` | Settings editor remains separate (#113) |
| 10 | Add/Edit Library Folder | Shared dialog with live Local Item preview | Same dialog and read-only preview API | **Done** (#95) | Approved dialog archived at `e5d8f962` | native picker vs server browser (deliberate) |
| 11 | Activity / Activité | Shared event list plus session status log | Same event list plus persisted Library jobs | **Done** (#95) | `reseed-guided/folders-activity-implementation.md` | Web job Cancel/Details remain in global Activity |
| 12 | Disk-rename consent | Native `ReseedConsent`, `RenameDialog` | none; Web refuses (`web/library.py:576`, `web/archives.py:70`) | DO | ADR-0013/0017 | — |
| 13 | Unpack-and-reseed and Repair Copy | **BV** shared approved dialogs | Same bundled dialogs and job services | **Done** (#98) | `reseed-guided/repair-archive-preview.md` | native destination picker vs server browser |
| 14 | Repair-copy dialog | **BV** shared repair/history/confirmation dialogs | Same bundled dialogs | **Done** (#98) | `reseed-guided/repair-archive-preview.md`, `library-evidence.md` | experimental qBittorrent-only independent copies |
| 15 | Evidence panel | Native `LibraryEvidence` (ReviewPanel tab) | `#candidate-evidence` | NU | `library-evidence.md` | file chooser, MediaInfo |

### Upload

| # | Surface | Desktop | Web | Status | Spec | Blockers |
|---|---|---|---|---|---|---|
| 16 | Guided Upload | **BV** `UploadBoard` | `upload-workspace.js` iframe | **Done** | `upload-guided/` (WebView) | file picker vs server browser; Postimages window |
| 17 | Upload preparation tools (advanced editor) | **BV** `UploadBoard` modal | same bundled modal in Upload iframe | **Done #99** | `upload-guided/preparation-tools.md` | native/server pickers; live mesh bounded to 16 MB / 2,000 triangles; desktop disk-rename consent |
| 18 | 3D view | Native QtQuick3D `ModelViewer` | server-rendered image with numeric camera | DO | none | live QtQuick3D can't move into a page |

### Search / Recherche

| # | Surface | Desktop | Web | Status | Spec | Blockers |
|---|---|---|---|---|---|---|
| 19 | Results | Native `SearchTab` (`search_view.py`, 1,586 lines), delegate-painted rows | `search.js`, `index.html:666-720` | NU | `search-redesign.md` (native first) | poster loading, QSettings state |
| 20 | Download queue | hidden sub-page of Search | own top-level nav item | NU | none | — |
| 21 | Torrent details / tabs | Shared Search detail tabs; readonly RSS dialog | Same bundled detail tabs | **Done** (#101) | `search-redesign.md` addendum | inline images/retry, movable tabs, Download now with category routing; browser-reserved Ctrl shortcuts remain a platform limit |

### RSS
- Shared under #102: inbox, subscription editor and category criteria, client comparison, saved selections, relative dates and queue explanation.
- Both hosts load `static/feeds/view.html`; global legacy rules and unknown categories survive editing.
- Deliberate host difference: desktop RSS details use the shared readonly modal; Web uses Search's movable detail tabs.
- Torznab category collisions and missing structured facts remain source limitations. See `rss-guided/implementation.md`.

### Torrents
- #103 replaces both renderers with the same bundled table/inspector. Both hosts have column selection and saved widths, tracker/client hierarchy, Files Download/Skip, 100-row pages, all-client actions, and separate delete-with-files confirmation.
- Both hosts expose state/tracker/category/tag filters, numeric column sorting and seed/c411 metric ranges. Sorting/filtering precede pagination. Refresh retains selection, scroll and draft filter text.
- Deliberate interaction limit: shared selection toolbar and inspector actions replace the native context menu; every action remains reachable on both hosts.
- Preferences are saved on the device: QSettings on desktop and browser local storage on Web. They do not sync across devices.
- Advanced controls are adapter-dependent in both hosts. qBittorrent supports reannounce, limits, category/tag additions and location; unsupported controls are disabled with an explanation. Client transfers are tracked separately in #105.

### Assistant

| # | Surface | Desktop | Web | Status | Spec | Blockers |
|---|---|---|---|---|---|---|
| 27 | Discussion | **BV** `AssistantPanel` | `assistant_panel.js` iframe, shared `static/assistant/` | **Done** (#106) | `assistant-chat-redesign.md` | Live job polling; provider token streaming is not offered |
| 28 | Automations | **BV** `AssistantPanel` | same bundled Assistant view | **Done** (#107) | same | Deletion remains unsupported by the service |
| 29 | History | **BV** `AssistantPanel` | same bundled Assistant view | **Done** (#106) | same | — |
| 30 | Selection cards / detail | **BV** `AssistantPanel` | same bundled Assistant view | **Done** (#107) | Existing selection and Upload review cards | Shared by full Assistant and Media compact chat (#111) |

### Media / Médias

| # | Surface | Desktop | Web | Status | Spec | Blockers |
|---|---|---|---|---|---|---|
| 31 | Video library | **BV** `MediaBrowserPanel` | same bundled `media/view.html` iframe | **Done** (#108) | `media-center-redesign.md` | Host dispatch retains native decoding |
| 32 | Music | **BV** `MediaBrowserPanel` | same bundled `media/view.html` iframe | **Done** (#109) | same | Playback stays with each host; shared controls provide the queue and saved-playlist actions (#110) |
| 33 | Player / Media Center mode | **BV** `PlayerView`, native decoding | Same bundled `player/view.html`, HTML decoding | Implemented (#110) | same | Native playback decision #89; external-player launch vs Web open/download; fullscreen APIs and partial-preview mechanisms remain host-owned |
| 34 | Media details | **BV** `MediaBrowserPanel` | same bundled dialog | **Done** (#108) | same | Original-file downloads remain Web-only; desktop uses its native player/external-player controls |
| 35 | Media chat side panel | **BV** compact `AssistantPanel` | same bundled `assistant/view.html` | **Done** (#111) | same | Native splitter vs Web resize handle; width stored per device |

### Shell and standalone

| # | Surface | Desktop | Web | Status | Spec | Blockers |
|---|---|---|---|---|---|---|
| 36 | Documentation | **BV** `DocumentationTab` | same bundled `documentation/view.html` | Implemented (#114) | `interface-backlog/README.md` | Native external browser vs Web links; standalone citation URLs remain plain documents |
| 37 | Reading room / Salon de lecture | Native `ReadingRoom` (`ebook_reader.py`) | none | DO | none | native EPUB/PDF rendering |
| 38 | Settings › Connections | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | system keyring |
| 39 | Settings › Library Folders | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | native picker |
| 40 | Settings › Search & Matching | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | — |
| 41 | Settings › Download Folders | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | picker, import from client |
| 42 | Settings › Client Paths | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | local disk |
| 43 | Settings › Zen | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | — |
| 44 | Settings › General | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | interface-size scaling is Qt |
| 45 | Settings › Assistant | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | — |
| 46 | Settings › Companion | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | local receiver port 8767 |
| 47 | Settings › Agent access | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | — |
| 48 | Clients… dialog | **BV** `SettingsView` | Same bundled Settings view | **Done** (#112/#113) | `settings-shared-implementation.md` | — |
| 49 | Update notice | **BV** shell update region | Same bundled update region | **Done** (#115) | `shell-shared-implementation.md` | Web notice refers to server installation |
| 50 | Shell: sidebar, header, client selector, status bar | **BV** `ShellView` | Same bundled shell view | **Done** (#115) | `shell-shared-implementation.md` | Browser-reserved shortcuts; Web authentication/Activity |
| 51 | Login | none | `/api/login` | WO | `web-070.md`, ADR-0016 | — |
| 52 | Activity (jobs) | none (status bar) | `/api/jobs*` | WO | `web-070.md` | — |
| 53 | Companion pairing page | served by desktop to the user's browser | `companion-connect.*` | WO | none | not an app panel |

**Counts:** Done 3 · Needs update 42 · Desktop-only 5 · Web-only 3.

## 2. Parity gaps

Tag: **Limit** = deliberate platform limit, **Gap** = plain gap, *unsure* where marked.

### Cross-cutting
- **BV Reseed and Upload are French only** (Gap). `reseed/view.js` and `upload/view.js` default to `language: "fr"` and never read it; Community is bilingual (`t(fr, en)`). The desktop Upload file-picker caption is French too (`upload_workspace.py:36-41`).
- **Theme tokens drift in light mode** (Gap). Dark values match across `gui/theme.py`, `app.css` and the three `view.css`. Light differs:

  | Where | bg | ink | muted | line | accent |
  |---|---|---|---|---|---|
  | `theme.py` | #f3f6fa | #203047 | #5c6c80 | #d5dfe9 | #087f76 |
  | `app.css` | #f5f7fa | #1b2938 | #657485 | #dce3ea | #087f79 |
  | `community/view.css` | #f4f7f8 | #21343c | #576e7b | #cbd6dc | #287c76 |
  | `reseed/view.css` | #f4f7f8 | #182d35 | #526a75 | #ccd9df | #087c77 |
  | `upload/view.css` | #f3f6fa | #203047 | #5c6c80 | #d5dfe9 | #087f76 |

  Each BV panel duplicates its own token block; there is no shared stylesheet. `app.css:592-602` holds an older dark block overridden at `:1189`.
- **Translations** (Gap): desktop uses Qt `.ts` (2,390 messages, complete); Web uses `data-en`/`data-fr`, `say()` and the `french` map in `app.js:23-162`. Separate sources. Web FR nav label "Media" vs desktop "Médias" (`index.html:59`).
- **Dialogs and toasts** differ per host: `QMessageBox` + status bar vs one `<dialog>` + `toast()`; each BV panel has its own toast/dialog.
- **Preferences** stored in QSettings on desktop vs `localStorage` on Web (Search state, Assistant sidebar width), so nothing carries between hosts.

### Shell
- Resolved by #115: shared sidebar/compact navigation, headings and descriptions, target-client selector, Zen band, update notice, theme/language and shortcut help.
- All clients is available only in Torrents; leaving it restores a specific client before scoped operations. The duplicate Torrents selector is removed.
- Platform limits: browser-reserved shortcuts; Web login/sign-out and Activity; native status messages. Update notices distinguish the running desktop from the server installation. See `shell-shared-implementation.md`.

### Zen
- Profile — Resolved by #91: both hosts load `static/profile/view.html` and its SVG charts. The measured-Zen label uses the selected period; “all history” applies only to All. The old implementations already used this same rule. Desktop persists the period in QSettings; Web uses localStorage. No deliberate platform limit.
- Seeding — Desktop-only: expanded state persisted per user. Web-only: sort/order selector.
- Plan — Web-only: "Queue selected downloads", sort/order, select whole plan / clear selection; Zen Profile fields live in Plan (desktop: Settings › Zen). Desktop-only: send summary with "Refresh first", "Stop fetching and plan now", "Stop sending", category → Download Folder prompt with native picker. Speed test measures desktop vs server (Limit).
- Catalogue — Parity (#90): shared per-category tiles, Fetch only, Fetch all, progress and pause/resume. Web jobs survive navigation and reload; desktop retains its existing worker and persisted checkpoints.

### Library
- Differs (Gap): desktop Library opens only Reseed; Local Items and Folders are modals. On Web they are pages.
- Desktop-only: disk-rename approval (Web refuses); offer to trash a verified archive (Web keeps it); footer batch progress and countdown.
- Differs (Gap): desktop Activity log appears unreachable (tab bar hidden).
- Differs (Limit): folder picking (`QFileDialog` vs server roots); Reseed `settings` and `add-client` route to each host's own UI.
- Differs (Gap): Web keeps a fallback link folder in `localStorage`; desktop reads settings only.

### Upload
- **Done #99:** one shared preparation modal replaces native `UploadTab` and legacy Web editor. Details, file/NFO editing, description preview, artwork, 3D controls, review and explicit seeding are available in both hosts.
- Intentional limits: live mesh geometry is bounded to 16 MB inputs and 2,000 displayed triangles; larger supported pieces use the CPU renderer. Web pickers use server roots, desktop uses native pickers. Web cannot approve disk renames for seeding; desktop retains the existing consent dialog.
- Postimages uses the existing isolated desktop popup or browser tab. Local render PNGs can be saved before selection in the host. See `upload-guided/preparation-tools.md` for extraction, cancellation and persisted-draft behavior.

### Search
- **Done #100/#101:** shared Search, numbered pagination, queue controls/context menu, movable detail tabs, Queue/Download all tabs, inline images and retry.
- Downloads use configured category folders. The folder dialog appears only for a missing category destination and persists it.
- Desktop supports Ctrl+W / Ctrl+Tab / Ctrl+Shift+Tab. Browsers reserve these shortcuts for browser tabs; both hosts provide arrow-key tab navigation, close buttons, middle-click close and the Open tabs menu.
- The readonly RSS desktop dialog uses the same detail assets without download controls.

### RSS
- Differs (Gap): criteria editor (click to prefer/require/avoid, right-click to rank on Web vs list pickers with Add/Move on desktop).
- Desktop-only: relative timestamps ("Today", "Updated N min ago"), *unsure* on Web. Web-only: queue explanation text.

### Torrents
- Desktop-only (Gap): column chooser, tracker tree toggle, saved column widths, context menu; Files tab "Download" / "Skip" (service supports it; no Web caller).
- Differs (Gap): paging (100/page vs one scrolling model); All clients mode (desktop acts across clients with confirmation; Web refuses); delete-with-files confirmation flow.
- Web-only (Gap): state/tracker/category/tag filters (desktop hides them).

### Assistant
- Resolved (#106): the first-run "Run within limits" acknowledgement lives in the owner Assistant service database and is shared by both hosts. Sidebar width persists per device, using QSettings on desktop and browser storage on Web.
- Deliberate existing limit: transcripts update as persisted messages, tool activity and decisions arrive, using job polling. Providers return complete model messages; #106 does not introduce token-by-token provider streaming.
- The main Assistant page and compact Media chat use the same bundled view (#106/#111), including Automations and selection cards (#107). The compact native mode and legacy Web chat renderer are removed. Settings connection forms now use the shared Settings view (#112); the old full native Assistant class remains for its existing standalone tests.
- Web-only: "Selection details" and "Presentation image" cards, *unsure* whether every field matches desktop `SelectionDetail`.

### Media
- Differs (Limit): `QMediaPlayer` vs HTML media; Media Center mode (window fullscreen vs Fullscreen API).
- Both hosts: shared transport, ±10 s video controls, audio/subtitle selection, repeat/shuffle, queue removal, save/load/delete playlists, chat and Media Center actions. The shared browser supplies watched state, Continue watching and playlist editing.
- Deliberate limits: OS external-player launch on desktop vs original-file/preview download in Web; browser-dependent embedded tracks; native verified-piece streaming vs Web fixed-prefix preview. Compact/Expand remains Web-only; desktop video fills its workspace.

### Settings
- Both hosts use `static/settings/view.html` for Connections, Clients, Companion, Agent access, Assistant, Library Folders, Download Folders, Client Paths, Search & Matching, Zen and General. TMDb and additional API keys, matching rules, client-folder import, diagnostics and media layout are available in both.
- Deliberate platform limits: desktop secrets use the system keyring, Web secrets use server storage or managed files. Desktop folder browsing opens a local picker; Web browsing stays within configured server roots. Interface size applies to the desktop after restart; browser zoom remains browser-controlled. Companion pairing and token/report downloads use their host's native handoff.
- Implementation and validation: `settings-shared-implementation.md`.

### Documentation
- Desktop-only (Gap): guide filter, Forward, separate guide-language selector. Web: guide select, Back, GitHub link.

### Endpoints
- Web endpoints with no desktop use: `/api/login`, `/api/logout`, `/api/jobs*`, `/api/folders`, `/api/zen/profile/download-tests*` (no caller found anywhere, *unsure*).
- Desktop capabilities with no Web endpoint: reading room, update check, TMDb key, matching settings and Ignored Files, interface size, import folders from client, Search "Download now". Torrent want/skip files is available in both shared inspectors since #103.

## 3. Open questions

- U1: whether the desktop Library Activity log is reachable at all.
- U3/U4: `rss-redesign.md` and `media-center-redesign.md` status lines say nothing is built, but the code implements them.
- U5 (#89 decision): retain native desktop playback. The Linux Wayland WebEngine probe rejects H.264/HEVC/AAC; VP9 plays with `--disable-gpu`. Windows/macOS artifact codec matrices remain unverified. See [playback investigation](../research/media-webview-playback.md).
- U6: whether the Web build omits the update check on purpose.
- U7 resolved by #112: the shared Connections editor stores the TMDb key through the owner Settings service.
- U9-U12: parity was compared from string sets and targeted reads, not by running both UIs; layout, ordering and enabled states may differ where strings match.
