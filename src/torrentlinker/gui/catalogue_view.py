"""Desktop adapter for the shared Catalogue; fetch ownership stays in MainWindow."""

import json
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Signal, Slot

from torrentlinker.catalogue_workspace import CategoryCard
from torrentlinker.gui.community_view import BundledView, ViewBridge


class CatalogueBridge(ViewBridge):
    def __init__(self):
        super().__init__()
        self.view: CatalogueBox | None = None

    @Slot(str, str, result=str)
    def request(self, action: str, payload: str) -> str:
        try:
            body = json.loads(payload)
            view = self.view
            if view is None or not isinstance(body, dict):
                raise ValueError("Invalid Catalogue request.")
            if action == "fetch" and not view.running:
                root = body.get("root")
                if root is None:
                    view.start_requested.emit()
                elif type(root) is int and any(c.root == root and c.fetchable for c in view.cards):
                    view.category_requested.emit(root)
                else:
                    raise ValueError("Unknown category.")
            elif action == "pause" and view.running:
                view.pause_requested.emit()
            elif action == "plan-now" and view.running:
                view.plan_requested.emit()
            else:
                raise ValueError("Catalogue action is unavailable.")
            return json.dumps({"data": None})
        except (ValueError, TypeError) as error:
            return json.dumps({"error": str(error)})


class CatalogueBox(BundledView):
    start_requested = Signal()
    pause_requested = Signal()
    category_requested = Signal(int)
    plan_requested = Signal()

    def __init__(self) -> None:
        self.running = self.paused = False
        self.status_text = self.phase_text = ""
        self.fraction: float | None = None
        self.cards: list[CategoryCard] = []
        self.gain: dict = {}
        bridge = CatalogueBridge()
        super().__init__(bridge, Path(__file__).parents[1] / "web/static/catalogue", "catalogue")
        bridge.view = self

    def set_state(self, running: bool, paused: bool) -> None:
        self.running, self.paused = running, paused
        self.refresh()

    def set_status(self, text: str) -> None:
        self.status_text = text
        self.refresh()

    def set_phase(self, text: str, fraction: float | None = None) -> None:
        self.phase_text, self.fraction = text, fraction
        self.refresh()

    def set_cards(self, cards: list[CategoryCard]) -> None:
        self.cards = cards
        self.refresh()

    def show_gain(self, root: int, added: int) -> None:
        self.gain = {"root": root, "added": added, "sequence": self.gain.get("sequence", 0) + 1}
        self.refresh()

    def refresh(self) -> None:
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
                "active": self.isVisible(),
                "catalogue": {"cards": [asdict(c) for c in self.cards], "paused": self.paused},
                "running": self.running,
                "status": self.status_text,
                "phase": self.phase_text,
                "fraction": self.fraction,
                "gain": self.gain,
            }
        )
        self.bridge.ready()
