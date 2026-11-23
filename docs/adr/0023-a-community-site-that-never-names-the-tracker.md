# A Community Site that never names the tracker

TorrentLinker's community lives in one thread on the tracker's forum. To grow it, and to share what users make (Pre-rolls for Médias, RSS presets, ReleaseScore profiles, Assistant prompts), the project gets its own site on `torrentlinker.fr`. The Owner runs it alone at first, with trusted moderators later, on their own VPS and with no budget.

The site never names the tracker in public. The public front is a short showcase: what the app does, screenshots, downloads, and links to the guides on GitHub, which do name it. Everything else (Community Items, the forum, comments) needs a Site Account, and the forum, where members may name the tracker, is readable only when signed in. The tracker thread stays for announcements; the site complements it.

A Site Account can only be created from a Linked App: the app, linked once with a device code, vouches that it is signed in to the tracker and sends a keyed hash of the tracker username, never the name. That gives one account per tracker account and bans that stick, without tracker data leaving the app. A patched app could lie, so a moderator still opens forum access. Sign-in is then by e-mail magic link, GitHub or Discord; mail goes out from the `torrentlinker.fr` MX Plan mailbox.

Community Items are shared from the app with "Partager": the app strips feed URLs, passkeys, paths and names before sending, and every item is reviewed before publishing until its author is trusted. Items have ratings, download counts, a comment thread and versions the app offers as updates. Pre-roll videos must be the uploader's own or freely licensed, already MP4 H.264/AAC at most 1080p and 50 MB, and are stored in a self-hosted S3 store (Garage) capped at 10 GB; the VPS never re-encodes.

The site is a separate private repository (`Vietnoirien/torrentlinker-site`): Next.js and TypeScript, its own Postgres, Garage, behind the VPS's existing Traefik, deployed from GitHub Actions through a private GHCR image. The Catalogue stays on its private GitHub release and is never served by the site. Crash reports do not go to the site either: the app drafts a GitHub issue the user reviews.

## Considered Options

- **Name the tracker publicly**: rejected; a public page tying the app to a private tracker invites scrutiny for the tracker and its members.
- **Open sign-up**: rejected; the forum discusses the tracker, so accounts come from a Linked App that is signed in to it.
- **A stronger membership proof** (a code posted on the tracker, checked by hand): rejected as too much work for a single operator; moderator approval of forum access covers the spoofing risk.
- **Discourse, Flarum or GitHub Discussions** for the forum: rejected for a forum built into the site, sharing its accounts, moderation and Community Item threads.
- **The app's Python stack for the site**: rejected for Next.js with TypeScript end to end.
- **Hosting the Catalogue on the site**: rejected; it is tracker data and stays a private release.
- **Sending mail from the existing vietnoirie MX Plan as `@torrentlinker.fr`**: impossible, OVH refuses a From domain other than the mailbox's (550 5.7.1), so `torrentlinker.fr` has its own MX Plan.
- **Re-encoding uploads, or a public video host**: rejected; the shared four-core VPS cannot transcode, and links to third-party hosts rot.

## Consequences

The app gains a link to the Community Site, "Partager" buttons and a Pré-rolls panel in Médias that browses and imports Community Items. The domain's A records move from OVH's shared hosting to the VPS. The publisher stays anonymous as a non-professional (LCEN), the legal notice naming OVH as host; the site needs a privacy policy and account deletion. Backups of the database and videos are pulled nightly to the Owner's PC, since the VPS has little free disk.
