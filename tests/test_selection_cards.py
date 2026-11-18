import copy
import os

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton

from tests import test_catalogue_selection
from tests.test_tool_activity import narrative_run
from torrentlinker.gui.chat_transcript import ChatTranscript, MessageText

catalogue_app = test_catalogue_selection.catalogue_app


def presentation_page():
    return {
        "presentation_id": "demo",
        "title": "An evening of discovery",
        "list_id": "list-demo",
        "revision": 3,
        "client_id": "default",
        "count": 3,
        "offset": 0,
        "has_more": True,
        "next_offset": 2,
        "items": [
            {
                "item_id": "0",
                "title": "The Lunar Archive.2024.1080p",
                "content_title": "The Lunar Archive",
                "kind": "movie",
                "category": "Film",
                "size_bytes": 2147483648,
                "torrent_note": 1.35,
                "estimated_zen_per_day": 0.1284,
                "zen_assumptions": "Demo estimate: 24 hours seeding per day.",
                "seeders": 42,
                "image_url": "",
                "note": "A quiet science-fiction mystery.",
                "subtitle": "2024 · 1080p",
                "facts": {"year": "2024"},
                "source_url": "https://example.com/torrent/1",
                "metadata_status": "available",
            },
            {
                "item_id": "1",
                "title": "A Field Guide to Distant Worlds.epub",
                "content_title": "A Field Guide to Distant Worlds",
                "kind": "ebook",
                "category": "Ebook",
                "size_bytes": 4194304,
                "torrent_note": None,
                "estimated_zen_per_day": None,
                "seeders": 18,
                "image_url": "",
                "note": "Continue exploring in book form.",
                "subtitle": "EPUB",
                "facts": {"format": "EPUB"},
                "source_url": "",
                "metadata_status": "missing",
            },
        ],
    }


def presentation_run():
    run = narrative_run()
    run["messages"] = [
        {"role": "user", "content": "Show me the selection before doing anything."},
        {
            "role": "assistant",
            "content": "I will present the saved selection.",
            "phase": "commentary",
        },
        {
            "role": "assistant",
            "content": "Here are your saved selections. Open a card for details.",
            "phase": "final",
        },
    ]
    run["events"] = [
        {
            "tool": "present_selection",
            "status": "finished",
            "after_message_index": 1,
            "arguments": {"list_id": "list-demo", "revision": 3},
            "result": {"presentation_id": "demo"},
        }
    ]
    return run


def test_cards_open_details_without_model_turn_and_paginate(qtbot):
    calls = []

    def page_loader(identifier, offset=0, limit=12):
        calls.append(("page", identifier, offset))
        page = copy.deepcopy(presentation_page())
        if offset:
            page.update(
                items=[dict(page["items"][0], item_id="2", title="Another release")],
                offset=2,
                has_more=False,
                next_offset=None,
            )
        return page

    def item_loader(identifier, item_id):
        calls.append(("item", identifier, item_id))
        return dict(
            presentation_page()["items"][int(item_id)],
            description_html="<p>A journey through an abandoned lunar library.</p>",
            provenance=[{"source": "Indexer"}],
        )

    transcript = ChatTranscript(presentation_page=page_loader, presentation_item=item_loader)
    qtbot.addWidget(transcript)
    transcript.resize(900, 950)
    transcript.set_runs([presentation_run()], str)
    transcript.show()
    qtbot.waitUntil(lambda: len(transcript.findChildren(QPushButton, "selectionCard")) == 2)
    cards = transcript.findChildren(QPushButton, "selectionCard")
    summary = transcript.findChildren(MessageText)[-1]
    assert (
        summary.mapTo(transcript.widget(), QPoint()).y()
        < cards[0].mapTo(transcript.widget(), QPoint()).y()
    )
    assert cards[0].property("kind") == "movie"
    assert cards[1].property("kind") == "ebook"
    score = cards[0].findChild(QLabel, "selectionScores")
    assert "1.35" in score.text() and "0.128" in score.text()
    assert "24 hours" in score.toolTip()
    assert "—" in cards[1].findChild(QLabel, "selectionScores").text()
    qtbot.mouseClick(cards[0], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(transcript.findChildren(QDialog, "selectionDetail")))
    dialog = transcript.findChild(QDialog, "selectionDetail")
    qtbot.waitUntil(lambda: dialog.findChild(QLabel, "selectionDetailTitle") is not None)
    assert dialog.findChild(QLabel, "selectionDetailTitle").text() == "The Lunar Archive"
    assert ("item", "demo", "0") in calls
    dialog.close()
    next_page = transcript.findChild(QPushButton, "selectionNext")
    qtbot.mouseClick(next_page, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: ("page", "demo", 2) in calls)
    qtbot.waitUntil(lambda: len(transcript.findChildren(QPushButton, "selectionCard")) == 1)
    transcript.set_runs([presentation_run()], str)
    qtbot.waitUntil(lambda: len(transcript.findChildren(QPushButton, "selectionCard")) == 1)
    assert calls.count(("page", "demo", 2)) == 1


def test_detail_closed_during_loading_does_not_crash(qtbot):
    import threading

    from torrentlinker.gui.chat_images import ChatImages
    from torrentlinker.gui.selection_cards import SelectionDetail

    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def loader(*args):
        started.set()
        release.wait(5)
        finished.set()
        return presentation_page()["items"][0]

    parent = ChatTranscript()
    qtbot.addWidget(parent)
    dialog = SelectionDetail("demo", "0", loader, ChatImages(parent), parent)
    dialog.open()
    qtbot.waitUntil(started.is_set)
    dialog.close()
    qtbot.wait(20)
    release.set()
    qtbot.waitUntil(finished.is_set)
    qtbot.wait(50)


def demo_artwork(title, color):
    """Clearly fictional graphic covers used only in presentation UI tests."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

    image = QImage(360, 520, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#ffffff"), 2))
    for radius in (45, 70, 95):
        painter.drawEllipse(180 - radius, 170 - radius, radius * 2, radius * 2)
    painter.setFont(QFont("Sans Serif", 22))
    painter.drawText(
        QRect(24, 300, 312, 145), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, title
    )
    painter.setFont(QFont("Sans Serif", 10))
    painter.drawText(QRect(24, 470, 312, 30), Qt.AlignmentFlag.AlignCenter, "DEMO ARTWORK")
    painter.end()
    return image


def test_native_card_preview(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication

    from torrentlinker.gui.chat_images import ChatImages

    page = presentation_page()
    page.update(has_more=False, next_offset=None, count=2, title="Your saved selection · demo")
    images = ChatImages()
    for item, color in zip(page["items"], ("#203b59", "#785742"), strict=True):
        item["image_url"] = "https://covers.example/" + item["item_id"] + ".png"
        images.images[item["image_url"]] = demo_artwork(item["content_title"], color)
    transcript = ChatTranscript(
        presentation_page=lambda *args, **kwargs: page,
        presentation_item=lambda *args: dict(
            page["items"][0], description="<p>A fictional story.</p>"
        ),
    )
    qtbot.addWidget(transcript)
    transcript.images = images
    transcript.resize(960, 900)
    transcript.set_runs([presentation_run()], str)
    transcript.show()
    qtbot.waitUntil(lambda: len(transcript.findChildren(QPushButton, "selectionCard")) == 2)
    QApplication.processEvents()
    qtbot.waitUntil(
        lambda: all(c.height() > 250 for c in transcript.findChildren(QPushButton, "selectionCard"))
    )
    transcript.grab().save(str(tmp_path / "selection-cards-desktop.png"))


@pytest.mark.skipif(os.environ.get("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
@pytest.mark.parametrize("root_path", ["", "/tl"])
@pytest.mark.parametrize("upload", [False, True])
def test_browser_cards_open_modal_and_keep_exact_pagination(tmp_path, root_path, upload):
    import socket
    import threading
    import time
    from urllib.parse import parse_qs, urlsplit

    import uvicorn
    from fastapi import FastAPI
    from playwright.sync_api import expect, sync_playwright
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication

    from torrentlinker.web.app import create_app

    qt_app = QApplication.instance() or QApplication([])
    assert qt_app
    saved = presentation_page()
    saved["title"] = "Your saved selection · demo"
    run = presentation_run()
    if upload:
        saved["presentation_type"] = "upload_drafts"
        run["events"][0]["tool"] = "present_upload_drafts"
        for item in saved["items"]:
            item.update(
                presentation_type="upload_drafts",
                torrent_note=None,
                estimated_zen_per_day=None,
                zen_assumptions="",
                source_url="",
                note="",
                facts={"Category": "Film", "Source": "Blu-ray", "Files": "1"},
                draft_id="demo-draft",
                draft_revision=1,
                saved_status="queued",
                draft_changed=True,
                current_revision=2,
                review_summary={"warnings": 1, "refusals": 1},
                nfo="Saved upload NFO",
                files=[{"path": "release.epub", "size": 1234}],
                upload_review={"warnings": ["Check edition"], "refusals": ["Missing option"]},
            )
    pngs = {}
    for item, color in zip(saved["items"], ("#203b59", "#785742"), strict=True):
        item["image_url"] = "https://covers.example/" + item["item_id"] + ".png"
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        demo_artwork(item["content_title"], color).save(buffer, "PNG")
        pngs[item["image_url"]] = bytes(buffer.data())
    app = create_app(tmp_path, password="test-password-long")
    if root_path:
        mounted = FastAPI()
        mounted.mount(root_path, app)
        app = mounted
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    calls, remote = [], []
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1050, "height": 980}, color_scheme="dark")

            def respond(route):
                url = urlsplit(route.request.url)
                calls.append(url.path)
                data = copy.deepcopy(saved)
                if "/items/" in url.path:
                    item_id = url.path.rsplit("/", 1)[-1]
                    data = dict(
                        saved["items"][int(item_id)],
                        description_html="<p>A journey through a lunar library.</p>"
                        "<script>window.bad=true</script>"
                        "<img src='https://untrusted.example/x'>"
                        "<a href='javascript:alert(1)'>unsafe link</a>",
                    )
                elif parse_qs(url.query).get("offset") == ["2"]:
                    data.update(
                        items=[
                            dict(
                                saved["items"][0],
                                item_id="2",
                                title="Another release",
                                content_title="Another release",
                            )
                        ],
                        offset=2,
                        has_more=False,
                        next_offset=None,
                    )
                route.fulfill(json=data)

            page.add_init_script("localStorage.setItem('tl-language', 'en')")
            page.route("**/api/assistant/presentations/**", respond)
            page.route(
                "**/api/assistant/image?**",
                lambda route: route.fulfill(
                    content_type="image/png",
                    body=pngs[parse_qs(urlsplit(route.request.url).query)["url"][0]],
                ),
            )
            page.on(
                "request",
                lambda request: (
                    remote.append(request.url) if request.url.startswith("https://") else None
                ),
            )
            page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}{root_path}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#workspace")).to_be_visible()
            page.evaluate(
                """run => {
                document.querySelectorAll('body > :not(script)').forEach(e => e.remove());
                const container = document.createElement('main');
                container.style.cssText = 'max-width:900px;margin:32px auto;padding:20px';
                container.append(aRunCard(run)); document.body.append(container);
            }""",
                run,
            )
            page.evaluate(
                """run => {
                run.events = run.events.map(e => ({...e, tool: "get_presentation"}));
                document.querySelector('main').append(aRunCard(run));
            }""",
                run,
            )
            expect(page.locator(".selection-presentation")).to_have_count(1)
            assert page.evaluate("""() => {
                const run = document.querySelector('.assistant-run');
                const summary = [...run.querySelectorAll('.assistant-message.assistant')].at(-1);
                const cards = run.querySelector('.selection-presentation');
                return !!(summary.compareDocumentPosition(cards)
                    & Node.DOCUMENT_POSITION_FOLLOWING);
            }""")
            expect(page.locator(".selection-card")).to_have_count(2)
            if upload:
                expect(page.locator(".selection-scores")).to_have_count(0)
                expect(page.locator(".selection-card").first).to_contain_text("Draft changed")
            else:
                expect(
                    page.locator(".selection-card").first.locator(".selection-scores")
                ).to_have_text("Note 1.35 · ≈ 0.128 Zen/day")
                expect(
                    page.locator(".selection-card").last.locator(".selection-scores")
                ).to_contain_text("—")
            page.wait_for_function(
                "() => Array.from(document.querySelectorAll('.selection-card img'))"
                ".every(i => i.complete && i.naturalWidth > 0)"
            )
            page.screenshot(path=str(tmp_path / "selection-cards-web.png"))
            page.get_by_role("button", name="The Lunar Archive", exact=True).click()
            expect(page.locator("dialog .selection-description")).to_contain_text("lunar library")
            if upload:
                page.get_by_role("tab", name="NFO", exact=True).click()
                expect(page.locator("dialog pre", has_text="Saved upload NFO")).to_be_visible()
                page.get_by_role("tab", name="Review", exact=True).click()
                expect(page.locator("dialog pre", has_text="Missing option")).to_be_visible()
            assert not page.evaluate("window.bad || false")
            assert page.locator("dialog script, dialog .selection-description img").count() == 0
            assert page.locator("dialog a[href^='javascript:']").count() == 0
            assert root_path + "/api/assistant/presentations/demo/items/0" in calls
            page.screenshot(path=str(tmp_path / "selection-card-modal-web.png"))
            page.get_by_role("button", name="Close", exact=True).click()
            page.get_by_role("button", name="Next", exact=True).click()
            expect(page.locator(".selection-card")).to_have_count(1)
            expect(page.locator(".selection-card")).to_contain_text("Another release")
            page.evaluate(
                """run => {
                document.querySelector('main').replaceChildren(aRunCard(run));
            }""",
                run,
            )
            expect(page.locator(".selection-card")).to_have_count(1)
            assert not remote
            assert len([c for c in calls if "/items/" not in c]) == (3 if upload else 2)
            if upload:
                page.route(
                    "**/api/upload/queue?**",
                    lambda route: route.fulfill(
                        json=[
                            {
                                "id": "demo-draft",
                                "revision": 1,
                                "status": "queued",
                                "form": {"title": "The Lunar Archive"},
                                "path": "/saved/release.epub",
                                "files": [{"path": "release.epub", "size": 1234}],
                            }
                        ]
                    ),
                )
                preview_calls = []

                def preview_response(route):
                    preview_calls.append(route.request.url)
                    route.fulfill(json=dict(saved["items"][0], description="Saved description"))

                page.route("**/api/upload/queue/demo-draft/preview?**", preview_response)
                # Reload the production workspace after the isolated chat-card view.
                # The queue and selected-draft actions now share the full editor.
                page.reload()
                expect(page.locator("#workspace")).to_be_visible()
                page.evaluate("""async () => {
                    state.clientId = 'default';
                    await navigate('upload');
                    uploadLegacy.hidden = false;
                    uploadFrame.hidden = true;
                    state.uploadDraft = uploadUI.rows[0];
                    $('upload-editor').hidden = false;
                    $('upload-help').hidden = true;
                    uploadEditorState();
                }""")
                expect(page.locator("#upload-local-queue")).to_contain_text("The Lunar Archive")
                page.locator("[data-upload-section=description]").click()
                page.get_by_role("button", name="Preview saved draft", exact=True).click()
                expect(page.locator("dialog h2")).to_have_text("Upload draft review")
                expect(page.locator("dialog .selection-description")).to_have_text(
                    "Saved description"
                )
                assert parse_qs(urlsplit(preview_calls[0]).query) == {
                    "revision": ["1"],
                    "client_id": ["default"],
                }
                page.screenshot(path=str(tmp_path / "upload-queue-preview-web.png"))
                page.get_by_role("button", name="Close", exact=True).click()
            browser.close()
    finally:
        server.should_exit = True
        worker.join(10)
        listener.close()


def test_shared_tool_presentation_renders_through_owner_loaders(qtbot, catalogue_app):
    from tests.test_agent_torrent_lists import selected, tool
    from torrentlinker.gui.torrent_details import DescriptionBrowser

    app, browser, token = catalogue_app
    selection = selected(browser, token, "ui-source")
    result = tool(
        browser,
        token,
        "present_selection",
        request_id="ui-cards",
        selection_id=selection,
        title="Saved for review",
    )
    assistant = app.state.assistant
    run = presentation_run()
    run["events"][0]["result"] = result
    transcript = ChatTranscript(
        presentation_page=assistant.presentation_page, presentation_item=assistant.presentation_item
    )
    qtbot.addWidget(transcript)
    transcript.resize(900, 900)
    transcript.set_runs([run], str)
    transcript.show()
    qtbot.waitUntil(lambda: len(transcript.findChildren(QPushButton, "selectionCard")) == 3)
    assert transcript.findChild(QLabel, "selectionTitle").text() == "Saved for review"
    qtbot.mouseClick(
        transcript.findChildren(QPushButton, "selectionCard")[0], Qt.MouseButton.LeftButton
    )
    qtbot.waitUntil(lambda: bool(transcript.findChildren(DescriptionBrowser)))
    assert browser.get("/api/queue").json() == []


def test_category_placeholder_never_interprets_html(qtbot):
    from torrentlinker.gui.chat_images import ChatImages
    from torrentlinker.gui.selection_cards import Artwork

    label = '<img src="file:///tmp/private-image.png"><b>Film</b>'
    art = Artwork({"category": label, "kind": "movie"}, ChatImages())
    qtbot.addWidget(art)
    assert art.text() == label
    assert art.textFormat() == Qt.TextFormat.PlainText


def test_reading_presentation_does_not_duplicate_cards(qtbot):
    run = presentation_run()
    run["events"].append({**run["events"][0], "tool": "get_presentation"})
    transcript = ChatTranscript(presentation_page=lambda *a, **kw: presentation_page())
    qtbot.addWidget(transcript)
    transcript.set_runs([run], str)
    qtbot.waitUntil(lambda: bool(transcript.findChildren(QPushButton, "selectionCard")))
    from torrentlinker.gui.selection_cards import SelectionCards

    assert len(transcript.findChildren(SelectionCards)) == 1
