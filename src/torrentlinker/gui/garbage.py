"""Keep Python's full garbage collections short, so video playback does not stutter.

The app keeps hundreds of thousands of long-lived objects: the Catalogue, the library and
their models. A full collection scanned them all, about 150 ms during which every Python
thread stood still, the thread that prepares video frames included. Freezing moves the
objects alive now out of the collector's reach, so later collections scan only newer
objects. Frozen objects are still freed when their last reference goes; only reference
cycles among them stay until the app exits.
"""

from __future__ import annotations

import gc

from PySide6.QtCore import QObject, QTimer

FREEZE_AFTER_MS = 30_000  # once startup has built the long-lived objects
FREEZE_EVERY_MS = 300_000  # for long-lived objects made since


def freeze() -> None:
    gc.collect()  # free garbage first; after the first freeze, this scans only newer objects
    gc.freeze()


def keep_collections_short(parent: QObject) -> None:
    QTimer.singleShot(FREEZE_AFTER_MS, parent, freeze)
    timer = QTimer(parent)
    timer.setInterval(FREEZE_EVERY_MS)
    timer.timeout.connect(freeze)
    timer.start()
