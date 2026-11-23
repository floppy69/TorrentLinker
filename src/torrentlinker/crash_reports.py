"""Build a public issue draft from code locations, never from exception text or locals."""

from __future__ import annotations

import platform
import re
import traceback
from pathlib import Path
from urllib.parse import urlencode

import httpx

from torrentlinker.updates import installed_version

ROOT = Path(__file__).parent.resolve()
ISSUES = "https://github.com/Vietnoirien/TorrentLinker/issues/new"


def unexpected(error: BaseException) -> bool:
    # Input validation, cancellation and network/filesystem errors already have recovery UI.
    return not isinstance(
        error, (ValueError, OSError, httpx.HTTPError, KeyboardInterrupt, SystemExit)
    )


def _draft(frames: list[str], category: str) -> dict[str, str]:
    version = str(installed_version())
    if not re.fullmatch(r"[0-9A-Za-z.+-]{1,50}", version):
        version = "unknown"
    system = platform.system()
    if system not in {"Windows", "Darwin", "Linux"}:
        system = "Other"
    body = (
        "## What happened?\n\nDescribe the steps and expected result here.\n\n"
        f"## Environment\n\nTorrentLinker: {version}\nOS: {system}\nComponent: {category}\n\n"
        "## Sanitized stack\n\n```text\n"
        + "\n".join(frames[-20:] or ["No application frames available."])
        + "\n```\n\nException messages, source lines, local variables and external paths "
        "are omitted. Review this draft before submitting.\n"
    )
    title = f"Unexpected {category} error in {version}"
    return {
        "title": title,
        "body": body,
        "url": ISSUES + "?" + urlencode({"title": title, "body": body}),
    }


def exception_draft(error: BaseException) -> dict[str, str]:
    frames = []
    for frame in traceback.extract_tb(error.__traceback__):
        try:
            path = Path(frame.filename).resolve().relative_to(ROOT)
        except ValueError:
            continue
        # Only shipped source filenames; no user plugins, dynamic filenames or source text.
        if not (ROOT / path).is_file() or not re.fullmatch(
            r"[a-zA-Z0-9_/.-]+\.py", path.as_posix()
        ):
            continue
        label = path.as_posix()
        if "c411" in label.lower():
            label = "[private module]"
        frames.append(f"{label}:{frame.lineno}")
    return _draft(frames, "application")
