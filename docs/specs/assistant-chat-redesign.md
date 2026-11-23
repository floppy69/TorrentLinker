# Assistant chat redesign: one chat look on the page and in the panel

Status: implemented in 1.0.0-beta.17 (desktop and web), 2026-10-27. Not done: deleting an automation, which the service does not support yet.

The Media Center side chat (`AssistantTab(compact=True)`) already has a header with ☰ / ⋯ / ✕, one composer whose button is Send while idle and Stop while running, and the button roles from `gui/controls.py`. The full Assistant page, on desktop and web, still has the old layout. This plan brings the page onto the same basis. It is workstream D of the [Media Center redesign](media-center-redesign.md) for the Assistant.

## What is wrong today

Seen in `docs/guide/images/assistant.png` and in `AssistantTab.__init__` (`gui/assistant.py`) and `web/static/assistant.js`.

- The mode ("Propositions uniquement") is a bare label above the tabs.
- The discussion list has three full-width text buttons around it: New, Delete, Move to folder.
- The composer row has four controls: a wide model combo, "Discussion settings", "Send" and "Stop".
- Automations and Connections are a plain list over a row of five text buttons.
- Your messages and the assistant's replies use the same card. The "Activity" line weighs as much as a reply.
- A new discussion is an empty transcript with no hint of what to ask.

## Decisions

- **History stays its own tab.**
- **Connections move to Settings → Assistant**, on desktop (`SettingsDialog`) and web. The Assistant page keeps a "Connect a model" call to action that opens that page.
- **Switching to "Run within limits" asks for confirmation the first time only.** The acknowledgement is stored in settings; later switches are immediate.

## Design

### 1. One shared composer

Extract the compact panel's composer into a `ChatComposer` widget (`gui/chat_composer.py`) used by both the page and the Media Center panel. The web gets the matching `chatComposer()` in `assistant.js`.

- A rounded field. The single Send/Stop icon button sits inside it, bottom right, in the primary role.
- Under the field, two chips:
  - **Model chip:** the connection and model name; a click opens the list of connections, plus "Manage connections…" (Settings → Assistant).
  - **Mode chip:** "Proposals" or "Run within limits"; a click toggles it, with the first-time confirmation above.
- Enter sends, Shift+Enter adds a line, Esc in an empty field closes the panel (panel only).
- No model connected: the field is replaced by one primary "Connect a model" button.

### 2. Discussion header

Above the transcript: the title, then ⋯ with Discussion settings, Rename, Move to folder, Delete. In the panel the header keeps its ☰ and ✕.

### 3. Discussion sidebar (page only)

- Top row: a search field that filters by title, and a ＋ icon button for a new discussion.
- The folder tree stays. Each discussion has a context menu (Rename, Move to folder, Delete); folders keep theirs.
- The sidebar width is saved, as in the Media Center (principle 3).
- No full-width buttons.

### 4. Messages

- **Yours:** right-aligned, compact, accent background.
- **The assistant's:** full width, no border, so tables and selection cards have room.
- **Activity:** a quiet single line (▸ 3 tools · finished), expandable as today.
- **Approval cards and questions** keep their bordered card: they are the only elements that ask for a decision.

### 5. Empty state

A new discussion shows four example prompts as clickable cards. A click fills the composer without sending:

- Find ten films I don't seed yet and show them before any action.
- Prepare a Plan within 200 GB with the best Zen gain.
- Review my local upload drafts and list what is missing.
- Play a film with French subtitles.

### 6. Automations and History

- **Automations:** one card per task with its name, schedule, status and next run. The main action ("Run now", or "Enable" when paused) is a secondary button; Edit, Pause and Delete go in ⋯. "Create task" is the page's primary button.
- **History:** unchanged content, restyled with the new message and activity styles.

### 7. Desktop and web

Same structure on both. Web styles go in `app.css` with the existing role classes; desktop uses `set_role` / `icon_button` only, with no page stylesheet setting button looks.

## Acceptance

- The Assistant page and the Media Center panel use the same `ChatComposer`.
- No full-width text buttons on the Assistant page.
- Connections are reachable from Settings → Assistant and from the model chip; the Connections tab is gone.
- The mode chip asks for confirmation on the first switch to "Run within limits" only, and the choice survives a restart.
- Sending, stopping, approving, answering a question, switching and moving discussions, and running a task work as before.
- Tests cover the composer states (idle, running, no model), the first-time confirmation, and the sidebar width persistence.
- Screenshots in French and English, dark and light, at 1280 × 720, on desktop and web, reviewed before publishing.

## Order

1. `ChatComposer` and the message styles, used by both page and panel.
2. Header, sidebar and empty state.
3. Connections moved to Settings, mode chip with first-time confirmation.
4. Automations cards and History restyle.
5. Web parity, screenshots, docs (`docs/guide/*/assistant.md`) and release.

## Shared panel port (#106, 2026-11-19)

The main desktop and Web discussion/history now load `web/static/assistant/view.html`
through the shared panel base. The approved layout and French/English labels are retained,
with shared light/dark tokens. Connections still open Settings → Assistant.
The owner service stores the mode acknowledgement once for both hosts. Sidebar width
is a device preference. Refresh keeps the transcript scroll and unsent composer text.

Existing Media compact chat remains in its current host pending #111.
Live transcript updates follow persisted job messages and activity; the existing providers
do not stream individual tokens. No tracker or model credentials enter the bundled page.

## Automations and selection cards (#107, 2026-11-19)

The main Assistant uses the same bundled automation cards, editor and saved selection
review in both hosts. The approved layout is unchanged. Numeric controls reject invalid
limits before saving or previewing a schedule, while preserving existing fractional GiB
budgets. The shared view formats file sizes without depending on the Web shell.

Browser checks cover scheduling, editing, limit persistence, pagination, saved review tabs,
images and reverse-proxy paths. The desktop check runs a simulated scheduled model task
and opens its saved Upload card, including private image assets, files, NFO and review.
English/French and light/dark rendering use shared panel tokens.

The superseded native automation cards/editor branch and Web automation renderer are
removed. The remaining legacy discussion editor belongs to compact Media chat and Settings
until #111/#112. Automation deletion remains deferred because the service does not support it.
