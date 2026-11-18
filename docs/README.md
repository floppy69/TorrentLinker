# Documentation TorrentLinker

[Présentation et téléchargement](../README.md) · [English introduction](../README.en.md)

Les guides et leurs captures sont aussi disponibles dans **Documentation**, juste au-dessus des **Paramètres**, sur le bureau et dans l’interface web. Le sélecteur de langue permet de passer du français à l’anglais. La copie embarquée correspond à votre installation et fonctionne sans accès Internet. **Ouvrir en ligne** donne accès à la documentation du dépôt.

## Commencer

1. [Installer et configurer](guide/fr/demarrage.md) : première connexion, client torrent, dossiers, NAS, Docker et proxy.
2. [Bibliothèque et remise en seed](guide/fr/bibliotheque.md) : ajouter un dossier, retrouver des correspondances et vérifier les fichiers.
3. [Rechercher et télécharger](guide/fr/recherche.md) : filtres, détails, onglets et file de téléchargement.

## Aller plus loin

- [Médias](guide/fr/media.md) : vidéos, musique, playlists et chat pendant la lecture.

- [Assistant et automatisations](guide/fr/assistant.md) : modèles locaux et API, discussion, recherche Web et tâches programmées.

- [Agents et accès MCP](guide/fr/agents.md) : connexions, propositions, permissions et objectifs.

- [Plusieurs clients torrent](guide/fr/clients.md) : profils nommés, dossiers et Plans répartis.

- [Gérer les torrents](guide/fr/torrents.md) : trackers, catégories et commandes.
- [Extension navigateur](guide/fr/companion.md) : installation Chrome/Brave/Edge, statistiques et téléchargements par session c411.
- [Zen et Plans](guide/fr/zen.md) : notes, gains estimés, budget et choix des torrents.
- [Communauté](guide/fr/community.md) : commentaires, votes et chat programmés.
- [Préparer un upload c411](guide/fr/upload.md) : brouillons et images ; [règles par catégorie](guide/fr/upload-categories.md).
- [Données, mises à jour et dépannage](guide/fr/donnees.md).
- [Développer, traduire et tester](guide/fr/developpement.md).

Les captures montrent l’interface en français, en thème sombre, avec des données d’exemple. Ce sont des captures des composants de l’application, réalisées hors ligne ; elles ne contiennent aucun compte ni fichier personnel. Les décorations des fenêtres dépendent du système utilisé.

## English guides

- [Media](guide/en/media.md)

- [Assistant and automations](guide/en/assistant.md)

- [Agents and MCP access](guide/en/agents.md)

- [Multiple Torrent Clients](guide/en/clients.md)

- [Setup and connections](guide/en/getting-started.md)
- [Library and reseeding](guide/en/library.md)
- [Search and download queue](guide/en/search.md)
- [Torrent management](guide/en/torrents.md)
- [Browser companion](guide/en/companion.md)
- [Zen and Plans](guide/en/zen.md)
- [Community](guide/en/community.md): scheduled comments, votes and chat.
- [Uploads and Drafts](guide/en/upload.md)
- [Data and troubleshooting](guide/en/data.md)
- [Development and testing](guide/en/development.md)

## Références techniques

- [Vocabulaire du projet](../CONTEXT.md)
- [Décisions d’architecture](adr/)
- [Recherches sur les API et règles c411](research/)
- [Notes de version](releases/)

## Actualiser les captures

Depuis la racine du dépôt, avec les dépendances de développement installées :

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/capture_docs.py
```

Le script utilise des paramètres et une base temporaires, interdit les connexions réseau et remplace l’accès au trousseau. Il enregistre les PNG dans `docs/guide/images/`. Les autres données de l’application ne sont pas modifiées.

Pour les captures en anglais, ajoutez `--language en` à cette commande. Elles sont enregistrées dans `docs/guide/images/en/`.

## Web et Docker

[Guide français](guide/fr/web-docker.md) · [English guide](guide/en/web-docker.md)

Les captures de l’interface web utilisent également un client fictif et une configuration temporaire :

```bash
TL_WEB_BROWSER=1 TL_WEB_SCREENSHOTS=docs/guide/images/web .venv/bin/pytest tests/test_web_browser.py
```

Les captures des profils et destinations de Plans se régénèrent hors ligne avec `QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/capture_client_profiles.py`.
