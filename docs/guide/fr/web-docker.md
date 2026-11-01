# Interface web et Docker

L'image est publiée sur `ghcr.io/vietnoirien/torrentlinker` pour amd64 et arm64. Choisissez son tag :

| Tag | Contenu |
| --- | --- |
| `beta` | dernière préversion (recommandé) |
| `latest` | dernière version stable |
| `1.0.0-beta.16` | une version précise, pour ne pas changer de version sans le décider |

## Démarrage sans les sources

Copiez [deploy/compose.example.yaml](../../../deploy/compose.example.yaml) dans un dossier vide sous le nom `compose.yaml`. Placez à côté un fichier `web-password.txt` (12 caractères au moins, `chmod 600`), remplacez `/srv/media` par le dossier de vos téléchargements, puis lancez :

```bash
docker compose pull
docker compose up -d
```

Pour mettre à jour, relancez ces deux commandes. Le volume `config` conserve vos paramètres.

## Démarrage depuis les sources

Depuis la racine du dépôt, créez le fichier de mot de passe. Choisissez au moins 12 caractères. La commande suivante masque la saisie et crée un fichier privé :

```bash
python3 - <<'PY'
import getpass, os
password = getpass.getpass('Mot de passe de l’interface web : ')
if len(password) < 12:
    raise SystemExit('Il faut au moins 12 caractères.')
fd = os.open('deploy/web-password.txt', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write(password)
PY
docker compose up -d --build
```

Sans `--build`, Compose utilise l'image publiée indiquée par `TL_IMAGE_TAG` (`latest` par défaut ; `TL_IMAGE_TAG=beta` pour la préversion).

Ouvrez `http://localhost:8787` et saisissez ce mot de passe. Le serveur est accessible uniquement depuis la machine hôte par défaut. Pour un accès sur le réseau local, définissez `TL_BIND_ADDRESS` avec l'adresse LAN de l'hôte. Pour l'accès distant, utilisez un reverse proxy HTTPS et `TL_SECURE_COOKIE=1` ; n'exposez pas directement un port HTTP sur Internet.

## Utilisateur du conteneur et permissions

L'image démarre toujours avec l'UID/GID 1000 par défaut. Les déploiements existants avec `cap_drop: [ALL]` ne changent pas. `TL_UID` et `TL_GID` restent disponibles à la construction.

La prise en charge de PUID/PGID au démarrage est disponible à partir de **1.0.0-beta.21**. Choisissez cette version ou le tag `beta` ; l'ancienne image stable `latest` ne la contient pas. Pour utiliser un compte du NAS, activez explicitement l'initialisation :

```bash
TL_IMAGE_TAG=1.0.0-beta.28 PUID=1001 PGID=100 docker compose \
  -f compose.yaml -f deploy/compose.identity.yaml up -d --pull always
```

La surcharge démarre le point d'entrée en root et rétablit `CHOWN`, `DAC_OVERRIDE`, `SETUID` et `SETGID`, retirées par le fichier Compose de base. Elle corrige les propriétaires uniquement sous `/config`, puis lance l'application sous `PUID:PGID`, sans groupes supplémentaires ni capacités effectives. Les deux identifiants doivent être des entiers strictement positifs. Sans ces variables, l'initialisation utilise les identifiants du compte défini à la construction. Définir uniquement `PUID`/`PGID` n'active pas l'initialisation.

Dans un fichier Compose autonome, définissez `user: "0:0"`, ajoutez `PUID` et `PGID` dans `environment`, puis `cap_add: [CHOWN, DAC_OVERRIDE, SETUID, SETGID]` en conservant `cap_drop: [ALL]`. Avec `docker run`, utilisez `--user 0:0 -e PUID=1001 -e PGID=100` ; les capacités Docker par défaut suffisent. N'utilisez pas `--privileged` pour cela.

Autre possibilité : `user: "1001:100"` avec un volume de configuration déjà accessible en écriture. Ce mode ne change ni l'identité ni les propriétaires, ignore `PUID`/`PGID` et conserve les groupes supplémentaires fournis par `group_add`. Utilisez-le pour un stockage NFS avec root squash dont les droits doivent être préparés sur le NAS.

Réservez `/config` aux données de l'application. La correction ne suit pas les liens symboliques, ne modifie pas les fichiers avec plusieurs liens physiques et ne touche pas aux montages imbriqués, même sur le même système de fichiers. Elle conserve les propriétaires déjà corrects et ne lance pas chmod. Linux peut retirer les bits setuid/setgid lors d’un changement de propriétaire. Montez les médias hors de `/config`, en lecture seule si possible. Ne modifiez pas l'arborescence de configuration pendant l'initialisation. Un chemin différent fourni par `TL_CONFIG_DIR` ou `--config` n'étend pas la liste autorisée ; préparez ses droits vous-même.

L'image utilise `/config/home`, `/config/cache` et `/config/tmp` pour `HOME`, `XDG_CACHE_HOME` et `TMPDIR`. Elle crée ces dossiers sous l'utilisateur de l'application. Avec `TL_CONFIG_DIR` ou `--config`, ces dossiers suivent le chemin de configuration effectif, sans étendre la correction root au-delà de `/config`. Si une correction échoue, l'initialisation avertit puis abandonne les privilèges. Le démarrage peut ensuite échouer si la configuration ou ces dossiers ne sont pas accessibles en écriture ; l'application ne s'exécute jamais en root comme solution de repli. Des capacités manquantes ou des identifiants invalides arrêtent le démarrage avant toute correction.

Tini est inclus dans l'image pour transmettre les signaux d'arrêt et récupérer les processus orphelins, y compris avec `docker run` sans `--init`. Le réglage Compose existant `init: true` reste compatible.

## Assistant de configuration

![Assistant de connexion en français](../images/web/setup-fr.png)

1. Choisissez qBittorrent, Deluge, Transmission ou µTorrent. Indiquez son adresse, testez la connexion, puis enregistrez-la. Deluge utilise le mot de passe de son interface Web.
2. Les dossiers fournis par le client sont proposés. Vous pouvez continuer sans accès aux fichiers pour gérer une seedbox à distance.
3. Ajoutez votre clé c411 ou choisissez de la configurer plus tard. La recherche nécessite `torznab:read` ; le profil Zen nécessite `profile:read`.
4. L'écran final indique les fonctions configurées. Les paramètres restent accessibles à tout moment.

Le bouton de test ne remplace pas votre configuration enregistrée. Les mots de passe laissés vides conservent la valeur enregistrée. Les clés configurées par fichier secret se modifient dans ce fichier, pas dans l'interface. Le proxy est dans les paramètres avancés ; il peut s'appliquer aux services Internet seuls ou également au client torrent.

## NAS et dossiers partagés

Montez vos médias en plus du volume de configuration :

```bash
TL_MEDIA_PATH=/srv/media docker compose \
  -f compose.yaml -f deploy/compose.storage.yaml up -d --build
```

Le dossier doit déjà exister. TorrentLinker le voit sous `/data`. Si votre client voit les mêmes fichiers sous `/downloads`, l'assistant permet de relier `/data` à `/downloads`. Utilisez **Detect matching folders** pour obtenir des suggestions, ou sélectionnez les deux chemins et vérifiez la correspondance. Si aucun fichier existant ne la confirme, TorrentLinker crée un fichier temporaire aléatoire de 16 Kio. Le client vérifie ses hashes avec un torrent privé sans tracker, gardé à l'arrêt. Le torrent de test est ensuite retiré sans suppression des données du client, puis TorrentLinker supprime son propre fichier temporaire. Aucun fichier témoin à déposer ni téléchargement n'est nécessaire.

Cette vérification des dossiers vides nécessite un montage accessible en écriture à TorrentLinker. Le montage d'exemple étant en lecture seule, passez-le en lecture/écriture pour utiliser le test temporaire. Les fichiers déjà présents permettent toujours de vérifier un montage en lecture seule. Le test prouve que le client peut lire le contenu, pas qu'il dispose des droits d'écriture.

Le montage de l'exemple est en lecture seule : le client torrent, et non TorrentLinker, écrit les nouveaux téléchargements. Une demande explicite de suppression de fichiers agit également dans le client et n'est donc pas bloquée par le montage en lecture seule de TorrentLinker.

Les dossiers proposés par **Parcourir** appartiennent au serveur. Les chemins sortant des racines déclarées sont refusés. Les analyses web refusent les arbres contenant des liens symboliques ; choisissez directement le dossier réel.

## Seedbox hébergée

Utilisez l'adresse HTTPS et les identifiants fournis par l'hébergeur, en conservant le préfixe de chemin éventuel. **localhost** dans un conteneur désigne ce conteneur, pas votre navigateur ni le serveur de la seedbox.

Sans montage, vous pouvez gérer les torrents, suivre les estimations Zen et rechercher sur c411. Pour analyser, comparer, préparer un Upload, télécharger avec protection contre les écrasements ou planifier selon l'espace disponible, montez le stockage de la seedbox sur l'hôte, puis utilisez le même exemple Compose. TorrentLinker ne crée pas automatiquement de montage SSHFS/NFS/SMB.

Un chemin saisi ne rend pas les fichiers accessibles. Si le dossier n'est pas monté, TorrentLinker affiche ce qui manque et refuse l'opération concernée. Il ne prend pas l'espace libre du conteneur pour celui de la seedbox.

## Clients sur le même hôte

Deux services Docker sur un même réseau peuvent utiliser un nom de service, par exemple `http://qbittorrent:8080`. Pour un client exécuté sur l'hôte Docker Desktop, utilisez `host.docker.internal`. Avec Docker Engine sous Linux, une configuration `extra_hosts: ["host.docker.internal:host-gateway"]` peut être nécessaire. Le service doit écouter sur une interface accessible et le pare-feu doit autoriser la connexion.

## Données et tâches

Le volume `torrentlinker_config` conserve les paramètres, le catalogue, la file, l'historique des tâches et les vérifications. Fermer un onglet ne les arrête pas. **Activité** permet de suivre et d'arrêter les tâches ; l'arrêt intervient au prochain point d'interruption, pas au milieu d'une commande déjà envoyée.

Après un arrêt brutal du serveur, une tâche inachevée est marquée interrompue. Vérifiez son résultat dans le client torrent avant de la relancer. Les vérifications de Reseed enregistrées reprennent leur suivi. Un envoi incertain reste visible dans la file ; il n'est pas renvoyé automatiquement.

Les identifiants saisis dans l'interface sont chiffrés dans `credentials.enc`. La clé de chiffrement `credentials.key` est dans le même volume : protégez le volume et sauvegardez les deux fichiers ensemble. Le chiffrement ne protège pas contre quelqu'un qui peut lire tout le volume. L'application de bureau continue d'utiliser le trousseau système.

Le mot de passe de l’interface web provient de `TL_WEB_PASSWORD_FILE` (recommandé). Si les fichiers sont peu pratiques, par exemple avec une pile Portainer, définissez `TL_WEB_PASSWORD`. Le fichier l’emporte si les deux sont définis. Les variables d’environnement sont visibles via `docker inspect` : préférez le fichier quand c’est possible.

Dans une pile Portainer, ou si vous préférez éviter un fichier, remplacez la ligne `TL_WEB_PASSWORD_FILE` et le secret `web_password` par `TL_WEB_PASSWORD: ${WEB_PASSWORD}`, puis définissez `WEB_PASSWORD` dans les variables d’environnement de la pile.

Les fichiers secrets Docker sont pris en charge avec `TL_INDEXER_API_KEY_FILE`, `TL_QBIT_PASSWORD_FILE`, `TL_QBIT_API_KEY_FILE`, `TL_DELUGE_PASSWORD_FILE`, `TL_TRANSMISSION_PASSWORD_FILE`, `TL_UTORRENT_PASSWORD_FILE` , `TL_ANNOUNCE_URL_FILE` et `TL_PROXY_PASSWORD_FILE`. Leur contenu n'est pas renvoyé au navigateur.

## Sans Docker

```bash
pip install '.[web]'
torrentlinker serve --config ./torrentlinker-data \
  --password-file ./deploy/web-password.txt --root /chemin/des/medias
```

Le serveur vise Linux et les NAS Linux. Pour installer l'interface de bureau depuis les sources, utilisez `pip install '.[desktop]'`. Un seul processus serveur peut utiliser un dossier de configuration. Pour un reverse proxy sous `/torrentlinker`, définissez `TL_ROOT_PATH=/torrentlinker`, retirez ce préfixe en amont et ouvrez l'URL avec son slash final.

## Limites de cette première interface

L'extraction d'archives et les renommages sur disque nécessaires à certains reseeds µTorrent restent dans l'application de bureau. L'éditeur web prépare les descriptions, NFO, options de catégorie, images hébergées et brouillons ; la prévisualisation 3D reste dans l'application de bureau. La publication finale d'un brouillon se fait sur c411. Un Upload préparé peut être envoyé au client depuis la même session serveur ; après un redémarrage, vérifiez d'abord le brouillon et utilisez l'application de bureau si nécessaire.

## Corriger les dossiers et utiliser le cache

Les paramètres permettent de retirer un dossier, même si son montage est déjà déconnecté. Les téléchargements et le planificateur vérifient la destination avec un fichier existant ou un fichier temporaire. Un test réussi est mémorisé cinq minutes pour le même client, les mêmes chemins et la même identité du dossier monté, sans persister après redémarrage. Un échec bloque l'opération.

Créer un plan actualise les entrées récentes du catalogue. Les estimations Zen et les notes restent provisoires. Le statut indique les limites de pagination connues et la présence de données Zen Lab. Si l’actualisation est lente ou indisponible, arrêtez-la dans Activité, puis cochez **Utiliser le catalogue en cache sans actualiser** et recréez le plan.

## Utiliser l’interface web au quotidien

Une fois l’assistant terminé, **Torrents** affiche le client connecté. Filtrez la liste par tracker, catégorie ou état, puis sélectionnez les torrents à gérer. Les commandes demandent confirmation lorsque nécessaire. **Activité** suit leur progression et permet d’annuler une tâche encore en cours.

![Gestion des torrents dans le navigateur](../images/web/torrents-fr.png)

**Paramètres** permet de reprendre la configuration. À l’étape des dossiers, importez les chemins du client et associez-les aux dossiers accessibles au serveur. Si vous n’avez aucun montage, passez cette étape pour gérer les torrents à distance ; les fonctions nécessitant les fichiers restent indisponibles.

![Configuration du stockage dans le navigateur](../images/web/storage-fr.png)

**Documentation**, au-dessus des **Paramètres**, ouvre ces mêmes guides sans quitter l’interface. Choisissez un guide dans le sélecteur ; la flèche revient au guide précédent. Le sélecteur de langue de la barre latérale change aussi la langue des guides. Le lien **GitHub** ouvre leur version en ligne.
