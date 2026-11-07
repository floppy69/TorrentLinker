#!/usr/bin/env python3
"""Audit the original Web UI's packaged links without modifying upstream files."""

from __future__ import annotations

import json
import re
import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class AssetReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"link", "script", "img"}:
            return
        for key, value in attrs:
            if key in {"src", "href"} and value:
                self.references.append(value)


def audit_web_assets(runtime: Path) -> dict[str, int]:
    """Fail if a bundled UI asset, guide, screenshot or extension file is absent."""
    site = runtime / "lib/python3.12/site-packages"
    package = site / "torrentlinker"
    static = package / "web/static"
    docs = runtime / "share/torrentlinker/docs"
    extension = package / "companion_extension"

    html = (static / "index.html").read_text(encoding="utf-8")
    refs = AssetReferences()
    refs.feed(html)
    checked_static = 0
    for reference in refs.references:
        if not reference.startswith("static/"):
            continue
        resource = (static / reference.removeprefix("static/")).resolve()
        if not resource.is_relative_to(static.resolve()) or not resource.is_file():
            raise ValueError(f"Web UI references a missing static resource: {reference}")
        checked_static += 1

    # A second HTML page is served by /companion/connect and has distinct URLs
    # backed by companion-connect.css/js in the original Web server.
    connect = AssetReferences()
    connect.feed((static / "companion-connect.html").read_text(encoding="utf-8"))
    for reference in connect.references:
        if reference not in {"connect.js", "connect.css"}:
            raise ValueError(f"Unknown companion connection asset: {reference}")
        if not (static / f"companion-{reference}").is_file():
            raise ValueError(f"Missing companion connection asset: {reference}")
        checked_static += 1

    guides = []
    for language in ("fr", "en"):
        guides.extend(sorted((docs / "guide" / language).glob("*.md")))
    if not (docs / "README.md").is_file() or len(guides) < 30:
        raise ValueError("The complete French and English Web documentation is missing")

    images = 0
    linked_pages = 0
    # Only check relative links: remote URLs and fragment-only anchors are not
    # package-owned. Documentation links to ADR/research files remain external
    # fallbacks in upstream's Web renderer, but the files must exist in the bundle.
    for guide in [docs / "README.md", *guides]:
        content = guide.read_text(encoding="utf-8")
        for match in re.finditer(r"(!?)\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)", content):
            is_image, target = match.groups()
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            path = (guide.parent / unquote(parsed.path)).resolve()
            if not path.is_relative_to(docs.resolve()):
                # A link to a repository-root document deliberately goes to
                # the upstream GitHub fallback and is not part of Web docs.
                continue
            if is_image:
                if not path.is_file():
                    raise ValueError(f"Missing guide image: {guide.relative_to(docs)} -> {target}")
                images += 1
            elif path.suffix.lower() == ".md":
                if not path.is_file():
                    raise ValueError(f"Missing guide link target: {guide.relative_to(docs)} -> {target}")
                linked_pages += 1

    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 3:
        raise ValueError("Browser companion is not a Manifest V3 extension")
    required = {
        "manifest.json", "receiver.json", "background.js", "collect.js",
        "descriptor.js", "companion.html", "companion.js", "style.css",
    }
    missing = required - {path.name for path in extension.iterdir() if path.is_file()}
    if missing:
        raise ValueError(f"Missing browser companion files: {sorted(missing)}")
    worker = manifest.get("background", {}).get("service_worker", "")
    if not (extension / worker).is_file():
        raise ValueError(f"Missing companion background worker: {worker}")
    for name in ("background.js", "companion.js"):
        content = (extension / name).read_text(encoding="utf-8")
        for imported in re.findall(r"\bfrom\s+[\"'](\./[^\"']+)[\"']", content):
            if not (extension / imported).is_file():
                raise ValueError(f"Missing companion JavaScript import: {name} -> {imported}")

    return {
        "static_links": checked_static,
        "guide_pages": len(guides),
        "guide_images": images,
        "local_markdown_links": linked_pages,
        "companion_files": len(required),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(audit_web_assets(arguments.runtime.resolve()), sort_keys=True))
