# Media Center redesign: chat panel, controls and browsing

Status: approved design, implemented in stages. Updated 2026-11-19 for #108: video sections, layouts and details now use one bundled desktop/Web view. The native video hero, shelves and episode widgets are removed. Updated for #109: albums, artists, tracks and playlists use the same bundled view; the native music browser is removed. Updated for #111: compact Media chat uses the shared Assistant view, with host-owned session context and width persistence. Updated for #110: player controls, options, tracks, queues and saved-playlist actions use `static/player/view.html` in both hosts. The native transport/menu widgets and separate Web controls are removed. Native decoding remains the #89 decision; this port does not change codec support.

This plan covers the desktop Media Center first. Its button rules then extend to the rest of the app, as stage 3 of the [polish plan](../releases/polish-plan.md).

## What is wrong today

Observed in 1.0.0-beta.9 (screenshots from the user, 2026-10-27) and confirmed in the code.

### The chat panel is the whole Assistant page

- `MediaTab.open_chat` (`gui/media.py`) embeds a full `AssistantTab` in the Media Center's splitter. That brings the Discussion / Automations / History / Connections tabs, the folder tree, and the New / Delete / Move-to-folder buttons into a side panel that only needs one conversation.
- Closing is a full-width "Close chat" `QPushButton` inserted above everything. The ✦ toolbar button opens the chat but does not close it.
- The width is not remembered. The first open forces `setSizes([700, 500])`, and nothing saves the sizes when the user drags the handle.
- In a non-maximized window the handle cannot be dragged. The likely cause is that the minimum widths of both sides (the embedded Assistant's tab bar, folder column and button row, plus the media toolbar and hero) already add up to the window width. To confirm by measuring `minimumSizeHint()` on both sides.
- The "Run within limits" notice and the model selector use a different visual language from the media view around them.

### Buttons come from several unrelated styles

- `theme.py` gives every `QPushButton` and `QToolButton` a bordered panel look with 7 × 12 px padding. Most of the 166 `QPushButton(` sites in `gui/` use it unchanged, at full text width.
- The Media Center adds its own roles (`mediaPrimary`, `mediaSecondary`, `mediaPlayerIcon`, `mediaCompactControl`) in a page stylesheet. The embedded Assistant uses the global style. Both appear side by side.
- Secondary actions are spelled out as large text buttons ("Discussion settings", "Move to folder…") instead of icons or menu entries.

### Browsing is one grid

The library shows a hero, "Continue watching", then one "Recently added" grid. Genres, years, ratings and directors from the c411 film details are not used to organize what you see.

## Design principles

1. **Few button roles, one definition.** Every button is one of four roles, styled once in `theme.py`:
   - **Primary:** one per area (Play, Send). Filled accent.
   - **Secondary:** bordered, compact.
   - **Quiet:** text only, for low-weight actions inside panels.
   - **Icon:** square 32 px (28 px compact), tooltip and accessible name required.

   Page stylesheets set roles, never their own button looks.
2. **Actions go where they act.** A control that opens something also closes it. Rare actions go into a ⋯ menu, not a permanent button.
3. **Panels remember their size.** Any user-resizable split saves its sizes and restores them.
4. **The Media Center stays dark and cinematic.** It shares spacing, radii, focus rings and button roles with the rest of the app, so both feel like one product.
5. **Nothing is lost.** Everything the side panel leaves out (folders, automations, history, connections) stays one click away in the Assistant page.

## Workstreams

### A. Shared button and spacing system (`gui/theme.py`)

- Define spacing tokens (4, 8, 12, 16, 24 px), radii (6 px controls, 10 px cards) and the four button roles. Use a `role` dynamic property, such as `QPushButton[role="primary"]`, generalizing the existing `primary="true"`.
- Add an `icon_button(icon, tooltip)` helper so icon buttons always get a tooltip, accessible name and focus ring.
- Inventory all 166 button sites with a script: file, label, role it should become, and whether it belongs in a ⋯ menu. Migrate the Media Center and the chat first, then the other pages view by view.
- **Acceptance:**
  - No page stylesheet defines `QPushButton` padding, border or background.
  - The Media Center and the chat use only the four roles.
  - Focus is visible on every button, in light and dark themes.

### B. A dedicated Media Center chat panel

Build a `MediaChatPanel` from the parts the Assistant already has: `ChatTranscript`, `ChatPrompt` and the model list. Do not embed the whole `AssistantTab`.

**Layout:**
- **Header:** the conversation title, a history icon (a menu of recent media discussions, with "New discussion"), a ⋯ menu ("Discussion settings", "Open in Assistant", "Delete discussion"), and a close ×.
- **Transcript:** full height, same rendering as today.
- **Composer:** one rounded field. A small model chip sits under it. Send and Stop share one icon button inside the field: Send while idle, Stop while running.
- **Removed:** no folder tree, no tabs, no "Run within limits" banner. Limits show only when one blocks an action, inline in the transcript.

**Opening and closing:**
- ✦ becomes a checkable toggle: it opens and closes the panel and shows its state. The × in the header closes it too. Esc closes it when the composer is empty.

**Width:**
- Save the splitter sizes in `media-desktop.ini` whenever the user releases the handle, and restore them on open. Default: 38 % of the window, with the chat at least 320 px and the media side at least 480 px.
- Give both sides a sane `minimumSizeHint`, so the handle can be dragged in any window size.
- Below about 900 px, the chat takes the whole Media Center with a back arrow, instead of squeezing both sides.

**Acceptance:**
- In a 1280 × 720 window: the chat opens, the handle drags, and the width survives closing the panel and restarting the app.
- ✦ toggles the panel; the panel has no full-width buttons.
- Sending, stopping, approving a proposal and switching discussions work as before.
- The tests cover persistence and toggling.

### C. Netflix-style browsing

Replace the single grid on the video home with horizontal rows. The continuous grid stays as each row's "See all" page.

**Rows, in order, each shown only if it has items:**
1. Continue watching
2. Recently added
3. One row per genre, for the 6–8 most common genres in the library
4. Series
5. Highly rated (★ 7+)
6. Not watched yet
7. By decade

**Row behavior:**
- Each row has a title, a count and "See all ›". The row scrolls sideways with the wheel or with arrows on hover, and loads posters lazily.
- Selecting a card updates the fixed description area, as today. Keyboard arrows move within and between rows.

**Data:**
- Rows come from `MediaLibrary.listing` with the existing `view` and `genre` filters, and a small `limit` per row.
- The genre list and its counts come from the `filters` already returned by `listing`. Rating and decade need two more filter values.

**Scale:**
- Load the first rows first and the rest as they scroll into view.
- Keep the artwork fetch limits that exist today.

**Acceptance:**
- With the 311-item library, the home shows the rows within 1 s on cached data.
- "See all" opens the filtered continuous grid with selection preserved.
- Music keeps its current layout until it has its own row plan.

### D. Roll out to the rest of the app

After A–C ship, apply the button roles and spacing to the Assistant page, Search, Library, Torrents, Upload, RSS, Zen and Settings, in the polish plan's view-by-view order. In the Assistant page, keep the folder tree, but make New / Delete / Move icon buttons with a ⋯ menu.

## How we assess the design

- **Screenshot inventory.**
  - Views: every Media Center state (home, film selected, player, fullscreen, chat open, empty library), at 1280 × 720, 1920 × 1080 and fullscreen.
  - Themes: dark and light, where the page supports both.
  - Languages: French and English.
  - Capture before and after each workstream, and keep them under `docs/testing/`.
- **Checklist per screen:**
  - one primary action;
  - no full-width text buttons outside dialogs;
  - every icon has a tooltip;
  - the panel can be resized and remembers its size;
  - long French labels fit;
  - focus is visible;
  - text contrast is at least 4.5:1.
- **Review points:** the user reviews the screenshots at the end of each workstream, before it is published.

## Order and releases

| Release | Content | Why first |
| --- | --- | --- |
| beta.10 | B: toggle, remembered and resizable width, compact chat panel | Fixes the three reported bugs and removes the worst buttons. |
| beta.11 | A: button roles in `theme.py`, Media Center and chat migrated | Gives the Media Center one visual language. |
| beta.12 | C: Netflix-style rows | Builds on the new controls. |
| later betas | D: other pages, view by view | Follows the polish plan. |

Each release keeps the full test suite and CI green and adds tests for its acceptance points.

## Open questions

1. Should the side chat show automations started from it (for example a queued download), or link to the Assistant page for those?
2. Should the Media Center follow the light theme when the app is light, or stay dark like most media players?
3. Which rows matter most to you, and should genre rows use c411's French genre names as they come?
4. Should music get the same row treatment (by artist, album, genre) in the same release, or later?


## Shared player implementation (#110)

`PlayerView` and the Web `player_host.js` adapt the same bundled controls to their existing playback session. Source tokens guard track changes, and queue revisions guard actions on rows captured before a queue changes. Playlist caches belong to the playback client. Video keeps seek, play/pause, ±10 seconds, volume and fullscreen in its overlay; music keeps the compact transport bar. Options contain tracks, repeat/shuffle, chat, Media Center, preview refresh, queue and playlists. Menus scroll within the frame so an expanded queue cannot hide the transport.

Deliberate platform differences remain: desktop uses `QMediaPlayer`, verified-piece streaming and the OS external-player launcher. Web uses HTML audio/video, fixed verified-prefix previews, browser track support and the Fullscreen API. Its external-player action opens or downloads the current original file or fixed preview. Expand/compact remains Web-only because desktop already gives video its workspace. Watched state, Continue watching and playlist editing remain in the shared Media browser.

Validation uses temporary libraries and simulated clients. Native tests decode audio/video and captions, switch embedded tracks and reject stale selections. Browser tests cover fullscreen, chat, queues, playlist ownership, preview refresh/stop and source changes. The bundled controls also render on Wayland in English/dark and French/light, including a narrow transport and a long fullscreen queue.
