"""Saved automation and Upload review through the real desktop Assistant panel."""

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from tests.test_assistant import generation_transport, login
from tests.test_upload_presentations import draft_payload
from torrentlinker.web.app import create_app


def test_desktop_automation_opens_saved_upload_and_private_image(qtbot, tmp_path, request):
    if not os.getenv("TL_AUTOMATION_CHILD"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
            env={**os.environ, "TL_AUTOMATION_CHILD": "1", "XDG_CONFIG_HOME": str(tmp_path / "qt")},
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from tests.test_community_interfaces import js, wait_js
    from torrentlinker.gui.assistant_view import AssistantPanel
    from torrentlinker.gui.theme import apply_theme
    from torrentlinker.upload_assets import Assets

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qt"))
    calls = 0
    draft = None

    def response(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "show",
                        "type": "function",
                        "function": {
                            "name": "present_upload_drafts",
                            "arguments": json.dumps(
                                {
                                    "request_id": "review",
                                    "client_id": "default",
                                    "drafts": [{"draft_id": draft["id"], "revision": 1}],
                                }
                            ),
                        },
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": "Review the saved Upload before sending."}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    app = create_app(
        tmp_path, password="test-password-long", assistant_transport=generation_transport(response)
    )
    with TestClient(app) as browser:
        login(browser)
        payload = draft_payload("Saved book")
        payload["form"]["image"] = ""
        payload["form"]["description"] = re.sub(
            r"\[img[^]]*\].*?\[/img\]", "", payload["form"]["description"], flags=re.S
        )
        picture = io.BytesIO()
        Image.new("RGB", (120, 180), "teal").save(picture, "PNG")
        asset = Assets(tmp_path).put(picture.getvalue(), "image/png", payload["path"])
        payload["form"]["assets"] = [asset["asset_id"]]
        payload["review"]["file_facts"] = {"assets": [asset], "file_count": 1}
        draft = app.state.agent_service.setup.store.save_local_draft(payload)
        model = browser.post(
            "/api/setup/assistant/providers",
            json={
                "name": "Test",
                "kind": "compatible",
                "url": "http://model.invalid/v1",
                "model": "test",
                "context_window": 131072,
            },
        ).json()
        task = browser.post(
            "/api/assistant/schedules",
            json={
                "name": "Weekly review",
                "provider_id": model["id"],
                "instruction": "Review Upload",
                "frequency": "weekly",
                "weekdays": [5],
                "at": "10:15",
                "timezone": "Europe/Paris",
                "policy": {"name": "Read", "clients": ["default"]},
            },
        )
        assert task.is_success, task.text
        widget = AssistantPanel(lambda: app.state.assistant)
        qtbot.addWidget(widget)
        widget.resize(1280, 720)
        widget.show()
        widget.activate()

        def click(label, selector="button"):
            query = (
                f"[...document.querySelectorAll({json.dumps(selector)})]"
                f".find(e=>e.textContent==={json.dumps(label)})"
            )
            wait_js(qtbot, widget, f"!!({query})")
            js(qtbot, widget, f"({query}).click()")

        click("Automations", "[role=tab]")
        wait_js(qtbot, widget, "document.body.innerText.includes('Weekly, Sat at 10:15 · Paused')")
        click("Enable")
        click("Run now")
        wait_js(qtbot, widget, "!!document.querySelector('.assistant-history')")
        # History is a saved snapshot: revisit after the simulated run completes.
        qtbot.waitUntil(
            lambda: app.state.assistant.history()[0]["status"] == "completed", timeout=10000
        )
        click("Discussion", "[role=tab]")
        click("History", "[role=tab]")
        assert app.state.assistant.history()[0]["events"][0]["status"] != "failed"
        wait_js(qtbot, widget, "document.querySelectorAll('.selection-card').length===1")
        wait_js(qtbot, widget, "document.querySelector('.selection-card img')?.naturalWidth > 0")
        js(qtbot, widget, "document.querySelector('.selection-card').click()")
        wait_js(
            qtbot,
            widget,
            "document.querySelector('dialog')?.innerText.includes('Upload draft review')",
        )
        wait_js(
            qtbot, widget, "document.querySelector('.selection-description img')?.naturalWidth > 0"
        )
        if directory := os.getenv("TL_AUTOMATION_SCREENSHOTS"):
            Path(directory).mkdir(parents=True, exist_ok=True)
            widget.grab().save(str(Path(directory) / "upload-review.png"))
        click("Files", "[role=tab]")
        assert "book.epub · 1.2 KiB" in js(
            qtbot, widget, "document.querySelector('dialog').innerText"
        )
        click("NFO", "[role=tab]")
        assert "Saved NFO" in js(qtbot, widget, "document.querySelector('dialog').innerText")
        click("Review", "[role=tab]")
        assert "Missing option" in js(qtbot, widget, "document.querySelector('dialog').innerText")
        assert app.state.agent_service.setup.store.local_draft(draft["id"]) == draft
        assert browser.get("/api/queue").json() == []
        click("Close")
        click("Automations", "[role=tab]")
        if directory := os.getenv("TL_AUTOMATION_SCREENSHOTS"):
            Path(directory).mkdir(parents=True, exist_ok=True)
            for language in ("en", "fr"):
                widget.language = language
                for theme in ("dark", "light"):
                    apply_theme(QApplication.instance(), theme)
                    widget.refresh()
                    wait_js(qtbot, widget, "!!document.querySelector('.assistant-task')")
                    qtbot.wait(200)
                    widget.grab().save(str(Path(directory) / f"{language}-{theme}.png"))
