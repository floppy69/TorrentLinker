"""Actual Chromium extension and WebUI against an intercepted c411 fixture only."""

import os
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.shell_support import shell_navigate
from tests.test_community import H
from tests.test_profile import PROFILE
from tests.test_web_profile import prepared, snapshot

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


class Site:
    def __init__(self):
        self.posts = []
        self.counts = {"comment_post": 0, "trust_vote": 0, "shout_message": 0}
        self.user = "42"
        self.own_comment = False
        self.existing_vote = None
        self.quota = False
        self.lost = False
        self.throttle = False
        self.slow = False
        self.history = []

    def route(self, route):
        path = urlsplit(route.request.url).path
        if route.request.method == "POST":
            if self.throttle:
                route.fulfill(status=429, headers={"Retry-After": "120"}, json={})
                return
            self.posts.append((path, route.request.post_data_json))
            kind = (
                "comment_post"
                if path.endswith("/comments")
                else "trust_vote"
                if path.endswith("/trust-vote")
                else "shout_message"
            )
            self.counts[kind] += 1
            if self.lost:
                route.abort("failed")
                return
            if kind == "comment_post":
                route.fulfill(json={"comment": {"id": 501}})
            elif kind == "trust_vote":
                route.fulfill(json={"trust": {"score": 100, "status": "trusted"}})
            else:
                route.fulfill(json={"success": True, "messageId": 601})
        elif path == "/api/user/profile":
            route.fulfill(
                json={
                    **PROFILE,
                    "id": self.user,
                    "username": "Demo account",
                    "class": {"effectiveSlug": "swarm-keeper"},
                }
            )
        elif path == "/api/ic/actions-catalog":
            route.fulfill(
                json={
                    "entries": [
                        {
                            "actionType": kind,
                            "xp": 25,
                            "today": 5 if self.quota else used,
                            "dailyLimit": 5,
                            "cooldownSec": 30,
                            "lock": None,
                            "audience": "all",
                        }
                        for kind, used in self.counts.items()
                    ]
                }
            )
        elif path == "/api/profile/active-seeds":
            route.fulfill(
                json={"data": [{"infoHash": H, "name": "Example release"}], "meta": {"total": 1}}
            )
        elif path == "/api/messages/channels":
            route.fulfill(
                json={
                    "space": "public",
                    "data": [
                        {
                            "id": 1,
                            "name": "Général",
                            "isDefault": True,
                            "canWrite": True,
                            "classSlug": None,
                        },
                        {
                            "id": 135,
                            "name": "Swarm Keeper",
                            "canWrite": True,
                            "classSlug": "swarm_keeper",
                        },
                        {"id": 26, "name": "Aide", "canWrite": True, "classSlug": None},
                        {"id": 3, "name": "Annonces", "canWrite": False, "classSlug": None},
                    ],
                }
            )
        elif path.endswith("/slow-mode-status"):
            route.fulfill(
                json={"canSend": not self.slow, "remainingMs": 120000 if self.slow else 0}
            )
        elif path in ("/api/messages/channels/1", "/api/messages/channels/135"):
            route.fulfill(json={"data": self.history, "channel": {"id": 1}})
        elif path.endswith("/comments"):
            route.fulfill(
                json={
                    "data": [{"author": {"id": 42}, "content": "Already here"}]
                    if self.own_comment
                    else [],
                    "meta": {"page": 1, "totalPages": 1, "total": 0},
                }
            )
        elif path == "/api/torrents/" + H:
            route.fulfill(
                json={
                    "trust": {"canVote": True, "userVote": self.existing_vote},
                    "commentAccess": {"canComment": True},
                    "commentsLocked": False,
                }
            )
        elif path == "/api/profile/detailed-stats":
            route.fulfill(json={"stats": snapshot()["details"]})
        elif path == "/api/tokens/history":
            route.fulfill(json={"success": True, "history": [], "total": 0})
        else:
            route.fulfill(
                content_type="text/html",
                body='<meta name="csrf-token" content="fixture-token"><h1>Fixture c411</h1>',
            )


@pytest.fixture
def tab():
    from playwright.sync_api import sync_playwright

    from torrentlinker import companion

    source = (Path(companion.__file__).parent / "companion_extension/community.js").read_text()
    source = source.replace("export async function", "async function")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        site = Site()
        page.route("https://c411.org/**", site.route)
        page.goto("https://c411.org/")
        page.evaluate("() => {" + source + "; window.communityTest = communityInTab;}")
        yield page, site
        browser.close()


def invoke(page, kind="comment", subject=H):
    return page.evaluate(
        "request => window.communityTest(request)",
        {
            "accountId": "42",
            "command": {
                "id": "b" * 32,
                "attempt": "c" * 32,
                "accountId": "42",
                "kind": kind,
                "subject": subject,
                "limit": 5,
                "expires": time.time() + 90,
                "content": "Un message utile pour la communauté",
                "vote": "approve",
            },
        },
    )


def test_executor_collects_only_general_and_class_and_posts_comment_vote_chat(tab):
    page, site = tab
    result = page.evaluate(
        "request => window.communityTest(request)", {"accountId": "42", "page": 1}
    )
    assert [c["id"] for c in result["snapshot"]["channels"]] == [1, 135]
    for kind, subject in [("comment", H), ("vote", H), ("chat", "135")]:
        result = invoke(page, kind, subject)
        assert result["outcome"] == "posted", result
    assert len(site.posts) == 3
    assert site.posts[1][1] == {"vote": "approve", "reason": "Un message utile pour la communauté"}
    assert "fixture-token" not in str(result)


@pytest.mark.parametrize(
    "block", ["quota", "own_comment", "account", "vote", "chat", "slow", "throttle"]
)
def test_executor_refuses_or_defers_without_posting(tab, block):
    page, site = tab
    kind, subject = "comment", H
    if block == "account":
        site.user = "other"
    elif block == "vote":
        site.existing_vote = 1
        kind = "vote"
    elif block in ("chat", "slow"):
        kind, subject = "chat", "1"
        site.slow = block == "slow"
        if block == "chat":
            site.history = [
                {"sender": {"id": 42}, "content": "Un message utile pour la communauté"}
            ]
    else:
        setattr(site, block, True)
    result = invoke(page, kind, subject)
    assert result["outcome"] in ("refused", "deferred"), result
    assert not site.posts


def test_executor_lost_response_is_uncertain(tab):
    page, site = tab
    site.lost = True
    result = invoke(page)
    assert result["outcome"] == "uncertain"
    assert len(site.posts) == 1


def test_webui_to_real_extension_and_durable_receipt(tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker import companion

    (tmp_path / "server").mkdir()
    app, setup = prepared(tmp_path / "server", monkeypatch)
    w = setup.profile_workspace()
    w.refresh(setup.settings.indexer.url, "fake-key")
    # Keep wall-clock progression during browser setup; only offset cooldowns.
    # A frozen clock can fall behind a minute-rounded UI due time in slow CI.
    clock = [0.0]
    w.clock = lambda: time.time() + clock[0]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    extension = Path(companion.__file__).parent / "companion_extension"
    site = Site()
    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(tmp_path / "browser"),
                channel="chromium",
                headless=True,
                viewport={"width": 1280, "height": 1000},
                args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
            )
            context.route("https://c411.org/**", site.route)
            tracker = context.new_page()
            tracker.goto("https://c411.org/")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_navigate(page, "setup")
            settings = page.frame_locator("#settings-frame")
            settings.get_by_role("button", name="Companion", exact=True).click()
            settings.get_by_role("button", name="Connect companion", exact=True).click()
            for _ in range(100):
                if w.state()["paired"]:
                    break
                page.wait_for_timeout(100)
            assert w.state()["paired"]
            worker = context.service_workers[0]
            shell_navigate(page, "zen")
            page.locator("#zen-community-tab").click()
            ui = page.frame_locator("#community-frame")
            expect(ui.locator("#community-library")).to_be_visible()
            expect(ui.locator("body")).to_have_css("padding-right", "16px")
            assert page.locator("#community-frame").evaluate(
                "el => el.getBoundingClientRect().bottom <= innerHeight - 16"
            )

            expect(ui.locator(".tabs button")).to_have_count(4)
            worker.evaluate("chrome.alarms.create('companion-commands', {delayInMinutes: 0.001})")
            expect(ui.locator(".torrent")).to_have_count(1, timeout=15000)
            ui.get_by_role("button", name="Community settings", exact=True).click()
            expect(
                ui.get_by_text("Daily quotas reset at midnight, Europe/Paris time.", exact=False)
            ).to_be_visible()
            ui.locator("#community-enabled").check()
            ui.get_by_role("button", name="Save settings", exact=True).click()
            expect(ui.locator("#drawer")).not_to_be_visible()
            ui.locator("#community-content").fill("Merci pour ce partage bien utile  \n")
            ui.get_by_role("button", name="Schedule", exact=True).click()
            expect(ui.locator(".tl-toast", has_text="Action scheduled").first).to_be_visible()
            # Fail the first receipt ACK, after the app already committed it.
            original = w.community.receipt
            failures = [1]

            def receipt(account, body):
                original(account, body)
                if failures[0]:
                    failures[0] -= 1
                    raise ValueError("Simulated lost acknowledgement")

            monkeypatch.setattr(w.community, "receipt", receipt)
            worker.evaluate("chrome.alarms.create('companion-commands', {delayInMinutes: 0.001})")
            ui.locator(".tabs [data-tab=history]").click()
            expect(ui.locator("#community-history-results")).to_contain_text(
                "Posted", timeout=20000
            )
            assert len(site.posts) == 1
            stored = worker.evaluate("chrome.storage.local.get('communityReceipts')")
            assert stored["communityReceipts"]
            # Restart the actual browser while the receipt is unacknowledged.
            context.close()
            context = pw.chromium.launch_persistent_context(
                str(tmp_path / "browser"),
                channel="chromium",
                headless=True,
                viewport={"width": 1280, "height": 1000},
                args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
            )
            context.route("https://c411.org/**", site.route)
            tracker = context.new_page()
            tracker.goto("https://c411.org/")
            worker = (
                context.service_workers[0]
                if context.service_workers
                else context.wait_for_event("serviceworker")
            )
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/#/zen/community")
            ui = page.frame_locator("#community-frame")
            expect(ui.locator("#community-library")).to_be_visible()
            worker.evaluate("chrome.alarms.create('companion-commands', {delayInMinutes: 0.001})")
            for _ in range(100):
                stored = worker.evaluate("chrome.storage.local.get('communityReceipts')")
                if not stored.get("communityReceipts"):
                    break
                page.wait_for_timeout(100)
            assert not stored.get("communityReceipts")
            assert len(site.posts) == 1
            for kind, subject in [("vote", H), ("chat", "135")]:
                clock[0] += 61
                ui.locator("[data-tab=" + ("chat" if kind == "chat" else "torrents") + "]").click()
                if kind == "chat":
                    expect(ui.locator("[data-command=channel]")).to_have_count(2)
                    expect(ui.locator("#community-suggestion option")).to_have_count(201)
                    ui.locator(f'[data-channel="{subject}"]').click()
                    ui.locator("#community-suggestion").select_option(index=1)
                else:
                    ui.locator("[data-kind=vote]").click()
                    ui.locator("#community-vote").select_option("approve")
                ui.get_by_role("button", name="Schedule", exact=True).click()
                expect(ui.locator(".tl-toast", has_text="Action scheduled").first).to_be_visible()
                worker.evaluate(
                    "chrome.alarms.create('companion-commands', {delayInMinutes: 0.001})"
                )
                ui.locator(".tabs [data-tab=history]").click()
                expect(ui.locator("#community-history-results .pill.green")).to_have_count(
                    2 if kind == "vote" else 3, timeout=20000
                )
            assert len(site.posts) == 3
            assert site.posts[-1][0] == "/api/messages/channels/135/messages"
            assert not errors, errors
            target = Path(os.getenv("TL_COMMUNITY_SCREENSHOTS", str(tmp_path)))
            target.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target / "tl-community-web.png"), full_page=True)
            # Language changes preserve the owner's unsaved draft.
            ui.locator("[data-tab=chat]").click()
            ui.locator("#chat-content").fill("Un brouillon à conserver sans aucune modification")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(ui.get_by_role("button", name="Brouillon", exact=True)).to_be_visible()
            expect(ui.locator("#chat-content")).to_have_value(
                "Un brouillon à conserver sans aucune modification"
            )
            ui.locator(".tabs [data-tab=history]").click()
            ui.locator("#community-history-results button").filter(
                has_text="Merci pour ce partage"
            ).click()
            expect(ui.locator("#drawer")).to_contain_text("XP en attente, 24 h")
            ui.get_by_role("button", name="Fermer", exact=True).click()
            page.set_viewport_size({"width": 600, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert ui.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
            page.screenshot(path=str(target / "tl-community-web-fr.png"), full_page=True)
            # The new controls persist their configuration and plan without posting.
            from tests.test_community import observation

            w.community.observe(
                "42",
                {**observation(), "candidates": [{"hash": "d" * 40, "title": "Future release"}]},
            )
            page.set_viewport_size({"width": 1280, "height": 1000})
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            ui.get_by_role("button", name="Community settings", exact=True).click()
            ui.locator("#community-enabled").uncheck()
            ui.get_by_role("button", name="Save settings", exact=True).click()
            expect(ui.locator("#drawer")).not_to_be_visible()
            ui.get_by_role("button", name="Automatic mode", exact=True).click()
            ui.locator("#community-auto-enabled").check()
            ui.locator("#community-auto-comment").check()
            ui.locator("#auto-template").fill("Merci pour le partage de {titre}")
            ui.get_by_role("button", name="Apply to calendar", exact=True).click()
            # A Sunday run can schedule the next available slot in the following week.
            for _ in range(4):
                if "Future release" in ui.locator("#community-calendar").inner_text():
                    break
                ui.get_by_role("button", name="Next period", exact=True).click()
            expect(ui.locator("#community-calendar")).to_contain_text("Future release")
            expect(ui.locator(".calendar-cell")).to_have_count(7)
            ui.get_by_role("button", name="Month", exact=True).click()
            assert ui.locator(".calendar-cell").count() in (28, 35, 42)
            ui.locator(".calendar-event").filter(has_text="Future release").click()
            expect(ui.locator("#drawer")).to_contain_text("Merci pour le partage de Future release")
            # Turning on automatic mode also runs the queue it fills.
            expect(ui.locator(".paused-notice")).to_have_count(0)
            ui.get_by_role("button", name="Close", exact=True).click()
            ui.get_by_role("button", name="Community settings", exact=True).click()
            ui.locator("#community-enabled").uncheck()
            ui.get_by_role("button", name="Save settings", exact=True).click()
            expect(ui.get_by_role("button", name="Auto · paused", exact=True)).to_be_visible()
            ui.locator(".calendar-event").filter(has_text="Future release").click()
            expect(ui.locator(".paused-notice")).to_contain_text("Sending paused")
            ui.get_by_role("button", name="Resume sending").click()
            expect(ui.locator("#drawer")).not_to_be_visible()
            page.reload()
            ui.get_by_role("button", name="Auto · active", exact=True).click()
            expect(ui.locator("#community-auto-comment")).to_be_checked()
            ui.get_by_role("button", name="Close", exact=True).click()
            ui.locator(".tabs [data-tab=history]").click()
            ui.locator("#community-history-search").fill("Future release")
            ui.locator("#community-history-kind").select_option("comment")
            ui.locator("[data-period=custom]").click()
            ui.locator("#community-history-from").fill("2000-01-01")
            ui.locator("#community-history-to").fill("2000-01-02")
            expect(ui.locator(".history-summary")).to_contain_text("0 operations")
            ui.locator("[data-period=all]").click()
            expect(ui.locator("#community-history-results")).to_contain_text("Future release")
            # The approved narrow layout opens the selected torrent in a drawer.
            page.set_viewport_size({"width": 600, "height": 900})
            ui.locator("[data-tab=torrents]").click()
            ui.locator(".torrent").filter(has_text="Future release").click()
            expect(ui.locator("#drawer")).to_be_visible()
            expect(ui.locator("#drawer")).to_contain_text("Future release")
            ui.get_by_role("button", name="Close", exact=True).click()
            page.set_viewport_size({"width": 1280, "height": 1000})
            ui.locator(".tabs [data-tab=history]").click()
            with page.expect_download() as downloaded:
                ui.get_by_role("button", name="Export", exact=True).click()
            assert "Future release" in Path(downloaded.value.path()).read_text(encoding="utf-8-sig")
            assert len(site.posts) == 3
            assert not errors, errors
            ui.locator("[data-tab=queue]").click()
            page.screenshot(path=str(target / "tl-community-calendar-built.png"), full_page=True)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("dark")
            expect(ui.locator("html")).to_have_attribute("data-theme", "dark")
            ui.locator("[data-tab=torrents]").click()
            page.screenshot(path=str(target / "tl-community-library-final.png"), full_page=True)
            # A response from before logout must not restore the old account.
            delayed = []
            snapshot = w.community_state()
            page.route("**/api/community", lambda route: delayed.append(route))
            for _ in range(50):
                if delayed:
                    break
                page.wait_for_timeout(100)
            assert delayed
            page.frame_locator("#shell-navigation-frame").locator("#logout").click()
            expect(page.locator("#login-screen")).to_be_visible()
            for route in delayed:
                route.fulfill(json=snapshot)
            expect(ui.locator(".torrent")).to_have_count(0)
            expect(ui.locator(".tabs")).to_have_count(0)
            context.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
