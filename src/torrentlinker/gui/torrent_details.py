"""Read-only RSS detail dialog using the same bundled detail page as Search."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtWidgets import QApplication, QDialog, QTextBrowser, QVBoxLayout

from torrentlinker.details_workspace import DetailsWorkspace
from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.torrent_details import website_url


class DescriptionBrowser(QTextBrowser):
    def loadResource(self, kind: int, url: QUrl | str) -> object:
        # Only explicitly fetched images enter the document through addResource.
        # QTextDocument must never read local paths or fetch arbitrary resources.
        return None


def decode_preview(data: bytes) -> QImage:
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 40_000_000:
        raise ValueError("Image dimensions exceed preview limit")
    if size.width() > 1200 or size.height() > 1600:
        reader.setScaledSize(size.scaled(QSize(1200, 1600), Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError("Could not decode image")
    return image


class DetailBridge(ViewBridge):
    response = Signal(int, str)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    @Slot(int, str, str)
    def requestAsync(self, identifier, action, payload):
        def run():
            try:
                body = json.loads(payload)
                if action == "detail":
                    value = self.owner.service.load(body["hash"])
                elif action == "detail-image":
                    value = self.owner.service.image(body["hash"], body["position"])
                elif action == "poster":
                    document = self.owner.service.documents[self.owner.row["hash"]]
                    value = self.owner.service.image(
                        self.owner.row["hash"], document["images"].index(body["url"])
                    )
                else:
                    raise ValueError("Unknown details operation.")
                result = {"data": value}
            except Exception:
                result = {
                    "error": "Could not load torrent details or image. Retry or open the website."
                }
            if not self.owner.closed:
                self.response.emit(identifier, json.dumps(result))

        self.owner.requests.submit(run)


class DetailBoard(BundledView):
    def __init__(self, owner):
        self.owner = owner
        language = QApplication.instance().property("language") or "auto"
        super().__init__(
            DetailBridge(owner), Path(__file__).parents[1] / "web/static/search", "search", language
        )

    def refresh(self):
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "client": "preview",
                "active": self.isVisible(),
                "page": "details",
                "readonly": True,
                "standalone": True,
                "row": self.owner.row,
                "indexer": self.owner.service.indexer.url,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
            }
        )
        self.bridge.ready()


class TorrentDetailsDialog(QDialog):
    def __init__(self, candidate, indexer, zen, assumptions, parent=None, *, torrent_note="—"):
        super().__init__(parent)
        self.closed = False
        self.service = DetailsWorkspace(indexer)
        self.requests = ThreadPoolExecutor(max_workers=2, thread_name_prefix="torrent-details")
        self.row = {
            "hash": candidate.infohash,
            "title": candidate.title,
            "size": candidate.size,
            "seeders": candidate.seeders,
            "website": website_url(candidate, indexer),
            "zen": zen if isinstance(zen, (int, float)) else None,
            "note": torrent_note if isinstance(torrent_note, (int, float)) else None,
        }
        self.setWindowTitle(self.tr("Torrent details"))
        self.resize(900, 740)
        self.board = DetailBoard(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.board)
        self.finished.connect(self.dispose)

    def dispose(self, *_):
        if self.closed:
            return
        self.closed = True
        self.requests.shutdown(wait=False, cancel_futures=True)
        self.board.close()
