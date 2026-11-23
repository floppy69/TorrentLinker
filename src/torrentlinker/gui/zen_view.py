"""The Zen tab: the Seeding view and, later, the Plan."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QVBoxLayout,
    QWidget,
)

from torrentlinker.catalogue_workspace import CategoryCard as CategoryCard
from torrentlinker.gui.catalogue_view import CatalogueBox as CatalogueBox
from torrentlinker.gui.plan_view import PlanView as PlanView
from torrentlinker.gui.profile_view import ProfileView
from torrentlinker.gui.seeding_view import SeedingView as SeedingView
from torrentlinker.gui.shell_view import ShellView
from torrentlinker.profile import ProfileError, ProfileProblem, UserProfile
from torrentlinker.seeding import Seeding
from torrentlinker.send import SendProgress
from torrentlinker.zen import ZenClass, ZenProfile

CLASS_LABELS = {
    ZenClass.TANKER: QT_TRANSLATE_NOOP("ZenClass", "Tanker"),
    ZenClass.SWARM_KEEPER: QT_TRANSLATE_NOOP("ZenClass", "Swarm Keeper"),
    ZenClass.REUPLOADER: QT_TRANSLATE_NOOP("ZenClass", "Reuploader"),
}


def class_label(zen_class: ZenClass) -> str:
    return QCoreApplication.translate("ZenClass", str(CLASS_LABELS[zen_class]))


def zen_text(value: float) -> str:
    return f"≈ {value:.2f}"


class ZenTab(QWidget):
    """Everything about Zen: what the user's seeding earns, and what to seed next."""

    def __init__(
        self,
        load_seeding: Callable[[], Callable[[], Seeding]],
        profile: Callable[[], ZenProfile],
        uploads: int = 0,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.seeding_view = SeedingView(load_seeding, profile, uploads)
        self.catalogue = CatalogueBox()
        self.plan_view = PlanView()
        layout.setContentsMargins(0, 0, 0, 0)
        from torrentlinker.gui.workspace_tabs import WorkspaceTabs

        self.pages = WorkspaceTabs()
        self.profile_view = ProfileView()
        self.pages.addTab(self.profile_view, self.tr("Profile"))
        catalogue_page = self.catalogue_page = self.catalogue
        self.pages.addTab(self.seeding_view, self.tr("Seeding"))
        self.pages.addTab(self.plan_view, self.tr("Plan"))
        self.pages.addTab(catalogue_page, self.tr("Catalogue"))
        layout.addWidget(self.pages)


KEYS_URL = "https://c411.org/user/integrations"
WARNING = QColor("#c62828")


class ZenBand(ShellView):
    """In the window's footer, on the right: Zen Balance, what seeding earns, Plan and
    Catalogue. `message`, for profile problems, goes above the workspace instead."""

    refresh_requested = Signal()
    catalogue_changed = Signal(str)
    profile_notice_changed = Signal(str)

    def __init__(self, language="en") -> None:
        self.values: dict[str, str | bool | None] = {
            "balance": None,
            "seeding": None,
            "plan": None,
            "catalogue": None,
            "busy": False,
        }
        super().__init__("band", self._snapshot, self._command, language=language)
        self.setObjectName("zenBand")
        self.profile_notice = ""

    def _snapshot(self):
        return {"language": self.language, "band": self.values}

    def _command(self, action, values):
        if action == "refresh-profile":
            self.refresh_requested.emit()

    def set_balance(self, balance: float | None) -> None:
        self.values["balance"] = f"{balance:.1f}" if balance is not None else None
        self.refresh()

    def set_seeding(self, view: Seeding | None) -> None:
        self.values["seeding"] = zen_text(view.day.total) if view is not None else None
        self.refresh()

    def set_plan(self, added: float | None) -> None:
        self.values["plan"] = f"+{added:.2f}" if added is not None else None
        self.refresh()

    def set_sending(self, progress: SendProgress | None, added: float | None = None) -> None:
        self.set_plan(added)
        if progress is not None:
            self.values["plan"] = (
                str(self.values["plan"] or "–")
                + " · "
                + self.tr("Sending the Plan: <b>{0}/{1}</b>")
                .format(progress.done, progress.total)
                .replace("<b>", "")
                .replace("</b>", "")
                + (" " + self.tr("(c411 limit, waiting)") if progress.retry_at is not None else "")
            )
            self.refresh()

    def set_catalogue(self, text: str | None) -> None:
        self.values["catalogue"] = text
        self.catalogue_changed.emit(self.tr("Catalogue: {0}").format(text or "–"))
        self.refresh()

    def busy(self, busy: bool) -> None:
        self.values["busy"] = busy
        self.refresh()

    def show_profile(self, profile: UserProfile) -> None:
        self.busy(False)
        self.set_balance(profile.balance)
        notes = []
        if not profile.download_allowed:
            if profile.blocked_reason == "insufficient_balance":
                notes.append(self.tr("Downloads are blocked on c411: not enough Zen."))
            else:
                notes.append(
                    self.tr("Downloads are blocked on c411 ({0}).").format(
                        profile.blocked_reason or "?"
                    )
                )
        if profile.zen_class is None:
            notes.append(
                self.tr(
                    "c411 Class “{0}” is not known here: enter your Zen Profile in Settings → Zen."
                ).format(profile.class_slug or self.tr("none"))
            )
        self._message(" ".join(notes))

    def show_profile_error(self, error: Exception) -> None:
        self.busy(False)
        problem = error.problem if isinstance(error, ProfileError) else ProfileProblem.FAILED
        texts = {
            ProfileProblem.NO_KEY: self.tr(
                "Enter your c411 key in Settings → Connections to see your Zen Balance."
            ),
            ProfileProblem.UNAUTHORIZED: self.tr(
                "c411 refused the key: check it in Settings → Connections."
            ),
            ProfileProblem.MISSING_SCOPE: self.tr(
                'Your c411 key cannot read your profile: create one with the "Profil '
                '(lecture)" scope at <a href="{0}">{0}</a>. Until then, enter your Zen '
                "Profile in Settings → Zen."
            ).format(KEYS_URL),
            ProfileProblem.RATE_LIMITED: self.tr(
                "c411 is limiting requests: refresh your profile in a minute."
            ),
        }
        self._message(
            texts.get(problem) or self.tr("Could not read your c411 profile: {0}").format(error)
        )

    def _message(self, text: str) -> None:
        import re
        from html import unescape

        self.profile_notice = unescape(re.sub(r"<[^>]+>", "", text))
        self.profile_notice_changed.emit(self.profile_notice)
