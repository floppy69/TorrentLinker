# Develop and test

[Documentation](../../README.md) · [Français](../fr/developpement.md)

[Development](#development) · [Translations](#translations) · [Testing against real services](#testing-against-real-services)

## Development

Run the following commands from the repository root.

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/torrentlinker
.venv/bin/pytest
```

Requires Python 3.11 or newer. Run the local checks with:

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q
```

For a Linux source installation, register the launcher so Wayland can match the window to its name and dock icon. Run this from the checkout you launch, then fully quit and reopen the app:

```bash
desktop-file-install --dir="$HOME/.local/share/applications" \
  --set-key=Exec --set-value="\"$PWD/.venv/bin/torrentlinker\"" \
  --set-key=Icon --set-value="$PWD/src/torrentlinker/assets/icon.png" \
  packaging/torrentlinker.desktop
update-desktop-database "$HOME/.local/share/applications"
```

## Translations

UI strings are English in the code; French lives in `src/torrentlinker/i18n/`. After changing UI text:

```bash
.venv/bin/pyside6-lupdate $(find src/torrentlinker -name "*.py") -ts src/torrentlinker/i18n/torrentlinker_fr.ts -no-obsolete
.venv/bin/pyside6-linguist src/torrentlinker/i18n/torrentlinker_fr.ts
.venv/bin/pyside6-lrelease src/torrentlinker/i18n/torrentlinker_fr.ts -qm src/torrentlinker/i18n/torrentlinker_fr.qm
```

## Publishing a release

Releases ship the Catalogue encrypted inside the app (ADR-0019), so every release starts with a fresh export:

1. Refresh the Catalogue in your desktop app (**Zen → Catalogue**). Then export it and replace the private release's file. The app may stay open; the local copy is deleted after the upload:

   ```bash
   .venv/bin/python scripts/export_catalogue.py
   ```

2. If the release changes what users see or do, update the guides in `docs/guide/en` and `docs/guide/fr`, and the screenshots they show. Check the README and `CONTEXT.md` too.
3. Set the version in `pyproject.toml` and `TL_IMAGE_TAG` in `docs/guide/{en,fr}/web-docker.md`, and write `docs/releases/v<version>.md`.
4. Once CI is green, commit "Release <version>", tag `v<version>` and push the tag.

The release workflow downloads the export with the `CATALOGUE_TOKEN` secret, a fine-grained token with read-only access to the contents of `Vietnoirien/torrentlinker-catalogue`. A tagged build refuses an export older than two days: export again, then re-run the failed jobs. Without the secret, the release ships no Catalogue.

## Testing against real services

The multi-client suite starts two qBittorrent instances, Deluge and Transmission on an internal Docker network. It checks profile credentials, Path Mappings, Reseeds, Upload seeding, queue and Plan destinations, real file transfers through a local tracker, and Web API action isolation. It uses generated data and removes its containers and network afterwards.

On Linux, cache the images once, then run:

```bash
docker pull qbittorrentofficial/qbittorrent-nox:5.2.4-1
docker pull lscr.io/linuxserver/deluge:2.2.0
docker pull lscr.io/linuxserver/transmission:4.1.3
TL_MULTI_DOCKER=1 .venv/bin/pytest -s -q tests/test_multi_client_docker.py
```

The tests require Docker access. They do not use your configured clients or c411 API key. Each container has separate temporary storage and credentials. Web UI ports are not published. This suite does not cover µTorrent.

Reseed against a real qBittorrent, using a throwaway localhost-only instance (never your own client):

```bash
python scripts/qbit_sandbox.py /tmp/qbt-sandbox
qbittorrent-nox --profile=/tmp/qbt-sandbox &
TL_QBIT_SANDBOX=http://127.0.0.1:18080 .venv/bin/pytest tests/test_qbit_integration.py
```

Reseed against a real Deluge in a throwaway Docker container that sees a temporary folder at the same path:

```bash
data=$(mktemp -d)
docker run -d --rm --name tl-deluge -p 127.0.0.1:18112:8112 -e PUID=$(id -u) -e PGID=$(id -g) -v "$data:$data" lscr.io/linuxserver/deluge:2.2.0
python scripts/deluge_sandbox.py http://127.0.0.1:18112
TL_DELUGE_SANDBOX=http://127.0.0.1:18112 TL_DELUGE_DATA="$data" .venv/bin/pytest tests/test_deluge_integration.py
docker stop tl-deluge
```

`tests/test_deluge_docker_paths.py` does the same with Deluge seeing the folder as `/data`, to test Path Mappings; its docstring has the commands.

Transmission works the same way, with `scripts/transmission_sandbox.py`, `tests/test_transmission_integration.py` and `tests/test_transmission_docker_paths.py`: their docstrings have the commands.

Search c411 for a real file (enter the API key in Settings → Connections first):

```bash
TL_LIVE=1 .venv/bin/pytest tests/test_live.py -s
```

[Documentation](../../README.md) · [Français](../fr/developpement.md)
