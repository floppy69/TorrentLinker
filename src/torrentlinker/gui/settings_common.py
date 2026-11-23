"""Shared desktop folder picking, content labels and credential names."""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication
from PySide6.QtWidgets import QFileDialog, QWidget

from torrentlinker.credentials import TMDB_API_KEY as TMDB_API_KEY
from torrentlinker.credentials import get_secret
from torrentlinker.domain import ContentKind

log = logging.getLogger(__name__)

QBIT_PASSWORD = "qbit-password"
QBIT_API_KEY = "qbit-api-key"
DELUGE_PASSWORD = "deluge-password"
TRANSMISSION_PASSWORD = "transmission-password"
UTORRENT_PASSWORD = "utorrent-password"
RTORRENT_PASSWORD = "rtorrent-password"
INDEXER_API_KEY = "indexer-api-key"
# Up to 4 more keys of the same c411 account, each within its own limits (ADR-0008).
EXTRA_INDEXER_KEYS = tuple(f"indexer-api-key-{n}" for n in range(2, 6))
ANNOUNCE_URL = "announce-url"  # holds the passkey: a secret like the keys (ADR-0011)
PROXY_PASSWORD = "proxy-password"


KIND_LABELS = {
    ContentKind.MOVIE: QT_TRANSLATE_NOOP("ContentKind", "Movies"),
    ContentKind.SERIES: QT_TRANSLATE_NOOP("ContentKind", "Series"),
    ContentKind.MUSIC: QT_TRANSLATE_NOOP("ContentKind", "Music"),
    ContentKind.EBOOK: QT_TRANSLATE_NOOP("ContentKind", "Ebooks"),
    ContentKind.GAME: QT_TRANSLATE_NOOP("ContentKind", "Games"),
    ContentKind.MODEL_3D: QT_TRANSLATE_NOOP("ContentKind", "3D models"),
    ContentKind.ADULT: QT_TRANSLATE_NOOP("ContentKind", "XXX"),
    ContentKind.OTHER: QT_TRANSLATE_NOOP("ContentKind", "Other"),
}


def kind_label(kind: ContentKind) -> str:
    return QCoreApplication.translate("ContentKind", str(KIND_LABELS[kind]))


def offered_kinds(adult: bool, current: ContentKind | None = None) -> list[ContentKind]:
    """Content Kinds to choose from: XXX only once adult content is enabled, or for a
    folder that already has it."""
    return [k for k in ContentKind if k is not ContentKind.ADULT or adult or k is current]


def extra_indexer_keys() -> list[str]:
    """The Indexer keys saved after the main one, in order, without empty ones."""
    return [k for name in EXTRA_INDEXER_KEYS if (k := get_secret(name))]


def choose_directory(parent: QWidget, title: str, start: str = "") -> str:
    """A folder the user picks, or "" if they cancel."""
    options = QFileDialog.Option.ShowDirsOnly
    if sys.platform.startswith("linux"):
        # The desktop-portal picker can hand back an empty path under Wayland.
        options |= QFileDialog.Option.DontUseNativeDialog
    path = QFileDialog.getExistingDirectory(parent, title, start or str(Path.home()), options)
    log.info("folder picked: %r", path)
    return path
