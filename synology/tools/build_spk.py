#!/usr/bin/env python3
"""Assemble a DSM 7.3/7.4 x86_64 SPK from a verified offline runtime.

This command never builds Python or downloads dependencies. A dedicated later
stage must supply a DSM-compatible runtime and all Python/native dependencies.
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import struct
import tarfile
import tempfile
from pathlib import Path

PACKAGE = "TorrentLinkerSynology"
PACKAGE_VERSION = "1.0.0-0003"
TARGET = "dsm73-x86_64"
TARGET_INFO = {
    "dsm73-x86_64": "INFO.in",
    "dsm74-x86_64": "INFO.dsm74.in",
}
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "package"
REQUIRED_FILES = (
    "runtime/bin/python3.12",
    "native/bin/7zz",
    "runtime/lib/python3.12/site-packages/torrentlinker/web/server.py",
    "runtime/lib/python3.12/site-packages/torrentlinker/web/static/index.html",
    "runtime/lib/python3.12/site-packages/torrentlinker/companion_extension/manifest.json",
    "runtime/lib/python3.12/site-packages/torrentlinker/companion_extension/background.js",
    "runtime/share/torrentlinker/docs/guide/en/getting-started.md",
    "runtime/share/torrentlinker/docs/guide/fr/demarrage.md",
)
LIFECYCLE_SCRIPTS = (
    "preinst", "postinst", "preuninst", "postuninst", "preupgrade",
    "postupgrade", "start-stop-status",
)


def validate_png(path: Path, size: int) -> None:
    data = path.read_bytes()
    if (
        len(data) < 24
        or data[:8] != b"\x89PNG\r\n\x1a\n"
        or data[12:16] != b"IHDR"
        or struct.unpack(">II", data[16:24]) != (size, size)
    ):
        raise ValueError(f"Icon must be a valid {size}x{size} PNG header: {path}")


def safe_payload(payload: Path) -> None:
    if not payload.is_dir():
        raise ValueError(f"Missing runtime payload: {payload}")
    for relative in REQUIRED_FILES:
        if not (payload / relative).is_file():
            raise ValueError(f"Required runtime file missing: {relative}")
    if not os.access(payload / REQUIRED_FILES[0], os.X_OK):
        raise ValueError("Packaged Python must be executable")
    if not os.access(payload / "native/bin/7zz", os.X_OK):
        raise ValueError("Bundled 7-Zip must be executable")
    python_header = (payload / REQUIRED_FILES[0]).read_bytes()[:20]
    if (
        len(python_header) < 20
        or python_header[:6] != b"\x7fELF\x02\x01"
        or struct.unpack_from("<H", python_header, 18)[0] != 62
    ):
        raise ValueError("Packaged Python must be a 64-bit little-endian x86_64 ELF")
    root = payload.resolve()
    for file in payload.rglob("*"):
        if file.is_symlink():
            if not file.resolve().is_relative_to(root):
                raise ValueError(f"Symlink escapes payload: {file}")
        elif not (file.is_file() or file.is_dir()):
            raise ValueError(f"Unsupported special file in runtime: {file}")


def normalized_info(info: tarfile.TarInfo, *, executable: bool | None = None) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    if info.isdir():
        info.mode = 0o755
    elif executable is not None:
        info.mode = 0o755 if executable else 0o644
    return info


def add_bytes(tar: tarfile.TarFile, path: str, data: bytes, *, executable: bool = False) -> None:
    info = tarfile.TarInfo(path)
    info.size = len(data)
    normalized_info(info, executable=executable)
    tar.addfile(info, io.BytesIO(data))


def package_payload(payload: Path, destination: Path) -> None:
    # Stable gzip header and stable tar metadata make the packaged runtime reproducible.
    with destination.open("wb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, mtime=0
    ) as zipped, tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(payload.rglob("*"), key=lambda p: p.relative_to(payload).as_posix()):
            relative = path.relative_to(payload).as_posix()
            info = normalized_info(tar.gettarinfo(str(path), arcname=relative))
            if info.isfile():
                with path.open("rb") as content:
                    tar.addfile(info, content)
            else:
                tar.addfile(info)


def build(
    payload: Path, icon64: Path, icon256: Path, output_dir: Path, *, target: str = TARGET
) -> Path:
    if target not in TARGET_INFO:
        raise ValueError(f"Unsupported DSM build target: {target}")
    source_root = TEMPLATE_ROOT.parent.parent.resolve()
    if payload.resolve().is_relative_to(source_root):
        raise ValueError("Runtime payload must be staged outside the upstream checkout")
    if output_dir.resolve().is_relative_to(source_root):
        raise ValueError("SPK output must be outside the upstream checkout")
    safe_payload(payload)
    validate_png(icon64, 64)
    validate_png(icon256, 256)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{PACKAGE}-{PACKAGE_VERSION}-{target}.spk"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing SPK: {output}")
    with tempfile.TemporaryDirectory(prefix="synology-package-", dir=output_dir) as tmp:
        payload_archive = Path(tmp) / "package.tgz"
        temporary_spk = Path(tmp) / "package.spk"
        package_payload(payload, payload_archive)
        with tarfile.open(temporary_spk, "w", format=tarfile.PAX_FORMAT) as tar:
            add_bytes(tar, "INFO", (TEMPLATE_ROOT / TARGET_INFO[target]).read_bytes())
            add_bytes(tar, "conf/privilege", (TEMPLATE_ROOT / "conf/privilege").read_bytes())
            add_bytes(tar, "conf/resource", (TEMPLATE_ROOT / "conf/resource").read_bytes())
            for script_name in LIFECYCLE_SCRIPTS:
                target = f"scripts/{script_name}"
                add_bytes(
                    tar, target, (TEMPLATE_ROOT / target).read_bytes(), executable=True,
                )
            add_bytes(tar, "PACKAGE_ICON.PNG", icon64.read_bytes())
            add_bytes(tar, "PACKAGE_ICON_256.PNG", icon256.read_bytes())
            info = normalized_info(tar.gettarinfo(str(payload_archive), arcname="package.tgz"))
            with payload_archive.open("rb") as source:
                tar.addfile(info, source)
        os.replace(temporary_spk, output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--icon64", type=Path, required=True)
    parser.add_argument("--icon256", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", choices=tuple(TARGET_INFO), default=TARGET)
    args = parser.parse_args()
    output = build(
        args.payload.resolve(), args.icon64.resolve(),
        args.icon256.resolve(), args.output_dir.resolve(), target=args.target,
    )
    print(f"SPK archive assembled (runtime compatibility NOT yet certified): {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
