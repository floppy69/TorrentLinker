# RSS redesign: a page and an editor made for humans

Status: original design implemented; shared desktop/Web port and approved category-aware extension implemented under #102 on 2026-11-18. See [implementation and limits](rss-guided/implementation.md).

The RSS page and its subscription editor are the last big screens still on the raw-model layout. This plan brings them onto the same basis as the Media Center and the Assistant ([media-center-redesign](media-center-redesign.md), [assistant-chat-redesign](assistant-chat-redesign.md)): button roles from `gui/controls.py`, few controls per row, plain words, no raw units.

## What is wrong today

Seen in `FeedsTab.__init__` and `FeedsTab.edit` (`gui/feeds.py`) and `web/static/feeds.js`.

**Editor**: one scrolling form of about 40 fields mapped one to one onto `Subscription` and `Preferences`.

- Categories are typed as Torznab numbers, with a hint listing a few IDs.
- Daily limit, disk reserve, minimum and maximum size are typed in bytes (`10737418240`).
- Allowed hours are a comma list of UTC hours.
- Ranking priorities are free text. Seeders are explained in a paragraph.
- 24 comma-separated lines (`quality · Required / accepted`, `… · Preferred in order`, `… · Excluded`, for 8 fields).
- Mode is a combo; its consequences are not shown.
- Preview is a button that dumps JSON into a text box, and a new subscription cannot be saved until it was previewed.
- Preview, Save and Cancel look the same.

**Page**

- A row of 8 equal text buttons, then a row of 6 more above the table.
- The status line shows an epoch (`Last success: 1793128077.473702`) and a large empty area sits above the table.
- Sizes of `0.00 GiB` for small or unknown sizes; ISO timestamps.
- The feed list is plain text: `Films 1080p (0)`, with no paused state.

## Constraints to keep

- Agents and MCP write the same `Subscription` / `Preferences` models through `feed_control.py`. No field may become impossible to see. Values the UI cannot express appear read-only under "Advanced", they are never dropped on save.
- `required` and `excluded` are hard filters; `preferred` is a soft, ordered ranking. Every preferred field must be in `priorities`; the validator appends missing ones.
- A new subscription, or a changed query or category set, needs a successful preview within 15 minutes (`FeedControl.save`). The editor must satisfy this itself instead of asking the user to remember it.
- `automatic_download` needs owner approval, a Download Folder, and uses the daily limits, hours and disk reserve. `app_queue` also needs a folder.
- Interval 15 to 1440 minutes. Hours are stored in UTC.

## Decisions

Open, to settle with the user before building:

1. **Editor shape**: one dialog with sections, or a short first screen with the essentials and an "Advanced" disclosure. Recommended: the essentials on top (what, how, where), the rest behind disclosures.
2. **Stored hours stay UTC** and the UI shows and edits local time, converted at the edge. Recommended: yes, no model change.
3. **Quality editing**: a Must / Prefer / Avoid chip per value for the common fields (quality, codec, audio, subtitles), and the other fields (format, bitrate, platform, license) under "More criteria". Recommended.
4. **Preview**: runs automatically (debounced) in the editor and shows a count and a few titles; it satisfies the preview requirement at save. Recommended.

## Design

### 1. The editor: four plain sections

1. **What to follow.** Name, words to match, and a category chooser built from `Settings.indexer_categories` (a tree of names, parents with their subcategories; Torznab IDs hidden). IDs the app does not know stay visible as read-only chips so they are not lost.
2. **What you accept.** Size as a range, each end a number with a MiB / GiB unit choice ("at least / at most"; the unit is picked automatically from the stored bytes, so 700 MiB stays 700 MiB), minimum seeders. Quality, codec, audio and subtitles as chips: tap once for Prefer, twice for Must, three times for Avoid. Preferred values keep a visible order (drag, or ◀ ▶). "What matters most" is a short drag list of the ranking priorities, including Seeders and Size, with "Prefer smaller" as a switch on Size. Other metadata fields sit under "More criteria".
3. **What happens.** Three cards: *Notify me* (review only), *Add to queue* (app queue), *Download automatically*. Each says in one line what will happen. Client and Download Folder appear for the last two. Limits appear only for automatic downloads: daily size in GiB, daily count, disk reserve in GiB, and allowed hours as a grid in local time with presets (Any time, Night only, Custom). The approval checkbox sits on the Automatic card and says what is authorized.
4. **How often.** Check every N minutes (a stepped choice from 15 minutes to 24 h), wait for alternatives (minutes or hours), "include what is available now", "replace better matches while pending". Collapsed by default.

A live preview strip under the sections shows "Would match today: 3 of 100 releases" with the first titles, and refreshes when the query or the categories change. Buttons: **Save** (primary), **Cancel** (quiet). Save runs the preview first if none is current, then saves.

An "Advanced" disclosure shows what the controls cannot express (unknown category IDs, criteria from agents) read-only, with a note that agents can edit them.

### 2. The page

- **Sidebar rows**: name, unread badge, ⏸ when paused; the mode as a small subtitle. A ＋ icon button at the top.
- **Header** for the chosen feed: its name, a status line in human words ("Updated 12 minutes ago", "Next check in 18 minutes", errors in the warning color), and **one** primary button for the main action ("Refresh now"), then ⋯ with Edit, Pause / resume, Process rules, Decisions, Delete. "All feeds" shows "New subscription" as the primary instead.
- **Page-level secondary actions**: Compare clients and Saved selections move to a ⋯ at the top right of the page.
- **Filters** as a segmented row (All, Unread, Saved, In client, Queued) instead of a combo.
- **Table**: human dates ("today 20:07", "yesterday"), sizes with `—` when unknown, a quiet state column. The "Coverage is limited" text becomes a small ⓘ with a tooltip.
- **Selection toolbar** that only appears when rows are selected: Mark read, Save, Dismiss, Add to queue, Save selection. No full-width buttons anywhere.
- Empty state for no subscription: one sentence and one primary "New subscription".

### 3. Desktop and web

Same structure on both. Desktop uses `set_role` / `icon_button` and no page stylesheet that reshapes buttons; web uses `app.css` role classes. Translation stays in `self.tr` and `at()` / `say()`.

### 4. Model and conversion code

A small module `feed_units.py` (pure, no UI) holds the conversions the two front ends share: bytes ↔ GiB, UTC hours ↔ local ranges and presets, the chip state ↔ `required` / `preferred` / `excluded`, and human time. It carries the tests, so desktop and web agree.

## Acceptance

- A subscription can be created in under a minute without typing an ID, a byte count, a UTC hour or a comma list.
- Editing a subscription written by an agent and saving it again changes nothing the user did not touch (round-trip test over a rich `Subscription`).
- The page has no row of equal text buttons; every area has at most one primary button.
- Dates and sizes are human everywhere; no epochs or ISO strings.
- The preview requirement and the automatic-download approval still hold; the save error text is readable.
- Tests cover `feed_units`, the round trip, the preview-then-save flow, and the automatic-mode limits shown only for that mode.
- Screenshots in French and English, dark and light, 1280 × 720, desktop and web, reviewed before publishing.

## Order

1. `feed_units.py` with tests (no UI).
2. Desktop page: sidebar, header, ⋯ menus, filters, selection toolbar, human dates.
3. Desktop editor: sections, category chooser, mode cards, limits, local hours.
4. Quality chips, priorities list, live preview, Advanced disclosure.
5. Web parity (`feeds.js`, `app.css`, `index.html`), screenshots, docs (`docs/guide/*/rss.md`).
