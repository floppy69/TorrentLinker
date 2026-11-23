"""Errors as the user reads them."""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox, QWidget

from torrentlinker.gui.tasks import run_in_background
from torrentlinker.indexer import KeyRefused, RateLimited, SessionRefused
from torrentlinker.library import LibraryReadTimeout
from torrentlinker.login_guard import LoginRefused
from torrentlinker.qbit import AlreadyInClient
from torrentlinker.transmission import PartialNamesOn


def error_text(error: Exception) -> str:
    if isinstance(error, LoginRefused):
        app = QCoreApplication.instance()
        return error.text(str(app.property("language") or "auto") if app else "auto")
    if isinstance(error, AlreadyInClient):
        message = QCoreApplication.translate(
            "Errors", "This torrent is already in the Torrent Client."
        )
        if (torrent := error.torrent) is not None:
            status = (
                QCoreApplication.translate("Errors", "It is already seeding.")
                if torrent.is_seeding
                else QCoreApplication.translate(
                    "Errors", "Check its state and save path in your torrent client."
                )
            )
            details = QCoreApplication.translate(
                "Errors", "Name: {0}\nHash: {1}\nState: {2}\nSave path: {3}"
            ).format(torrent.name, torrent.hash, torrent.state, torrent.save_path)
            message += " " + status + "\n\n" + details
        return message
    if isinstance(error, LibraryReadTimeout):
        if error.operation == "folder":
            return QCoreApplication.translate(
                "Errors",
                "Reading the Library Folder timed out: {0}\n\n"
                "Check that the drive or network share is available, then scan again. "
                "The previous Library list has been kept.",
            ).format(error.target)
        if error.operation == "files":
            message = QCoreApplication.translate(
                "Errors",
                "The Torrent Client timed out while reading the files of “{0}” after two attempts.",
            ).format(error.target)
        else:
            message = QCoreApplication.translate(
                "Errors",
                "The Torrent Client timed out while reading its torrent list after two attempts.",
            )
        return (
            message
            + "\n\n"
            + QCoreApplication.translate(
                "Errors",
                "Check the Torrent Client connection in Settings and try again "
                "when it is responsive. "
                "The previous Library list has been kept to avoid marking seeded files as Orphans.",
            )
        )
    if isinstance(error, SessionRefused):
        return QCoreApplication.translate(
            "Errors",
            "The c411 session download stopped: {0} Check Settings → Companion. "
            "It never falls back to your API key.",
        ).format(str(error))
    if isinstance(error, KeyRefused) and error.scope == "drafts:rw":
        return QCoreApplication.translate(
            "Errors",
            "c411 refused your API key for Drafts (HTTP {0}). Your main key needs the "
            "“Brouillons d'upload” (drafts:rw) scope: create one at "
            "https://c411.org/user/integrations and enter it in Settings → Connections.",
        ).format(error.status)
    if isinstance(error, KeyRefused) and error.key_number > 1:
        return QCoreApplication.translate(
            "Errors",
            "c411 refused API key {1} (HTTP {0}). Check it in Settings → Connections, under "
            "More API keys: it needs the torznab:read scope.",
        ).format(error.status, error.key_number)
    if isinstance(error, KeyRefused):
        return QCoreApplication.translate(
            "Errors",
            "c411 refused your API key (HTTP {0}). Check it in Settings → Connections: "
            "create one at https://c411.org/user/integrations with the torznab:read scope "
            "(add profile:read to see your Zen Balance).",
        ).format(error.status)
    if isinstance(error, RateLimited):
        return QCoreApplication.translate(
            "Errors",
            "c411 is asking to wait before more requests: try again at {0}. A Plan being "
            "sent waits on its own.",
        ).format(time.strftime("%H:%M", time.localtime(time.time() + error.retry_after)))
    return str(error) or type(error).__name__


def offer_whole_names(parent: QWidget, error: Exception, then: Callable[[], object]) -> bool:
    """When Transmission would rename files to .part, offer to turn that off, then run
    `then`. Whether `error` was that refusal (ADR-0010)."""
    if not isinstance(error, PartialNamesOn):
        return False
    answer = QMessageBox.question(
        parent,
        "Transmission",
        QCoreApplication.translate(
            "Errors",
            "Transmission appends .part to the names of incomplete files: during a Reseed "
            "that would rename your own files.\n\nTurn off “Append .part to incomplete "
            "files' names” in Transmission? It applies to all its torrents. Your files are "
            "left as they are either way.",
        ),
    )
    if answer == QMessageBox.StandardButton.Yes:
        run_in_background(
            error.turn_off,
            lambda _: then(),
            lambda e: QMessageBox.warning(parent, "Transmission", error_text(e)),
        )
    return True
