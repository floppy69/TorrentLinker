# Search redesign: c411's layout, our exclusives

Status: built 2026-10-27, desktop and web (everything in this plan, nothing deferred). Decisions: c411 structure in our own palette; Simple view with a Compact / Comfortable switch and no Groupé; desktop first. Counts come from the listing's `meta` (global per root, not filtered); posters are TMDB thumbnails fetched by a bounded, cached loader (the web page proxies them through `/api/poster`); Team is a free-text filter (`team=<name or slug>`, verified live); the detail page stays a separate follow-up.

The Search tab keeps working but looks like a raw query form: a text field, a category tree popup, a grid of checklist buttons and a plain table. c411's own torrents page (screenshot supplied by the user) is faster to scan: category pills with counts, one filter row, rich result rows. This plan brings Search closer to it, on the same basis as the RSS and Assistant redesigns ([rss-redesign](rss-redesign.md), [assistant-chat-redesign](assistant-chat-redesign.md)), without losing what only TorrentLinker does.

## What is wrong today

Seen in `SearchTab.__init__` and `SearchFilters` (`gui/search_view.py`, `gui/search_filters.py`) and `#view-search` (`web/static/index.html`, `app.js`).

**Desktop**

- A single row mixes the query, a category tree popup, Search, and "Subscribe to RSS" (a second button that looks like Search's sibling).
- Filters are up to 14 identical `MultiFilter` tool buttons in a 6-column grid, plus a second row (year, uploader, Exclusive, a three-state combo for revival), plus a third (sort combo, direction combo, status, Retry, Clear). Sort is two combos, not column chips.
- Results are a plain table: title, size, seeders, category, revival, Zen/day, Note, age. No cover, no year, no rating, no release tags, no leechers, no completions, no uploader, even though the API returns leechers, completions, uploader and exclusivity.
- Below the table: a row of paging buttons, a row for the download folder, a row for tab queueing. Five areas, three of them full-width button strips. No numbered pages.
- Results and the Download queue are two `QTabWidget` tabs inside the Search tab; a notice row above them repeats the queue count.

**Web**

- `#view-search` is a toolbar, a bare "RSS" button, a facet toolbar, a "More filters" `<details>`, a table and a pager with `←` `→`. Same gaps as desktop, plus the queue button sits in the pager.

## What c411 does well (from the screenshot)

- **Header**: "Torrents" with Simple / Groupé view tabs and a Compact / Confortable density switch.
- **Search bar**: one large field with an inline "Casting & équipe" chip (`crew=true`) and an orange Rechercher button.
- **Category pills** with counts (Tout 228 298, Films & Vidéos 138 013, …), each with a color dot. One click filters.
- **Filter row**: rounded dropdown buttons, each opening a facet popover; below it the toggles Exclusivités and Soins palliatifs, and "Tout effacer".
- **Pagination on top**: 1 2 3 … 400, Suivante →, Dernière ».
- **Results card**: header with total size and count, sort as a row of chips (Âge, Seeders, Leechers, Taille, Complétés, Commentaires, Nom, Type).
- **Rows**: cover, type badge, title, year, rating, release name in monospace, colored tags (language, resolution, source, audio, codec), size, seeders/leechers with a ratio bar, age, completions, uploader, download button.

## Constraints to keep

- c411 Search uses the **native** catalogue API (`Indexer.search_categories`, `search_filter_options`, `native_search`). Native IDs differ from Torznab IDs (roots positive, children negative in `SearchTree`). Other Indexers fall back to Torznab search with no facets; the page must still work there (category pill row from `Settings.indexer_categories`, no facet row, no uploader or exclusives).
- Agents and MCP search tools call the same code (`indexer_search.py`, `search_options`). No change to their contract.
- One search rate limiter is shared with Torznab. Fetching category counts must not add more than one request per refresh (see decisions).
- Zero-config safety: nothing here touches the user's torrent clients. Tests keep the `conftest` guard.

## Exclusives to keep, and where they go

| Exclusive | Today | In the redesign |
| --- | --- | --- |
| Zen estimate and note (`≈ Zen/day`, `≈ Note`), "already seeding" mark (`set_seeding`) | two table columns | a small Zen pill on each row (`≈ 1.42 Zen/day`), tooltip unchanged; sortable via a "Zen" sort chip. A Compact density keeps the columns. |
| Subscribe to RSS (`subscribe_requested`, `#subscribe-search`) | button beside Search | one quiet "Follow in RSS" button in the filter-row end, next to "Clear all". It carries query and filters into the editor. |
| Add to app queue, download folder per category, folder override | button row below the table | a selection bar that appears only when rows are checked: "Add to queue (N)", folder chip ("Category folders" or the chosen path, click to change). Row download button queues one. |
| Queue, "Download all tabs", "Queue all tabs" | tab strip + button row | the Download queue stays a second page, reached from a queue badge in the header (`Queue 3`). Tab actions move into the browser-tab bar menu (⋯). |
| Metadata preview dialog (`TorrentDetailsDialog`, shared with RSS) | double click / "Open in tabs" | click a row title or cover to open it; unchanged internals. |
| Client comparison and "already in client" state | not shown in Search today | an "In client" check on the row if the infohash is known to the active client (cheap local lookup, no client call per row). Stretch goal; see step 6. |
| Palliative (Soins palliatifs) | combo with three states | a heart toggle like c411 with the count; the existing `include` / `only` states stay (click toggles only, long state in a tooltip). Row mark stays. |
| Assistant / MCP search tools | separate code | unchanged. |

## Decisions

Open, to settle with the user before building. Recommendation first.

1. **How literally to copy c411.** Recommended: copy the *structure* (header, search bar, pills, filter row, results card, row layout) but keep TorrentLinker's palette and theme tokens (`gui/theme.py`, web CSS variables), with our existing primary color for the Search button. Orange primary and c411's exact dark gradient only if the user wants the app to look like c411 everywhere; it would clash with the RSS and Assistant pages already redesigned.
2. **"Groupé" view.** c411's grouped view collapses releases of one film or season. Our API call uses `viewMode=flat`; grouping needs a different response shape (to verify) and a different row. Recommended: no Groupé in this pass; build Simple only, keep the tab slot out. Add it later if the user misses it.
3. **Density switch (Compact / Confortable).** Recommended: yes. Confortable = c411 rows with cover and tags; Compact = one line per row with the Zen columns, close to today's table, so power users keep their dense view. Remembered in `QSettings`/localStorage.
4. **Desktop first or web first.** Recommended: desktop first (as in RSS), web parity at the end of each step group.
5. **Category counts.** Settled by the spike: `meta.categories` and `meta.subcategories` carry counts in the same response, so pills show counts at no extra request. Open: whether they follow the text query and filters (test one filtered request in step 2 before labelling them).
6. **Covers.** Settled by the spike: rows carry `posterUrl` (TMDB, `w500`) and `media.title/year/rating`. Fetching 100 posters per page still costs bandwidth and tells TMDB what you browse. Recommended: show posters in Comfortable rows through a bounded, cached, asynchronous loader (small thumbnails, at most N in flight, off by a setting), and a type icon until a poster arrives or when it is off.
7. **Detail page.** The other screenshots show c411's torrent page (versions, MediaInfo, trust votes, sticky download bar). Recommended: out of scope here; the preview dialog is shared with RSS and gets its own spec later.

## Design

### 1. Page structure

1. **Header**: "Torrents" title, a quiet queue badge (`Download queue 3`) that opens the queue page, density switch (Compact / Comfortable).
2. **Search bar**: large field, the "Cast & crew" chip (`crew=true`, only for Films & Vidéos), the primary **Search** button. Enter searches. No other button in this row.
3. **Category pills**: *All* plus the roots from the fetched tree (never an invented list), color dot, count when known. Picking a root loads its facets; the subcategory dropdown is the first item in the filter row. Non-c411 Indexers use `Settings.indexer_categories` roots.
4. **Filter row**: rounded dropdown buttons (Subcategory, Profile, Resolution, Source, HDR, Audio, Codec, Language, Season, Type, Genre, Year, Team, Uploader as the root allows). Each opens the existing searchable multi-select (`MultiFilter`) styled as a popover, count in the label when active. Year and Uploader become dropdowns with a small input inside. Then toggles **Exclusives** (star) and **Palliative** (heart), **Follow in RSS**, and **Clear all**. Selected values also show as removable chips below the row when there are more than three.
5. **Pagination bar**: numbered pages with ellipsis, Next, Last, above the results (and again below). Replaces `Previous page` / `Next page`.
6. **Results card**: header with the total ("137 565 torrents · 1.56 PB") when the API gives them, and the limit warning (`c411 limits this search…`) as a quiet ⓘ. Sort chips: Age, Seeders, Leechers, Size, Completed, Comments, Name, Type (the existing `sort` / `order` values; clicking the active chip flips the direction, with an arrow). Relevance appears only while a text query is set.
7. **Rows (Comfortable)**: cover or type icon, type badge, title with year and rating, release name in monospace, colored tags parsed from the release name (language, resolution, source, audio, codec) with the same parser the RSS editor uses, Zen pill, size, seeders ↑ / leechers ↓ with a ratio bar, age, completions, uploader, an "Already seeding" mark, a download button. Selection by checkbox. **Compact**: title, tags, size, seeds, age, Zen, Note in one line.
8. **Selection bar** (only with checked rows): "Add to queue (N)", folder chip, "Open in tabs", "Open on website" for one row.

### 2. Data (done in step 1)

`Candidate` stays as it is. `Candidate.metadata` feeds RSS ranking (`feeds.py`), so display facts do not go there. `native_search` returns them on `SearchPage` instead, next to `labels` and `palliative`: `details` (a `ListingRow` per infohash: leechers, completions, comments, uploader, exclusive, free-leech, title, year, rating, kind, poster URL, badges), `root_counts`, `subcategory_counts` and `total_size`. Field shapes are in `docs/research/search-filters.md`.

### 3. Release tags

c411 rows get their badges from the parsed `tech` block (`listing_tags`), in a fixed order: language, resolution, source, audio and channels, video codec, HDR (hidden when SDR). Other Indexers (Torznab) have no `tech`; they get no badges in this pass. A release-name parser for them is a later, optional step: it would be display only and never feed filtering.

### 4. Desktop and web

Same structure on both. Desktop: a `ResultRow` delegate or row widgets in a `QListView` (virtualised; 100 rows with covers must not stall the GUI, see the stall watchdog notes), `FlowLayout` for pills and filter chips, `set_role` / `icon_button` and the `chip` property styles from `gui/theme.py`. Web: `app.css` role classes, `aMenu` / `aIconButton` helpers, `.search-*` CSS. Text through `self.tr` and `say()` / `at()`.

## Acceptance

- A search by title with category, two facets, and sort by seeders takes five clicks or fewer and no typing besides the title.
- The page has one primary button per area: Search in the bar, "Add to queue" in the selection bar.
- Every current exclusive is reachable (table above), including Zen estimate, Subscribe to RSS, queue, per-category folders, preview dialog and revival marking, on desktop and web.
- A non-c411 Indexer still searches and queues, with no facet row and no uploader or exclusives controls.
- 100 comfortable rows scroll without GUI stalls above 25 ms (measure with `TORRENTLINKER_STALL_MS=25`).
- No Torznab ID, byte count or ISO date is shown anywhere.
- Tests: the row parsing (`listing_tags`, `parse_listing_row`), pagination model (numbers with ellipsis), filter state to params round trip (`test_search_filters`), selection bar visibility, Indexer fallback. `test_i18n` stays green.
- Screenshots in French and English, dark and light, 1280 × 720, desktop and web, reviewed before any publish.

## Order

1. Done: spike, `ListingRow` and counts on `SearchPage`, tests, shape recorded in `docs/research/search-filters.md`.
2. Done: desktop page skeleton (header, search bar, pills, filter row, numbered pages, sort chips).
3. Done: desktop rows (Comfortable and Compact), Zen pill, selection bar, queue badge.
4. Done: filter chips, palliative and exclusive toggles, empty and error states, In client / Queued marks (both densities).
5. Done: Year / Team / Uploader dropdowns, automatic search after a pause, one results card, page links above and below, the queue page reached from the header, tab actions in the Open tabs menu, `poster_cache.py` and the poster loader with a Posters switch.
6. Done: web parity (`index.html`, `search.js`, `app.css`, `/api/poster`, `search_listing` in the search job), real-data check, Torznab test, guides (EN and FR).

## Addendum 2026-10-28: c411's compact table and torrent page

Screenshots of c411's compact mode and its torrent page were supplied after the first build.

- **Compact** now has c411's columns: type badge, release name with EXCLU / language / quality tags, comments, age, size, completed, seeders, leechers, then our Zen columns and the download button. Headers sort the whole search through the same sort state as the chips (`HEADER_SORTS`). `ListingRow` gained `language` and `quality`, the wording c411 prints in its tags.
- **Detail tab** (`gui/torrent_details.py`, web `details()` in `app.js`): type badge and flags, title, byline (sender, team, date), the not-tested banner, size and live swarm chips, hash and files, c411's facts as chips, NFO and files as disclosures, the TMDB card with IDs, read-only community trust, the description, and a bar that keeps the download actions in view. `parse_details` now reads uploader, team, date, exclusivity, low-bitrate, swarm, facts, trust and the TMDB media block; the web `details` job returns them as `info`.
- **Left out on purpose:** the **Versions** list needs c411's grouped listing (`/api/torrents/group-children` with a release ID that flat rows do not carry), and trust **voting**, favourites and reports need a website session, not the API key. The detail tab keeps an Open on website / Vote on the website button for them. The previous and next episode link (S10E53) is not in the detail response.

## Shared detail implementation (#101, 2026-11-18)

The existing detail layout now lives in `web/static/search/details.js` and `details.css`, loaded by both hosts. The readonly RSS dialog uses the same assets. Native BrowserTabs and the former Web detail dialog renderer were removed.

Details retain their tabs when returning to Search. Tabs support drag reordering, arrow navigation, closing and queue/download-all actions. Inline images use bounded anonymous requests, per-host cooldowns and explicit retry. Changing language rerenders cached details; responses from closed/replaced tabs are ignored. Desktop links open in the external browser.

Download now queues and starts only the chosen torrents, using configured category destinations and prompting only when a destination is missing. Browser Ctrl+W and Ctrl+Tab remain browser shortcuts; equivalent visible controls and arrow-key navigation are shared.

Validation covers the details/image service, Chromium workflows and real Wayland Search/RSS rendering with simulated network responses and temporary storage. No live tracker downloads are used.
