"""Render a packaged shared WebView before declaring a desktop bundle healthy."""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
from PySide6.QtWidgets import QApplication

from torrentlinker.gui.shell_view import ShellView


def webview_smoke_checks() -> None:
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("The WebView smoke check requires QApplication.")
    view = ShellView(
        "header",
        lambda: {
            "language": "en",
            "theme": "dark",
            "page": "torrents",
            "clients": [],
            "client_id": "",
            "allow_all": True,
        },
        lambda *_: None,
    )
    view.resize(760, 140)
    view.show()
    deadline = time.monotonic() + 20
    rendered = False
    try:
        assert view.web is not None
        while time.monotonic() < deadline:
            answers: list[object] = []
            view.web.page().runJavaScript(
                """(() => {
                  const title = document.getElementById('page-title');
                  return !!title && title.textContent === 'Torrents' &&
                    title.getBoundingClientRect().width > 0 &&
                    getComputedStyle(document.documentElement)
                      .getPropertyValue('--bg').trim() !== '';
                })()""",
                answers.append,
            )
            while not answers and time.monotonic() < deadline:
                app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
                time.sleep(0.01)
            if answers and answers[0] is True:
                rendered = True
                break
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            time.sleep(0.02)
        if not rendered:
            raise RuntimeError("The packaged shared WebView did not render its header and styles.")
    finally:
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    print("shared WebView smoke test OK")
