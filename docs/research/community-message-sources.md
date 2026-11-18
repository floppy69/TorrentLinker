# French shout suggestions

Prepared on 17 November 2026 for the first comments, votes and chat queue.
The library is `src/torrentlinker/assets/community_messages_fr.json`.

It contains 200 editable suggestions: 14 quotations, 96 jokes and 90 short
poems. Quotes carry the author's name in the message itself. The other entries
were written for this feature, with `author: "TorrentLinker"`, `original: true`
and `source: null`. They are original drafts, not attributed folklore or
extracts from contemporary comedians, songs or poetry.

## Quotation sources

The quotations were checked against digitized primary texts on Wikisource.
The cited works and editions predate 1900, except the 1915 edition of Charles
d'Orléans, whose poem dates from the fifteenth century. The authors died in
1695, 1711, 1896 and 1465 respectively. Only the literary text is reproduced,
not modern introductions, notes or illustrations.

| Entry IDs, with the `fr-quote-` prefix omitted | Author and text | Inspected edition |
| --- | --- | --- |
| `petit`, `patience` | Jean de La Fontaine, *Le Lion et le Rat* | [Fables, Bernardin-Béchet, 1874, pp. 74–75](https://fr.wikisource.org/wiki/Fables_de_La_Fontaine_(%C3%A9d._1874)/Le_Lion_et_le_Rat) |
| `tortue` | Jean de La Fontaine, *Le Lièvre et la Tortue* | [Fables, Bernardin-Béchet, 1874, pp. 188–190](https://fr.wikisource.org/wiki/Fables_de_La_Fontaine_(%C3%A9d._1874)/Le_Li%C3%A8vre_et_la_Tortue) |
| `travail` | Jean de La Fontaine, *Le Laboureur et ses enfants* | [Fables, Bernardin-Béchet, 1874, p. 164](https://fr.wikisource.org/wiki/Fables_de_La_Fontaine_(%C3%A9d._1874)/Le_Laboureur_et_ses_enfants) |
| `roseau` | Jean de La Fontaine, *Le Chêne et le Roseau* | [Fables, Bernardin-Béchet, 1874, pp. 58–59](https://fr.wikisource.org/wiki/Fables_de_La_Fontaine_(%C3%A9d._1874)/Le_Ch%C3%AAne_et_le_Roseau) |
| `clarte`, `ouvrage`, `effacer`, `rime`, `conseil`, `limites` | Nicolas Boileau, *L'Art poétique*, chant I | [Œuvres poétiques, Imprimerie générale, 1872](https://fr.wikisource.org/wiki/Boileau_-_%C5%92uvres_po%C3%A9tiques/L%E2%80%99Art_po%C3%A9tique/Texte_Entier) |
| `ciel`, `arbre` | Paul Verlaine, *Le ciel est par-dessus le toit* | [Sagesse, L. Vanier, 1893, pp. 101–102](https://fr.wikisource.org/wiki/Sagesse_(1893)/Le_ciel_est_par-dessus_le_toit) |
| `printemps` | Charles d'Orléans, *Le temps a laissié son manteau*, rondeau LXIII | [Poésies complètes, texte établi par Charles d'Héricault, Flammarion, 1915, p. 115](https://fr.wikisource.org/wiki/Le_temps_a_laissi%C3%A9_son_manteau) |

Line breaks and spaces are normalized for chat; terminal punctuation closes an
excerpt when its source continues. The words are preserved, including the old
spelling in Charles d'Orléans. Short excerpts from verse remain quotations in
the picker. The `poem` category contains the newly written poems.

## Use in the queue

These are suggestions to select and edit, not preapproved messages. Loading the
library must not enable posting or enqueue all entries. General and class
channels share the site's shout budget. A suggestion being locally unused does
not prove that the site will treat it as new or award XP.

The picker uses stable entry IDs; the send journal retains the actual edited
text. Duplicate checks use that normalized submitted text across both channels
and all previous local sends, so reimporting the library does not clear history. Do not automatically add
punctuation or vary words to evade the site's repetition rule.

## Validation

The build check read every entry and verified:

- Exactly 200 entries, with unique stable ASCII IDs.
- The three categories and expected schema types.
- At least five words in every message, with at least five in each quotation
  even before its author attribution.
- A maximum of 500 characters; these entries range from 48 to 147.
- No duplicate text after Unicode normalization, accent removal, case folding
  and punctuation/whitespace normalization.
- Quotation entries have an HTTPS source and attribution; original entries
  have no external source or invented attribution.

The library is inert JSON. No message was sent during its preparation.
