"""Public guides shared by the desktop, Web UI and packaged distributions."""

from __future__ import annotations

import posixpath
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ONLINE = "https://github.com/Vietnoirien/TorrentLinker/blob/main/docs/"
GUIDES = (
    ("demarrage", "getting-started", "Installer et configurer", "Setup and connections"),
    ("web-docker", "web-docker", "Interface web et Docker", "Web UI and Docker"),
    ("clients", "clients", "Plusieurs clients torrent", "Multiple Torrent Clients"),
    ("assistant", "assistant", "Assistant et automatisations", "Assistant and automations"),
    ("agents", "agents", "Agents et accès MCP", "Agents and MCP access"),
    ("torrents", "torrents", "Gérer les torrents", "Manage torrents"),
    ("bibliotheque", "library", "Bibliothèque et reseed", "Library and reseeding"),
    ("recherche", "search", "Recherche et téléchargements", "Search and downloads"),
    ("rss", "rss", "Abonnements RSS", "RSS subscriptions"),
    ("media", "media", "Médias", "Media"),
    ("zen", "zen", "Zen et Plans", "Zen and Plans"),
    ("community", "community", "Communauté", "Community"),
    ("companion", "companion", "Extension navigateur", "Browser companion"),
    ("upload", "upload", "Préparer un upload", "Prepare an Upload"),
    ("upload-categories", "upload-categories", "Règles des uploads", "Upload category rules"),
    ("donnees", "data", "Données et dépannage", "Data and troubleshooting"),
    ("developpement", "development", "Développement", "Development"),
)


def guides(language: str) -> list[dict[str, str]]:
    french = language == "fr"
    return [
        {
            "path": f"guide/{'fr' if french else 'en'}/{g[0 if french else 1]}.md",
            "title": g[2 if french else 3],
        }
        for g in GUIDES
    ]


def root() -> Path:
    candidates = [
        Path(getattr(sys, "_MEIPASS", Path(__file__).parents[2])) / "docs",
        Path(sys.prefix) / "share/torrentlinker/docs",
    ]
    for candidate in candidates:
        if (candidate / "guide/en/getting-started.md").is_file():
            return candidate.resolve()
    raise FileNotFoundError("The bundled documentation is missing. Reinstall TorrentLinker.")


def document_path(name: str) -> Path:
    """Only public guides and their images may be loaded as documentation."""
    base = root()
    path = (base / name).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Not a bundled guide.")
    relative = path.relative_to(base).as_posix()
    pages = {g["path"] for lang in ("fr", "en") for g in guides(lang)} | {"README.md"}
    if relative not in pages and not (
        relative.startswith("guide/images/") and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    ):
        raise ValueError("Not a bundled guide.")
    if not path.is_file():
        raise FileNotFoundError(relative)
    return path


def link_path(current: str, target: str) -> str:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        raise ValueError("External link.")
    if not parsed.path:
        return current
    return posixpath.normpath(posixpath.join(posixpath.dirname(current), unquote(parsed.path)))


def heading_anchor(title: str) -> str:
    """Stable guide anchor shared by rendered pages and agent section references."""
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
