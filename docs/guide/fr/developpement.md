# Développer et tester

[Documentation](../../README.md) · [English](../en/development.md)

[Développement](#développement) · [Traductions](#traductions) · [Tests avec des services réels](#tests-avec-des-services-réels)

## Développement

Exécutez les commandes suivantes depuis la racine du dépôt.

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/torrentlinker
.venv/bin/pytest
```

Python 3.11 ou plus récent est nécessaire. Pour lancer les contrôles locaux :

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q
```

Pour une installation Linux depuis les sources, enregistrez le lanceur pour que Wayland associe la fenêtre au nom et à l’icône du dock. Exécutez ces commandes depuis le dépôt utilisé, puis quittez et relancez complètement l’application :

```bash
desktop-file-install --dir="$HOME/.local/share/applications" \
  --set-key=Exec --set-value="\"$PWD/.venv/bin/torrentlinker\"" \
  --set-key=Icon --set-value="$PWD/src/torrentlinker/assets/icon.png" \
  packaging/torrentlinker.desktop
update-desktop-database "$HOME/.local/share/applications"
```

## Traductions

Les textes de l’interface sont en anglais dans le code ; leur traduction française se trouve dans `src/torrentlinker/i18n/`. Après modification d’un texte :

```bash
.venv/bin/pyside6-lupdate $(find src/torrentlinker -name "*.py") -ts src/torrentlinker/i18n/torrentlinker_fr.ts -no-obsolete
.venv/bin/pyside6-linguist src/torrentlinker/i18n/torrentlinker_fr.ts
.venv/bin/pyside6-lrelease src/torrentlinker/i18n/torrentlinker_fr.ts -qm src/torrentlinker/i18n/torrentlinker_fr.qm
```

## Publier une version

Les versions publiées contiennent le Catalogue, chiffré dans l’application (ADR-0019). Chaque publication commence donc par un export à jour :

1. Actualisez le Catalogue dans l’application de bureau (**Zen → Catalogue**). Exportez-le ensuite et remplacez le fichier de la version privée. L’application peut rester ouverte ; la copie locale est supprimée après l’envoi :

   ```bash
   .venv/bin/python scripts/export_catalogue.py
   ```

2. Si la version change ce que les utilisateurs voient ou font, mettez à jour les guides de `docs/guide/en` et `docs/guide/fr`, ainsi que leurs captures d’écran. Vérifiez aussi le README et `CONTEXT.md`.
3. Indiquez la version dans `pyproject.toml` et dans `TL_IMAGE_TAG` de `docs/guide/{en,fr}/web-docker.md`, puis rédigez `docs/releases/v<version>.md`.
4. Quand la CI est verte, validez « Release <version> », créez le tag `v<version>` et poussez-le.

Le workflow de publication télécharge l’export avec le secret `CATALOGUE_TOKEN`, un jeton à portée fine en lecture seule sur le contenu de `Vietnoirien/torrentlinker-catalogue`. Une version taguée refuse un export de plus de deux jours : exportez de nouveau, puis relancez les tâches en échec. Sans le secret, la version ne contient aucun Catalogue.

## Tests avec des services réels

La suite multiclient démarre deux instances qBittorrent, Deluge et Transmission sur un réseau Docker interne. Elle vérifie les identifiants des profils, les correspondances de chemins, le reseed, la mise en seed des uploads, les destinations des files et des Plans, le transfert réel de fichiers via un tracker local et l'isolation des actions de l'API web. Elle utilise des données générées et supprime ses conteneurs et son réseau à la fin.

Sous Linux, téléchargez les images une première fois, puis lancez :

```bash
docker pull qbittorrentofficial/qbittorrent-nox:5.2.4-1
docker pull lscr.io/linuxserver/deluge:2.2.0
docker pull lscr.io/linuxserver/transmission:4.1.3
TL_MULTI_DOCKER=1 .venv/bin/pytest -s -q tests/test_multi_client_docker.py
```

Ces tests nécessitent l'accès à Docker. Ils n'utilisent ni vos clients configurés ni votre clé API c411. Chaque conteneur dispose d'un stockage temporaire et d'identifiants séparés. Les ports des interfaces web ne sont pas publiés. Cette suite ne couvre pas µTorrent.

Pour tester une remise en seed avec qBittorrent, utilisez une instance temporaire accessible uniquement en local, jamais votre client habituel :

```bash
python scripts/qbit_sandbox.py /tmp/qbt-sandbox
qbittorrent-nox --profile=/tmp/qbt-sandbox &
TL_QBIT_SANDBOX=http://127.0.0.1:18080 .venv/bin/pytest tests/test_qbit_integration.py
```

Pour Deluge, utilisez un conteneur Docker temporaire qui voit un dossier temporaire sous le même chemin :

```bash
data=$(mktemp -d)
docker run -d --rm --name tl-deluge -p 127.0.0.1:18112:8112 -e PUID=$(id -u) -e PGID=$(id -g) -v "$data:$data" lscr.io/linuxserver/deluge:2.2.0
python scripts/deluge_sandbox.py http://127.0.0.1:18112
TL_DELUGE_SANDBOX=http://127.0.0.1:18112 TL_DELUGE_DATA="$data" .venv/bin/pytest tests/test_deluge_integration.py
docker stop tl-deluge
```

`tests/test_deluge_docker_paths.py` teste aussi les correspondances de chemins, avec un dossier vu comme `/data` dans Deluge. Sa docstring contient les commandes.

Transmission suit le même principe avec `scripts/transmission_sandbox.py`, `tests/test_transmission_integration.py` et `tests/test_transmission_docker_paths.py`. Leurs docstrings donnent les commandes.

Pour rechercher un vrai fichier sur c411, renseignez d’abord votre clé API dans **Paramètres → Connexions** :

```bash
TL_LIVE=1 .venv/bin/pytest tests/test_live.py -s
```

[Documentation](../../README.md) · [English](../en/development.md)
