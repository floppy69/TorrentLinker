# Invitation page design preview, #127

Status: layout **B** (the form beside what is shared) chosen by the owner on 2026-11-21,
for the invitations of ADR-0022. Not implemented yet.

The page an invitation link opens, outside the app. Built only from approved components:
the shared palette (`panel/base.css`) and the Web shell's welcome screen (`app.css`: the
brandmark, heading, card and full-width primary button of the sign-in page), embedded in
`invite-prototype.html` so it opens anywhere. Fictional data; nothing is sent.

Open `invite-prototype.html` directly. `?variant=B` is the chosen layout; A (everything in
the sign-in card) and C (three steps: account, password, notifications) stay in the file as
the rejected alternatives. The bottom bar switches the link's state and light/dark.

Decided:
- **Layout B.** "Vincent vous invite", with the link's expiry. On one side "Votre compte":
  display name and sign-in name (pre-filled from the invitation), password and its
  confirmation with a strength bar. On the other "Ce qui vous est partagé": the Owner's note,
  what the Member will see, whether and how much they may request, and that the Owner can
  change it while their own progress stays theirs.
- **Rules:** a password of at least 12 characters, both entries equal; "Rejoindre" stays
  disabled until then, then leads to a welcome that opens Médias.
- **Closed links:** an expired link asks the Owner for a new one; a used link offers to sign
  in. An invitation link works once.
- The Owner's side is in `../members-settings/users-prototype.html`: "Inviter quelqu'un" →
  "Créer le lien" shows the link, its QR code, Copy, the expiry and preset, and email sending
  (disabled until mail is configured in Paramètres → Notifications). A pending invitation can
  show its link again or be cancelled.
