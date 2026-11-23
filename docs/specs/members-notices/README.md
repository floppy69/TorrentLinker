# Notifications settings design preview, #127

Status: layout **A** (sections) chosen by the owner on 2026-11-21 for Paramètres →
Notifications (ADR-0022). Implemented in the Web server for #136; this file preserves
the design preview.

Built only from approved components: the shared palette (`panel/base.css`) and the Settings
page's stylesheet (`settings/view.css`), embedded in `notices-prototype.html` so it opens
anywhere. Fictional data; nothing is sent.

Open `notices-prototype.html` directly. `?variant=A` is the chosen layout; B (a table, mail
set up in a dialog) and C (a three-step setup) stay in the file as the rejected
alternatives. "Vu par" in the bar switches between the Owner and a Member.

Decided:
- **Channels.** In the app (always on), the browser, and e-mail. The Owner enables the
  channels and sets their defaults; each person then chooses their own, within the enabled
  ones.
- **Mail.** SMTP, or an OVHcloud MX Plan preset (`ssl0.ovh.net`, port 465, SSL/TLS, the full
  e-mail address as the login), with a sender and "Envoyer un e-mail de test". E-mail stays
  unavailable until mail is set up. An e-mail carries only the title and the state, with a
  link to the app.
- **Browser.** Works when the Web UI is served over HTTPS; each person allows it in their
  own browser.
- **Events.** For Approvers: new Request, new Wish, Request cancelled. Every Approver is
  notified; the first answer wins and the others see who answered. For Members: Request
  accepted, Request refused (with the note), film arrived in Médias, Wish found a release.
  For the Owner: download margin below a threshold (in GB), invitation accepted, new Shared
  Screen, account locked after too many attempts.
- **Layout A.** Stacked cards: E-mail, Navigateur, then one card per event group, each event
  with its three channel checkboxes. A Member sees "Mon compte" and "Notifications" with
  only their own Requests' events.

Review paths:
- Envoi des e-mails → OVHcloud MX Plan: the prefilled server, port and security.
- Envoi des e-mails → Désactivé: the E-mail checkboxes grey out.
- Vu par Léa (membre): only "Mes demandes".
