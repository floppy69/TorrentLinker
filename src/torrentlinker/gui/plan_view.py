"""Desktop Plan adapter; the bundled page owns presentation and review controls."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import Signal, Slot

from torrentlinker.gui.community_view import BundledView, ViewBridge
from torrentlinker.gui.errors import error_text
from torrentlinker.plan import Plan, PlanOptions
from torrentlinker.plan_workspace import plan_data
from torrentlinker.send import SendProgress, SendReport
from torrentlinker.web.operations import JobRequest


class PlanBridge(ViewBridge):
    def __init__(self) -> None:
        super().__init__()
        self.view: PlanView | None = None

    @Slot()
    def ready(self) -> None:
        if self.view is not None:
            self.view.refresh(force=True)

    @Slot(str, str, result=str)
    def request(self, action: str, payload: str) -> str:
        try:
            body = json.loads(payload)
            if not isinstance(body, dict) or self.view is None:
                raise ValueError("Invalid Plan request.")
            return json.dumps({"data": self.view.request(action, body)})
        except (ValueError, TypeError, KeyError, OSError) as error:
            return json.dumps({"error": error_text(error)})


class PlanView(BundledView):
    make_requested = Signal()
    cached_requested = Signal()
    send_requested = Signal(object)
    queue_requested = Signal(object)
    categories_changed = Signal(object)
    stop_fetch_requested = Signal()
    stop_send_requested = Signal()
    speed_test_requested = Signal()
    options_changed = Signal(object)

    def __init__(self) -> None:
        self.plan: Plan | None = None
        self.plan_id = ""
        self.options = PlanOptions()
        self._busy = self._fetching = self._testing = False
        self.progress: SendProgress | None = None
        self.report: SendReport | None = None
        self.message = self.notice = ""
        self.speed: float | None = None
        self.speed_tested: str | None = None
        self.keys = 1
        self.client_names: dict[str, str] = {}
        self.category_options: list[tuple[int, str, bool]] = []
        self.chosen_categories: set[int] | None = None
        self.without_folder: set[int] = set()
        self.configuration: Callable[[], dict] = lambda: {"client_id": "default"}
        self.action: Callable[[str, dict], object] | None = None
        self.approval: tuple[str, str, tuple[str, ...], str] | None = None
        self.review_revision = 0
        self._result_key: tuple | None = None
        self._result_cache: dict = {}
        self._sent_key: tuple | None = None
        bridge = PlanBridge()
        super().__init__(bridge, Path(__file__).parents[1] / "web/static/plan", "plan")
        bridge.view = self

    def request(self, action: str, body: dict):
        client = self.configuration().get("client_id", "default")
        if body.pop("_client", client) != client:
            raise ValueError("The target client changed. Review the current Plan.")
        if action == "state":
            return self.state()
        if action == "stop-fetch":
            self.stop_fetch_requested.emit()
            return None
        if action == "stop-send":
            self.message = self.tr("Stopping after the current torrent…")
            self.stop_send_requested.emit()
            self.refresh()
            return None
        if self._busy:
            raise ValueError("Wait for the current Plan operation to finish.")
        if action in {"configure", "build"}:
            request = JobRequest(kind="plan", **body.get("options", {}))
            if self.action is not None and request.client_ids:
                self.action(
                    "destinations", request.model_dump(include={"client_ids", "client_budgets"})
                )
            options = request.planning_options()
            if options != self.options:
                self.options = options
                self.options_changed.emit(options)
            chosen = set(request.planning_categories() or ()) or None
            if chosen != self.chosen_categories:
                self.chosen_categories = chosen
                self.categories_changed.emit(chosen)
            if action == "build":
                (self.cached_requested if body.get("cached_only") else self.make_requested).emit()
        elif action == "speed-test":
            self.speed_test_requested.emit()
        elif action in {"review", "send", "queue"}:
            selected = self.selection(body)
            hashes = tuple(sorted(i.candidate.infohash for i in selected.items))
            if action == "review":
                token = secrets.token_urlsafe(32)
                self.approval = (token, self.plan_id, hashes, client)
                return {"token": token, "renames": []}
            if action == "send":
                if self.approval != (body.get("confirmation"), self.plan_id, hashes, client):
                    raise ValueError("Review this selection before sending.")
                self.approval = None
                self.send_requested.emit(selected)
            else:
                if self.action is None:
                    raise ValueError("Queue is unavailable.")
                return self.action("queue", {"plan": selected})
        elif self.action is not None and action in {
            "preferences",
            "destinations",
            "folders",
            "pick",
            "save-folder",
        }:
            result = self.action(action, body)
            self.refresh()
            return result
        else:
            raise ValueError("Unknown Plan operation.")
        self.refresh()
        return None

    def selection(self, body: dict) -> Plan:
        if self.plan is None or not self.plan_id or body.get("plan_id") != self.plan_id:
            raise ValueError("The Plan changed. Review the current Plan.")
        hashes = body.get("hashes")
        if (
            not isinstance(hashes, list)
            or not hashes
            or not all(isinstance(h, str) for h in hashes)
        ):
            raise ValueError("Select torrents from the current Plan.")
        known = {i.candidate.infohash for i in self.plan.items}
        if set(hashes) - known:
            raise ValueError("The selection contains torrents outside this Plan.")
        items = [i for i in self.plan.items if i.candidate.infohash in hashes]
        return replace(self.plan, items=items, zen_added=sum(i.zen for i in items))

    def state(self) -> dict:
        configuration = self.configuration()
        key = (self.plan_id, configuration.get("client_id", "default"), self.speed, self.keys)
        if key != self._result_key:
            self._result_cache = plan_data(
                self.plan or Plan(),
                client_id=key[1],
                download_speed=self.speed,
                indexer_keys=self.keys,
            )
            self._result_key = key
        result = self._result_cache
        return {
            **configuration,
            "result": {**result, "plan_id": self.plan_id, "notice": self.notice},
            "options": asdict(self.options),
            "categories": self.category_options,
            "chosen_categories": sorted(self.chosen_categories) if self.chosen_categories else None,
            "without_folder": sorted(self.without_folder),
            "client_names": self.client_names,
            "busy": self._busy,
            "fetching": self._fetching,
            "testing": self._testing,
            "progress": asdict(self.progress) if self.progress else None,
            "message": self.message,
            "report": asdict(self.report) if self.report else None,
            "review_revision": self.review_revision,
            "download_speed": self.speed,
            "download_speed_tested": self.speed_tested,
        }

    def refresh(self, *, force: bool = False) -> None:
        state = self.state()
        if not force and self._sent_key == self._result_key:
            state["result"] = {
                **{k: v for k, v in state["result"].items() if k not in {"rows", "on_disk"}},
                "rows_unchanged": True,
            }
        self._sent_key = self._result_key
        self.bridge.environment_value = json.dumps(
            {
                "mode": "desktop",
                "language": self.language,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
                "active": self.isVisible(),
                "state": state,
            }
        )
        self.bridge.environment.emit(self.bridge.environment_value)

    def set_options(self, value: PlanOptions) -> None:
        self.options = value
        self.refresh()

    def set_category_options(self, options, chosen, without_folder=None) -> None:
        self.category_options = options
        self.chosen_categories = chosen
        if without_folder is not None:
            self.without_folder = without_folder
        self.refresh()

    def set_notice(self, text: str) -> None:
        self.notice = text
        self.refresh()

    def invalidate(self) -> None:
        self.plan, self.plan_id, self.approval = None, "", None
        self._busy = False
        self.message = self.tr("Plan options changed. Make a new Plan to apply them.")
        self.refresh()

    def show_report(self, report: SendReport) -> None:
        self.report = report
        self.refresh()

    def begin(self) -> None:
        self.report = None
        self.plan, self.plan_id, self.approval = None, "", None
        self.notice = ""
        self.busy(True)

    def busy(self, busy: bool, text: str | None = None) -> None:
        self._busy = busy
        self.message = text or (self.tr("Making a Plan…") if busy else "")
        self.refresh()

    def fetching(self, fetching: bool) -> None:
        self._fetching = fetching
        self.refresh()

    def show_plan(self, plan: Plan) -> None:
        self.plan, self.plan_id, self.approval = plan, secrets.token_urlsafe(16), None
        self._busy = self._fetching = False
        self.message = self.notice = ""
        self.refresh()

    def failed(self, error: Exception) -> None:
        self.busy(False, self.tr("Could not make a Plan: {0}").format(error_text(error)))

    def set_speed(self, speed: float | None, tested: str | None) -> None:
        self.speed, self.speed_tested, self._testing = speed, tested, False
        self.refresh()

    def speed_testing(self) -> None:
        self._testing = True
        self.refresh()

    def sending(self, progress: SendProgress | None) -> None:
        if progress is not None and self.progress is None:
            self.report = None
        self.progress = progress
        self._busy = progress is not None
        self.refresh()

    def open_review(self) -> None:
        self.review_revision += 1
        self.refresh()
