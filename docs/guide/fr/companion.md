# Extension navigateur

[Documentation](../../README.md) · [English](../en/companion.md)

L'extension facultative TorrentLinker relie un onglet c411 connecté à
TorrentLinker. Elle prend en charge Chrome, Brave et Edge. Firefox n'est pas pris
en charge. Gérez la connexion dans **Paramètres → Extension** sur le bureau,
ou **Réglages → Extension** dans l'interface web. Les statistiques du compte
restent dans **Zen → Profil**.

## Ses capacités

| Fonction | Fonctionnement |
| --- | --- |
| Lire les résultats XXX | Avec **Afficher le contenu XXX** activé, Recherche lit la catégorie XXX par votre session c411. Mettez l’extension à jour pour cela. La première lecture peut prendre environ 30 secondes. |
| Synchroniser les statistiques du compte | Actualise l'identité, le solde Zen, la Classe, le niveau, les transferts, la durée totale de seed, les uploads validés et le nombre de seeds actifs toutes les deux minutes. |
| Compléter l'historique Zen | Toutes les six heures, lit environ trois mois de votre historique Zen c411 (la date et le montant de chaque opération, jamais leur motif) pour que la courbe Zen du Profil couvre les jours antérieurs aux relevés de TorrentLinker. Les jours relevés par l'API ne sont jamais remplacés. |
| Récupérer les fichiers `.torrent` avec la session navigateur | Facultatif et désactivé par défaut. Utilise le compte c411 connecté lorsque TorrentLinker demande les métadonnées d'un torrent, notamment pour vérifier des candidats de la Bibliothèque ou envoyer une file ou un Plan. |

L'extension complète le profil API ; elle ne remplace ni ses valeurs ni vos
réglages de Plan. La clé API c411 reste à configurer dans TorrentLinker pour la
recherche et les accès API. Elle doit disposer du droit `profile:read` pour que
TorrentLinker identifie le compte à connecter.

Le navigateur récupère les métadonnées `.torrent`, pas les médias eux-mêmes.
TorrentLinker confie toujours le téléchargement ou la vérification des fichiers
au client torrent configuré. L'extension ne gère pas directement les clients
torrent et ne publie pas d'uploads.

## Installer et connecter

1. Ouvrez **Paramètres → Extension** sur le bureau ou **Réglages → Extension** dans
   l'interface web. Enregistrez ou téléchargez le ZIP de l'extension, puis
   extrayez-le dans un dossier que vous conserverez. Pour une installation locale
   sur le bureau, le fichier `TorrentLinker-companion.zip` des téléchargements de
   la version convient également.
2. Ouvrez `chrome://extensions`, `brave://extensions` ou `edge://extensions` dans le
   navigateur choisi. Activez le **Mode développeur**, puis **Charger l'extension
   non empaquetée**. Sélectionnez le dossier extrait `torrentlinker-companion`
   qui contient `manifest.json`.
3. Connectez-vous à c411 dans ce navigateur avec le même compte que celui de la
   clé API configurée dans TorrentLinker. Gardez un onglet c411 ouvert.
4. Revenez dans les paramètres de l'extension et cliquez sur **Connecter
   l'extension**. TorrentLinker ouvre une page de connexion et transmet les
   informations à l'extension installée. Aucun code n'est à copier. Sur le bureau,
   la page s'ouvre dans le navigateur par défaut : installez l'extension et
   connectez-vous à c411 dans ce profil de navigateur.
5. Vérifiez l'état de connexion dans les paramètres et les statistiques dans
   **Zen → Profil**. Un clic sur l'icône de l'extension ouvre sa page d'état. Cette
   page peut être fermée ; l'onglet c411 connecté doit rester ouvert.

Si **Connecter l'extension** est désactivé, vérifiez la clé API et actualisez le
profil API dans **Zen → Profil**. Le compte API doit être identifié avant la
connexion. Si vous avez installé l'extension après l'ouverture de la page de
connexion, revenez dans TorrentLinker et cliquez à nouveau sur **Connecter
l'extension**.

### Interface web distante et Docker

Utilisez HTTPS et téléchargez l'extension depuis **Réglages → Extension sur ce
serveur**. Ce ZIP est configuré pour son adresse et son chemin de proxy inverse.
Le ZIP fourni avec une version convient au bureau local et à une WebUI sur
localhost ; il n'est pas configuré pour votre serveur distant. Installez le ZIP
du serveur dans le navigateur de votre ordinateur, pas dans le conteneur Docker.
Le navigateur doit pouvoir joindre c411 et l'interface web.

En HTTP simple, le navigateur empêche une page distante de parler à l'extension :
une adresse comme `http://100.x.y.z:8787` ne peut pas se connecter. Avec
Tailscale, lancez `tailscale serve --bg 8787` sur le serveur, ouvrez l'adresse
`https://….ts.net` affichée, puis retéléchargez l'extension depuis cette adresse.

Si un reverse proxy authentifie les utilisateurs de l'interface web, l'extension
n'envoie aucun cookie et ne peut pas passer cette connexion. Faites contourner
ses cinq chemins, comme décrit dans
[Connexion par un reverse proxy](web-docker.md#connexion-par-un-reverse-proxy).

## Activer les téléchargements par session

Après la connexion, cochez **Télécharger les .torrent avec ma session c411** dans
les paramètres de l'extension. L'option est désactivée par défaut et conservée
après un redémarrage tant que la connexion reste valide.

Pour les `.torrent` absents du cache, TorrentLinker demande alors au navigateur
de les récupérer avec la session c411 au lieu de la clé API. Les envois de la
file et du Plan peuvent demander jusqu'à 100 fichiers à l'avance, avec quatre
requêtes navigateur simultanées par défaut. TorrentLinker n'ajoute pas de quota
propre, mais les autorisations et limites de c411 s'appliquent toujours. Cela ne
garantit ni des téléchargements illimités ni un débit précis.

- Un refus de session, notamment HTTP 401 ou 403, arrête l'envoi. Vérifiez le
  compte connecté puis reconnectez l'extension. TorrentLinker ne bascule pas sur
  la clé API.
- HTTP 429 fait respecter l'attente demandée par c411. Les paramètres affichent
  le délai restant ; reconnecter l'extension ne l'annule pas.
- Un torrent introuvable ou un délai dépassé sur un fichier est signalé pour cet
  élément. Un onglet fermé, déconnecté ou bloqué peut empêcher le lot de se terminer.

Décochez l'option pour utiliser la clé API lors des prochaines demandes de
`.torrent` absents du cache. Déconnecter l'extension désactive aussi l'option.

## Données échangées et conservées

La synchronisation du profil transmet uniquement les statistiques du compte,
sans titres de torrents, hashes ni listes de fichiers. Les téléchargements par
session échangent les hashes demandés et renvoient les fichiers `.torrent` à
TorrentLinker. Ces fichiers contiennent les métadonnées, dont les noms de fichiers
et les adresses des trackers. TorrentLinker vérifie le compte, la taille des
métadonnées et le hash attendu avant d'accepter un fichier.

L'extension n'exporte ni les cookies de connexion ni la clé API c411. Elle conserve
son jeton de connexion localement ; TorrentLinker conserve une empreinte du jeton
et le cache du profil. Les demandes par session gardent temporairement les
métadonnées en mémoire, mais les `.torrent` acceptés peuvent aussi être enregistrés
dans le cache habituel de TorrentLinker et transmis au client torrent. Leur
conservation n'est donc pas limitée à la mémoire.

## Suspendre, déconnecter et mettre à jour

- **Pause automatic sync** dans l'extension suspend les mises à jour du profil et
  la relève des demandes de téléchargement par session. Reprenez la
  synchronisation avant de réutiliser les téléchargements par session.
- **Déconnecter et effacer** dans TorrentLinker révoque la connexion, efface les
  statistiques de l'extension et désactive les téléchargements par session. Cela
  ne supprime pas les métadonnées de torrents en cache et n'arrête pas les torrents
  déjà actifs dans le client.
- Changer l'adresse de l'Indexeur ou la clé API efface la connexion et le cache du
  compte. Reconnectez l'extension pour le nouveau compte.
- Pour mettre à jour, téléchargez un nouveau ZIP depuis la même installation de
  TorrentLinker, remplacez les fichiers du dossier extrait, puis cliquez sur
  **Actualiser** dans la page Extensions du navigateur. Reconnectez l'extension si
  nécessaire. Une WebUI distante demande à nouveau son propre ZIP, pas le ZIP
  générique de la version.

La connexion survit normalement aux redémarrages de l'application et du navigateur.
Si le navigateur est fermé, si c411 est déconnecté ou si le compte diffère, les
anciennes statistiques restent visibles avec leur date de synchronisation. Après
cinq minutes, elles sont signalées comme en attente d'une mise à jour navigateur.
La synchronisation du profil reprend lorsque l'onglet du bon compte est disponible
et que l'extension n'est pas en pause. Une session de téléchargement refusée peut
encore demander une reconnexion avant un nouvel envoi.
