"""The approved Assistant discussion rendered by the desktop bundled panel."""

import os
import subprocess
import sys

import httpx
from fastapi.testclient import TestClient

from tests.test_assistant import login
from tests.test_assistant_ui import provider
from torrentlinker.web.app import create_app


def test_shared_desktop_discussion_sends_and_keeps_composer_visible(qtbot, tmp_path, request):
    if not os.getenv("TL_ASSISTANT_NATIVE_CHILD"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
            env={
                **os.environ,
                "TL_ASSISTANT_NATIVE_CHILD": "1",
                "XDG_CONFIG_HOME": str(tmp_path / "qt-config"),
            },
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qt"))

    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.gui.assistant_view import AssistantPanel

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=httpx.MockTransport(provider)
    )
    with TestClient(app) as browser:
        login(browser)
        browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Test", "kind": "ollama", "model": "test"},
        )
        ready = False

        def service():
            if not ready:
                raise ValueError("Port unavailable. Reopen the Assistant tab to retry.")
            return app.state.assistant

        widget = AssistantPanel(service)
        qtbot.addWidget(widget)
        widget.resize(1280, 720)
        widget.show()
        widget.activate()
        wait_js(qtbot, widget, "document.body.innerText.includes('Port unavailable')")
        ready = True
        widget.activate()
        try:
            wait_js(qtbot, widget, "!!document.querySelector('#assistant-prompt')")
        except Exception:
            raise AssertionError(
                js(
                    qtbot,
                    widget,
                    "document.body.innerText",
                )
            ) from None
        js(
            qtbot,
            widget,
            "document.querySelector('#assistant-prompt').value='Help me build a Plan.';"
            "document.querySelector('#assistant-send').click()",
        )
        wait_js(qtbot, widget, "document.body.innerText.includes('Ready to prepare a Plan')")
        assert len(browser.get("/api/assistant/conversations").json()) == 1
        assert js(
            qtbot,
            widget,
            "document.querySelector('#assistant-prompt').getBoundingClientRect().bottom"
            " <= innerHeight",
        )
        if output := os.getenv("TL_ASSISTANT_SCREENSHOT"):
            from pathlib import Path

            from PySide6.QtWidgets import QApplication

            from torrentlinker.gui.theme import apply_theme

            Path(output).mkdir(parents=True, exist_ok=True)
            for language in ("en", "fr"):
                widget.language = language
                for theme in ("dark", "light"):
                    apply_theme(QApplication.instance(), theme)
                    widget.refresh()
                    wait_js(
                        qtbot,
                        widget,
                        f"document.documentElement.lang === '{language}' && "
                        f"document.documentElement.dataset.theme === '{theme}' && "
                        "!!document.querySelector('#assistant-prompt')",
                    )
                    qtbot.wait(300)
                    widget.grab().save(str(Path(output) / f"{language}-{theme}.png"))
