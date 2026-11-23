# Sign-in and "Qui regarde ?" design preview, #127

Status: layout **C** (big screen) chosen by the owner on 2026-11-21 for the Viewer picker
of ADR-0022. Not implemented yet.

Built only from approved components: the shared palette (`panel/base.css`) and the Web
shell's welcome screen (`app.css`), embedded in `signin-prototype.html` so it opens anywhere.
Fictional data; nothing is sent.

Open `signin-prototype.html` directly: it opens on "Qui regarde ?". `?variant=C` is the
chosen layout; A (an avatar grid) and B (a list inside the sign-in card) stay in the file as
the rejected alternatives. The bar's menu shows the sign-in screens, which all layouts share.

Decided:
- **Sign-in.** The Web sign-in card with a sign-in name: "Identifiant", "Mot de passe", and
  "Cet écran est partagé" with the screen's name ("Télé du salon"). "Je suis le propriétaire"
  switches to the server's startup password. A wrong password says so without telling which
  field; too many attempts lock the form for a minute; a forgotten password is a new link
  from the Owner.
- **Shared Screen.** Only a browser marked shared asks who watches; it stays signed in for
  90 days of disuse. Unmarked browsers go straight to the account holder.
- **Layout C, "Qui regarde ?".** Big tiles for a TV: each Viewer's initial, name and a lock
  when a code is needed; the arrows move the selection and OK (Enter) opens it, as with a
  remote. A locked profile opens a PIN pad, typed or clicked. The heading names the screen.
- **PIN rule.** Once an account has a more restricted Viewer, opening a less restricted one
  takes its PIN; going down never asks. Then "Bonne séance, Hugo", with "Ouvrir Médias" and
  "Changer de profil".
- Managing Viewers and Shared Screens is in `../members-settings/users-prototype.html`
  (Modifier → "Profils et écrans partagés").

Review paths:
- Arrows to Hugo, Enter: opens without a code. Back, then Léa: the PIN pad (1234).
- Menu → Connexion: untick "Cet écran est partagé" and sign in: no picker.
- Menu → Mauvais mot de passe, Trop d'essais, Propriétaire.
