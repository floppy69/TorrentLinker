# Members: the rules behind the screens, #127

Status: decided by the owner on 2026-11-21. Being implemented (#128 to #138). Complements ADR-0022 and
the design previews in `members-settings/`, `members-invite/`, `members-signin/`,
`members-media/`, `members-requests/`, `members-notices/` and `members-ratings/`. Terms are
those of `CONTEXT.md`.

## Server opt-in

Members are off by default. `TL_WEB_MEMBERS=on` or `--members on` enables them after a restart.
With Members off, trusted proxies always act as the Owner and their user headers are ignored.
Member routes, invitations, Shared Screens and Requests return 404; their UI is hidden.
Disabling Members revokes links and sessions while preserving accounts and history.
The identity rules below apply when Members are enabled.

## Who makes a request

Every Web request resolves to one **actor**: the Owner, a Member, or a Viewer under an
account holder (the Owner or a Member).

- The startup password, or a trusted proxy with no user header, signs in the Owner.
- A Member's sign-in name and password, or a trusted proxy's user header (only from an
  address in `TL_TRUSTED_PROXIES`) that names a Member, signs in that Member. An unknown
  header name is refused, never mapped to the Owner. The header is `Remote-User`. It is read
  only once an account has a proxy name, so an existing proxy that already sends one keeps
  signing the Owner in; the Owner may give their own name too, on their card in Utilisateurs.
- On a Shared Screen, the chosen Viewer is carried by the session; the actor is that Viewer,
  with the account holder's Permissions narrowed by the Viewer's own.
- A disabled Member has no actor: every session ends at once.
- The desktop application and its local media server stay the Owner's. MCP (`/mcp`) keeps
  its Agent Grants and never accepts a Member's session.

## Enforcement

Each route declares the Permission it needs; the middleware checks it before the handler
runs. A route without a declaration is **Owner-only**, so a new route is safe by default.
Hiding a tab is only presentation.

Media is also filtered by **visibility**: an item is visible to an actor when its Library
Folder is allowed, its Content Kind is allowed, its Age Rating is at or under the limit (an
unrated item is hidden under any limit), and it is not adult content unless that Permission
is granted. Every Media route that names an item (detail, artwork, subtitles, stream,
preview, progress) answers 404 for an item that is not visible, the same as a missing one,
so hidden titles do not leak through guessed identifiers. Lists, the home rows, search
inside Médias and the tracker rows are filtered the same way. A Member never chooses the
Torrent Client: `client_id` is ignored and the server uses the client that holds the item.

## Route table

In code (#128) a route declares its need on its handler with `@needs(...)` from
`torrentlinker/web/permissions.py`: Permissions from `torrentlinker/accounts.py` (any one of
them), `Audience.PUBLIC`, `Audience.SIGNED_IN` or `Audience.ACCOUNT_HOLDER`, and optionally
the path values allowed (`action={...}`). The middleware checks it on `/api/*` and
`/documentation/*`; `/`, `/healthz` and `/static/*` serve no data and stay open as before.
A row below is declared by the issue that makes its handler answer for the actor (#131 Media
with visibility and per-person progress, #133 and #134 Requests, #137 Search, queue and
torrents, #138 the Assistant); until then the route stays Owner-only. Today the "nothing",
"signed in", `/api/members*`, `/api/account*` (#135), Media rows and the Member's Requests
rows (#133: listing their own, sending, cancelling, Wishes) are declared (the Media chat
waits for #138). In code (#131) a Member's age limit and Library Folders live in `media_limits` in
`accounts.sqlite` (no row: no limit, every folder); the limit applies to videos, music having
no Age Rating. Tracker rows are unrated films: a Member sees them with the Films Permission
and no limit. A Member's shell reads `/api/shell` instead of the Owner's setup snapshot.

| Routes | Needs |
| --- | --- |
| `/healthz`, `/api/login`, `/static/*`, `/companion/*` (its own pairing token) | nothing |
| `/`, `/api/shell` (navigation trimmed to the actor), `/api/logout`, `/api/documentation*`, `/documentation/*` | signed in |
| `GET /api/media`, `/api/media/home`, `/api/media/items/{id}`, `…/artwork`, `…/subtitles/*`, `…/stream`, `POST …/watched`, `…/forget-progress`, `…/preview`, `/api/media/previews/*`, `/api/media/sessions`, `/api/media/sessions/{id}` | Vidéo or Musique, by Content Kind, and visibility |
| `/api/media/playlists*` | Vidéo or Musique; playlists are the actor's own |
| `/api/media/sessions/{id}/chat` | Assistant, within its daily cap |
| `/api/media/scan`, `/api/media/tracker/{hash}/download` | Owner |
| New: `GET /api/requests` | signed-in Member: their own; Approver: everyone's |
| New: `POST /api/requests` (from a tracker film), `POST /api/requests/{id}/cancel` (own, pending) | Demander des films |
| New: `POST /api/wishes` | Faire des vœux |
| New: `POST /api/requests/{id}/accept`, `/refuse`, `/retry`, `/resolve` (a Wish to a release) | Accepter ou refuser les demandes |
| New: `/api/members*` (create, edit, invite, disable, delete, Viewers, Shared Screens of others) | Gérer les membres; never the Owner's account, never granting a Permission the editor lacks |
| New: `/api/account*` (own password, Viewers, PINs, Shared Screens, notification choices) | signed-in Member or Owner; not a Viewer |
| New: `POST /api/media/items/{id}/rating`, film details | Modifier classements et fiches |
| `GET /api/member-workspace/search` | Recherche c411 (consultation), using the same Indexer rate limiter and Media visibility rules. Asking goes through `POST /api/requests`. Owner Search jobs, filesystem browsing, queue mutations and settings stay Owner-only. |
| `GET /api/member-workspace/queue`, `/api/member-workspace/torrents` | Voir la file / Voir les torrents respectively; only the account’s accepted Requests, with no paths, trackers or private URLs. |
| `GET /api/queue`, `GET /api/torrents`, `GET /api/jobs/{id}` | Voir la file / Voir les torrents: only rows of the actor's accepted Requests, with no paths, trackers or private URLs |
| `/api/assistant/conversations*`, `/api/assistant/jobs*`, `/api/assistant/presentations/*`, `/api/assistant/image` | Assistant: the actor's own conversations and jobs, within the daily cap |
| Everything else: clients, settings, setup (including `/api/setup/assistant*`), confirmations, diagnostics, folders, library, `POST /api/jobs`, queue changes, reseed, upload, Zen, catalogue, seeding, c411 profile and community, feeds, agents, Assistant schedules, torrents workspace, `/mcp` | Owner |

A Viewer reaches only the Media rows above and `/api/logout`; never Requests, Wishes,
Search, the Assistant or `/api/account`.

## Requests

States: `pending` → `accepted` → `sent` → `downloading` → `available`, or `refused`,
`cancelled`, `expired`; `send_failed` after an accept that could not reach the Torrent
Client. A Wish is `pending` until an Approver resolves it to a release (it becomes an
accepted Request) or refuses it.

- **Sending.** The Member sends from a tracker film or from Search. The server checks the
  caps at sending: accepted this week plus pending must stay under the weekly count and size,
  and pending under the pending cap. A reached cap refuses with its reason and the next reset.
- **Week.** Monday 00:00 to Sunday 24:00, server time. Only accepted Requests count;
  refused, cancelled and expired ones give their slot and size back. Size counts the
  accepted release, which the Approver may change.
- **Answering.** Every Approver is notified; the first answer wins and the others see who
  answered. An Approver may accept their own Requests; they still count against their caps.
  An Approver may accept past a Member's caps: the inspector warns and the history flags it.
  A refusal may carry a note for the Member.
- **Accepting** sends the release to the Torrent Client at once, as the Owner's download
  would, into the folder its Content Kind maps to. If that fails (client offline, margin
  gone), the Request is `send_failed` with the reason for Approvers and "Retry"; the
  Member sees "en attente d'envoi".
- **Expiry.** A Request or Wish pending for 14 days expires and the Member is told.
- **Cancelling.** The Member may cancel while pending.
- **Available.** When the release's item appears in Médias, the Request becomes
  `available` and the Member is told.

In code (#133) Requests and Wishes are `requests`, with their timeline in `request_events`, in
`accounts.sqlite` (`torrentlinker/member_requests.py`), with no foreign key so they outlive
their Member. A cap refusal answers 409 with the `cap` reached (`count`, `size`, `pending`)
and the `reset`; a pending Wish counts toward the week and the pending cap, with no size. An
answer the Member has not seen is `unread` until the drawer opens (`POST /api/requests/seen`).
The Owner has no display name, so the button reads "Demander au propriétaire".

## Sessions and sign-in

- Accounts are stored with a slow password hash (scrypt); the Owner's startup password and
  the proxy stay as today.
- A Member's session on an unshared browser lasts 30 days of disuse; a Shared Screen's
  token 90 days. Both are HttpOnly, SameSite=Strict cookies, `Secure` behind HTTPS, stored
  hashed on the server and revocable one by one.
- Changing a password, disabling or deleting the account ends every session and Shared
  Screen of that account.
- Sign-in throttling is per account and per address: after 5 failures, a 1-minute lock that
  doubles on repeat, up to 15 minutes; the Owner is alerted (logged until the notifications
  of #136). The error never says which field was wrong. A success clears both counts. The
  Owner signs in with no sign-in name and the startup password, under the same throttling.
- Invitation links are single-use random tokens, stored hashed, valid 24 h, 3 or 7 days.
  Password links work the same way. In code (#130) a token is derived from `accounts.key`, a
  random key kept outside the database, so "Voir le lien" can show it again; it travels in
  the URL's fragment (`join#…`) and never reaches a server log. Behind a proxy there are none. A Viewer's PIN is 4 to 8 digits, stored hashed, with
  its own throttling; a forgotten PIN is reset with the account's password.
- The existing `X-TorrentLinker` header check, request size limits and security headers
  apply to every actor.

In code (#135) Viewers are `viewers` in `accounts.sqlite`, the account holder's own PIN
`holder_pins`, and Shared Screens `screens`, whose `viewer` is NULL until "Qui regarde ?"
is answered: until then the actor is a picker with no Permission (`/api/screen`,
`/api/screen/choose`). "Changer de profil" shows the picker while the current profile keeps
watching, so going down asks no PIN. A profile more restricted than another makes the
broader one need a PIN, refused until it has one; a profile with a PIN asks for it from the
picker, and from another profile only when stepping up. The Owner may also mark a screen
shared and have Viewers. Behind a proxy there are no Shared Screens. "Mon compte" is the
Settings section of every account holder; a Member's Settings hold only it and, for a
manager, Utilisateurs.

## Data

- A new `accounts.sqlite` beside the other stores holds accounts (the Owner as the fixed
  account `owner`), Permissions, caps, Viewers, sessions and Shared Screens, invitations,
  Requests and Wishes with their timelines, notification choices and Assistant usage.
- `media_progress`, `media_playlists` and Media sessions gain the actor (account and
  optional Viewer). Migration gives all existing rows to `owner`, once, in a transaction.
- Age Ratings live with the Media item, with their source (NFO, TMDb, or the person who set
  it). In code (#132) they are `media_ratings` in `media.sqlite`, one row per item
  with its `rank` on the CNC scale (0 Tous publics to 4 −18, indexed), so a limit is one join;
  a series is rated as a whole, and a scan never replaces a person's rating. The page reads
  `GET /api/media/ratings` and `POST /api/media/ratings/confirm`, both Modifier classements.

## Assistant for Members

Allowed with a simple daily cap until the measure in ADR-0022 is decided: a number of
messages per day, set per Member in the editor (default 20), reset at midnight server time.
The Assistant runs with the Member's Permissions: Media and read-only Search tools only; a
download it proposes becomes a Request. It always uses the Owner's providers, which Members
never see or configure. Schedules stay the Owner's.

## Removing a Member

"Désactiver" ends every session and Shared Screen and keeps everything; "Réactiver" undoes
it. "Supprimer" (only on a disabled Member) erases the account, its Viewers, progress,
playlists, Shared Screens, notification choices and Assistant conversations; their Requests
stay in the history as "ancien membre". Pending Requests are cancelled first.

## Later

- The real measure of the Assistant's cap for Members.
- Members on the desktop application.

In code (#138), `/api/member-assistant` owns account-scoped conversations and daily message
usage in `accounts.sqlite`. The Member selects no provider and sees no provider settings.
The configured Owner chat provider receives only that Member's recent conversation and a
fixed tool list: visible Media, permitted tracker film search, and Requests. Permissions
are rechecked before each tool call; downloads never go directly to a Torrent Client.
The cap reserves a message atomically and resets by the server's local calendar date.
Deleting the account cascades to its Assistant history and usage. The Owner's Assistant
routes, schedules, MCP tools and conversation store remain Owner-only.
