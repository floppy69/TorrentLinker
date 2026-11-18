#!/usr/bin/env python3
"""Convert a TorrentLinker tag into a monotonically ordered DSM SPK version.

Accepted: vMAJOR.MINOR.PATCH[-alpha.N|-beta.N|-rc.N].
The 4-digit DSM build order is alpha 1xxx < beta 3xxx < rc 6xxx < stable 9000.
"""
from __future__ import annotations
import argparse
import re

TAG_RE = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?$")
STAGE = {"alpha": 1000, "beta": 3000, "rc": 6000}


def from_tag(tag: str) -> str:
    match = TAG_RE.fullmatch(tag)
    if not match:
        raise ValueError(f"Unsupported TorrentLinker release tag: {tag!r}")
    major, minor, patch, phase, sequence = match.groups()
    if phase is None:
        revision = 9000
    else:
        number = int(sequence)
        if number > 999:
            raise ValueError("Pre-release sequence exceeds the DSM revision band (999)")
        revision = STAGE[phase] + number
    return f"{major}.{minor}.{patch}-{revision:04d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Git release tag, e.g. v1.0.0-beta.43")
    args = parser.parse_args()
    print(from_tag(args.tag))


if __name__ == "__main__":
    main()
