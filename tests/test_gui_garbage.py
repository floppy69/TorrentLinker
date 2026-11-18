"""Long-lived objects are frozen, so full garbage collections stay short during playback."""

import gc

from PySide6.QtWidgets import QWidget

from torrentlinker.gui import garbage


def test_objects_alive_after_startup_are_frozen_then_again_periodically(qtbot, monkeypatch):
    monkeypatch.setattr(garbage, "FREEZE_AFTER_MS", 10)
    monkeypatch.setattr(garbage, "FREEZE_EVERY_MS", 50)
    window = QWidget()
    qtbot.addWidget(window)
    try:
        gc.unfreeze()
        garbage.keep_collections_short(window)
        qtbot.waitUntil(lambda: gc.get_freeze_count() > 0, timeout=2000)
        kept = [object() for _ in range(1000)]
        frozen = gc.get_freeze_count()
        qtbot.waitUntil(lambda: gc.get_freeze_count() > frozen, timeout=2000)
        assert kept
    finally:
        gc.unfreeze()
