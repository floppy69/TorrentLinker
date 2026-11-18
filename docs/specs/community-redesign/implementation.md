# Community interface implementation

The approved preview is the visual specification, not a menu of optional ideas. Reproduce variant A’s typography, spacing, panels and interactions inside the existing app shell.

Exactly four Community tabs: Torrents, Chat, File d’attente, Historique. The compact library has separate comment/vote badges and a persistent inspector on wide windows; narrow windows open the inspector in a right drawer. Chat has general/class segments, a live message preview and the last recorded sent message. The waitlist defaults to the calendar, with its Calendar/List switch inside the view. Settings, automation and operation details use right drawers. The quota cards and automatic sync status stay compact. No separate top-level calendar, draft or settings tabs.

Approved layout: compact searchable torrent library with an action/detail panel, separate chat preparation, queue and operation history. Seed discovery starts automatically and traverses all pages through the paired companion. No manual next-page step. Preserve unsaved editor contents during background refresh.

History retains operation text and state transitions. Search, action filters, all-time/today/7-day/30-day/custom inclusive dates and a navigable monthly timeline make older operations retrievable.

Upcoming operations have a calendar, week/month navigation and day details. Show manual versus automatic origins and estimated local times. Operations can be inspected, paused, cancelled and edited/rescheduled. Actual dispatch must retain the existing account checks, live site eligibility, quotas, cooldowns and uncertain-send protection.

Automatic mode is opt-in, with separate comment, prepared-vote and chat toggles, editable comment template, selected chat messages/channels, publication hours/timezone and existing per-action daily limits/intervals. Plan at most seven days ahead, reserve capacity alongside manual operations, do not repeat known actions. Votes keep the owner's prepared choice. Disabling automatic actions preserves manual operations. Settings and journal survive restart.

Desktop and Web UI must render this same design, not merely expose the same capabilities. Uploads remain excluded. No live c411 posts in tests. Test seams approved by the user: CommunityActions, public desktop/Web interfaces, browser acceptance. Implement in the canonical checkout and refresh the unpacked companion at dist/torrentlinker-companion. Commit on current branch; no publication requested.

Approved interactive prototype archived on `prototype/community-redesign-20261117` at `f3efc41fba65ecdcc44280af72985f8e2aa937f8`. The production implementation uses the shared persistent journal; the preview’s fictional data and simulated sending are not shipped.

The bundled `web/static/community` view is rendered by both the Web UI and Qt WebEngine inside the desktop Community tab. A narrow QWebChannel bridge calls the existing Community service. The embedded desktop page can load only its bundled assets; canonical torrent links open in the system browser only when clicked. Web messages check both origin and source, then use the existing owner-authenticated API. The component alone permits same-origin framing; other application pages remain unframeable. Qt packaging must include WebEngine and the shared assets. Loading is deferred until the desktop tab is opened.

Visual acceptance must inspect rendered desktop and Web screens against the archived preview at comparable content widths. Functional tests alone do not establish design parity. Check the library, chat, queue calendar/list, history timeline and right drawers, including narrow layouts. Preserve unsaved text, text selection and persisted drafts through polling and restart.
