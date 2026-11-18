# Community

Open **Zen → Community** on desktop or WebUI. Install the updated companion from
Settings → Companion, pair it, and keep a signed-in c411 tab open. The app/server
must remain running. Uploads are outside this feature.

Your active seeds and writable general/class channels load automatically when you
open Community. Discovery continues page by page in the background. Search the
**Torrents** list and select a title to see its local actions or prepare a comment
or vote. **Refresh library** starts a new scan; otherwise the cache is refreshed
after six hours. This does not scan disks or torrent file lists. The site checks eligibility before each publication.

Choose a comment, your own confidence vote, or a chat message. Write and edit its
text, pick a channel where applicable, and set **Send after** in your local time.
**Save draft** stores it without sending. **Schedule** adds it to the waitlist. Use
the settings icon to enable the queue, set each action's daily maximum
and minimum interval, and edit reusable comment/chat templates. Defaults are
five per action, with 60 seconds between comments/votes and 600 seconds between
chat messages. Sending starts disabled. A maximum of zero disables that action.

The French picker provides 200 editable quotes, jokes and tiny poems. Selecting
one fills the editor and live preview. Quotations retain their authors in the text.
General and class channels share one chat budget. Chat messages require at
least five words; repeated messages are refused. The queue does not create
positive votes automatically or invent an opinion about downloaded content.

Pause the entire queue or individual entries, move an entry first, cancel it,
or edit it. Editing pauses the entry immediately; saving returns it to draft,
so it must be queued again. Items already sending or published cannot be edited
here. Pausing cannot recall a request already sent to c411.

The waitlist shows timers, site counters, local usage and outcomes. Timers are
an earliest send time, not an exact appointment: the browser polls about every
30 seconds. The site may impose slower timing or refuse a message. Each action
has a maximum of five/day, adjustable downward. Site and local daily quotas reset at midnight in Europe/Paris,
including daylight-saving changes. The interval between posts still applies
across midnight. Other activity on the site can consume the available daily quota.

Scheduled items, templates, quotas and receipts survive restarting the app or
browser. The journal follows the c411 account ID, so changing an API key does
not reset duplicate checks. A closed browser or disconnected companion leaves
items waiting. A rate limit preserves the server's requested wait.

If a request might have succeeded but its response is lost, the item becomes
**Uncertain**. It is never resent automatically. Check c411 before taking any
further action. Successful comments show **XP pending, 24 h** and subsequently
**XP unconfirmed**: publication alone does not prove an award. The current
implementation does not attribute XP ledger entries to individual posts or
claim a fixed Zen payout.

## Calendar and history

**Waitlist → Calendar** shows upcoming operations by week or month, with a daily agenda.
The Calendar/List switch changes the view without leaving the waitlist.
Automatic and manual origins are identified. Open an operation to inspect its
text, pause, cancel or edit its date. Desktop and WebUI share the same calendar. Both show local-time estimates that include
reserved quota and cooldowns. These are not guaranteed publication times.

**History** keeps the text and state transitions of each operation. Search titles
or messages, filter by action, and choose today, 7 days, 30 days, all time or an
inclusive date range. Navigate the monthly timeline and select a day to retrieve
older operations. Open an entry to inspect its edits, attempts and receipt.
**Export** saves the filtered operations as JSON.

## Automatic mode

Open **Automatic mode** above the four Community tabs, then enable
**Plan automatically** and choose comments, prepared votes and/or chat. Sending
still requires the queue to be running. Set the daily limits and intervals,
publication hours and IANA timezone. The planner reserves up to seven days ahead.

Comments use your template; `{titre}` or `{title}` inserts the torrent title.
Votes use the choice and date you saved. When automatic votes are enabled,
saving a vote makes it available for automatic scheduling. The app never chooses
an approval for you. Chat uses your selected messages, one per line, and the
selected general/class channels. Add suggestions individually or paste your own
messages. A shared chat quota applies to both channels.

Disabling a type cancels its unsent automatic slots and preserves manual entries.
Changing selected chat messages/channels removes obsolete slots; comment-template
changes update unsent automatic comments. Explicitly cancelled operations stay
cancelled. Automatic mode and its selected content survive restart.
