#!/usr/bin/env python3
"""Build native, self-contained Synology DSM 7 SPKs; no Docker dependency."""
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

ARCHES = {"x86_64": (62, "x86_64"), "aarch64": (183, "armv8")}
NOOP = "#!/bin/sh\nexit 0\n"
POSTINST = """#!/bin/sh
set -eu
: "${SYNOPKG_PKGVAR:?missing package data directory}"
umask 077
mkdir -p "$SYNOPKG_PKGVAR/config" "$SYNOPKG_PKGVAR/home/cache" "$SYNOPKG_PKGVAR/tmp"
password="$SYNOPKG_PKGVAR/web-password"
if [ ! -e "$password" ]; then
    test -r /dev/urandom || exit 1
    tmp="$password.tmp.$$"
    trap 'rm -f "$tmp"' EXIT HUP INT TERM
    od -An -N32 -tx1 /dev/urandom | tr -d ' \\n' > "$tmp"
    test "$(wc -c < "$tmp" | tr -d ' ')" -eq 64
    chmod 600 "$tmp"
    mv "$tmp" "$password"
    trap - EXIT HUP INT TERM
fi
exit 0
"""
SERVICE = """#!/bin/sh
set -eu
: "${SYNOPKG_PKGDEST:?missing package destination}"
: "${SYNOPKG_PKGVAR:?missing package data directory}"
var="$SYNOPKG_PKGVAR"
python="$SYNOPKG_PKGDEST/runtime/bin/python3.12"
pidfile="$var/server.pid"
export HOME="$var/home" XDG_CACHE_HOME="$var/home/cache" TMPDIR="$var/tmp"
export PYTHONDONTWRITEBYTECODE=1
export LD_LIBRARY_PATH="$SYNOPKG_PKGDEST/runtime/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
running() {
  test -s "$pidfile" || return 1
  pid="$(cat "$pidfile")"
  case "$pid" in *[!0-9]*|'') return 1 ;; esac
  kill -0 "$pid" 2>/dev/null || return 1
  test -r "/proc/$pid/cmdline" || return 1
  tr '\\000' ' ' < "/proc/$pid/cmdline" | grep -Fq 'torrentlinker.web.server'
}
case "${1:-}" in
  prestart|prestop) exit 0 ;;
  status) running && exit 0; exit 3 ;;
  start)
    if running; then exit 0; fi
    mkdir -p "$var/config" "$var/home/cache" "$var/tmp"
    test -x "$python" && test -r "$var/web-password" || exit 1
    "$python" -m torrentlinker.web.server --host 0.0.0.0 --port 8787 \\
      --config "$var/config" --password-file "$var/web-password" \\
      >> "$var/server.log" 2>&1 &
    printf '%s\\n' "$!" > "$pidfile"
    sleep 2
    if running; then exit 0; fi
    rm -f "$pidfile"
    exit 1
    ;;
  stop)
    if ! running; then rm -f "$pidfile"; exit 0; fi
    pid="$(cat "$pidfile")"
    kill -TERM "$pid"
    i=0
    while [ "$i" -lt 30 ]; do
      if ! running; then rm -f "$pidfile"; exit 0; fi
      i=$((i + 1))
      sleep 1
    done
    echo 'TorrentLinker did not stop cleanly' >&2
    exit 1
    ;;
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



def validate_runtime(runtime: Path, arch: str) -> None:
    exe = runtime / "bin" / "python3.12"
    app = runtime / "lib" / "python3.12" / "site-packages" / "torrentlinker" / "web" / "server.py"
    if not exe.is_file() or not app.is_file() or not (exe.stat().st_mode & 0o111):
        raise ValueError("Runtime must bundle an executable Python 3.12 and TorrentLinker web")
    with exe.open("rb") as stream:
        h = stream.read(20)
    if h[:5] != b"\x7fELF\x02" or h[5] != 1 or int.from_bytes(h[18:20], "little") != ARCHES[arch][0]:
        raise ValueError(f"Bundled Python ELF architecture is not {arch}")
    base = runtime.resolve()
    for p in runtime.rglob("*"):
        if p.is_symlink() and not p.resolve().is_relative_to(base):
            raise ValueError(f"External symlink in runtime: {p}")


def build(version: str, arch: str, runtime: Path, output: Path) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+-\d+", version) or arch not in ARCHES:
        raise ValueError("Invalid DSM version or CPU architecture")
    validate_runtime(runtime, arch)
    info = "\n".join([
        'package="TorrentLinker"',
        f'version="{version}"',
        'displayname="TorrentLinker"',
        'description="Native TorrentLinker Web server for Synology DSM 7"',
        'maintainer="floppy69"',
        f'arch="{ARCHES[arch][1]}"',
        'os_min_ver="7.0-40000"',
        'adminprotocol="http"',
        'adminport="8787"',
        'adminurl="/"',
        'ctl_stop="yes"',
        'silent_upgrade="yes"',
        'thirdparty="yes"',
        "",
    ])
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz", format=tarfile.GNU_FORMAT) as archive:
        archive.add(runtime, arcname="runtime")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, mode="w", format=tarfile.GNU_FORMAT) as archive:
        text_file(archive, "INFO", info)
        text_file(archive, "package.tgz", payload.getvalue())
        text_file(archive, "conf/privilege", json.dumps({"defaults": {"run-as": "package"}}))
        text_file(archive, "conf/resource", "{}\n")
        for name in ("preinst", "preuninst", "postuninst", "preupgrade", "postupgrade"):
            text_file(archive, f"scripts/{name}", NOOP, mode=0o755)
        text_file(archive, "scripts/postinst", POSTINST, mode=0o755)
        text_file(archive, "scripts/start-stop-status", SERVICE, mode=0o755)
        text_file(archive, "PACKAGE_ICON.PNG", png(64))
        text_file(archive, "PACKAGE_ICON_256.PNG", png(256))
    with tarfile.open(output) as archive:
        assert {"INFO", "package.tgz", "conf/privilege", "scripts/start-stop-status"} <= set(archive.getnames())
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--arch", choices=ARCHES, required=True)
    parser.add_argument("--run-number", required=True, type=int)
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    source = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    match = re.match(r"^(\d+\.\d+\.\d+)", source)
    if not match or args.run_number < 1:
        parser.error("Unsupported upstream version or run number")
    version = f"{match.group(1)}-{args.run_number}"
    build(version, args.arch, args.runtime, args.output_dir / f"TorrentLinker-{version}-{args.arch}.spk")


if __name__ == "__main__":
    main()
