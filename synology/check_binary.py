#!/usr/bin/env python3
"""Fail the CI build for an incompatible ELF architecture or glibc requirement."""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ARCHES = {"x86_64": 62, "aarch64": 183}
MAX_GLIBC = (2, 26)  # Synology DSM 7.0/7.1 toolchain baseline


def check(root: Path, arch: str) -> int:
    checked = 0
    errors = []
    for file in root.rglob("*"):
        if not file.is_file() or file.is_symlink():
            continue
        with file.open("rb") as handle:
            h = handle.read(20)
        if h[:4] != b"\x7fELF":
            continue
        checked += 1
        if h[4:6] != b"\x02\x01" or int.from_bytes(h[18:20], "little") != ARCHES[arch]:
            errors.append(f"Wrong ELF CPU: {file}")
            continue
        result = subprocess.run(["readelf", "-W", "--version-info", str(file)],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            errors.append(f"Cannot inspect {file}: {result.stderr.strip()}")
            continue
        for major, minor in re.findall(r"Name:\s+GLIBC_(\d+)\.(\d+)", result.stdout):
            if (int(major), int(minor)) > MAX_GLIBC:
                errors.append(f"{file} requires GLIBC_{major}.{minor} (DSM baseline is 2.26)")
    if checked == 0:
        errors.append("No ELF binaries in the bundled runtime")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Checked {checked} native ELF files against DSM glibc <= 2.26 ({arch})")
    return checked


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--arch", choices=ARCHES, required=True)
    args = parser.parse_args()
    check(args.runtime, args.arch)
