# Paramètres → Utilisateurs design preview, #127

Status: layout **A** (member cards with the editor) chosen by the owner on 2026-11-21,
for the Members and Permissions of ADR-0022. Not implemented yet.

Built only from approved components: the shared palette (`panel/base.css`) and the
Settings page's stylesheet (`settings/view.css`), embedded in `users-prototype.html` so it
opens anywhere: section navigation, cards, Clients-style cards, fieldsets, checks, the File
access table, the dialog and the sticky Save bar. Fictional data; nothing is saved.

Open `users-prototype.html` directly. `?variant=A` is the chosen layout; B (one table of
Permissions × Members) and C (a preset, then only the differences) stay in the file as the
rejected alternatives. The bottom bar switches light/dark.

Decided:
- **Layout A.** A new last Settings section. "Partager TorrentLinker" offers an invite link
  (valid 24 h, 3 or 7 days) or an account with a password; the Owner's own card is locked.
  One card per Member summarises their Permissions; "Modifier" opens the editor under it.
- **The Permission list**, as the editor groups it:
  - Account: display name, sign-in name, the reverse proxy's user name (`Remote-User`),
    a starting preset, a password link, the account's Viewers.
  - Médias: video by Content Kind (films, series, anime), music, Media Center, visible
    Library Folders, an Age Rating limit (unrated titles are hidden under a limit), adult
    content (only with no limit or 18).
  - Demandes: make Requests, make Wishes, and three optional caps: Requests per week, Go
    per week, Requests pending at once. Caps need the Request Permission.
  - Outils: Search (read-only), the Assistant (cap to define later), read-only views of the
    download queue and of the torrents.
  - Équipe: accept or refuse Requests, manage Members (never the Owner or their settings),
    edit ratings and film details.
  - Owner-only, shown locked: settings and credentials, Zen and the c411 profile, Upload,
    agent access, the Assistant's providers.
- **Presets** are starting points only: Spectateur, Famille, Enfant, Administrateur.
- **Invitations** (page in `../members-invite/`): "Créer le lien" shows the one-time link, its
  QR code, Copy, the expiry and preset, and email sending once mail is configured. A pending
  invitation's card offers "Voir le lien" and "Annuler l'invitation".

Review paths:
- Edit Léa: set the age limit to -12 and see adult content disabled; untick "Demander des
  films" and see the caps disabled.
- Switch Léa's preset to Enfant: her name stays, her Permissions change.
- "Inviter quelqu'un" → "Créer le lien" shows the link and QR code; Karim's card can show it again or cancel it.
