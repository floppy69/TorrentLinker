# Web UI and Docker

The image is published at `ghcr.io/vietnoirien/torrentlinker` for amd64 and arm64. Pick a tag:

| Tag | Contents |
| --- | --- |
| `beta` | newest preview (recommended) |
| `latest` | newest stable release |
| `1.0.0-beta.16` | one fixed version, so upgrades happen only when you choose |

## Start without the source

Copy [deploy/compose.example.yaml](../../../deploy/compose.example.yaml) into an empty folder as `compose.yaml`. Put a `web-password.txt` next to it (12 characters or more, `chmod 600`), replace `/srv/media` with your downloads folder, then run:

```bash
docker compose pull
docker compose up -d
```

To upgrade, run both commands again. The `config` volume keeps your settings.

## Start from the source

From the repository root, create a private password file. Use at least 12 characters:

```bash
python3 - <<'PY'
import getpass, os
password = getpass.getpass('Web UI password: ')
if len(password) < 12:
    raise SystemExit('Use at least 12 characters.')
fd = os.open('deploy/web-password.txt', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write(password)
PY
docker compose up -d --build
```

Without `--build`, Compose uses the published image named by `TL_IMAGE_TAG` (`latest` by default; `TL_IMAGE_TAG=beta` for the preview).

Open `http://localhost:8787` and sign in. The default port binding is host-only. Set `TL_BIND_ADDRESS` to your host's LAN address for LAN access. For remote access, use an HTTPS reverse proxy and `TL_SECURE_COOKIE=1`. Do not expose the plain HTTP port directly to the Internet.

## Container user and permissions

The image still starts as UID/GID 1000 by default. Existing deployments with `cap_drop: [ALL]` need no change. `TL_UID` and `TL_GID` remain build-time options.

Runtime PUID/PGID support is available from **1.0.0-beta.21**. Select that version or the `beta` tag; the older `latest` stable image does not include it. To use a NAS account, enable initialization explicitly:

```bash
TL_IMAGE_TAG=1.0.0-beta.28 PUID=1001 PGID=100 docker compose \
  -f compose.yaml -f deploy/compose.identity.yaml up -d --pull always
```

The override starts the entrypoint as root and restores `CHOWN`, `DAC_OVERRIDE`, `SETUID` and `SETGID`, which the base Compose file drops. It repairs ownership only under `/config`, then starts the application as `PUID:PGID`, with no supplementary groups or effective capabilities. Both IDs must be positive integers. Without these variables, root initialization uses the image's build-time account IDs. Setting `PUID`/`PGID` alone does not activate initialization.

For a standalone Compose file, set `user: "0:0"`, add `PUID` and `PGID` to `environment`, and add `cap_add: [CHOWN, DAC_OVERRIDE, SETUID, SETGID]` alongside `cap_drop: [ALL]`. With `docker run`, use `--user 0:0 -e PUID=1001 -e PGID=100`; Docker's default capabilities suffice. Never use `--privileged` for this.

Alternatively, use `user: "1001:100"` with a configuration volume already writable by that account. This skips identity changes and ownership repair, ignores `PUID`/`PGID`, and preserves supplementary groups supplied through `group_add`. Use this mode for root-squashed NFS storage whose ownership must be prepared on the NAS.

Reserve `/config` for application state. Ownership repair never follows symlinks, changes hardlinked files, or touches nested mounts, including same-filesystem bind mounts. It leaves already-correct ownership unchanged and does not run chmod. Linux may clear setuid/setgid bits when ownership changes. Mount media outside `/config`, read-only where possible. Do not modify the configuration tree concurrently with initialization. `TL_CONFIG_DIR` or `--config` pointing elsewhere does not extend the ownership allowlist; prepare that location yourself.

The image uses `/config/home`, `/config/cache` and `/config/tmp` for `HOME`, `XDG_CACHE_HOME` and `TMPDIR`. It creates them as the application user. With a custom `TL_CONFIG_DIR` or `--config`, these directories follow the effective configuration path, without extending root ownership repair beyond `/config`. If an ownership change fails, initialization warns and still drops privileges. Startup can then fail if the configuration or runtime directories are not writable; it never falls back to running the application as root. Missing initialization capabilities or invalid IDs stop startup before repair.

Tini is included in the image to forward shutdown signals and reap orphaned children, including with `docker run` without `--init`. Existing Compose `init: true` remains compatible.

## Guided setup

![Connection wizard in English](../images/web/setup-en.png)

1. Choose qBittorrent, Deluge, Transmission or µTorrent. Test its address and credentials, then save. Deluge uses its Web UI password.
2. Review folders reported by the client. API-only seedbox users can continue without mounted files.
3. Add your c411 key, or do this later. Search needs `torznab:read`; the Zen profile needs `profile:read`.
4. Review available features and open Torrents. Each connection remains editable in Settings.

Testing does not replace saved settings. Blank password fields retain the saved value. Credentials supplied through secret files must be edited in those files. Advanced settings include a proxy for Internet services, optionally also used for the Torrent Client.

## Mounted NAS or seedbox storage

```bash
TL_MEDIA_PATH=/srv/media docker compose \
  -f compose.yaml -f deploy/compose.storage.yaml up -d --build
```

The host directory must already exist. TorrentLinker sees it as `/data`; your client may see the same files as `/downloads`. Use **Detect matching folders** for suggestions, or enter both paths and check the mapping. If an existing torrent file cannot confirm the mapping, TorrentLinker creates a random 16 KiB temporary file and asks the Torrent Client to hash-check a private, trackerless torrent while stopped. It then removes the test torrent without deleting client data and deletes its own temporary file. No manual sample or download is needed.

The example mount is read-only. Checking an empty folder with a temporary file requires write access from TorrentLinker; change the storage volume to read/write if you want this check. Existing torrent samples can still verify read-only mounts. The temporary-file check proves that the client can read the mapped content; it does not prove the client's write permissions. New downloads are written by the Torrent Client through its own filesystem. Explicit deletion of torrent files also happens in the Torrent Client, so TorrentLinker's read-only mount does not prevent it.

The folder browser lists server directories within configured storage roots. Web scans reject symbolic links in scanned trees; choose the real directory directly.

For a hosted seedbox, use the provider's HTTPS URL, including any URL prefix. Without a mount, management, Zen and Search remain available. Scan, comparison, Upload preparation, safe downloads and planning require access to the seedbox's actual files. Mount its storage on the host first, then use the same Compose override. TorrentLinker does not mount SSHFS/NFS/SMB shares automatically.

Remove an old folder from Settings before disconnecting its storage. Folder removal remains possible if the mount is already unavailable. Download and Plan jobs validate the destination using an existing sample or the temporary-file check. Successful probes are remembered for five minutes for the same client, paths and mounted directory identity; they are not saved across restarts. A failed check blocks the operation.

Entering a path does not provide access. Missing storage is never treated as empty, and container free space is never substituted for seedbox capacity.

## Client addresses

Containers on one Docker network can use service names, such as `http://qbittorrent:8080`. Docker Desktop provides `host.docker.internal` for host services. Native Linux Docker Engine may need `extra_hosts: ["host.docker.internal:host-gateway"]`. The service must listen on a reachable interface and its firewall must allow the connection. `localhost` always means the TorrentLinker container in this deployment.

## Catalogue and plans

Building a Plan refreshes recent catalogue entries first. Zen and note estimates remain provisional. Catalogue status reports known paging limits and snapshot provenance. If a refresh is slow or unavailable, stop it in Activity, then enable **Use cached catalogue without refreshing** and build again.

## Persistence and recovery

The `torrentlinker_config` volume holds configuration, catalogue, queue, job history and Verification records. Jobs survive browser disconnects. Activity shows progress and cancellation; an in-flight client command finishes before cancellation takes effect.

After an abrupt restart, unfinished jobs are marked interrupted and are not replayed. Check the Torrent Client before retrying. Persisted Reseed Verification is monitored again. A queue entry with an uncertain send remains visible and is not automatically sent a second time.

UI-entered credentials are encrypted in `credentials.enc`. Back up it and `credentials.key` together and protect the configuration volume. Someone who can read both files can decrypt the credentials. Desktop credentials still use the operating system keyring.

The Web UI password comes from `TL_WEB_PASSWORD_FILE` (recommended). Where files are impractical, such as a Portainer stack, set `TL_WEB_PASSWORD` instead. The file wins if both are set. Environment variables are visible through `docker inspect`, so prefer the file when you can.

In a Portainer stack, or anywhere you would rather not manage a file, replace the `TL_WEB_PASSWORD_FILE` line and the `web_password` secret with `TL_WEB_PASSWORD: ${WEB_PASSWORD}` and define `WEB_PASSWORD` in the stack's environment variables.

Secret-file overrides: `TL_INDEXER_API_KEY_FILE`, `TL_QBIT_PASSWORD_FILE`, `TL_QBIT_API_KEY_FILE`, `TL_DELUGE_PASSWORD_FILE`, `TL_TRANSMISSION_PASSWORD_FILE`, `TL_UTORRENT_PASSWORD_FILE`, `TL_ANNOUNCE_URL_FILE`, `TL_PROXY_PASSWORD_FILE`. Credentials never appear in setup API responses.

## Run without Docker

```bash
pip install '.[web]'
torrentlinker serve --config ./torrentlinker-data \
  --password-file ./deploy/web-password.txt --root /path/to/media
```

The server targets Linux and Linux NAS systems. Install the desktop from source with `pip install '.[desktop]'`. Only one server process may use a configuration directory. For a reverse proxy under `/torrentlinker`, set `TL_ROOT_PATH=/torrentlinker`, strip that prefix upstream, and open the URL with its trailing slash.

## Initial interface limits

Archive extraction and µTorrent disk-renaming confirmations remain in the desktop application. Web Uploads support category rules, hosted images, descriptions, NFO, options and Draft creation. The desktop retains the 3D renderer. Publish Drafts on c411 after review. A prepared Upload can be seeded during the same server session; after a restart, inspect the Draft and use the desktop workflow if needed.

Run API tests with `pytest tests/test_web_setup.py tests/test_web_jobs.py`. For the real browser flow, install `.[browser-test]`, run `playwright install chromium`, then `TL_WEB_BROWSER=1 pytest tests/test_web_browser.py`. Tests use fake clients and temporary media.

## Use the Web UI day to day

After setup, **Torrents** shows the connected client. Filter by tracker, category or state, then select the torrents to manage. Commands ask for confirmation when needed. **Activity** tracks progress and lets you cancel a running job.

![Torrent management in the browser](../images/web/torrents-en.png)

Open **Settings** to revisit setup. At the storage step, import client folders and map them to folders the server can access. Without a mount, skip this step to manage torrents remotely; features requiring file access remain unavailable.

![Storage setup in the browser](../images/web/storage-en.png)

**Documentation**, above **Settings**, opens these guides inside the Web UI. Choose a guide from the selector; the arrow returns to the previous guide. The sidebar language selector also changes the guides’ language. **GitHub** opens their online version.
