# Cross-seed design previews, #151

Design previews for ADR-0024 (automatic Cross-seed across many Indexers). Not implemented yet.

## Cross-seed tab

Status: layout **A** (Flux) chosen by the owner on 2026-11-22.

Built only from approved components: the shared palette (`panel/base.css`) and the Reseed board's stylesheet
(`reseed/view.css`), embedded in `cross-seed-tab-prototype.html` so it opens anywhere. Fictional Indexers
(c411, Nebula, Orion, Vega) and torrents; nothing is sent.

Open `cross-seed-tab-prototype.html` directly. `?variant=A` is the chosen layout; B (one tile per Indexer) and
C (review cards first, the rest as a feed) stay in the file as the rejected alternatives.

Decided:
- **Place.** A fourth tab of the Reseed board: Remise en seed, Cross-seed, Dossiers, Activité.
- **Running bar.** Active or paused, what is in progress, what waits for review, the automatic rule (Full,
  and Partial ≥ 95 %), the number of Indexers and the `cross-seed` tag.
- **Layout A.** State tiles as filters (Tous, À vérifier, Ajoutés, En attente, Échecs, Données disparues),
  then the board's list and inspector. Each row: the target Indexer, the torrent, from → to, size, coverage,
  state and when.
- **Inspector.** The reason in words; a coverage bar with the threshold marked; missing files ("absent ·
  ignoré"); the decision: "Ajouter sans les fichiers manquants" or "Décompresser et remettre en seed", and
  "Écarter"; "Réessayer" after a failed Verification (otherwise never proposed again); "Retirer du client
  (garder les données)" when its data disappeared. Then what the client gets (tags `cross-seed` and the
  Indexer, the original's category and folder, the client's layout) and the steps: searched, matched, added
  stopped, verified at 100 %, seeding.

Review paths:
- Select The Bear (88 %, under the threshold): "Ajouter sans les fichiers manquants" → verification → added.
- "Simuler un téléchargement terminé" in the bar: a new torrent is searched, matched on Nebula, verified,
  added on its own.

## Indexers settings

Status: layout **A** (Cartes) chosen by the owner on 2026-11-22.

Built only from approved components: the shared palette (`panel/base.css`) and the Settings page's stylesheet
(`settings/view.css`), embedded in `indexers-prototype.html`. Fictional Indexers; nothing is sent.

Open `indexers-prototype.html` directly. `?variant=A` is the chosen layout; B (one table) and C (three steps)
stay in the file as the rejected alternatives.

Decided:
- **Place.** A new Settings section, "Indexeurs", after ReleaseScore.
- **Layout A.** "Ajouter un indexeur Torznab" first, then one Clients-style card per Indexer: name, source
  (Intégré, Prowlarr, Jackett, Ajouté à la main) and URL; state (Connecté, Limité, Erreur with the reason);
  the id searches its caps advertise (IMDb, TMDb, TVDB); its pace in words; "Chercher sur cet indexeur",
  Tester, Modifier, Retirer. c411 is built in: dashed card, its hourly budget, never removed.
- **Adding by hand.** A dialog: name, Torznab URL, API key; "Tester" also reads the caps.
- **Prowlarr or Jackett.** Service, address, API key; the list of its indexers (already imported or
  available), "Importer la sélection", "Resynchroniser" with the last sync time. Removing an Indexer leaves
  its Cross-seeds in the client.
- **Cross-seed rules.** "Ajouter automatiquement les correspondances sûres"; the Partial threshold as a
  slider (default 95 %); a reminder that adds are stopped, verified at 100 % then started and never
  download missing files; the sources and layout in words; "Suspendre le cross-seed".

Review paths:
- Tick Lyra in the Prowlarr list, "Importer la sélection": a new card.
- "Ajouter un indexeur Torznab", "Tester" in the dialog: the caps line fills in.
- Move the threshold: the label follows; untick the automatic adds: the slider is disabled.
