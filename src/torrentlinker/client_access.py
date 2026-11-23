"""Serialize calls sharing a Torrent Client session, without locking whole jobs."""

from __future__ import annotations

import threading
from functools import wraps


class SerializedClient:
    def __init__(self, client):
        self.client = client
        self.lock = threading.RLock()

    def __getattr__(self, name):
        value = getattr(self.client, name)
        if not callable(value):
            return value

        @wraps(value)
        def call(*args, **kwargs):
            with self.lock:
                return value(*args, **kwargs)

        return call
