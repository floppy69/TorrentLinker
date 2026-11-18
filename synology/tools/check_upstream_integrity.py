#!/usr/bin/env python3
"""Ensure Synology packaging never changes a tracked TorrentLinker upstream file."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_PREFIX = "synology/"
RELEASE_WORKFLOW = ".github/workflows/release.yml"
RELEASE_BEGIN = "# SYNOLOGY_RELEASE_BEGIN\n"
RELEASE_END = "# SYNOLOGY_RELEASE_END\n"


def is_additive_synology_release(repo: Path, base_ref: str) -> bool:
    """Allow ONLY an inserted Synology job block; original workflow stays byte-identical."""
    original = git(repo, "show", f"{base_ref}:{RELEASE_WORKFLOW}")
    current = git(repo, "show", f"HEAD:{RELEASE_WORKFLOW}")
    start, separator, tail = current.partition(RELEASE_BEGIN.encode())
    if not separator or current.count(RELEASE_BEGIN.encode()) != 1:
        return False
    addition, separator, end = tail.partition(RELEASE_END.encode())
    if not separator or tail.count(RELEASE_END.encode()) != 1:
        return False
    required = (b"  synology-build:\n", b"  synology-release:\n",
                b"needs: [synology-build]", b"softprops/action-gh-release@v2")
    return all(part in addition for part in required) and start + end == original
ALLOWED_FILES = frozenset({
    ".github/workflows/synology-integrity.yml",
    ".github/workflows/synology-dsm73-build.yml",
})
BASELINE_PATH = Path("synology/upstream.sha")


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def tracked_tree(repo: Path, ref: str) -> dict[str, tuple[bytes, bytes, bytes]]:
    """Map path to (mode, kind, Git blob ID); keep Git's raw bytes until parsing."""
    tree: dict[str, tuple[bytes, bytes, bytes]] = {}
    for record in git(repo, "ls-tree", "-r", "-z", "--full-tree", ref).split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        mode, kind, object_id = header.split(b" ", 2)
        tree[path.decode("utf-8", "surrogateescape")] = (mode, kind, object_id)
    return tree


def check(repo: Path, *, check_worktree: bool = False) -> list[str]:
    base_file = repo / BASELINE_PATH
    if not base_file.is_file():
        return [f"Missing {BASELINE_PATH}"]

    base_ref = base_file.read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[0-9a-f]{40}", base_ref) is None:
        return [f"Invalid SHA-1 commit ID in {BASELINE_PATH}"]

    git(repo, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    original = tracked_tree(repo, base_ref)
    current = tracked_tree(repo, "HEAD")
    errors: list[str] = []

    for path, identity in original.items():
        if current.get(path) != identity:
            if path == RELEASE_WORKFLOW and is_additive_synology_release(repo, base_ref):
                continue
            errors.append(f"Upstream file changed or removed: {path}")

    for path in current.keys() - original.keys():
        if not (path.startswith(ALLOWED_PREFIX) or path in ALLOWED_FILES):
            errors.append(f"New file outside Synology allowlist: {path}")

    if check_worktree:
        # CI must build outside the source tree, keeping it completely clean.
        if git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
            errors.append("Working tree contains modified or untracked files")

    return sorted(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--check-worktree", action="store_true")
    args = parser.parse_args()
    try:
        errors = check(args.repo.resolve(), check_worktree=args.check_worktree)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[FAIL] Integrity inspection failed: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    print("[OK] Upstream application files preserved; release.yml permits Synology-only additions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
