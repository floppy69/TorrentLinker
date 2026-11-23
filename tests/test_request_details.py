import json
import os

import pytest
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton

from torrentlinker.agent.presentation import request_summary
from torrentlinker.gui.chat_transcript import ChatTranscript
from torrentlinker.gui.request_details import RequestDetails


def queue_removal_event():
    return {
        "review": {
            "client": "Test client",
            "operation": {
                "kind": "edit-queue-selection",
                "queue_action": "remove",
                "client_id": "default",
                "selection_rows": [
                    {
                        "title": "Film 01 <img src=x>",
                        "hash": "a" * 40,
                        "key": "first",
                        "folder": "/downloads/films",
                    },
                    {
                        "title": "Film 02",
                        "hash": None,
                        "key": "hashless-entry",
                        "folder": "/downloads/other",
                    },
                ],
            },
            "selection": {"selected_count": 2, "total_size_bytes": 20, "criteria": {}},
        }
    }


@pytest.mark.parametrize("language", ["en", "fr"])
def test_queue_removal_review_shows_exact_entries_without_opening_json(qtbot, qapp, language):
    previous = qapp.property("language")
    qapp.setProperty("language", language)
    try:
        widget = RequestDetails(queue_removal_event())
        qtbot.addWidget(widget)
        widget.show()
        targets = widget.findChild(QPlainTextEdit, "queueRemovalTargets")
        assert targets.isVisible() and targets.isReadOnly()
        assert "Film 01 <img src=x>" in targets.toPlainText()
        assert "a" * 40 in targets.toPlainText()
        assert "Film 02\nhashless-entry\n/downloads/other" in targets.toPlainText()
        assert not widget.code.isVisible()
        summary = "\n".join(label.text() for label in widget.findChildren(QLabel))
        assert ("Retirer 2" if language == "fr" else "Remove 2") in summary
    finally:
        qapp.setProperty("language", previous)


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
@pytest.mark.parametrize("language,decision", [("en", "approve"), ("fr", "reject")])
def test_browser_queue_removal_review_lists_targets_before_deciding(tmp_path, language, decision):
    from pathlib import Path

    from playwright.sync_api import expect, sync_playwright

    static = Path(__file__).parents[1] / "src/torrentlinker/web/static"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1000, "height": 800})
        page.set_content("<main></main>")
        page.add_style_tag(path=str(static / "app.css"))
        page.add_script_tag(
            content="""
            let language = 'en'; const calls = [];
            const say = (en, fr) => language === 'fr' ? fr : en;
            function element(tag, text, cls) {
              const el = document.createElement(tag);
              if (text !== undefined) el.textContent = text;
              if (cls) el.className = cls;
              return el;
            }
            function button(text, action, cls) {
              const el = element('button', text, cls); el.type = 'button';
              el.onclick = action; return el;
            }
            async function request(action, {path, body}) {
              calls.push(path); return window.review;
            }
        """
        )
        page.add_script_tag(path=str(static / "settings/assistant.js"))
        page.add_script_tag(path=str(static / "settings/agents.js"))
        page.evaluate(
            "data => { language = data.language; window.review = data.review; }",
            {"language": language, "review": queue_removal_event()["review"]},
        )
        page.evaluate("aReview('removal', async () => {})")
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text("Retirer 2" if language == "fr" else "Remove 2")
        expect(dialog.locator(".queue-removal-targets li")).to_have_count(2)
        expect(dialog).to_contain_text("Film 01 <img src=x>")
        expect(dialog.locator("img")).to_have_count(0)
        expect(dialog).to_contain_text("hashless-entry")
        assert page.evaluate("calls") == ["agents/proposals/removal/review"]
        if output := os.getenv("TL_WEB_SCREENSHOTS"):
            target = Path(output)
            target.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target / f"queue-removal-review-{language}.png"))
        dialog.get_by_role(
            "button", name="Approve this action" if decision == "approve" else "Refuser", exact=True
        ).click()
        expect(dialog).not_to_be_visible()
        assert page.evaluate("calls")[-1] == f"agents/proposals/removal/{decision}"
        browser.close()


def queued_event():
    return {
        "tool": "enqueue_selection",
        "status": "waiting",
        "arguments": {"request_id": "queue", "selection_id": "selected"},
        "result": {"id": "proposal", "requires_owner_approval": True},
        "review": {
            "operation": {
                "kind": "enqueue",
                "client_id": "default",
                "hashes": [f"{i:040x}" for i in range(500)],
                "upload": {"title": "<img src=x>"},
            },
            "selection": {
                "selected_count": 500,
                "total_size_bytes": 482880872220,
                "criteria": {"categories": [2030]},
            },
        },
    }


def test_grouped_destructive_summary_shows_clients_targets_folders_and_warning():
    event = {
        "tool": "manage_selection",
        "review": {
            "operation": {"kind": "manage", "action": "delete"},
            "torrent_instance_count": 2,
            "groups": [
                {
                    "client": "NAS",
                    "client_id": "nas",
                    "torrent_instance_count": 1,
                    "metadata_size_bytes": 1024,
                    "targets": [{"name": "Shared film", "hash": "a" * 40, "folder": "/srv/media"}],
                },
                {
                    "client": "Seedbox",
                    "client_id": "seedbox",
                    "torrent_instance_count": 1,
                    "metadata_size_bytes": 1024,
                    "targets": [{"name": "Shared film", "hash": "a" * 40, "folder": "/data/media"}],
                },
            ],
            "warning": "Other torrents may share these files.",
        },
    }
    summary = "\n".join(request_summary(event))
    assert "Delete 2" in summary
    assert "NAS" in summary and "Seedbox" in summary
    assert "/srv/media" in summary and "/data/media" in summary
    assert "Other torrents may share these files" in summary


def test_large_approval_stays_compact_and_full_command_survives_refresh(qtbot):
    widget = ChatTranscript()
    qtbot.addWidget(widget)
    widget.resize(900, 700)
    event = queued_event()
    rows = [
        {
            "id": "run",
            "messages": [],
            "error": "",
            "status": "awaiting_approval",
            "events": [event],
            "calls": 1,
            "tokens": 100,
        }
    ]
    widget.set_runs(rows, str)
    widget.show()
    detail = widget.findChild(RequestDetails)
    assert not detail.code.isVisible()
    summary = "\n".join(label.text() for label in detail.findChildren(QLabel))
    assert "500 torrents" in summary
    assert "482,880,872,220" in summary
    assert event["review"]["operation"]["hashes"][-1] not in summary
    assert "upload" not in summary
    assert detail.height() < 300
    detail.toggle.click()
    assert detail.code.isVisible()
    assert detail.code.height() <= 320
    assert json.loads(detail.code.toPlainText())["review"] == event["review"]
    detail.code.highlighter.rehighlight()
    assert detail.code.document().findBlockByNumber(1).layout().formats()
    widget.set_runs(rows, str)
    assert widget.findChild(RequestDetails).toggle.isChecked()
    qtbot.waitUntil(lambda: any(b.isVisible() for b in widget.findChildren(QPushButton)))
    with qtbot.waitSignal(widget.decisionSubmitted) as signal:
        next(
            b
            for b in widget.findChildren(QPushButton)
            if b.text() == "Approve once" and b.isVisible()
        ).click()
    assert signal.args == ["run", 0, True]

    # A changed receipt must replace its previously reusable approval controls.
    event["decision"] = "approved"
    event["status"] = "finished"
    rows[0]["status"] = "completed"
    widget.set_runs(rows, str)
    assert not any(b.text() == "Approve once" for b in widget.findChildren(QPushButton))


def test_summary_keeps_destructive_effect_and_global_folder_scope_visible():
    deleted = {"review": {"operation": {"kind": "manage", "action": "delete", "hashes": ["a"]}}}
    assert "AND their files" in request_summary(deleted)[0]
    folder = {
        "review": {
            "operation": {"kind": "configure-download-folder", "category": None, "path": "/films"}
        }
    }
    assert any("ALL categories" in line for line in request_summary(folder))
    assert any("TOUTES les catégories" in line for line in request_summary(folder, "fr"))


def test_french_summary_and_command_toggle(qtbot, qapp):
    from torrentlinker import i18n

    previous = qapp.property("language")
    translators = i18n.install(qapp, "fr")
    try:
        widget = RequestDetails(queued_event())
        qtbot.addWidget(widget)
        assert widget.toggle.text() == "Afficher la commande complète"
        assert any("Ajouter 500 torrents" in label.text() for label in widget.findChildren(QLabel))
    finally:
        for translator in translators:
            qapp.removeTranslator(translator)
        qapp.setProperty("language", previous)


# Uses the shipped renderer and CSS with synthetic data; no model or tracker access.
@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_browser_command_is_collapsed_colored_and_preserved_on_refresh(tmp_path):
    from pathlib import Path

    from playwright.sync_api import expect, sync_playwright

    static = Path(__file__).parents[1] / "src/torrentlinker/web/static"
    event = queued_event()
    event["summary"] = {lang: request_summary(event, lang) for lang in ("en", "fr")}
    run = {
        "id": "run",
        "messages": [],
        "error": "",
        "status": "awaiting_approval",
        "events": [event],
        "calls": 1,
        "tokens": 100,
        "created": 0,
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 700, "height": 850})
        page.set_content('<main id="root"></main>')
        page.add_style_tag(path=str(static / "panel/base.css"))
        page.add_style_tag(path=str(static / "assistant/view.css"))
        page.add_script_tag(
            content="""
            const say = (en, fr) => en;
            const $ = id => document.getElementById(id);
            const state = {view: "", language: "en"};
            function element(tag, text, cls) {
              const e = document.createElement(tag);
              if (text !== undefined) e.textContent = text;
              if (cls) e.className = cls;
              return e;
            }
            function button(text, action, cls) {
              const b = element("button", text, cls); b.onclick = action; return b;
            }
        """
        )
        page.add_script_tag(path=str(static / "assistant/view.js"))
        page.evaluate("run => document.querySelector('#root').replaceChildren(aRunCard(run))", run)
        panel = page.locator(".assistant-decision")
        expect(panel).to_contain_text("Add 500 torrents")
        code = panel.locator("pre")
        expect(code).not_to_be_visible()
        panel.get_by_text("Show full command", exact=True).click()
        expect(code).to_be_visible()
        assert json.loads(code.inner_text())["review"] == event["review"]
        assert panel.locator(".json-key").count() > 0
        assert panel.locator("img").count() == 0
        assert code.bounding_box()["height"] <= 360
        page.evaluate("run => document.querySelector('#root').replaceChildren(aRunCard(run))", run)
        expect(panel.locator("pre")).to_be_visible()
        page.screenshot(path=str(tmp_path / "request-web.png"))
        browser.close()


@pytest.mark.parametrize(
    "action,fragment",
    [("remove", "Remove 3 unsent"), ("retry", "Return 3 failed"), ("priority", "priority 7")],
)
def test_queue_edit_summary_identifies_action_and_keeps_client_files_scope_visible(
    action, fragment
):
    event = {
        "review": {
            "operation": {"kind": "edit-queue-selection", "queue_action": action, "priority": 7},
            "selection": {"selected_count": 3},
        }
    }
    english = request_summary(event)
    assert fragment in english[0]
    assert "Keeps files and Torrent Client torrents" in english[1]
    assert "Downloads will not start" in english[1]
    french = request_summary(event, "fr")
    assert "Conserve les fichiers et les torrents du client" in french[1]
