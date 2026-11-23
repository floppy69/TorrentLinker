import os
import socket
import threading
import time
from html.parser import HTMLParser

import httpx
import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QBuffer, QCoreApplication, QEvent, QIODevice, QUrl
from PySide6.QtGui import QImage, QTextDocument

from tests.shell_support import shell_navigate
from tests.test_assistant import login
from torrentlinker.assistant.images import fetch_image
from torrentlinker.assistant.markdown import render
from torrentlinker.assistant.research import PublicTransport
from torrentlinker.web.app import create_app


class Elements(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_chat_embeds_public_covers_with_clickable_originals_and_safe_markup():
    html = render(
        "![Book cover](https://covers.example/cover.jpg?edition=2&size=large)\n\n"
        "[Full cover](https://covers.example/cover.jpg)\n\n"
        "<script>alert(1)</script>\n\n![local](file:///etc/passwd)"
    )
    tags = Elements(html).elements
    images = [attrs for tag, attrs in tags if tag == "img"]
    assert len(images) == 1
    assert images[0]["alt"] == "Book cover"
    assert images[0]["src"].startswith("api/assistant/image?url=https%3A%2F%2Fcovers.example")
    assert images[0]["loading"] == "lazy"
    assert images[0]["referrerpolicy"] == "no-referrer"
    assert any(
        attrs.get("href") == "https://covers.example/cover.jpg?edition=2&size=large"
        for tag, attrs in tags
        if tag == "a"
    )
    assert not any(tag == "script" for tag, _ in tags)


@pytest.fixture
def public_images(monkeypatch):
    import socket

    pixels = QImage(480, 720, QImage.Format.Format_RGB32)
    pixels.fill(0xFF225588)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert pixels.save(buffer, "PNG")
    png = bytes(buffer.data())
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        if request.url.path == "/html":
            return httpx.Response(
                200, text="<script>bad</script>", headers={"content-type": "image/png"}
            )
        if request.url.path == "/large":
            return httpx.Response(
                200, content=png + b"x" * 5_000_000, headers={"content-type": "image/png"}
            )
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    monkeypatch.setattr(
        PublicTransport,
        "__init__",
        lambda self: setattr(self, "http", httpx.MockTransport(respond)),
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34", 443),
            )
        ],
    )
    fetch_image.cache_clear()
    yield png, requests
    fetch_image.cache_clear()


def test_chat_image_endpoint_requires_login_and_never_fetches_private_redirects(
    tmp_path, public_images
):
    png, requests = public_images
    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app) as browser:
        assert (
            browser.get(
                "/api/assistant/image", params={"url": "https://covers.example/cover.png"}
            ).status_code
            == 401
        )
        assert not requests
        login(browser)
        response = browser.get(
            "/api/assistant/image", params={"url": "https://covers.example/cover.png"}
        )
        assert response.status_code == 200
        assert response.content == png
        assert response.headers["content-type"] == "image/png"
        assert "'self' data:" in response.headers["content-security-policy"]
        assert requests[0].headers.get("cookie") is None
        assert requests[0].headers.get("authorization") is None
        assert requests[0].headers.get("referer") is None
        for url in [
            "file:///etc/passwd",
            "http://127.0.0.1/private",
            "https://covers.example/redirect",
            "https://covers.example/html",
            "https://covers.example/large",
        ]:
            failed = browser.get("/api/assistant/image", params={"url": url})
            assert failed.status_code == 400, url
        assert not any(request.url.path == "/private" for request in requests)


def test_native_cover_loads_async_resizes_and_survives_transcript_refresh(
    qtbot, public_images, monkeypatch, tmp_path
):
    from PySide6.QtGui import QDesktopServices

    from torrentlinker.gui.chat_images import ChatImages
    from torrentlinker.gui.chat_transcript import MessageText

    _, requests = public_images
    url = "https://covers.example/cover.png"
    cache = ChatImages()
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda value: opened.append(value.toString()))
    widget = MessageText(f"![Film poster]({url})", images=cache)
    qtbot.addWidget(widget)
    widget.resize(400, 500)
    widget.show()
    qtbot.waitUntil(lambda: url in cache.images, timeout=5000)
    image = widget.document().resource(QTextDocument.ResourceType.ImageResource, QUrl(url))
    assert isinstance(image, QImage) and not image.isNull()
    assert image.height() == 360
    assert "Film poster" in widget.toPlainText()
    assert widget.height() >= 360
    original_height = widget.height()
    widget.anchorClicked.emit(QUrl(url))
    assert opened == [url]
    widget.resize(160, 600)
    qtbot.waitUntil(lambda: widget.height() < original_height)
    assert widget.horizontalScrollBar().maximum() == 0
    refreshed = MessageText(f"![Film poster]({url})", images=cache)
    qtbot.addWidget(refreshed)
    refreshed.show()
    qtbot.wait(20)
    assert len(requests) == 1
    refreshed.grab().save(str(tmp_path / "chat-cover-native.png"))


def test_many_images_are_bounded_and_private_images_stay_text():
    text = "\n\n".join(f"![cover {i}](https://covers.example/{i}.png)" for i in range(20))
    tags = Elements(render(text + "\n\n![private](http://192.168.1.1/image)")).elements
    assert len([tag for tag, _ in tags if tag == "img"]) == 8
    assert len([tag for tag, _ in tags if tag == "a"]) == 20


def test_closing_chat_before_image_response_does_not_touch_deleted_widgets(
    qtbot, public_images, monkeypatch
):
    from torrentlinker.gui.chat_transcript import MessageText

    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    original = PublicTransport.handle_request

    def delayed(self, request):
        entered.set()
        release.wait(5)
        try:
            return original(self, request)
        finally:
            done.set()

    monkeypatch.setattr(PublicTransport, "handle_request", delayed)
    widget = MessageText("![Cover](https://covers.example/delayed.png)")
    widget.show()
    try:
        qtbot.waitUntil(entered.is_set)
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        release.set()
    qtbot.waitUntil(done.is_set)
    qtbot.wait(50)


def test_documentation_links_only_open_bundled_guides():
    tags = Elements(
        render("[Guide](/documentation/guide/en/agents.md#connections)\n\n[bad](/api/logout)")
    ).elements
    assert [attrs["href"] for tag, attrs in tags if tag == "a"] == [
        "/documentation/guide/en/agents.md#connections"
    ]


@pytest.mark.skipif(os.environ.get("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
@pytest.mark.parametrize("root_path", ["", "/tl"])
def test_browser_cover_uses_authenticated_proxy_and_opens_original(
    tmp_path, public_images, root_path
):
    import uvicorn
    from fastapi import FastAPI
    from playwright.sync_api import expect, sync_playwright

    from tests.test_tool_activity import narrative_run

    app = create_app(tmp_path, password="test-password-long")
    if root_path:
        mounted = FastAPI()
        mounted.mount(root_path, app)
        app = mounted
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 560, "height": 760})
            errors, remote = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: (
                    remote.append(request.url)
                    if request.url.startswith("https://covers.example")
                    else None
                ),
            )
            page.goto(f"http://127.0.0.1:{port}{root_path}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#workspace")).to_be_visible()
            shell_navigate(page, "assistant")
            panel = page.frame_locator("#assistant-frame")
            panel.locator("#assistant-prompt").wait_for(state="attached")
            frame = next(f for f in page.frames if f.url.endswith("assistant/view.html"))
            frame.wait_for_function("typeof aMarkdown === 'function'")
            frame.evaluate(
                "html => document.body.append(aMarkdown({html}))",
                render("![Book cover](https://covers.example/cover.png)"),
            )
            image = panel.locator(".assistant-markdown img")
            expect(image).to_be_visible()
            frame.wait_for_function(
                "document.querySelector('.assistant-markdown img').naturalWidth === 480"
            )
            assert image.bounding_box()["height"] <= 360
            link = panel.locator(".assistant-markdown a")
            expect(link).to_have_attribute("href", "https://covers.example/cover.png")
            expect(link).to_have_attribute("target", "_blank")
            assert not errors and not remote
            panel.locator(".assistant-markdown").screenshot(path=str(tmp_path / "chat-cover.png"))
            frame.evaluate(
                "html => document.body.append(aMarkdown({html}))",
                render("![Unavailable cover](https://covers.example/html)"),
            )
            expect(panel.locator(".assistant-image-error")).to_be_visible()
            expect(panel.locator(".assistant-markdown a").last).to_have_attribute(
                "href", "https://covers.example/html"
            )
            run = narrative_run()
            frame.evaluate("run => document.body.append(aRunCard(run))", run)
            card = panel.locator(".assistant-run").last
            assert card.locator(":scope > *").evaluate_all(
                "nodes => nodes.map(n => n.className)"
            ) == [
                "assistant-message user",
                "assistant-message assistant",
                "assistant-activity",
                "assistant-message assistant",
            ]
            activity = card.locator(".assistant-activity")
            assert "read_documentation" not in activity.locator(":scope > summary").inner_text()
            assert activity.locator("pre").count() == 0
            activity.locator(":scope > summary").click()
            activity.locator(".assistant-tool > summary").click()
            expect(activity.locator(".assistant-json")).to_be_visible()
            assert activity.locator(".json-key").count() > 0
            frame.evaluate(
                "run => document.querySelector('.assistant-run').replaceWith(aRunCard(run))", run
            )
            expect(panel.locator(".assistant-tool .assistant-json")).to_be_visible()
            panel.locator(".assistant-run").screenshot(
                path=str(tmp_path / "chat-tool-activity.png")
            )
            failed = narrative_run()
            failed["id"] = "failed-tool"
            failed["events"][0]["status"] = "finished"
            error = "Choose an allowed client. <b>Literal error</b>"
            failed["events"][0]["result"] = {"job": {"status": "failed", "error": error}}
            frame.evaluate("run => document.body.append(aRunCard(run))", failed)
            failed_card = panel.locator(".assistant-run").last
            summary = failed_card.locator(".assistant-activity > summary")
            expect(failed_card.locator(".assistant-tool-error")).to_have_count(0)
            assert failed_card.locator(".assistant-tool-error b").count() == 0
            expect(summary).to_have_css("color", "rgb(180, 35, 50)")
            assert failed_card.locator("pre").count() == 0
            summary.click()
            expect(failed_card.locator(".assistant-tool > summary")).to_have_css(
                "color", "rgb(180, 35, 50)"
            )
            failed_card.locator(".assistant-tool > summary").click()
            expect(failed_card.locator(".assistant-tool-error")).to_have_text(error)
            expect(failed_card.locator(".assistant-tool-error")).to_be_visible()
            assert failed_card.locator(".assistant-tool-error b").count() == 0
            expect(failed_card.locator(".assistant-json")).to_be_visible()
            failed_card.screenshot(path=str(tmp_path / "chat-tool-error.png"))
            frame.evaluate(
                "html => document.body.append(aMarkdown({html}))",
                render("[Documentation](/documentation/guide/en/agents.md#connections)"),
            )
            citation = panel.get_by_role("link", name="Documentation", exact=True)
            assert citation.evaluate("link => new URL(link.href).pathname") == (
                root_path + "/documentation/guide/en/agents.md"
            )
            with page.expect_popup() as opened:
                citation.click()
            guide = opened.value
            guide.wait_for_load_state()
            assert guide.url.endswith("/documentation/guide/en/agents.md#connections")
            expect(guide.locator("h1")).to_be_visible()
            chats = [
                {"id": "film", "name": "Find a film", "folder": "film_research"},
                {"id": "upload", "name": "My upload", "folder": "uploads"},
            ]
            frame.evaluate(
                "chats => { const pane = document.createElement('aside'); "
                "pane.id = 'folder-demo'; document.body.append(pane); "
                "aConversationFolders(pane, chats); }",
                chats,
            )
            groups = panel.locator("#folder-demo .assistant-folder")
            expect(groups).to_have_count(2)
            expect(groups.nth(0).get_by_role("button", name="Find a film")).to_be_visible()
            groups.nth(0).locator("summary").click()
            expect(groups.nth(0).get_by_role("button", name="Find a film")).not_to_be_visible()
            chats[1]["name"] = "Upload ready"
            frame.evaluate(
                "chats => aConversationFolders(document.getElementById('folder-demo'), chats)",
                chats,
            )
            expect(groups.nth(0).get_by_role("button", name="Find a film")).not_to_be_visible()
            expect(groups.nth(1).get_by_role("button", name="Upload ready")).to_be_visible()
            identifier = frame.evaluate(
                """async () => {
                  const model = await api('setup/assistant/providers',
                    {name: 'Local', kind: 'ollama', model: 'test'});
                  const chat = await api('assistant/conversations',
                    {name: 'Film ideas', provider_id: model.id,
                     policy: {name: 'Read', clients: ['default']}});
                  assistantConversation = chat.id;
                  aMoveConversation(chat, [chat]);
                  return chat.id;
                }"""
            )
            dialog = panel.locator("dialog.assistant-dialog")
            dialog.locator("select").select_option("__new__")
            dialog.locator('input[type="text"]').fill("My films")
            expect(dialog.locator('input[type="checkbox"]')).not_to_be_checked()
            dialog.locator(".toolbar button").first.click()
            expect(dialog).not_to_be_visible()
            moved = frame.evaluate(
                "async id => (await api('assistant/conversations')).find(c => c.id === id)",
                identifier,
            )
            assert (moved["folder"], moved["folder_source"]) == ("My films", "manual")
            expect(panel.locator("#assistant-folders summary")).to_have_text("▱My films")
            frame.evaluate(
                """async id => {
                  await api(`assistant/conversations/${id}/folder`, {folder: '__new__'}, 'PUT');
                  const chats = await api('assistant/conversations');
                  aMoveConversation(chats.find(c => c.id === id), chats);
                }""",
                identifier,
            )
            expect(dialog.locator("select")).to_have_value("__new__")
            expect(dialog.locator('input[type="text"]')).not_to_be_visible()
            dialog.locator(".toolbar button").first.click()
            expect(dialog).not_to_be_visible()
            expect(panel.locator("#assistant-folders summary")).to_have_text("▱__new__")
            browser.close()
    finally:
        server.should_exit = True
        worker.join(5)
        listener.close()
