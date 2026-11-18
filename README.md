# TorrentLinker

Français · [English](README.en.md) · [Documentation](docs/README.md)

Dépôt principal : [GitHub](https://github.com/Vietnoirien/TorrentLinker) · [Miroir du dépôt](https://git.mma.dev/Vietnoirien/TorrentLinker)

Retrouvez les torrents qui correspondent à vos fichiers et remettez-les en seed dans **qBittorrent, Deluge, Transmission ou rTorrent**, avec une prise en charge expérimentale de **µTorrent Classic et BitTorrent Classic**. TorrentLinker recherche les correspondances auprès d’un indexeur Torznab comme **c411**, puis fait vérifier les fichiers par le client torrent avant de lancer le partage.

![TorrentLinker : suivi Zen, catégories et notes des torrents](docs/guide/images/zen.png)

*Interface en français, thème sombre, données d’exemple.*

## Ce que l’application permet

- **Assistant intégré** : modèles locaux ou API, discussion, recherche Web et tâches programmées. [Guide](docs/guide/fr/assistant.md).
- **Médias** : lecture vidéo et musicale intégrée, reprise, playlists et discussion avec l’Assistant depuis le lecteur, sur bureau et sur le Web. [Guide](docs/guide/fr/media.md).
- **Agents MCP** : connecter un assistant, préparer des Plans et approuver ses actions. [Guide](docs/guide/fr/agents.md).
- **Clients nommés** : plusieurs connexions, une vue commune et des Plans répartis entre les clients choisis.
- **Bibliothèque** : parcours guidé, liste avec inspection et progression indépendante des fichiers, de la recherche à la remise en seed.
- **Recherche** : filtrer les torrents, consulter leurs détails dans des onglets et préparer une file de téléchargement.
- **Zen** : suivre les gains estimés et les notes, puis préparer un Plan selon l’espace et le budget disponibles.
- **Torrents** : gérer les téléchargements et le partage, avec une arborescence par tracker et catégorie.
- **Upload** : choisir une source, vérifier l’existant et préparer un brouillon avec fichiers, présentation, images et NFO, à relire avant envoi à c411.

Avec qBittorrent, Deluge et Transmission, les fichiers existants ne sont pas renommés sur le disque. Avec rTorrent, µTorrent Classic et BitTorrent Classic, un renommage sur le disque peut être nécessaire et demande une confirmation explicite. Sur l’application de bureau, les clés API et mots de passe sont conservés dans le trousseau système. L’interface est disponible en français et en anglais, avec un thème système, clair ou sombre.

## Télécharger

| Plateforme | Téléchargement |
| --- | --- |
Nous recommandons la dernière préversion 1.0 (bêta) : elle contient toutes les nouveautés. Ouvrez la [liste des tags](https://github.com/Vietnoirien/TorrentLinker/tags), où la plus récente est en haut, puis téléchargez le fichier de votre plateforme dans sa page de version. La version stable 0.12.2 reste disponible dans les [versions](https://github.com/Vietnoirien/TorrentLinker/releases).

| Plateforme | Fichier |
| --- | --- |
| Windows x64 | `TorrentLinker.exe` |
| Linux x86_64 | `TorrentLinker-x86_64.AppImage` |
| macOS (Apple Silicon) | `TorrentLinker-macOS-arm64.dmg` |
| Docker (amd64, arm64) | `ghcr.io/vietnoirien/torrentlinker:beta` |

Sous Linux, rendez l’AppImage exécutable avant de l’ouvrir. Sous macOS, l’application n’est pas notariée : au premier lancement, faites un clic droit sur l’application puis **Ouvrir**.

## Premiers pas

1. Activez l’interface Web de votre client torrent.
2. Lancez TorrentLinker et renseignez sa connexion ainsi que la clé API de votre indexeur dans les Paramètres. Le premier démarrage vous guide vers cet écran.
3. Dans **Bibliothèque → Remise en seed → Disque**, sélectionnez vos fichiers existants. Pour de nouveaux téléchargements, ouvrez **Recherche** ou **Zen → Plan**.

Le [guide de démarrage illustré](docs/guide/fr/demarrage.md) détaille la configuration, y compris pour Docker et les NAS.

## Guides et aide

Le bouton **Documentation**, au-dessus des Paramètres, ouvre les guides illustrés dans l’application, même hors ligne.

[Torrents et dossiers du client](docs/guide/fr/torrents.md) · [Bibliothèque](docs/guide/fr/bibliotheque.md) · [Recherche et téléchargements](docs/guide/fr/recherche.md) · [Zen et Plans](docs/guide/fr/zen.md) · [Extension navigateur](docs/guide/fr/companion.md) · [Uploads](docs/guide/fr/upload.md)

[Documentation complète](docs/README.md) · [Dépannage](docs/guide/fr/donnees.md) · [Signaler un problème](https://github.com/Vietnoirien/TorrentLinker/issues) · [Contribuer](docs/guide/fr/developpement.md)

## Interface web et Docker

Une interface web avec assistant de configuration est publiée en image Docker pour les NAS et seedboxes : `ghcr.io/vietnoirien/torrentlinker`. Partez de l’[exemple Compose](deploy/compose.example.yaml) et consultez le [guide Docker](docs/guide/fr/web-docker.md) pour l’accès aux dossiers.
