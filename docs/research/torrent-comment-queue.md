# Torrent history and XP actions through the companion

Investigated against TorrentLinker beta.39, commit `1181625`, on 17 November 2026.
This note inventories repository capabilities and proposes a design for comments,
confidence votes, daily login, completed downloads and shouts. Uploads are
explicitly outside this pass at the user's request. Repository evidence is combined
with first-party public frontend code and read-only signed-in GET checks. A source
contract is not a successfully tested POST and does not establish permission for
scheduled automation. No comment, vote or shout was posted; no account setting
was changed. Public bundle names below identify the version inspected on this date.

## What can be listed today

A useful list can be built from the configured Torrent Clients now. The common
`Torrent` model contains the infohash, title, tags, progress, client state and
tracker identities; it does not currently retain completion timestamps or
lifetime downloaded bytes. `indexer_torrents()` recognizes c411 torrents from
tracker URLs, known hashes and app tags. Client summaries can be requested without
per-torrent file lists, which matters for large libraries. This provides
**currently observed client torrents**, not a complete account download history.
[Model](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/domain.py#L102),
[indexer membership](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/seeding.py#L77),
[qBittorrent summaries](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/qbit.py#L217).

The existing app queues are not an archive of all previous downloads. Successful
Search sends are removed from `download_queue`, and startup deletes older `sent`
rows. A saved Plan is replaced/cleared as a working document. Request/feed
journals may provide partial provenance for those workflows, but cannot restore
all historic manual downloads or torrents removed from clients.
[Successful queue handoff](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/download_queue.py#L223),
[startup cleanup](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/store.py#L269),
[Plan clearing](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/store.py#L1258).

The companion currently imports aggregate account statistics. Its active-seed
collector requests only two records to obtain the total and deliberately drops
titles, hashes and file lists. Profile history stores daily aggregates rather
than per-release download events. We need a new, explicitly defined history
import, not an interpretation of the current snapshot as a torrent list.
[Collector](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/companion_extension/collect.js#L95),
[Profile history](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/profile_history.py#L1).

Keep these concepts distinct in the UI and data model:

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| `.torrent` descriptor fetched | Metadata requested from c411 | Media downloaded, completed or watched |
| Accepted by a Torrent Client | Client accepted a download/reseed operation | Download completed |
| Client reports progress 100% | Selected client content is complete | Bytes were downloaded from c411 rather than supplied locally |
| Site reports completed or seeding | Eligibility evidence under the supplied site rule | A review/opinion about the content |
| Imported download/snatch history | Whatever the site's documented record means | Completion unless the API explicitly says so |

A Reseed can be eligible under the supplied **completed or seeding** rule. It
must not be labelled a new download simply because it is complete. Likewise,
fetching a descriptor must not automatically put an item in a completed-download
XP list.

## Rules supplied in the conversation

These were transcribed from the user's screenshot and checked against the site's
[actions catalog](https://c411.org/api/ic/actions-catalog). The screenshot specifies
**XP**. Public frontend helpers separately explain the indirect Zen reward below.

| Action | XP | Daily cap | Timing and eligibility supplied |
| --- | ---: | ---: | --- |
| Torrent comment | 25 | 5 | Completed or seeding release; one comment per torrent; 30-second cooldown. XP arrives 24 hours after posting if the comment is still visible. Removed/hidden comments before then earn no XP but still consume the day's comment count. |
| Confidence vote | 25 | 5 | Completed or seeding release; once per torrent. No cooldown shown. |
| Completed download | 25 | 5 | Once per release. |
| Shout | 25 | 5 | 30-second cooldown; at least five words; not repeated. These content requirements were shown for shouts, not comments. |
| Daily login | 25 | 1 | 50 from day 7; 75 from day 30. |

The five/day limits describe XP-bearing actions; they do not by themselves prove
a hard website posting limit. The proposed rewards queue should stop at its
configured reward budget and obey any stricter posting limits.

Comment quota must be consumed at **posting**, not 24 hours later when XP may be
awarded. `Posted / awaiting XP` and `XP confirmed` are different states. An
app-side daily count cannot see comments made from another browser/device, so
site totals must be reconciled before dispatch if the site exposes them.

## Verified download-history entry point

Read-only site inspection opened the site's [download-history page](https://c411.org/user/downloads)
and inspected its [first-party frontend bundle](https://c411.org/_nuxt/CttA6OI8.js).
That page calls `GET /api/profile/downloads` with `page`, `perPage` and `q`.
The current account has history recording disabled. The setting was **not**
changed. This verifies an entry point, not a populated response schema or a
complete historical import. Do not treat a disabled/empty history as proof that
the account has never downloaded anything. An explicit user choice would be
needed to enable future recording, and it must not be presented as retroactive
reconstruction of past downloads.

## First-party contracts and current evidence

### Release candidates

A signed-in read-only call to
[`GET /api/profile/active-seeds`](https://c411.org/api/profile/active-seeds)
with `page` and `perPage` returned paginated, site-recognized active seeds even
while download history was disabled. It returned `data` records containing
`torrentId`, `infoHash`, `name`, `size`, `seeders`, `leechers`, `seedingTime`,
`uploaded`, `isFreeleech`, `counted`, `untied` and `category`; pagination is in
`meta.total`, `page`, `perPage` and `totalPages`. A request for two records was
clamped to ten. No account titles, hashes or totals are retained in this note.

Use this as the initial candidate source, augmented by current client summaries
and optional enabled download history. A seeded torrent's detail page showed
enabled confidence-vote buttons and an editable comment composer during the
read-only check. This is evidence for the current account/release only. It does
not establish every seed's eligibility, absence of a previous comment, or an XP
award. The detail flags and current server rules must be checked per release.

### Rules, counters and award history

These signed-in GETs were verified without changing account state:

| Route | Observed response | Use |
| --- | --- | --- |
| `/api/ic/actions-catalog` | Entries include `actionType`, `xp`, `dailyLimit`, `today`, `lock`, `audience`, `condition` | Authoritative rules and used-today counters; separate buckets per action |
| `/api/ic/level` | `success`, `level`, `xp`, `xpToNext`, `streakDays`, `streakDaysMax` | Current XP and login streak |
| `/api/ic/recent-actions?limit=2` | `success`, `actions`, `nextCursor`; sampled entries have numeric `id`, `actionType`, `bucketDay`, `createdAt`, `xpGained`, `publicationId` | Cursor-based award ledger and server day buckets |

The [rank UI](https://c411.org/_nuxt/CkkwDb2Y.js) normally reads recent actions
25 at a time using `limit` and optional `cursor`. Sampled `publicationId` values
were null, so its mapping to a torrent/comment is still unverified. A ledger row
must not be attributed to a queued comment solely because it earned 25 XP.
Use catalog counters and ledger `bucketDay` rather than inventing a local day
boundary. The server's reset timezone is still unknown. Catalog login XP is the
base 25; the UI uses the current streak to display 50 or 75.
[Level API](https://c411.org/api/ic/level),
[recent actions API](https://c411.org/api/ic/recent-actions?limit=2).

### Comments and confidence votes

The [torrent page bundle](https://c411.org/_nuxt/C-fIN-tS.js) and its imported
[shared comments component](https://c411.org/_nuxt/DWujoaSA.js) establish these
frontend contracts. They have not been POST-tested:

- `GET /api/torrents/{infoHash}/comments` accepts `page`, `limit` and `sort`.
  The component requests 20 records and uses `recent` or `top`; it consumes
  `data`, `meta.page`, `meta.totalPages`, `meta.total`. Comment entries expose
  `id`, `author.id`, `content`, `createdAt` and optional `replyTo` in the UI.
- `POST /api/torrents/{infoHash}/comments` sends `{content, replyToId?}`.
  The UI treats `response.comment.id` as its publication receipt. Its minimum
  is three characters after plain-text conversion; its default maximum is 500.
  These are frontend checks, not proof of every server validation rule.
- `POST /api/torrents/{infoHash}/trust-vote` sends
  `{vote: "approve" | "disapprove" | "remove", reason}`. The detail state exposes
  `trust.canVote`, `userVote`, `voteReason` and the comment controls expose
  `commentAccess.canComment`, `commentAccess.reason`, `minLevel` and
  `commentsLocked`. Vote removal/change exists in the UI but must not be treated
  as another XP opportunity.
- Both write adapters use `csrf-token`. The
  [CSRF helper](https://c411.org/_nuxt/CNndkeMO.js), exported as `t`, reads
  `meta[name="csrf-token"]` in the page. The extension can use this locally in
  the c411 context; it must not export the token or session cookies to the app.
  The investigation read helper source only, not any actual token.

`canComment` is a posting permission, not a proven reward-eligibility flag or an
existing-comment check. Source lists delete/edit/hide operations, but those are
outside the proposed queue. No server idempotency key was found. Listing the
account's previous comments can help reconciliation, but pagination, deleted or
hidden comments, replies and once-per-release XP semantics still need resolving.

### Shout transport and limits

The [app bundle](https://c411.org/_nuxt/DrTdFsnn.js) sends channel messages over
WebSocket when connected and uses a REST fallback:

```text
POST /api/messages/channels/{channelId}/messages
body: {content, replyToId}
header: csrf-token
response consumed: success, messageId, isFirstEver
```

Its imported [WebSocket store](https://c411.org/_nuxt/BgND3Klp.js) emits
`channel:send` with `{channelId, content, tempId, replyToId}` and an acknowledgement
callback. A temporary message ID is not evidence of server-side idempotency.
The app also applies channel and personal slow modes; these may impose a stricter
wait than the 30-second XP rule. The owner confirmed that general and class channels qualify for XP. A follow-up
read verified public channels expose `isDefault`, `classSlug`, `canWrite` and
`isArchived`. The exact server word/duplicate validation remains unverified. A generic channel POST is not enough to claim shout support.

### Daily login and completed downloads

No dedicated check-in or completed-download award call was found in the inspected
app, rank, profile and authentication sources. The
[authentication store](https://c411.org/_nuxt/egtodoHx.js) initializes/refreshes
with `GET /api/auth/me`; this does not establish that this GET earns login XP.
The app receives `ic:xp_gained` events with `actionType`, `xpGained`, optional
`zenGained` and daily counters. Events and the ledger can observe an award, but
do not establish the server trigger. Completion appears suitable for observation
and reconciliation through the client/tracker/site, not an extension command to
manufacture a completion. Exact server semantics remain unknown.

## Remaining XP actions: repository capabilities and gaps

The same account-level service can present all five actions, but each needs its
own rule and evidence. Current extension dispatch only imports `collectProfile`
and `collectDescriptors`; there is no existing comment, confidence-vote, shout
or daily-check-in executor to expose in the UI.
[Current dispatch imports](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/companion_extension/background.js#L1).

| Action | Reusable today | Remaining gap | Appropriate extension role |
| --- | --- | --- | --- |
| Comments | Account binding, client/site seed list, source-confirmed comment routes, catalog counters | Previous-comment/XP eligibility reconciliation, POST error semantics, publication-to-award mapping | Prepare drafts, submit once when due, retain receipts and check delayed rewards |
| Confidence votes | Same release/account identity, source-confirmed vote route and permission/current-vote fields | Actual award receipt mapping and server validation | Send the user's chosen vote; completion alone is not a positive opinion |
| Daily login | Signed-in session, level/streak and action ledger | Qualifying trigger and reset timezone | Show today's award/streak; no forced logout/login or invented claim action |
| Completed downloads | Progress/state, accepted-send receipts, site seeds and action ledger | Durable local completion history, site history schema and award mapping | Observe and reconcile real completion; metadata retrieval is not completion |
| Shouts | Account transport and source-confirmed channel send contract | XP-eligible channel, word/duplicate validator and history reconciliation | Submit prepared text under its own rules; repeating an identical template conflicts with the non-repeat condition |

### XP and reward observations

`UserProfile` already preserves total XP, current level, progress into the level
and XP to the next level. `ProfileHistory` records total XP by local day, allowing
a trend or aggregate change, but not attribution to a particular action. The
companion's own snapshot preserves only `profile.level`, not total XP or action
receipts. A rise in total XP can come from another action or device, so it is not
proof that one queued comment earned its 25 XP. Add per-action evidence when the
site exposes it; otherwise display **unknown/unattributed**, not confirmed.
[Profile fields and parser](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/profile.py#L41),
[XP daily history](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/profile_history.py#L22),
[companion snapshot](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/companion_extension/collect.js#L67).

The site does pay Zen indirectly through level completion. Its
[XP helper](https://c411.org/_nuxt/B6BDWZAc.js) uses 75 XP to finish level 1,
then 13 more XP per level: completing current level `L` costs
`75 + 13 × (L - 1)` XP. The cumulative threshold to enter level `L` is
`75 × (L - 1) + 13 × (L - 1) × (L - 2) / 2`.
The [reward helper](https://c411.org/_nuxt/CX57Wolf.js) and
[rank tooltip](https://c411.org/_nuxt/C1eZjdrL.js) attach Zen to the **level being
completed**:

| Completed level | Zen | Completed level | Zen |
| --- | ---: | --- | ---: |
| 1–6 | 1 | 104–122 | 10 |
| 7–17 | 2 | 123–152 | 12 |
| 18–24 | 3 | 153–182 | 14 |
| 25–36 | 4 | 183–214 | 16 |
| 37–48 | 5 | 215–248 | 18 |
| 49–60 | 6 | 249–283 | 20 |
| 61–74 | 7 | 284–327 | 22 |
| 75–88 | 8 | 328–380 | 25 |
| 89–103 | 9 | 381–400 | 27 |

The displayed level caps at 400. Thereafter each 5,262 XP tranche pays 27 Zen.
Consequently, a 25-XP action has no fixed immediate Zen payout. A forecast should
start from current XP and count level thresholds crossed; pending comment XP
must stay projected until awarded. These are public frontend formulas, not a
newly tested payout. The [streak helper](https://c411.org/_nuxt/CyqVrFfL.js)
independently confirms the 25/50/75 XP thresholds at days 1/7/30.

A client can already distinguish incomplete, completed-paused and actively
seeding states. Those observations are useful evidence, but site eligibility and
XP decisions remain separate. TorrentLinker's existing download-budget code
already checks progress to reconcile completed storage reservations; it does not
claim an XP award or retain a universal completion log.
[Client model](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/domain.py#L114),
[completion used for storage accounting](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/agent/budgets.py#L38).

### Shared implementation without conflating actions

An `account_action` journal can hold an action type plus its specific subject,
prepared payload, due time, attempt/result and reward status. Use separate quota
buckets for comments, confidence votes, shouts and completed downloads; daily
login has its own streak/day eligibility. Do not use one shared five-action daily
budget or let reconnecting clear any bucket. A generic dispatcher can enforce
account binding, persistence and uncertain outcomes, while action-specific
validators determine eligibility and payload rules.

For the first UI, show **available / scheduled / posted or recorded / waiting for
reward / confirmed / unknown**, with an explanation of the evidence. A completed
download is observed rather than "sent" by this dispatcher. Login status is
claimable only if the site exposes such an action. Shout text needs separate
validation from comments. Automatic choices and numeric defaults beyond the
supplied caps should wait for the endpoint and rule investigation.

## Existing extension transport

The foundation is usable. Pairing binds a one-time code to the API account,
remembers the extension origin, and stores a hash of the receiver bearer token.
The extension keeps the token in trusted local extension storage. Browser session
credentials stay in the c411 tab; executed functions use same-origin requests
without exporting cookies. Both the native receiver and WebUI route incoming
companion requests through `ProfileWorkspace.receive()`.
[Account binding and pairing](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/profile_workspace.py#L249),
[receiver authentication](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/profile_workspace.py#L398),
[extension transport](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/companion_extension/background.js#L15),
[Web receiver](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/web/profile.py#L23).

The descriptor executor restricts itself to a fixed c411 route, checks account
identity before/after its batch and returns allowlisted results. It has HTTP 429
handling and propagates a requested cooldown. These are useful patterns for a
comment executor, but it cannot simply change GET to POST: a lost POST response
may still mean the comment was published.
[Executor](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/companion_extension/descriptor.js#L25).

The current descriptor queue is **ephemeral**: jobs are in a dictionary, expire
within minutes and do not survive an app restart. Its stable request ID prevents
duplicates only within retained jobs. The extension does not persist completed
result receipts for acknowledgement retry. A comment queue therefore needs its
own durable state and delivery protocol.
[Queue lifetime and idempotency](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/companion_downloads.py#L48),
[result upload](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/companion_extension/background.js#L151).

The browser currently polls commands with a 30-second alarm. This is a wake-up
mechanism, not an exact timer. A signed-in c411 tab and reachable TorrentLinker
receiver are required; a sleeping/closed browser cannot post on time. Scheduled
work should remain due and resume within its constraints rather than promise an
exact posting instant or burst all overdue work.
[Polling and prerequisites](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/companion_extension/background.js#L114),
[alarms](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/companion_extension/background.js#L225).

## Proposed minimum implementation

This is a design proposal, not implemented code or a commitment to site support.

1. **Torrent activity store.** Add a durable account-level list with c411 release
   identifier, infohash, title/link, provenance, client IDs, first observed time,
   site completion/seeding evidence and existing-comment status. Import paginated
   site active seeds and optional enabled history; label client-only evidence honestly.
   Reconcile incrementally with shared client summaries rather than rescan disks
   or request every torrent's file list. Deduplicate the same release across
   clients. Preserve history when a torrent leaves a client.
2. **Account-scoped comment journal.** Store a unique account/release queue item,
   immutable text for each attempt, template/version, due time, optional minimum
   interval, state, attempt ID, remote comment ID, posting timestamp, reward due
   timestamp and result. Account identity should be c411 origin plus stable
   account ID, not just the API-key binding hash: changing a key/re-pairing must
   not reset the once-per-torrent guard or daily cap. Disconnect disables
   dispatch while retaining the journal.
3. **Transactional scheduler.** Use the app/server as the single authority for
   due work and quota reservations. Claim at most one posting attempt per account
   at a time. Enforce the site's 30-second comment interval and the five/day XP budget,
   reconciled with authoritative catalog counters and ledger day buckets. A user cap can lower this.
   The site's daily reset timezone must be verified; do not substitute the OS
   timezone silently. Existing download reservations and timezone-aware schedules
   provide patterns, but their current rules are not comment rules.
   [Reservations](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/agent/budgets.py#L74),
   [timezone-aware schedule](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/assistant/models.py#L42).
4. **Dedicated extension executor.** Add a typed comment command and separate
   feature enablement from descriptor downloads. Validate the exact account,
   release identifier, text revision and approved fixed-origin endpoint. Check
   current eligibility/existing comment before sending. Store the attempt and
   result receipt in extension local storage until the app acknowledges it. Retry
   an acknowledgement with the same receipt, never repeat a POST merely because
   its acknowledgement failed. HTTP 401/403 pauses posting; 429 preserves the
   server's cooldown through reconnection and restart.
5. **Desktop/Web parity.** Both frontends use one headless service/store. The
   account's actions view can show eligible torrents, selected drafts, a waitlist,
   next eligible send time, today's used/reserved quota, connection status and
   posted comments awaiting their 24-hour reward check. Provide editing before
   dispatch, reorder, pause and cancel. A saved template may prepare text; it
   should not invent claims that the user watched, read or verified content.
   Display confirmed XP separately from expected XP. Project Zen only from verified
   level thresholds and label it as projected until awarded.

Suggested delivery states:

```text
Draft → Queued → Scheduled → Sending → Posted
                     ↘ Paused/refused     ↘ Uncertain
Posted → Awaiting 24-hour check → XP confirmed / Not rewarded / Unknown
```

`Uncertain` is essential if a POST may have succeeded but its response was lost.
Reconcile against the account's comments/remote comment ID if supported. Without
an authoritative reconciliation method, leave it visible for review rather than
automatically repost. Existing send code already follows this principle for
Torrent Client mutations.
[Uncertain send](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/send.py#L57),
[restart treatment](https://github.com/Vietnoirien/TorrentLinker/blob/1181625/src/torrentlinker/store.py#L272).

## External questions still requiring verification

- Download history's populated schema, retention and exact meaning. Does it
  include descriptor-only events, and can it identify completed downloads?
- Previous-comment lookup coverage, deleted/hidden/reply handling and exact
  once-per-torrent reward semantics. `canComment` alone cannot answer these.
- Server comment validation, error and response-loss behaviour. No server
  idempotency guarantee has been established for comments, votes or shouts.
- Mapping a pending comment to a delayed award. Recent action samples had null
  `publicationId`; a non-null mapping must be demonstrated before attribution.
- Server day-reset timezone and whether catalog counters include pending
  comments, refused posts and external-device activity exactly as expected.
- Exact server duplicate/word-count rules and complete history lookup for
  reconciling ambiguous sends. The owner confirmed general and class channels
  qualify; both share `shout_message` counters.
- Daily-login qualifying trigger and tracker/completion-award semantics. No
  dedicated frontend action was found; do not create a speculative endpoint.
- Whether the site's rules permit scheduled template posting through an
  extension. Endpoint existence alone does not settle this question.

## Test requirements before enabling posting

Use fixtures for the workflow first. Cover account changes and API-key rotation;
multiple clients seeing one release; descriptor-only records; known reseeds;
existing comments; daily boundaries and daylight-saving transitions; external
site activity consuming quota; lost POST responses; lost receipt acknowledgements;
app/extension restart; closed browser; 429 cooldown persistence; and comments
removed before 24 hours. Confirm uncertain sends never create a second comment.
A live posting test requires a concrete user-authorized comment and destination;
this investigation has not sent one.
