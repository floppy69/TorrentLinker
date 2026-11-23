# TorrentLinker

Reconciles files a user already has on disk with torrents on a private tracker, so the data can be seeded again from the Torrent Client without re-downloading or touching the files, and plans which new torrents to seed to earn the tracker's Zen reward.

## Language

### Library side

**Library Folder**:
A folder the user registers for scanning, with a Content Kind and a scan grouping: Automatic (Local Items are detected, ADR-0015) or a fixed scan depth.
_Avoid_: Source folder, watch folder

**Local Item**:
One entry found in a Library Folder — at its scan depth, or detected in Automatic mode — a single file or a folder, treated as the unit that a torrent may correspond to. In Automatic mode an episode is a Local Item of its own and also part of its season or show pack.
_Avoid_: File, release, media

**Content Kind**:
The nature of a Library Folder's contents (movie, series, music, ebook, game, 3D model…), which decides how Local Items are searched.
_Avoid_: Type, category (category is a tracker/Torrent Client term)

**Path Mapping**:
A correspondence between a path prefix as this app sees it and the same location as the Torrent Client sees it, for a client in Docker, on a NAS or on another computer. One list of them applies to every path exchanged with the Torrent Client: Library Folders, Download Folders and Reseeds.
_Avoid_: Remote path, docker path

**Ignored File**:
A file (.nfo, thumbnails, samples, partial downloads…) excluded from every comparison between a Local Item and a torrent.
_Avoid_: Junk, extra

### Reconciliation

**Seeded Item**:
A Local Item whose files are already content of an Indexer torrent in the Torrent Client. A torrent of another tracker does not count: its files can still be cross-seeded.

**Partially Seeded Item**:
A Local Item of which some files, but not all, are content of Indexer torrents in the Torrent Client; not searched unless the user forces it.

**Orphan**:
A Local Item that no Indexer torrent in the Torrent Client covers, even if a torrent of another tracker does; the kind searched automatically. Explicit compatible discovery also accepts Seeded and Partially Seeded Items.
_Avoid_: Missing, unseeded

**Indexer**:
A Torznab endpoint (URL + API key) where Candidates are searched, added by hand or imported from Prowlarr or Jackett; c411 is one of them.
_Avoid_: Tracker (when meaning the search API), site

**Candidate**:
A torrent returned by an Indexer search for a Local Item, not yet verified against local data.
_Avoid_: Result, hit

**Match**:
A Candidate whose file tree has been compared to the Orphan's files and found to correspond by size; either Full (every torrent file has a local counterpart) or Partial (some torrent files are absent locally and will be skipped).
A Match inside an archive pairs the torrent's files with what a .zip, .rar or .7z Local Item holds; Reseeding it means unpacking the archive first, which only the user decides.
_Avoid_: Link

**Rejection**:
A user decision that a given Candidate is not the Orphan, remembered so it is never proposed again.

### Seeding

**Torrent Client**:
The program that seeds, qBittorrent, Deluge, Transmission, rTorrent, µTorrent Classic or BitTorrent Classic, as the user chooses; Reseeds and Plans are added to it, and its torrents decide which Local Items are Seeded.
_Avoid_: Client (alone, when the Indexer's API client could be meant), qBit (outside code)

**Reseed**:
Adding a Match to the Torrent Client pointed at existing data, then verifying by hash check before seeding. The board and Local Items share a per-client layout choice: rename paths inside the torrent where supported, or preserve torrent paths with a persistent Link Folder. Clients that would rename original files on disk require links. Existing prepared layouts retain their choice (ADR-0021).
The board requires every torrent file and verifies locally before the client's own check. Original files remain at their existing names and paths.
_Avoid_: Inject, relink

**Cross-seed**:
A Reseed of a torrent's data, or a Library Item's, onto another Indexer, found and added automatically: Full Matches and Partial Matches above a coverage threshold go in after Verification, the rest waits for review. Tagged `cross-seed` and the Indexer's name; independent of the original torrent.
_Avoid_: Inject, hardlink seeding

**Link Folder**:
A dedicated folder outside Library Folders holding persistent symlink layouts for Reseeds. Each link points to an original file using the Torrent Client's path namespace. Keep these layouts for as long as their torrents remain in use; they are not temporary verification files.

**Verification**:
The Torrent Client's hash check a Reseed must pass at 100% before the torrent is started; a failed Verification removes the torrent (never the data) and becomes a Rejection.

**Provenance Evidence**:
An original release name and file association recovered from an imported torrent. Size is a suggestion; verified target pieces establish byte correspondence. Evidence becomes stale when a local file changes.

**Repair Copy**:
An independent copy created for an explicitly confirmed download of missing target pieces. The existing Local Item remains unchanged. A Repair Copy is separate from an ordinary Reseed.

### Uploading

**Upload**:
A new torrent the app creates from an Orphan that no Candidate matches, named and described by the Indexer's rules, with its NFO, to be published on the Indexer and seeded from the existing data.
_Avoid_: Reupload (c411's term for one kind of Upload), release, post

**Upload Category**:
The c411 category an Upload is made for (Films & Vidéos, Ebook, Imprimante 3D…); it decides the Upload's rules, name, NFO and description. The Library Folder's Content Kind only proposes one; the user can pick another.
_Avoid_: Kind (a Content Kind is the Library's notion, not c411's)

**Category Options**:
The choices c411 asks for beyond the category (language, genre, format…), listed per subcategory; some are required, some allow several values. An Upload's Draft carries the chosen ones.
_Avoid_: Tags, metadata

**Local Draft**:
An editable Upload snapshot saved in TorrentLinker for review, scoped to one named Torrent Client. It contains the form, file snapshot and category checks. Saving it does not create a torrent or contact c411. Each edit creates a new revision.

**Local Draft Queue**:
The persistent collection of Local Drafts. Users review them here before explicitly sending a saved revision to c411. Automated Upload tasks stop here; an agent's send request always needs owner approval. Editing invalidates older send approvals. An uncertain send requires checking c411 before allowing another attempt.

**Draft**:
An Upload saved on c411 but not yet published; the user reviews and publishes it there.

**Refusal**:
A c411 rule a program can check (archives, formats, no file…): while an Orphan breaks one, its Draft cannot be sent to c411. A Local Draft can still be saved for correction.

**Warning**:
A c411 rule only the uploader can judge (no independent creators' paid files, one theme per pack): shown in the Upload tab beside the Refusals, but the Draft can still be saved.

**Inspection**:
A profile's reading of what an Upload's files say about themselves (audio tags and bitrate, MediaInfo and TMDb for video), done off the GUI thread when an item is selected; Refusals and names that need those facts say nothing until it ends.
_Avoid_: Scan (that is the Library's reading of file names and sizes)

**Existing Release**:
A release c411 already has for the item being uploaded, found by its title words or, for a category that has them, by ids, and shown before the Draft is saved. Information only: Team Pending refuses duplicates, the app never decides one.
_Avoid_: Duplicate (that is Team Pending's verdict)

**Presentation Image**:
The picture of an Upload that its description needs and c411's image upload refuses an API key for; the app renders the model itself and keeps private PNG assets for local review. A Pack's selected models appear on labelled contact-sheet pages of up to nine models each, with explicit coverage and saved camera settings. Public image hosting is required before sending the Draft; the app does not upload artwork publicly on its own.
_Avoid_: Screenshot, thumbnail, cover

**Announce URL**:
The user's private tracker address, holding their passkey, that every Upload's torrent carries.
_Avoid_: Passkey (alone), tracker URL

### Zen

**Zen**:
The c411 reward earned by seeding, spent as download credit (1 Zen covers 1 Go downloaded).
_Avoid_: Token, points, bonus

**Zen Estimate**:
The Zen per day a torrent is expected to earn for this user, from its size, seeders and seed age.
_Avoid_: Yield, reward (alone)

**Zen Profile**:
The user's own parameters that change Zen: Class, progression tree already unlocked, seed hours per day and torrent cap; read from the user's c411 profile where the API allows, entered by hand otherwise.

**Zen Balance**:
The Zen the user currently holds on c411, as reported by their profile; distinct from any Zen Estimate.

**Class**:
The c411 role a user picks, which decides how Zen is paid; Tanker and Swarm Keeper are paid on seeding, Reuploader on uploads.

**Catalogue**:
The locally stored list of torrents available on an Indexer, with size, seeders and category, that a Plan chooses from.
For c411, the Catalogue bundled with the app (or, in a build without one, the public Zen Lab snapshot) supplies older entries, and direct c411 metadata takes precedence. A snapshot or paging limit does not establish complete tracker coverage.
_Avoid_: Database, index

**Plan**:
A recommended set of Catalogue torrents to download and seed, chosen for estimated Zen or highest torrent notes within the user's free space, maximum download size, torrent limits and per-torrent size range.
_Avoid_: Portfolio, selection

**Download Folder**:
Where a Plan's torrents are downloaded, set per Indexer category or subcategory (falling back to the category's, then a default); it may lie inside a Library Folder.
_Avoid_: Save path (qBittorrent's term), download location (Deluge's), destination

### Sharing

**Owner**:
The person whose c411 account, passkey and Torrent Clients TorrentLinker works for; they hold every Permission and cannot be restricted.
_Avoid_: Admin, main user, user (when this person is meant)

**Member**:
A person the Owner gives access to, with an account of their own and only the Permissions granted to them.
_Avoid_: User, guest, friend, family account

**Permission**:
One thing a Member may see or do, granted per Member: a feature, a Library Folder, a Content Kind, adult content, making or accepting Requests, managing Members.
_Avoid_: Role, right, access level

**Viewer**:
A person who watches under the Owner's or a Member's account without signing in, chosen on a Shared Screen; they have their own watch progress and playlists, only Media Permissions, never broader than the account's, and never make Requests.
_Avoid_: Profile (Zen Profile and ReleaseScore profiles), home user, sub-account

**Shared Screen**:
A browser an account holder marked as shared when signing in, named ("Télé du salon") and remembered for 90 days of disuse; it asks who watches, and opening a less restricted Viewer there takes that Viewer's PIN.
_Avoid_: Device (a browser is all the server can tell apart), TV

**Request**:
A Member's ask to download a tracker release, waiting for an Approver; once accepted it is sent to the Torrent Client at once.
_Avoid_: Proposal (an agent's), order, download request

**Wish**:
A Request for a title with no release chosen yet; the Approver picks the release.
_Avoid_: Free-text request, suggestion

**Approver**:
The Owner, or a Member holding the Permission to accept or refuse Requests.
_Avoid_: Admin, moderator

**Age Rating**:
The minimum viewing age of a film or series on the French scale (Tous publics, −10, −12, −16, −18), from its metadata or set by the Owner or a Member allowed to edit it; a rating from another country is mapped to this scale. A Member's or Viewer's limit hides what is rated above it, and what has no rating yet.
_Avoid_: Certification, PEGI, parental rating

### Community Site

**Community Site**:
The project's own site on `torrentlinker.fr`, run by the project's maintainer: a public showcase that never names the tracker, and, for Site Accounts, Community Items and a forum.
_Avoid_: Community (the tracker's community page in the app), website, portal

**Site Account**:
A person's account on the Community Site, created only from a Linked App that is signed in to the tracker; one per tracker account.
_Avoid_: Member (a person on one TorrentLinker server), user

**Linked App**:
A TorrentLinker installation its Owner linked to their Site Account with a device code; it shares and imports Community Items and vouches for tracker membership.
_Avoid_: Paired app (the companion extension pairs), client

**Community Item**:
Something a Site Account shares for others to import: a Pre-roll, an RSS preset, a ReleaseScore profile or an Assistant prompt; reviewed before publishing, versioned, rated and commented.
_Avoid_: Upload (a tracker Upload), plugin, asset

**Pre-roll**:
A short video Médias plays before a film or episode, chosen from local and community clips by sequences, schedules and rules.
_Avoid_: Intro (a film's own opening), trailer (one kind of Pre-roll)
