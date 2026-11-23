"""Shared torrent facts, sanitized descriptions and bounded inline images."""

from __future__ import annotations

import base64
import io
import re
import threading
import time
from collections import OrderedDict
from dataclasses import asdict
from urllib.parse import urlsplit

import httpx
from PIL import Image

from torrentlinker.indexer import Indexer
from torrentlinker.torrent_details import fetch_image, parse_details, preview_html


class DetailsWorkspace:
    def __init__(self, indexer: Indexer, *, clock=time.monotonic):
        self.indexer = indexer
        self.clock = clock
        self.lock = threading.RLock()
        self.documents: OrderedDict[str, dict] = OrderedDict()
        self.images: OrderedDict[tuple[str, int], str] = OrderedDict()
        self.host_retry: dict[str, float] = {}

    def load(self, infohash: str) -> dict:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", infohash):
            raise ValueError("Select a torrent with a valid hash.")
        infohash = infohash.lower()
        with self.lock:
            raw = self.indexer.torrent_json(infohash)
            detail = parse_details(raw)
            markup, images = preview_html(detail.description, detail.poster)
            facts = asdict(detail)
            for key in ("description", "nfo", "files", "has_nfo"):
                facts.pop(key, None)
            result = {
                "title": str(raw.get("name") or ""),
                "size": raw.get("size") if isinstance(raw.get("size"), int) else 0,
                "description": markup,
                "images": images,
                "nfo": detail.nfo,
                "files": detail.files,
                "info": facts,
            }
            self.documents[infohash] = result
            self.documents.move_to_end(infohash)
            self.images = OrderedDict((k, v) for k, v in self.images.items() if k[0] != infohash)
            while len(self.documents) > 24:
                removed, _ = self.documents.popitem(last=False)
                self.images = OrderedDict((k, v) for k, v in self.images.items() if k[0] != removed)
            return result

    def image(self, infohash: str, position: int) -> dict:
        infohash = infohash.lower()
        with self.lock:
            document = self.documents.get(infohash)
            if document is None:
                document = self.load(infohash)
            if not isinstance(position, int) or not 0 <= position < len(document["images"]):
                raise ValueError("Choose an image from this torrent's description.")
            key = (infohash, position)
            if key in self.images:
                self.images.move_to_end(key)
                return {"src": self.images[key]}
            url = document["images"][position]
            host = urlsplit(url).hostname
            remaining = self.host_retry.get(host or "", 0) - self.clock()
            if remaining > 0:
                return {"error": "Image host rate limit", "retry_after": remaining}
            try:
                data = fetch_image(url)
                with Image.open(io.BytesIO(data)) as image:
                    if image.width * image.height > 40_000_000:
                        raise ValueError("Image dimensions exceed preview limit")
                    image.thumbnail((1200, 1600))
                    output = io.BytesIO()
                    image.convert("RGBA").save(output, format="PNG")
                result = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
                self.images[key] = result
                while sum(len(value) for value in self.images.values()) > 16 * 1024 * 1024:
                    self.images.popitem(last=False)
                return {"src": result}
            except (httpx.HTTPError, ValueError, OSError, Image.DecompressionBombError) as error:
                delay = 0.0
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
                    try:
                        delay = max(60.0, float(error.response.headers.get("Retry-After", "60")))
                    except ValueError:
                        delay = 60.0
                    self.host_retry[host or ""] = self.clock() + delay
                return {"error": "Image unavailable", "retry_after": delay}
