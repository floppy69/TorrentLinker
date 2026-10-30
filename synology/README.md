# TorrentLinker pour Synology (DSM 7.2.1+)

Ce dossier construit un vrai paquet `.spk` installable dans le Centre de paquets.
Il exploite la ressource officielle **docker-project** de Synology, fournie par
**Container Manager >= 1432**. Il **ne** modifie **pas** le logiciel amont : le
conteneur contient l'interface web existante de TorrentLinker.

## Compatibilité et installation

- DSM **7.2.1 ou plus récent**, sur un NAS disposant de Container Manager.
- Image multiarchitecture `linux/amd64` et `linux/arm64`. Le fichier SPK
  est `noarch`, mais le NAS doit effectivement prendre en charge l'image.
- Sur le fork, ouvrir **Releases**, choisir la version `synology-…`, télécharger
  `TorrentLinker-…-noarch.spk`, puis **Centre de paquets > Installation manuelle**.
- Le paquet nécessite une connexion à GHCR et que l'image
  `ghcr.io/floppy69/torrentlinker` soit **publique**. Vérifier cette visibilité
  lors de la première publication dans les paramètres du package GHCR.
- Ouvrir `http://IP_DU_NAS:8787` sur un réseau de confiance. Pour un accès
  depuis Internet, mettre un reverse proxy HTTPS et adapter `TL_SECURE_COOKIE`
  dans Compose. **Ne pas exposer directement le port 8787 sur Internet.**

Le mot de passe de l'interface Web est créé aléatoirement lors de l'installation
(64 caractères hexadécimaux). Pour le consulter avec un compte administrateur
SSH sur le NAS :

```sh
sudo grep '^TL_WEB_PASSWORD=' /var/packages/TorrentLinker/var/config.env
```

Éviter de partager ou de committer ce fichier.

## Données et médias

Le paquet conserve les données hors du dossier d'installation :

- `/var/packages/TorrentLinker/var/config` : catalogue, paramètres et secrets ;
- `/var/packages/TorrentLinker/var/config.env` : mot de passe, identité du
  compte Synology, dossier média ;
- `/var/packages/TorrentLinker/var/media` : dossier média initial **vide**.

L'image lance une initialisation temporaire avec les capacités minimales
`CHOWN`, `DAC_OVERRIDE`, `SETUID`, `SETGID`, puis se rabaisse à l'UID/GID
dédiés au paquet. Les données ne sont pas rendues accessibles à tous par
`chmod 777`. Le répertoire `/config` est persistant lors d'une mise à jour
normale du SPK. **Sauvegardez-le avant une désinstallation**, car DSM peut
supprimer les données propres au paquet.

Par défaut, aucun dossier partagé du NAS n'est exposé. Pour accéder aux fichiers :

1. Éditer `TL_MEDIA_PATH` dans
   `/var/packages/TorrentLinker/var/config.env` (par exemple
   `/volume1/Films`). Préparer les droits de lecture de ce dossier pour
   l'utilisateur du paquet et privilégier le montage en lecture seule.
2. Appliquer la même valeur au fichier
   `/var/packages/TorrentLinker/target/project/.env` et **recréer** le
   conteneur dans Container Manager (Projet `torrentlinker`). Un simple
   redémarrage ne modifie pas un montage de volume existant.
3. Dans l'interface Web, associer `/data` au chemin utilisé par le client
   torrent (qBittorrent, Deluge ou Transmission).

Le fichier `config.env` dans `var` reste la source de vérité et sera recopié
au prochain upgrade. L'identité est conservée afin de pouvoir réutiliser le
dossier de configuration après les mises à jour.

## Mises à jour automatiques du fork et des artefacts

Le workflow `.github/workflows/synology.yml` s'exécute toutes les six heures,
lors des push sur `main` et manuellement dans **Actions**.

1. Pour une exécution planifiée/manuelle, récupérer
   `Vietnoirien/TorrentLinker:main` et réaliser un **merge normal** dans
   `floppy69/TorrentLinker:main`. Ne jamais forcer ni écraser les fichiers
   Synology. En cas de conflit, le workflow échoue et ne pousse rien.
2. Construire un candidat SPK ; vérifier son contenu et les scripts.
3. Construire et tester une image avec `/healthz`.
4. Pousser le merge sur le fork si le test réussit.
5. Si la redistribution est autorisée et que la publication est activée :
   produire une image GHCR multiarchitecture liée à la révision Git,
   puis publier un nouveau SPK dans **GitHub Releases**. Le SPK référence
   un tag d'image `sha-<12 caractères>`, jamais `beta` ou `latest`.

Le numéro de révision DSM suit le compteur monotone de GitHub Actions :
`<version du projet>-<run_number>` (par exemple `1.0.0-123`).
Un commit déjà publié avec un tag `synology-*` n'est pas republié.

**Droits de redistribution :** le dépôt d'origine ne fournit pas de fichier
`LICENSE` dans la version examinée. Le simple fait qu'un dépôt soit public
n'accorde pas automatiquement le droit de distribuer des images et des SPK.
La publication GHCR / Releases est donc désactivée par défaut. Après avoir
clarifié les droits avec le mainteneur, créer la variable GitHub Actions
`SYNOLOGY_PUBLISH=true` dans **Settings > Secrets and variables > Actions >
Variables**, puis déclencher **Actions > Synology SPK and upstream sync > Run
workflow**. Les compilations non publiées restent disponibles dans
les **Artifacts** de l'exécution GitHub Actions, soumis aux règles
d'accès et de rétention de GitHub.

**Attention :** une nouvelle release GitHub ne met **pas** automatiquement
à jour le logiciel déjà installé sur le NAS. Installer le nouveau SPK via
le Centre de paquets. Pour mettre à jour depuis le Centre de paquets
sans intervention, il faudra configurer un dépôt Synology de paquets
(`spkrepo`) ou un mécanisme d'administration DSM distinct.

## Développement et tests

```sh
python3 -m unittest discover -s synology -p 'test_*.py'
python3 synology/build_spk.py \
  --image ghcr.io/floppy69/torrentlinker:sha-012345abcdef \
  --run-number 1
```

Le générateur n'utilise que la bibliothèque standard de Python 3.11+.
L'archive est validée localement par le script et les tests ; la compatibilité
d'installation sur un **vrai NAS Synology** reste à confirmer avant de considérer
la release comme stable. Tester en particulier le worker `docker-project`,
les permissions du compte package et les sauvegardes/restaurations.
