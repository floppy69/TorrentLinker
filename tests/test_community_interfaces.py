import os
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_community import H, observation
from tests.test_web_jobs import login
from tests.test_web_profile import ORIGIN, OWNER, prepared
from torrentlinker.community import DEFAULTS
from torrentlinker.gui.community_view import CommunityView


def ready(tmp_path, monkeypatch):
    app, setup = prepared(tmp_path, monkeypatch)
    w = setup.profile_workspace()
    w.refresh(setup.settings.indexer.url, "fake-key")
    w.community.observe("42", observation())
    return app, setup, w


def js(qtbot, view, script):
    results = []
    view.web.page().runJavaScript(script, results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=10000)
    return results[0]


def wait_js(qtbot, view, script):
    qtbot.waitUntil(lambda: bool(js(qtbot, view, script)), timeout=20000)


def test_native_approved_design_and_persistent_editor(qtbot, tmp_path, monkeypatch):
    # Qt Quick's offscreen renderer is selected process-wide by other GUI tests.
    # Exercise WebEngine in a fresh process with its own Qt application and profile.
    if not os.getenv("TL_COMMUNITY_NATIVE_CHILD"):
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                f"{__file__}::test_native_approved_design_and_persistent_editor",
            ],
            env={**os.environ, "TL_COMMUNITY_NATIVE_CHILD": "1"},
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from PySide6.QtGui import QColor, QPalette

    _, _, w = ready(tmp_path, monkeypatch)
    view = CommunityView(w, "en")
    palette = view.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#161d23"))
    view.setPalette(palette)
    qtbot.addWidget(view)
    view.resize(1280, 900)
    view.show()
    wait_js(qtbot, view, "document.querySelectorAll('.torrent').length === 1")
    assert (
        js(
            qtbot,
            view,
            "Array.from(document.querySelectorAll('.tabs button')).map(b=>b.dataset.tab).join(',')",
        )
        == "torrents,chat,queue,history"
    )
    assert js(qtbot, view, "document.documentElement.lang") == "en"
    view.language = "fr"
    view.refresh()
    # The approved design has compact rows beside a persistent inspector.
    assert js(qtbot, view, "document.querySelector('.workspace').getBoundingClientRect().top < 250")
    assert js(
        qtbot,
        view,
        "document.querySelector('.inspector').getBoundingClientRect().left > do"
        "cument.querySelector('.library').getBoundingClientRect().left",
    )
    js(
        qtbot,
        view,
        "document.getElementById('community-content').value='Merci pour ce part"
        "age bien utile'; document.getElementById('community-content').dispatch"
        "Event(new Event('input')); document.querySelector('[data-command=save-"
        "draft]').click()",
    )
    qtbot.waitUntil(lambda: len(w.community_state()["items"]) == 1)
    assert w.community_state()["items"][0]["content"] == "Merci pour ce partage bien utile"
    js(
        qtbot,
        view,
        "document.getElementById('community-content').value='Un brouillon encor"
        "e en cours de rédaction'; document.getElementById('community-content')"
        ".dispatchEvent(new Event('input'))",
    )
    view.refresh()
    assert (
        js(qtbot, view, "document.getElementById('community-content').value")
        == "Un brouillon encore en cours de rédaction"
    )
    # Polling preserves the insertion point as well as the unsaved text.
    js(
        qtbot,
        view,
        "document.getElementById('community-content').focus(); document.getElem"
        "entById('community-content').setSelectionRange(3,9)",
    )
    view.refresh()
    assert (
        js(
            qtbot,
            view,
            "[document.getElementById('community-content').selectionStart,document."
            "getElementById('community-content').selectionEnd].join(',')",
        )
        == "3,9"
    )
    qtbot.wait(40)
    target = Path(os.getenv("TL_COMMUNITY_SCREENSHOTS", str(tmp_path)))
    target.mkdir(parents=True, exist_ok=True)
    assert view.grab().save(str(target / "tl-community-desktop.png"))

    # DOM success is insufficient: Wayland GPU failures leave a live but black view.
    def rendered_pixels():
        image = view.grab().toImage()
        return (
            len(
                {
                    image.pixelColor(x, y).rgb()
                    for x in range(20, image.width(), 40)
                    for y in range(20, image.height(), 40)
                }
            )
            > 10
        )

    qtbot.waitUntil(rendered_pixels, timeout=5000)
    js(qtbot, view, "document.querySelector('[data-tab=queue]').click()")
    assert js(qtbot, view, "document.querySelectorAll('.calendar-cell').length") == 7
    js(qtbot, view, "document.querySelector('[data-command=automation]').click()")
    assert js(qtbot, view, "document.querySelector('dialog').open")
    assert js(
        qtbot,
        view,
        "document.querySelector('dialog').getBoundingClientRect().right === doc"
        "ument.documentElement.clientWidth",
    )
    js(
        qtbot,
        view,
        "document.querySelector('[data-command=close]').click(); document.query"
        "Selector('[data-tab=torrents]').click()",
    )
    # A new renderer hydrates the persisted draft after restart.
    view.close()
    view.show()
    wait_js(qtbot, view, "Boolean(document.getElementById('community-content'))")
    assert (
        js(qtbot, view, "document.getElementById('community-content').value")
        == "Merci pour ce partage bien utile"
    )
    # The embedded renderer has no arbitrary API bridge.
    import json

    assert "error" in json.loads(view.bridge.request("setup", "{}"))
    assert "error" in json.loads(view.bridge.request("community/save", "[]"))
    assert "error" in json.loads(view.bridge.request("community", "invalid json"))
    from PySide6.QtWidgets import QFileDialog

    export = tmp_path / "community-history.json"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args: (str(export), "JSON (*.json)")
    )
    exported = [{"title": "=HYPERLINK(example)", "content": "Un texte conservé", "events": []}]
    result = view.bridge.request("community/export", json.dumps({"text": json.dumps(exported)}))
    assert json.loads(result)["data"]["saved"]
    assert json.loads(export.read_text()) == exported


def test_web_owner_and_extension_protocol_share_journal(tmp_path, monkeypatch):
    app, setup, w = ready(tmp_path, monkeypatch)
    with TestClient(app) as c:
        assert c.get("/api/community").status_code == 401
        login(c)
        assert "frame-ancestors 'none'" in c.get("/").headers["Content-Security-Policy"]
        shared = c.get("/static/community/view.html")
        assert shared.status_code == 200
        assert "frame-ancestors 'self'" in shared.headers["Content-Security-Policy"]
        assert "default-src 'none'" in shared.headers["Content-Security-Policy"]
        assert (
            c.post(
                "/api/community/settings", headers={"X-TorrentLinker": ""}, json=DEFAULTS
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/api/community/save",
                headers=OWNER,
                json={
                    "kind": "comment",
                    "subject": H,
                    "content": "Merci pour ce partage bien utile",
                },
            ).status_code
            == 200
        )
        item = c.get("/api/community").json()["items"][0]
        assert w.community_state()["items"][0]["id"] == item["id"]
        c.post(
            "/api/community/control",
            headers=OWNER,
            json={
                "id": item["id"],
                "revision": item["revision"],
                "action": "queue",
            },
        ).raise_for_status()
        c.post(
            "/api/community/settings", headers=OWNER, json={**deepcopy(DEFAULTS), "enabled": True}
        ).raise_for_status()
        ext = {"Origin": ORIGIN}
        code = w.pairing()["code"]
        token = c.post(
            "/api/companion/pair", headers=ext, json={"code": code, "accountId": "42"}
        ).json()["token"]
        ext["Authorization"] = "Bearer " + token
        assert (
            c.post(
                "/api/companion/actions-claim", headers=ext, json={"accountId": "other"}
            ).status_code
            == 403
        )
        response = c.post("/api/companion/actions-claim", headers=ext, json={"accountId": "42"})
        command = response.json()["command"]
        assert command["content"] == "Merci pour ce partage bien utile"
        assert (
            c.post("/api/companion/actions-claim", headers=ext, json={"accountId": "42"}).json()[
                "command"
            ]
            is None
        )
        body = {**command, "outcome": "posted", "remoteId": "123"}
        assert c.post("/api/companion/actions-receipt", headers=ext, json=body).status_code == 200
        assert c.post("/api/companion/actions-receipt", headers=ext, json=body).status_code == 200
        assert c.get("/api/community").json()["items"][0]["state"] == "posted"
        assert len(c.get("/api/community/messages").json()["entries"]) >= 180
        w.bind(setup.settings.indexer.url, "rotated-key")
        w.refresh(setup.settings.indexer.url, "rotated-key")
        assert w.community_state()["items"][0]["state"] == "posted"
        assert not w.community_state()["paired"]
