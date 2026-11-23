# Age Ratings design preview, #127

Status: layout **A** (a list) chosen by the owner on 2026-11-21 for rating the films that have
no Age Rating (ADR-0022). Not implemented yet.

Built only from approved components: the shared palette (`panel/base.css`) and the Media
page's stylesheet (`media.css`), embedded in `ratings-prototype.html` so it opens anywhere.
Fictional data: Vincent, the Owner; Léa, a Member limited to −12.

Open `ratings-prototype.html` directly: each layout opens on its own screen. `?variant=A` is
the chosen layout; B (a "Sans classification" home row) and C (one film at a time, keys 1 to
5) stay in the file as the rejected alternatives. "Vu par" switches to Léa.

Decided:
- **Scale.** The French CNC scale: Tous publics, −10, −12, −16, −18. Ratings from other
  countries are mapped to it.
- **Sources.** The NFO file (`<mpaa>`, `<certification>`), then TMDb's French certification
  (needs a TMDb API key in Settings; c411's film details carry none), then a person. French
  ratings apply on their own; a mapped foreign rating ("TMDb : R (États-Unis) → −16 ?") waits
  for confirmation.
- **Unrated films** are hidden from every Member and Viewer with an age limit until rated.
- **Who edits.** The Owner, and Members granted the Permission to edit ratings.
- **Title panel.** The rating sits before the year; for whoever may edit, its source and
  "Modifier" below, opening the five levels. An unrated film shows "Sans classification",
  the suggestion with "Confirmer", and the five levels.
- **Layout A.** "Sans classification (n)" in the Media menu, for editors only, opens a page
  listing every unrated film: poster, title, year, genre, the suggestion or "Aucune
  classification trouvée", and the five levels. "Confirmer les n suggestions" accepts all
  mapped ratings at once. Rated films leave the list.

Review paths:
- Confirmer les 2 suggestions, then rate the other two: "Tous les films ont une
  classification".
- Accueil, pick Le Monde après nous: the suggestion on the title panel.
- Vu par Léa: no unrated film and nothing above −12.
