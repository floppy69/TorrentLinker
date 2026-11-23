# Médias as a Member design preview, #127

Status: layout **B** (a bell with a drawer) chosen by the owner on 2026-11-21 for where a
Member follows their Requests (ADR-0022). Not implemented yet.

Built only from approved components: the shared palette (`panel/base.css`) and the Media
page's stylesheet (`media.css`: posters, rows, the title panel and its release block, status
badges, buttons), embedded in `member-prototype.html` so it opens anywhere. Fictional data:
Léa, a Member; Vincent, the Owner.

Open `member-prototype.html` directly. `?variant=B` is the chosen layout; A (a "Mes
demandes" row in the home) and C (a "Mes demandes" tab and page) stay in the file as the
rejected alternatives. The bar simulates Vincent's answer and a reached quota.

Decided:
- **What a Member sees.** Médias without the Owner's tools: no client selector, no library
  refresh (⟳), no Assistant (✦) unless granted, no XXX tab unless granted.
- **Requesting.** On a tracker film, "Demander à Vincent" replaces "Télécharger", above the
  remaining quota ("Il vous reste 2 demandes et 58 Go cette semaine"). A reached cap
  disables the button and says why and until when. Once requested, the panel shows the state
  and "Annuler la demande"; the poster carries a status badge.
- **Wishes.** "Faire un vœu": a title, an optional year and a note for the Owner, from the
  title panel, the tracker row and the drawer.
- **Layout B.** A bell in the Media menu, with a badge counting new answers, opens a drawer:
  the quota, each Request and Wish with its state and the approver's note, "Annuler la
  demande" while pending, and "Faire un vœu". New answers are marked until seen. Answers also
  show a short notice on screen.

Review paths:
- Demander Dune, then simulate "Vincent refuse": the notice, the badge on the bell, the note
  in the drawer and on the title panel.
- "Quota atteint" in the bar: the button disabled with its reason.
- Faire un vœu, then open the bell.
