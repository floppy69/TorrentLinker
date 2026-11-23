"""The approved Community workspace, shared with the Web UI.

Qt renders only bundled assets. The channel exposes the owner Community service;
no browser session, arbitrary URL, filesystem or general API is exposed to JS.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QGuiApplication, QHideEvent, QShowEvent
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from torrentlinker import i18n
from torrentlinker.community import message_library
from torrentlinker.profile_workspace import ProfileWorkspace

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PySide6.QtWebEngineWidgets import QWebEngineView

ASSETS = Path(__file__).parents[1] / "web" / "static" / "community"


class ViewBridge(QObject):
    environment = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.environment_value = "{}"

    @Slot()
    def ready(self) -> None:
        self.environment.emit(self.environment_value)


class CommunityBridge(ViewBridge):
    def __init__(self, workspace: ProfileWorkspace, parent: QObject | None):
        super().__init__(parent)
        self.workspace = workspace

    @Slot(str, str, result=str)
    def request(self, path: str, payload: str) -> str:
        try:
            body = json.loads(payload)
            if path == "community":
                result = self.workspace.community_state()
            elif path == "community/messages":
                result = {"entries": message_library()}
            elif path == "community/export" and isinstance(body, dict):
                text = body.get("text")
                if not isinstance(text, str) or len(text) > 10_000_000:
                    raise ValueError("Invalid history export.")
                filename, _ = QFileDialog.getSaveFileName(
                    None,
                    self.tr("Export community history"),
                    "torrentlinker-community-history.json",
                    "JSON (*.json)",
                )
                if filename:
                    Path(filename).write_text(text, encoding="utf-8")
                result = {"saved": bool(filename)}
            elif path in {
                "community/settings",
                "community/refresh",
                "community/save",
                "community/control",
            } and isinstance(body, dict):
                result = self.workspace.community_update(path.split("/")[1], body)
            else:
                raise ValueError("Unknown community operation.")
            return json.dumps({"data": result}, ensure_ascii=False)
        except (ValueError, TypeError, KeyError, OSError) as error:
            return json.dumps({"error": str(error)})


class BundledView(QWidget):
    def __init__(self, bridge: ViewBridge, assets: Path, channel_name: str, language: str = "en"):
        super().__init__()
        self.setProperty("ownsScrolling", True)
        self.assets = assets.resolve()
        self.channel_name = channel_name
        self.language = language
        self.bridge = bridge
        bridge.setParent(self)
        self.web: QWebEngineView | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        # The lazy web view composites through Qt Quick. Adding the first one to a
        # shown raster window makes Qt destroy and recreate that native window,
        # which Wayland and X11 show as the app reopening. This hidden Qt Quick
        # widget makes the top level composite that way from its first show.
        from PySide6.QtQuickWidgets import QQuickWidget

        QQuickWidget(self).hide()

    @property
    def language(self) -> str:
        return i18n.pick_language(self._language)

    @language.setter
    def language(self, value: str) -> None:
        self._language = value

    def _load_view(self) -> None:
        # Load Chromium only when the Community tab is opened.
        # Wayland's GBM/Vulkan texture import can leave a live page entirely black.
        # This HTML workspace needs no GPU. Keep Qt's media/3D rendering unchanged.
        if QGuiApplication.platformName().startswith("wayland"):
            flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
            if "--disable-gpu" not in flags.split():
                os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{flags} --disable-gpu".strip()
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import (
            QWebEnginePage,
            QWebEngineSettings,
            QWebEngineUrlRequestInfo,
            QWebEngineUrlRequestInterceptor,
        )
        from PySide6.QtWebEngineWidgets import QWebEngineView

        assets = self.assets
        self_view = self

        class LocalAssets(QWebEngineUrlRequestInterceptor):
            def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
                url = info.requestUrl()
                allowed = (
                    url.toString() == "qrc:///qtwebchannel/qwebchannel.js"
                    or self_view.channel_name
                    in {"profile", "search", "assistant", "media", "documentation", "nowplaying"}
                    and re.match(r"^data:image/(png|jpeg|gif|webp);base64,", url.toString())
                    is not None
                    or url.isLocalFile()
                    and Path(url.toLocalFile()).resolve()
                    in {
                        assets / name
                        for name in (
                            "view.html",
                            "view.css",
                            "view.js",
                            "transfers.js",
                            "audit.js",
                            "tracker-updates.js",
                            "transport.js",
                            "inspector.js",
                            "recovery.js",
                            "preparation.js",
                            "rules.js",
                            "results.js",
                            "release-score.js",
                            "indexers.js",
                            "indexers.css",
                            "secrets.js",
                            "secrets.css",
                            "cross-seed.js",
                            "cross-seed.css",
                            "details.js",
                            "details.css",
                            "queue.js",
                            "browser.js",
                            "common.js",
                            "assistant.js",
                            "companion.js",
                            "agents.js",
                            "file-access.js",
                            "members.js",
                            "account.js",
                            "notifications.js",
                            "community-site.js",
                            "achievements.js",
                            "prerolls.js",
                            "prerolls.css",
                            "studio.js",
                            "ratings.js",
                            "requests.js",
                            "watch.js",
                        )
                    }
                    | {
                        assets.parent / "panel" / name
                        for name in (
                            "base.css",
                            "toast.js",
                            "toast.css",
                            "community-items.js",
                            "community-items.css",
                            "transport.js",
                            "i18n.js",
                            "media-flags.js",
                            "torrent-list.css",
                            "torrent-filters.js",
                            "file-access.js",
                            "file-access.css",
                        )
                    }
                    or self_view.channel_name == "shell"
                    and url.isLocalFile()
                    and Path(url.toLocalFile()).resolve() == assets.parent / "favicon.svg"
                    or self_view.channel_name == "media"
                    and url.isLocalFile()
                    and Path(url.toLocalFile()).resolve() == assets.parent / "media.css"
                )
                if not allowed:
                    # A blocked page or script leaves the view blank: say which one.
                    log.warning("%s view blocked %s", self_view.channel_name, url.toString()[:200])
                info.block(not allowed)

        channel_name = self.channel_name
        host_view = self

        class LocalPage(QWebEnginePage):
            def javaScriptConsoleMessage(self, level, message, line, source):
                if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                    name = source.rsplit("/", 2)[-2:]
                    log.warning("%s view: %s (%s:%s)", channel_name, message, "/".join(name), line)

            def createWindow(self, window_type):
                if channel_name != "upload":
                    return None
                from PySide6.QtWidgets import QDialog, QVBoxLayout

                dialog = QDialog(host_view)
                dialog.setWindowTitle("Postimages")
                dialog.resize(740, 720)
                view = QWebEngineView(dialog)
                # No WebChannel, file access or application bridge in remote content.
                page = QWebEnginePage(view)
                view.setPage(page)
                page.settings().setAttribute(
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False
                )
                layout = QVBoxLayout(dialog)
                layout.addWidget(view)
                page.windowCloseRequested.connect(dialog.close)
                dialog.finished.connect(lambda _: view.setUrl(QUrl("about:blank")))
                dialog.show()
                return page

            def acceptNavigationRequest(
                self,
                url: QUrl | str,
                navigation_type: QWebEnginePage.NavigationType,
                is_main_frame: bool,
            ) -> bool:
                target = QUrl(url)
                if (
                    channel_name == "search"
                    and navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
                    and target.scheme() in {"http", "https"}
                    and target.host()
                    and not target.userInfo()
                ):
                    QDesktopServices.openUrl(target)
                    return False
                if (
                    navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
                    and target.scheme() == "https"
                    and target.host() == "c411.org"
                    and re.fullmatch(r"/torrents/[a-fA-F0-9]{40}", target.path())
                    and not target.hasQuery()
                    and not target.hasFragment()
                ):
                    QDesktopServices.openUrl(target)
                    return False
                return (
                    target.isLocalFile()
                    and Path(target.toLocalFile()).resolve() == assets / "view.html"
                )

        self.web = QWebEngineView(self)
        page = LocalPage(self.web)
        self.interceptor = LocalAssets(page)
        page.setUrlRequestInterceptor(self.interceptor)
        self.web.setPage(page)
        settings = page.settings()
        for attribute in (
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
            QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,
            QWebEngineSettings.WebAttribute.LocalStorageEnabled,
        ):
            settings.setAttribute(attribute, False)
        if self.channel_name == "upload":
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
        self.channel = QWebChannel(page)
        self.channel.registerObject(self.channel_name, self.bridge)
        page.setWebChannel(self.channel)
        self.web.loadFinished.connect(self.refresh)
        self.web.loadFinished.connect(self._load_failed)
        page.renderProcessTerminated.connect(
            lambda status, code: log.warning(
                "%s view lost its render process: %s (%s)", self.channel_name, status, code
            )
        )
        self._layout.addWidget(self.web)
        self.web.setUrl(QUrl.fromLocalFile(str(assets / "view.html")))

    def refresh(self) -> None:
        self.bridge.environment_value = json.dumps(
            {
                "language": self.language,
                "theme": "dark" if self.palette().window().color().lightness() < 128 else "light",
                "active": self.isVisible(),
            }
        )
        self.bridge.ready()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self.web is None:
            self._load_view()
        self.refresh()

    def _load_failed(self, ok: bool) -> None:
        if not ok:
            log.warning("%s view failed to load", self.channel_name)

    def closeEvent(self, event: QCloseEvent) -> None:
        # pytest and shutdown can stop the event loop before deferred widget
        # destruction. Release the page before Qt destroys its shared profile.
        if self.web is not None:
            web = self.web
            self.web = None
            web.deleteLater()
            QCoreApplication.sendPostedEvents(web, QEvent.Type.DeferredDelete)
        super().closeEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self.refresh()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "bridge"):
            self.refresh()


class CommunityView(BundledView):
    def __init__(self, workspace: ProfileWorkspace, language: str = "en"):
        self.workspace = workspace
        super().__init__(CommunityBridge(workspace, None), ASSETS, "community", language)
