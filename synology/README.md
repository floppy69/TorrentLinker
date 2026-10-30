# TorrentLinker natif pour Synology DSM 7

**Aucun Docker / Container Manager / Python à installer sur le NAS.** Le
paquet SPK contient Python 3.12, TorrentLinker, ses bibliothèques et un
service contrôlé par le Centre de paquets. L'interface utilisée est le
**serveur Web** de TorrentLinker, et non son application de bureau Qt.

## Compatibilité

- DSM 7.0 ou supérieur, sous réserve de validation sur le modèle cible.
- Deux fichiers distincts :
  - `TorrentLinker-<version>-x86_64.spk` pour les NAS Intel / AMD 64 bits ;
  - `TorrentLinker-<version>-aarch64.spk` pour les NAS ARM 64 bits (famille
    `armv8` dans les métadonnées DSM).
- Les ARM 32 bits et les modèles non compatibles ne sont pas couverts.
- Les dépendances ELF sont contrôlées contre la glibc 2.26 de DSM 7.
  Cela ne remplace **pas** une vérification sur un vrai NAS.
- Aucun logiciel supplémentaire ne doit être installé sur le NAS pour
  démarrer le serveur Web. Certaines fonctions multimédias peuvent toutefois
  nécessiter des bibliothèques qui restent à embarquer et à tester :
  notamment la bibliothèque native MediaInfo ; le wrapper Python seul
  ne suffit pas. L'extraction d'archives propre à l'interface de bureau
  n'est pas exposée par l'interface Web.

## Installation

Une fois le build et les tests validés, récupérer le fichier adapté à
l'architecture dans les **Artifacts** de GitHub Actions ou dans **Releases**
si la publication est activée. Dans DSM :

1. **Centre de paquets > Installation manuelle** ; sélectionner le SPK.
2. Démarrer TorrentLinker depuis le Centre de paquets.
3. Ouvrir `http://IP_DU_NAS:8787` depuis le réseau local.
4. Récupérer le mot de passe généré lors de l'installation avec SSH :
   `sudo cat /var/packages/TorrentLinker/var/web-password`.

Ne pas exposer le port 8787 directement sur Internet. Utiliser un reverse
proxy HTTPS et activer les cookies sécurisés si vous rendez l'interface
accessible à distance.

## Fonctionnement et données

Le script DSM `scripts/start-stop-status` exécute directement
`runtime/bin/python3.12 -m torrentlinker.web.server` sous l'utilisateur
restreint du paquet. Il gère les fonctions **Démarrer**, **Arrêter**,
**État** et les arrêts propres.

Les données sont conservées dans :

- `/var/packages/TorrentLinker/var/config` : paramètres, catalogue et
  identifiants chiffrés ;
- `/var/packages/TorrentLinker/var/web-password` : mot de passe Web,
  généré avec 256 bits d'aléa et protégé en 0600 ;
- `/var/packages/TorrentLinker/var/server.log` : journaux du serveur.

La mise à jour d'un SPK conserve le dossier `var` ; le script
d'installation ne remplace jamais un mot de passe déjà présent.
Sauvegarder les données avant une désinstallation : DSM peut les supprimer.

Par sécurité, **aucun dossier média n'est accessible par défaut**.
Pour utiliser une bibliothèque existante, il faudra donner au compte du
paquet les droits adaptés sur le dossier partagé du NAS, puis ajouter
la racine autorisée au service (voir `--root` dans
`src/torrentlinker/web/server.py`). Cette configuration doit encore
être intégrée dans une interface d'installation pour éviter les
modifications manuelles.

## Automatisation du fork et du SPK

`.github/workflows/synology.yml` :

- Toutes les six heures, comparer `Vietnoirien/TorrentLinker:main`
  et `floppy69/TorrentLinker:main`.
- Fusionner sans force-push si des changements sont disponibles.
  Arrêter le workflow en cas de conflit ; ne jamais écraser les
  modifications Synology du fork.
- Construire sur des runners Linux **natifs** x86_64 et ARM64. Le pipeline
  copie une distribution Python portable dans chaque paquet, prépare les
  wheels compatibles avec DSM, vérifie les exigences glibc, teste les
  scripts et sauvegarde les SPK comme artifacts.
- Une variable Actions `SYNOLOGY_PUBLISH=true` autorisera ensuite les
  GitHub Releases publiques ; elle est **désactivée par défaut**
  tant que les droits de redistribution ne sont pas clarifiés.
  Le dépôt d'origine consulté ne contient pas de fichier `LICENSE`.

**Une nouvelle release n'installe pas automatiquement le paquet sur le NAS.**
Pour cela, il faudra ultérieurement ajouter un dépôt de paquets DSM
(`spkrepo`), puis activer les mises à jour du Centre de paquets.

## Générer le SPK manuellement

Sur un poste de compilation Linux possédant déjà un dossier `runtime`
autonome et compatible DSM, contenant Python 3.12 et
`lib/python3.12/site-packages/torrentlinker` :

```sh
python3 synology/check_binary.py --runtime runtime --arch x86_64
python3 -m unittest discover -s synology -p 'test_*.py'
python3 synology/build_spk.py --arch x86_64 --runtime runtime --run-number 1
```

La compilation ne nécessite pas Docker. Les packages générés sont des
**candidats** tant qu'une installation, un redémarrage et une mise à jour
réels sur le modèle Synology visé n'ont pas été testés.
