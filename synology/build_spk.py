#!/usr/bin/env python3
"""Build a DSM 7.2.1+ Container Manager SPK without the Synology SDK.

The .spk itself is architecture independent. The image specified by --image
must be published for linux/amd64 and linux/arm64 before distributing it.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import struct
import tarfile
import tomllib
import zlib
from pathlib import Path


PKG = "TorrentLinker"
NOOP = "#!/bin/sh\nexit 0\n"
POSTINST = """#!/bin/sh
set -eu

: "${SYNOPKG_PKGDEST:?missing package destination}"
: "${SYNOPKG_PKGVAR:?missing package data directory}"
umask 077

# DSM's dedicated package user owns the data. The image drops root to this
# UID/GID after its narrowly scoped initialization; never chmod data 777.
mkdir -p "$SYNOPKG_PKGVAR/config" "$SYNOPKG_PKGVAR/media"
config_file="$SYNOPKG_PKGVAR/config.env"

if [ ! -f "$config_file" ]; then
    [ -r /proc/sys/kernel/random/uuid ] || exit 1
    first="$(tr -d '-' < /proc/sys/kernel/random/uuid)"
    second="$(tr -d '-' < /proc/sys/kernel/random/uuid)"
    tmp="$config_file.tmp.$$"
    trap 'rm -f "$tmp"' EXIT HUP INT TERM
    {
        printf 'TL_WEB_PASSWORD=%s%s\\n' "$first" "$second"
        printf 'TL_UID=%s\\n' "$(id -u)"
        printf 'TL_GID=%s\\n' "$(id -g)"
        printf 'TL_MEDIA_PATH=%s/media\\n' "$SYNOPKG_PKGVAR"
    } > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$config_file"
    trap - EXIT HUP INT TERM
fi

# The Docker Project worker reads compose.yaml plus .env from package target.
# Keep the master copy in /var (preserved on upgrades), never in the SPK.
cp "$config_file" "$SYNOPKG_PKGDEST/project/.env"
chmod 600 "$SYNOPKG_PKGDEST/project/.env"
exit 0
"""
START_STOP = """#!/bin/sh
# Container Manager's docker-project resource controls start/stop.
case "${1:-}" in
  start|stop|status|prestart|prestop) exit 0 ;;
  *) exit 1 ;;
esac
"""


def text_file(tar: tarfile.TarFile, path: str, data: str | bytes, mode: int = 0o644) -> None:
    content = data.encode("utf-8") if isinstance(data, str) else data
    entry = tarfile.TarInfo(path)
    entry.size = len(content)
    entry.mode = mode
    entry.mtime = 0
    entry.uid = entry.gid = 0
    entry.uname = entry.gname = ""
    tar.addfile(entry, io.BytesIO(content))


def png(size: int) -> bytes:
    """Deterministic, square RGBA icon; no Pillow dependency."""
    def chunk(tag: bytes, value: bytes) -> bytes:
        return (struct.pack(">I", len(value)) + tag + value
                + struct.pack(">I", zlib.crc32(tag + value) & 0xffffffff))

    lines = []
    for y in range(size):
        line = bytearray(b"\x00")
        for x in range(size):
            background = (25, 40, 69, 255)
            # TL monogram in two tones; stays recognizable at 64 px.
            t = ((x >= size * 0.15 and x < size * 0.56 and
                  y >= size * 0.22 and y < size * 0.34)
                 or (x >= size * 0.30 and x < size * 0.41 and
                     y >= size * 0.22 and y < size * 0.77))
            ell = ((x >= size * 0.60 and x < size * 0.71 and
                    y >= size * 0.22 and y < size * 0.77)
                   or (x >= size * 0.60 and x < size * 0.85 and
                       y >= size * 0.65 and y < size * 0.77))
            line.extend((238, 245, 255, 255) if t else
                        (69, 216, 194, 255) if ell else background)
        lines.append(line)
    payload = zlib.compress(b"".join(lines), level=9)
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", payload) + chunk(b"IEND", b""))


def build(version: str, image: str, output: Path) -> None:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-[0-9]+", version):
        raise ValueError("DSM version must look like 1.0.0-123")
    if not re.fullmatch(r"ghcr\.io/floppy69/torrentlinker:sha-[a-f0-9]{12}", image):
        raise ValueError("Only immutable-style fork image tags are accepted")

    # Compose must use a corresponding multiarch image, not upstream's
    # mutable beta tag. A new SPK pins each tested source revision.
    compose = f"""services:
  torrentlinker:
    image: {image}
    container_name: torrentlinker-synology
    user: "0:0"
    cap_drop: [ALL]
    cap_add: [CHOWN, DAC_OVERRIDE, SETUID, SETGID]
    security_opt: [no-new-privileges:true]
    environment:
      TL_WEB_HOST: "0.0.0.0"
      TL_WEB_PORT: "8787"
      TL_WEB_PASSWORD: "${{TL_WEB_PASSWORD:?installation password missing}}"
      PUID: "${{TL_UID:?package uid missing}}"
      PGID: "${{TL_GID:?package gid missing}}"
    ports:
      - "8787:8787"
    volumes:
      - /var/packages/TorrentLinker/var/config:/config
      - "${{TL_MEDIA_PATH:?media path missing}}:/data:ro"
    restart: unless-stopped
"""

    info = "\n".join([
        'package="TorrentLinker"',
        f'version="{version}"',
        'displayname="TorrentLinker"',
        'description="TorrentLinker Web for Synology via Container Manager"',
        'maintainer="floppy69"',
        'thirdparty="yes"',
        'arch="noarch"',
        'os_min_ver="7.2.1-69057"',
        'install_dep_packages="ContainerManager>=1432"',
        'adminprotocol="http"',
        'adminport="8787"',
        'adminurl="/"',
        'ctl_stop="yes"',
        'silent_upgrade="yes"',
        "",
    ])
    privilege = json.dumps({"defaults": {"run-as": "package"}}, indent=2) + "\n"
    resource = json.dumps({
        "docker-project": {
            "projects": [{
                "name": "torrentlinker",
                "path": "project",
                "build_params": {
                    "force_pull": True,
                    "force_recreate": True,
                    "build": False,
                },
            }]
        }
    }, indent=2) + "\n"
    # Build inner package payload first, then outer SPK (uncompressed TAR).
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz", format=tarfile.GNU_FORMAT) as archive:
        text_file(archive, "project/compose.yaml", compose)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, mode="w", format=tarfile.GNU_FORMAT) as archive:
        text_file(archive, "INFO", info)
        text_file(archive, "package.tgz", payload.getvalue())
        text_file(archive, "conf/privilege", privilege)
        text_file(archive, "conf/resource", resource)
        for name in ("preinst", "preuninst", "postuninst", "preupgrade", "postupgrade"):
            text_file(archive, f"scripts/{name}", NOOP, mode=0o755)
        text_file(archive, "scripts/postinst", POSTINST, mode=0o755)
        text_file(archive, "scripts/start-stop-status", START_STOP, mode=0o755)
        text_file(archive, "PACKAGE_ICON.PNG", png(64))
        text_file(archive, "PACKAGE_ICON_256.PNG", png(256))

    # Fail the build rather than publish a malformed archive.
    with tarfile.open(output) as archive:
        expected = {"INFO", "package.tgz", "conf/privilege", "conf/resource",
                    "scripts/postinst", "scripts/start-stop-status",
                    "PACKAGE_ICON.PNG", "PACKAGE_ICON_256.PNG"}
        assert expected.issubset(archive.getnames())
        for path in ("conf/resource", "conf/privilege"):
            json.load(archive.extractfile(path))
        with tarfile.open(fileobj=archive.extractfile("package.tgz"), mode="r:gz") as inner:
            assert inner.getnames() == ["project/compose.yaml"]
            assert image in inner.extractfile("project/compose.yaml").read().decode()
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="GHCR image pinned to a fork SHA")
    parser.add_argument("--run-number", required=True, type=int, help="Monotonically increasing GitHub run number")
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    source = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    match = re.match(r"^(\d+\.\d+\.\d+)", source)
    if not match or args.run_number < 1:
        parser.error("Unsupported upstream version or run number")
    version = f"{match.group(1)}-{args.run_number}"
    build(version, args.image, args.output_dir / f"TorrentLinker-{version}-noarch.spk")


if __name__ == "__main__":
    main()
