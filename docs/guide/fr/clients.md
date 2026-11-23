# Plusieurs clients torrent

Cliquez sur **Clients…**, à côté du sélecteur de client cible de l'application, pour ajouter une connexion, modifier ses paramètres ou choisir le client par défaut. Donnez un nom court à chaque connexion, par exemple NAS ou Seedbox. Vous pouvez utiliser plusieurs instances de qBittorrent ou mélanger qBittorrent, Deluge, Transmission, rTorrent, µTorrent Classic et BitTorrent Classic.

![Clients torrent nommés](../images/clients.png)

Votre connexion actuelle est conservée automatiquement. Chaque client possède ses propres identifiants, dossiers de téléchargement et correspondances de chemins. Ouvrez **Modifier les paramètres**, testez la connexion, puis configurez ses dossiers. Les dossiers de bibliothèque et le compte c411 sont communs à l'application.

Les catégories sont présentées avec leurs sous-catégories en retrait. Dans la WebUI, le chemin complet reste visible après sélection pour distinguer les noms identiques. Une catégorie parente peut avoir son propre dossier, hérité par ses enfants sauf destination spécifique. Une correspondance de chemins vide se vérifie automatiquement avec un fichier temporaire et un torrent de test gardé à l'arrêt, tous deux supprimés ensuite. Ce test nécessite un montage accessible en écriture à TorrentLinker.

Le sélecteur **Client cible** concerne les vérifications et reseeds de la bibliothèque, le seed des uploads, les téléchargements de la recherche et la file du client sélectionné. La file indique le client de chaque torrent. Renommer un profil ou changer le client par défaut ne redirige pas les opérations en attente.

Dans **Torrents**, cochez **Tous les clients** pour afficher une vue commune. Filtrez par nom et utilisez le menu contextuel sur les lignes sélectionnées pour agir sur les clients correspondants. Retirer un torrent conserve les fichiers ; leur suppression demande une confirmation. L'estimation Zen globale ne compte chaque hash qu'une fois.

## Adresses, secrets et connexions refusées

Une adresse sans `http://`, comme `192.168.0.50:8080`, est acceptée. Une adresse erronée nomme le champ et ce qu’il faut saisir.

Les mots de passe, clés d’API et jetons enregistrés s’affichent sous la forme `••••••••`. L’œil permet d’en révéler un. Les quatre clés d’API c411 supplémentaires se modifient une par une.

Si un client refuse votre connexion, TorrentLinker cesse de s’y reconnecter automatiquement jusqu’à ce que vous modifiiez ses réglages ou appuyiez sur **Tester**. Cela évite un bannissement : qBittorrent bannit une IP après plusieurs échecs de connexion. Quand qBittorrent a banni l’adresse, le message le dit. Une clé d’API ne sert jamais à se connecter.

## Plans

Ouvrez **Destinations du Plan…**. Sélectionnez un seul client pour lui réserver le Plan, ou plusieurs pour une répartition automatique. Indiquez le budget de chaque client en Gio. La valeur zéro utilise l'espace disponible après votre marge de sécurité.

![Choix des destinations du Plan](../images/plan-clients.png)

Vérifiez les colonnes Client et Dossier de téléchargement avant l'envoi. Un Plan réparti affecte chaque torrent à un seul client et partage le budget d'espace libre lorsque plusieurs clients utilisent le même disque monté. Le calcul utilise l'heuristique Zen existante et ne garantit pas une répartition mathématiquement optimale.

Une destination indisponible produit un échec visible. TorrentLinker ne la remplace pas par un autre client. Terminez ou retirez les éléments de file, Plans et vérifications en attente avant de remplacer ou retirer leur connexion.

## Interface web

Utilisez le sélecteur en haut de la page. Les paramètres proposent **Ajouter un client**, **Définir par défaut** et **Retirer ce client**, avec un champ de nom dans le formulaire de connexion. La configuration des dossiers s'applique au client sélectionné.

**Tous les clients** affiche une vue commune. Sélectionnez un client précis pour modifier ses torrents ou démarrer sa file. Dans le planificateur, ouvrez **Destinations du Plan**, sélectionnez les clients et leurs budgets, puis examinez le résultat. Chaque ligne permet de choisir sa destination avant la mise en file. Changer cette destination utilise le dossier de téléchargement configuré pour le nouveau client.

Le serveur doit accéder aux fichiers pour l'analyse, le reseed et la préparation d'uploads. Les téléchargements web nécessitent toujours un dossier monté et vérifié. Une seedbox accessible uniquement par son API permet la gestion des torrents.

![Destinations du Plan dans l'interface web](../images/web-clients.png)

## Fichiers d'une seedbox en SFTP, FTPS ou FTP

Sans accès à ses fichiers, une seedbox permet la gestion des torrents, Zen et la recherche. Pour analyser, comparer, faire un reseed, utiliser le centre multimédia ou préparer un upload, montez le dossier de téléchargement de la seedbox sur cet ordinateur avec [rclone](https://rclone.org/), puis ajoutez une correspondance de chemins. TorrentLinker ne crée pas ce montage lui-même.

Préférez SFTP, puis FTPS. Le FTP simple envoie votre mot de passe en clair. Lancez `rclone config` et créez un remote nommé `seedbox` : type `sftp`, ou type `ftp` avec TLS explicite pour FTPS. Saisissez l'hôte, l'utilisateur et le mot de passe fournis par l'hébergeur. Montez-le ensuite en lecture seule :

```bash
rclone mount seedbox:/home/user/downloads /mnt/seedbox --read-only --vfs-cache-mode full --vfs-cache-max-size 20G
```

Remplacez `/home/user/downloads` par le dossier où le client torrent télécharge, tel que la seedbox le voit. Sous Windows, rclone nécessite [WinFsp](https://winfsp.dev/) et monte sur une lettre de lecteur comme `S:`. Sous macOS, il nécessite macFUSE.

Dans les correspondances de chemins du client, reliez `/mnt/seedbox` sur cet ordinateur à `/home/user/downloads` côté client, ou utilisez **Détecter** (**Detect matching folders** dans l'interface web) une fois le montage actif. Utilisez les dossiers montés comme dossiers de bibliothèque et de téléchargement.

Limites à prévoir :

- La première analyse parcourt chaque dossier par le réseau et peut durer plusieurs minutes sur une grande bibliothèque.
- La préparation d'un upload lit chaque octet pour calculer les hashes, ce qui télécharge toute la release à travers le montage. Le centre multimédia ne lit que ce qu'il joue ; le cache ci-dessus garde jusqu'à 20 Go sur cet ordinateur.
- Un montage FTP ne peut pas indiquer l'espace libre de la seedbox : rclone affiche une taille inventée. Fixez le budget de ce client dans **Destinations du Plan** au lieu de zéro. SFTP indique l'espace libre si l'hébergeur le permet.
- Un montage en lecture seule ne peut pas être vérifié avec un fichier temporaire. La vérification utilise alors un fichier d'un torrent existant : gardez au moins un torrent dans le dossier relié.
- Si le montage s'arrête, son dossier devient vide ou indisponible, et une analyse n'y trouve alors rien. Vérifiez que le montage tourne avant d'analyser.


## Compatibilité des clients

Ce tableau décrit les fonctions accessibles dans TorrentLinker. L’accès aux fichiers et les correspondances de chemins restent nécessaires pour les opérations sur les données.

| Client | Gestion / téléchargements / Plans | Reseed complet | Reseed partiel | Vidéo séquentielle | Aperçu pendant le téléchargement |
| --- | --- | --- | --- | --- | --- |
| qBittorrent | Oui | Oui | Oui | Oui | Oui, vidéo unique et pièces vérifiées |
| Transmission | Oui | Selon disposition et réglage `.part` | Selon disposition | 4.1+ | Non |
| Deluge | Oui | Oui | Oui | Demandée dans les options | Non |
| rTorrent | Oui ; retrait sans suppression des fichiers | Dossier de liens requis | Non | Non | Non |
| µTorrent Classic | Expérimental ; dossier par défaut et sous-dossiers | Dossier de liens et réglages compatibles requis | Non | Non via cette API | Non |
| BitTorrent Classic | Même adaptateur expérimental que µTorrent | Dossier de liens et réglages compatibles requis | Non | Non via cette API | Non |

Le tableau de reseed exige une correspondance complète pour tous les clients ; la colonne partielle concerne les parcours proposant des correspondances partielles. Le dossier de liens doit rester hors des dossiers de bibliothèque et être conservé tant que les torrents l’utilisent. La lecture de fichiers complets dépend de l’accès aux fichiers et des codecs du lecteur, pas du client torrent. Voir aussi le [tableau détaillé en anglais](../en/clients.md#client-compatibility).
