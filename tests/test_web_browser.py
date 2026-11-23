"""Opt-in real-browser tests against a temporary server and fake Torrent Client."""

import json
import os
import re
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.shell_support import (
    shell_close_drawer,
    shell_navigate,
    shell_open_navigation,
)

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_guided_setup_and_management_on_small_screen(tmp_path: Path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.client_folders import ClientFolder
    from torrentlinker.domain import Torrent
    from torrentlinker.web.app import create_app

    class Client:
        def __init__(self):
            self.paused = False
            self.wanted = True

        def check(self):
            return "qBittorrent test"

        def folder_settings(self):
            return [ClientFolder("", "/downloads", "default")]

        def torrents(self, **kwargs):
            return [
                Torrent(
                    "a" * 40,
                    "Example book.epub",
                    Path("/downloads"),
                    size=1048576,
                    state="pausedUP" if self.paused else "uploading",
                    connected_seeds=3,
                    connected_peers=2,
                    swarm_seeders=42,
                    swarm_peers=13,
                )
            ]

        def torrent(self, hash, **kwargs):
            return self.torrents()[0]

        def file_listing(self, hash):
            from torrentlinker.domain import TorrentFile

            return [TorrentFile(0, "Example book.epub", 1048576, self.wanted)]

        def set_file_priority(self, hash, indexes, priority):
            assert hash == "a" * 40
            assert indexes == [0]
            self.wanted = priority > 0

        def pause(self, hash):
            self.paused = True

    client = Client()
    app = create_app(
        tmp_path / "config", password="test-password-long", connector=lambda *args: client
    )
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
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1100, "height": 850}, locale="en-US")
            page.route(
                "**/api/shell",
                lambda route: route.fulfill(
                    json={
                        "version": "1.0.0",
                        "release": {
                            "tag": "v1.1.0",
                            "url": "https://github.com/Vietnoirien/TorrentLinker/releases/tag/v1.1.0",
                        },
                    }
                ),
            )
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            expect(page.locator("#view-setup")).to_be_visible()
            navigation = page.frame_locator("#shell-navigation-frame")
            update = page.frame_locator("#shell-update-frame")
            expect(update.locator("#update-message")).to_contain_text("Web server installation")
            navigation.locator("#shortcuts").click()
            help_panel = page.frame_locator("#shell-help-frame")
            expect(help_panel.locator("#help-text")).to_contain_text("remain with the browser")
            help_panel.locator("#help-close").click()
            update.locator("#dismiss").click()
            expect(page.locator("#shell-update-host")).to_be_hidden()
            settings = page.frame_locator("#settings-frame")
            for label in ("Password", "Client API key", "Proxy password", "Announce URL"):
                expect(settings.get_by_label(label, exact=True)).to_have_value("")
            settings.get_by_label("Address", exact=True).fill(
                "https://seedbox.example/qbittorrent/"
            )
            settings.get_by_label("Username", exact=True).fill("reader")
            settings.get_by_label("Password", exact=True).fill("client-password")
            settings.get_by_role("button", name="Test connection", exact=True).click()
            expect(settings.locator(".tl-toast.ok")).to_contain_text("qBittorrent test")
            screenshot = os.getenv("TL_WEB_SCREENSHOTS")
            if screenshot:
                Path(screenshot).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshot) / "setup-en.png"))
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "fr"
                )
                page.screenshot(path=str(Path(screenshot) / "setup-fr.png"))
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "en"
                )
            settings.get_by_role("button", name="Save", exact=True).click()
            expect(settings.locator("#settings-status")).to_contain_text("Settings saved")
            settings.get_by_role("button", name="Download Folders", exact=True).click()
            settings.get_by_role("button", name="Read folders from client", exact=True).click()
            expect(settings.locator(".settings-form")).to_contain_text("/downloads")
            shell_navigate(page, "library")
            band = page.frame_locator("#shell-band-frame")
            expect(page.locator("#shell-band-host")).to_be_visible()
            expect(band.locator("#seeding")).not_to_contain_text("—")
            expect(band.locator("#catalogue")).to_contain_text("torrents")
            shell_navigate(page, "torrents")
            torrents = page.frame_locator("#torrents-frame")
            expect(torrents.locator("tbody")).to_contain_text("Example book.epub")
            expect(torrents.locator("#inspector")).to_contain_text("3 (42) / 2 (13)")
            expect(torrents.locator("[data-action=pause]")).to_be_disabled()
            torrents.locator("tbody input").check()
            torrents.locator("[data-tab=files]").click()
            expect(torrents.locator(".files")).to_contain_text("Example book.epub")
            file_choice = torrents.locator("[data-file]")
            file_choice.select_option("skip_files")
            expect(torrents.locator("#dialog li")).to_contain_text("Example book.epub")
            torrents.locator("#cancel").click()
            expect(file_choice).to_have_value("want_files", timeout=500)
            file_choice.select_option("skip_files")
            torrents.locator("#confirm").click()
            expect(file_choice).to_have_value("skip_files")
            file_choice.select_option("want_files")
            torrents.locator("#confirm").click()
            expect(file_choice).to_have_value("want_files")
            torrents.locator("[data-tab=summary]").click()
            torrents.locator("tbody input").check()
            torrents.locator("[data-action=pause]").click()
            torrents.locator("#confirm").click()
            expect(torrents.locator("tbody")).to_contain_text("Paused", timeout=10000)
            # Assistant writes use a separate connection while this view stays open.
            from torrentlinker.download_queue import enqueue, entries
            from torrentlinker.indexer import Candidate, Indexer
            from torrentlinker.store import Store

            writer = Store(tmp_path / "config" / "catalogue.sqlite")
            indexer = Indexer("https://example.test/api", "key")
            candidate = Candidate(
                "Assistant queue entry", 1024, "https://example.test/a", 2, "b" * 40
            )
            shell_navigate(page, "queue")
            queue = page.frame_locator("#search-frame")
            enqueue(writer, indexer, candidate, tmp_path)
            expect(queue.locator("#queue-table")).to_contain_text(candidate.title, timeout=6000)
            checkbox = queue.locator("#queue-table tbody input[type=checkbox]")
            checkbox.check()
            writer.download_outcome(entries(writer)[0].key, "sent")
            expect(queue.locator("#queue-table")).to_contain_text("Sent", timeout=6000)
            expect(checkbox).to_be_checked()
            expect(queue.locator("#queue-summary")).to_contain_text("1 total · 0 waiting · 1 sent")
            expect(queue.locator("#start-queue")).to_be_disabled()
            queue.locator("#queue-table tbody tr").click(button="right")
            expect(queue.locator("#queue-menu")).to_be_visible()
            expect(
                queue.locator("#queue-menu").get_by_role("menuitem", name="Retry selected")
            ).to_be_disabled()
            if screenshot:
                page.screenshot(path=str(Path(screenshot) / "queue-web-context-menu.png"))
            page.keyboard.press("Escape")
            expect(queue.locator("#queue-menu")).to_be_hidden()
            checkbox.focus()
            page.keyboard.press("Shift+F10")
            expect(queue.locator("#queue-menu")).to_be_visible()
            queue.locator("#queue-menu").get_by_role("menuitem", name="Remove selected").click()
            expect(queue.locator("#queue-summary")).to_contain_text("0 total")
            expect(queue.locator("#remove-queue")).to_be_disabled()
            assert entries(writer) == []
            # An ambiguous handoff requires checking the client, not a direct retry.
            source = tmp_path / "preserved-source.bin"
            source.write_bytes(b"Keep the source files")
            enqueue(writer, indexer, candidate, tmp_path)
            uncertain = entries(writer)[0]
            writer.download_outcome(uncertain.key, "uncertain", "Interrupted send")
            expect(queue.locator("#queue-table")).to_contain_text("Check client", timeout=6000)
            expect(queue.locator("#queue-table")).to_contain_text(
                "Check the client before removing and queueing again."
            )
            checkbox.check()
            expect(queue.locator("#retry-queue")).to_be_disabled()
            expect(queue.locator("#start-queue")).to_be_disabled()
            jobs_before = page.evaluate("async () => await api('jobs')")
            queue.locator("#remove-queue").click()
            expect(queue.locator("#queue-summary")).to_contain_text("0 total")
            assert entries(writer) == []
            assert page.evaluate("async () => await api('jobs')") == jobs_before
            assert source.read_bytes() == b"Keep the source files"
            # A real queue send removes its row and the open browser follows automatically.
            import httpx

            from tests.fake_qbit import FakeQbit
            from tests.test_download_queue import process
            from tests.test_send import release
            from torrentlinker.torrent_meta import read_torrent

            data = release(tmp_path, "Queue completion")
            meta = read_torrent(data)
            sender = Indexer(
                "https://example.test/api",
                "key",
                http=httpx.Client(
                    transport=httpx.MockTransport(lambda request: httpx.Response(200, content=data))
                ),
            )
            sent = Candidate(
                meta.name,
                sum(meta.files.values()),
                "https://example.test/download",
                infohash=meta.infohash,
            )
            destination = tmp_path / "queue-downloads"
            destination.mkdir()
            enqueue(writer, sender, sent, destination)
            expect(queue.locator("#queue-table")).to_contain_text(sent.title, timeout=6000)
            process(writer, sender, FakeQbit())
            expect(queue.locator("#queue-summary")).to_contain_text("0 total", timeout=6000)
            expect(queue.locator("#queue-table tbody tr[data-key]")).to_have_count(0)
            expect(queue.locator("#start-queue")).to_be_disabled()
            shell_navigate(page, "torrents")
            if screenshot:
                for lang in ("fr", "en"):
                    page.frame_locator("#shell-navigation-frame").locator(
                        "#language"
                    ).select_option(lang)
                    page.screenshot(path=str(Path(screenshot) / f"torrents-{lang}.png"))
            shell_navigate(page, "documentation")
            guide = page.frame_locator("#documentation-frame")
            expect(guide.locator("#guide-content")).to_contain_text("Read guides inside the app")
            guide.locator('[data-guide-path="guide/en/torrents.md"]').click()
            expect(guide.locator("#guide-content h1")).to_have_text("Manage torrents")
            expect(guide.locator("#guide-content img").first).to_have_js_property("complete", True)
            assert guide.locator("#guide-content img").first.evaluate("i=>i.naturalWidth>0")
            if screenshot:
                page.screenshot(path=str(Path(screenshot) / "documentation-en.png"))
            guide.locator("#guide-back").click()
            expect(guide.locator("#guide-content")).to_contain_text("Read guides inside the app")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            guide.locator("#guide-language").select_option("fr")
            expect(guide.locator("#guide-content")).to_contain_text("Consulter les guides")
            if screenshot:
                guide.locator('[data-guide-path="guide/fr/torrents.md"]').click()
                expect(guide.locator("#guide-content h1")).to_have_text("Gérer les torrents")
                expect(guide.locator("#guide-content img").first).to_have_js_property(
                    "complete", True
                )
                assert guide.locator("#guide-content img").first.evaluate("i=>i.naturalWidth>0")
                page.screenshot(path=str(Path(screenshot) / "documentation-fr.png"))
            page.set_viewport_size({"width": 390, "height": 800})
            # A phone keeps one Navigation control: the drawer is closed until its toggle opens it.
            expect(page.locator("#app-sidebar")).to_be_hidden()
            page.locator("#navigation-toggle").click()
            expect(navigation.locator("#pages")).to_be_visible()
            expect(navigation.locator("#page-select")).to_be_hidden()
            expect(navigation.locator("#theme")).to_be_visible()
            header = page.frame_locator("#shell-header-frame")
            expect(header.locator("#target-client")).to_be_visible()
            assert header.locator("#target-client").evaluate(
                "el => el.getBoundingClientRect().right <= innerWidth"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_close_drawer(page)
            shell_navigate(page, "torrents")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("dark")
            shell_close_drawer(page)
            if screenshot:
                page.wait_for_timeout(250)
                page.screenshot(path=str(Path(screenshot) / "torrents-small.png"))
            shell_navigate(page, "setup")
            settings.get_by_role("button", name="Connections", exact=True).click()
            password = settings.get_by_label("Password", exact=True)
            expect(password).to_have_value("••••••••")
            pending_proxy = []

            def delay_proxy_save(route):
                pending_proxy.append((route, route.fetch()))

            page.route("**/api/settings/connections", delay_proxy_save)
            settings.get_by_role("button", name="Save", exact=True).click()
            for _ in range(50):
                if pending_proxy:
                    break
                page.wait_for_timeout(20)
            assert pending_proxy
            proxy = settings.get_by_label("Proxy password", exact=True)
            proxy.fill("test-proxy-secret")
            pending_proxy[0][0].fulfill(response=pending_proxy[0][1])
            expect(settings.locator("#settings-status")).to_contain_text("Settings saved")
            expect(proxy).to_have_value("test-proxy-secret")
            page.unroute("**/api/settings/connections", delay_proxy_save)
            settings.get_by_role("button", name="Save", exact=True).click()
            expect(proxy).to_have_value("••••••••")
            announce = settings.get_by_label("Announce URL", exact=True)
            announce.fill("https://tracker.example/announce/test-secret")
            settings.get_by_role("button", name="Save", exact=True).click()
            expect(announce).to_have_value("••••••••")
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            shell_close_drawer(page)
            expect(settings.get_by_label("Mot de passe", exact=True)).to_have_value("••••••••")
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_close_drawer(page)
            settings.get_by_role("button", name="Clients", exact=True).click()
            settings.get_by_label("New client name", exact=True).fill("Unsubmitted client")
            shell_navigate(page, "torrents")
            shell_navigate(page, "setup")
            settings.get_by_role("button", name="Connections", exact=True).click()
            settings.get_by_label("Client name", exact=True).fill("Seedbox renamed")
            settings.get_by_role("button", name="Save", exact=True).click()
            expect(
                page.frame_locator("#shell-header-frame").locator("#target-client option")
            ).to_have_count(1)
            expect(
                page.frame_locator("#shell-header-frame").locator("#target-client option:checked")
            ).to_have_text("Seedbox renamed")
            settings.get_by_role("button", name="Clients", exact=True).click()
            settings.get_by_label("New client name", exact=True).fill("Remote Deluge")
            settings.get_by_role("button", name="Add client", exact=True).click()
            settings.locator(".client-card").filter(has_text="Remote Deluge").get_by_role(
                "button", name="Edit settings", exact=True
            ).click()
            expect(settings.get_by_label("Password", exact=True)).to_have_value("")
            settings.get_by_label("Client type", exact=True).select_option("deluge")
            settings.get_by_label("Address", exact=True).fill("https://other-seedbox.example")
            settings.get_by_label("Password", exact=True).fill("second-password")
            settings.get_by_role("button", name="Save", exact=True).click()
            expect(settings.locator("#settings-status")).to_contain_text("Settings saved")
            expect(
                page.frame_locator("#shell-header-frame").locator("#target-client option:checked")
            ).to_have_text("Remote Deluge")
            page.frame_locator("#shell-header-frame").locator("#target-client").select_option(
                "default"
            )
            expect(settings.get_by_label("Client type", exact=True)).to_have_value("qbittorrent")
            expect(settings.get_by_label("Address", exact=True)).to_have_value(
                "https://seedbox.example/qbittorrent"
            )
            shell_navigate(page, "torrents")
            page.frame_locator("#shell-header-frame").locator("#target-client").select_option("all")
            expect(page.locator("#view-torrents")).to_be_visible()
            expect(page.frame_locator("#torrents-frame").locator("tbody")).to_contain_text(
                "Remote Deluge"
            )
            shell_navigate(page, "zen")
            expect(
                page.frame_locator("#shell-header-frame").locator("#target-client")
            ).to_have_value("default")
            expect(page.locator("#zen-profile-panel")).to_be_visible()
            page.locator("#zen-seeding-tab").click()
            expect(page.locator("#zen-seeding-panel")).to_be_visible()
            page.locator("#zen-plan-tab").click()
            expect(page.frame_locator("#plan-frame").locator("#plan-clients")).to_contain_text(
                "Remote Deluge"
            )
            if screenshot:
                page.set_viewport_size({"width": 1100, "height": 850})
                expect(page.frame_locator("#plan-frame").locator("#plan-clients")).to_be_visible()
                for language in ("en", "fr"):
                    page.frame_locator("#shell-navigation-frame").locator(
                        "#language"
                    ).select_option(language)
                    page.screenshot(path=str(Path(screenshot) / f"multi-clients-{language}.png"))
            shell_navigate(page, "setup")
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_close_drawer(page)
            settings.get_by_role("button", name="Agent access", exact=True).click()
            expect(settings.locator("#view-agents")).to_be_visible()
            expect(settings.locator("#agents-enabled")).not_to_be_checked()
            settings.locator("#agents-enabled").check()
            expect(page.locator("#view-setup")).to_be_visible()
            expect(page.frame_locator("#shell-header-frame").locator("#page-title")).to_have_text(
                "Settings"
            )
            expect(settings.locator("#agent-connections")).to_contain_text("No connections yet")
            settings.locator("[data-agent-tab=new]").click()
            settings.locator("#agent-name").fill("My assistant")
            expect(settings.locator("#agent-mode")).to_have_value("propose")
            settings.locator("#agent-form button.primary").click()
            expect(settings.locator("#agent-token-box")).to_be_visible()
            token = settings.locator("#agent-token").input_value()
            with page.expect_download() as download:
                settings.locator("#agent-token-save").click()
            assert download.value.suggested_filename == "torrentlinker-token.txt"
            assert Path(download.value.path()).read_text() == token + "\n"
            settings.locator("[data-agent-tab=connections]").click()
            expect(settings.locator("#agent-token")).to_have_value("")
            expect(settings.locator("#agent-token-box")).to_be_hidden()
            expect(settings.locator("#agent-connections")).to_contain_text("My assistant")
            expect(settings.locator("#agent-connections")).to_contain_text("Proposals only")
            expect(settings.locator("#agent-connections")).to_contain_text("Seedbox renamed")
            expect(settings.locator("#agent-connections")).to_contain_text("10 GiB")
            expect(settings.locator("#agent-connections")).to_contain_text("None")
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            shell_close_drawer(page)
            expect(settings.locator("#agent-connections")).to_contain_text(
                "Propositions uniquement"
            )
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_close_drawer(page)
            settings.locator("[data-agent-tab=new]").click()
            expect(settings.locator("#agent-token")).to_have_value("")
            settings.locator("#agent-name").fill("Upload helper")
            settings.locator("#agent-mode").select_option("execute")
            settings.locator("#agent-permissions input[value=uploads]").check()
            settings.locator("#agent-form button.primary").click()
            expect(settings.locator("#agent-token-box")).to_be_visible()
            settings.get_by_role("button", name="General", exact=True).click()
            expect(settings.get_by_label("Media interface", exact=True)).to_be_visible()
            expect(
                settings.get_by_role("button", name=re.compile("Export.*diagnostic"))
            ).to_have_text("Export diagnostics…")
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            shell_close_drawer(page)
            expect(
                settings.get_by_role("button", name=re.compile("Export.*diagnostic"))
            ).to_have_text("Exporter le diagnostic…")
            with page.expect_download() as diagnostic_download:
                settings.get_by_role("button", name=re.compile("Export.*diagnostic")).click()
            assert diagnostic_download.value.suggested_filename == "torrentlinker-diagnostics.json"
            support = json.loads(Path(diagnostic_download.value.path()).read_text())
            assert support["schema_version"] == 1
            assert token not in json.dumps(support)
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_close_drawer(page)
            settings.get_by_role("button", name="Agent access", exact=True).click()
            expect(settings.locator("#agent-token")).to_have_value("")
            settings.locator("[data-agent-tab=connections]").click()
            expect(settings.locator("#agent-connections")).to_contain_text(
                "Upload drafts and seeding"
            )
            settings.locator("#agent-connections .card").filter(
                has_text="My assistant"
            ).get_by_role("button").click()
            expect(settings.locator("#agent-connections")).to_contain_text("Revoked")
            expect(settings.locator("#agent-connections").get_by_role("button")).to_have_count(1)
            for width in (600, 390):
                page.set_viewport_size({"width": width, "height": 850})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            if screenshot:
                page.screenshot(
                    path=str(Path(screenshot) / "agent-settings-mobile.png"), full_page=True
                )
                page.set_viewport_size({"width": 1440, "height": 1000})
                for language in ("en", "fr"):
                    page.frame_locator("#shell-navigation-frame").locator(
                        "#language"
                    ).select_option(language)
                    expect(settings.locator("#agent-connections")).to_contain_text(
                        "Revoked" if language == "en" else "Révoquée"
                    )
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(
                        path=str(Path(screenshot) / f"agent-access-{language}.png"), full_page=True
                    )
                shell_open_navigation(page)
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    "en"
                )
                shell_close_drawer(page)
                shell_open_navigation(page)
                page.frame_locator("#shell-navigation-frame").locator("#theme").select_option(
                    "light"
                )
                shell_close_drawer(page)
                page.screenshot(
                    path=str(Path(screenshot) / "agent-settings-light.png"), full_page=True
                )
                settings.locator("[data-agent-tab=new]").click()
                page.screenshot(
                    path=str(Path(screenshot) / "agent-settings-new.png"), full_page=True
                )
                settings.locator("[data-agent-tab=activity]").click()
                page.screenshot(
                    path=str(Path(screenshot) / "agent-settings-activity.png"), full_page=True
                )
            # A late create response must not restore a token after leaving its panel.
            settings.locator("[data-agent-tab=new]").click()
            settings.locator("#agent-name").fill("Delayed connection")
            pending = []

            def delay_creation(route):
                if route.request.method == "POST":
                    pending.append((route, route.fetch()))
                else:
                    route.continue_()

            page.route("**/api/agents", delay_creation)
            settings.locator("#agent-form button.primary").click()
            for _ in range(50):
                if pending:
                    break
                page.wait_for_timeout(20)
            assert pending
            settings.locator("[data-agent-tab=connections]").click()
            pending[0][0].fulfill(response=pending[0][1])
            expect(settings.locator(".tl-toast", has_text="token was dismissed")).to_be_visible()
            settings.locator("[data-agent-tab=new]").click()
            expect(settings.locator("#agent-token")).to_have_value("")
            expect(settings.locator("#agent-token-box")).to_be_hidden()
            page.unroute("**/api/agents", delay_creation)
            # A persistent tab button may keep focus without blocking background refresh.
            settings.locator("[data-agent-tab=connections]").click()
            created_elsewhere = page.request.post(
                f"http://127.0.0.1:{port}/api/agents",
                headers={"X-TorrentLinker": "1"},
                data={"name": "Another window", "clients": ["default"]},
            )
            assert created_elsewhere.ok
            expect(settings.locator("#agent-connections")).to_contain_text(
                "Another window", timeout=7000
            )
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.mark.parametrize("viewport", [(1000, 780), (1280, 600), (390, 844)])
def test_local_upload_queue_review_edit_and_explicit_send(tmp_path, monkeypatch, qapp, viewport):
    import httpx
    import uvicorn
    from fastapi.testclient import TestClient
    from playwright.sync_api import expect, sync_playwright

    from tests.test_upload_completeness import complete_description
    from tests.test_upload_queue import UploadClient
    from tests.test_web_jobs import finished, login
    from torrentlinker.web.app import create_app

    posted = []

    def response(request):
        if request.method == "POST":
            posted.append(request)
            return httpx.Response(200, json={"data": {"id": 321}})
        if request.url.params.get("t") == "caps":
            return httpx.Response(200, text="<caps><categories/></caps>")
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        "torrentlinker.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(response)),
    )
    root = tmp_path / "models"
    root.mkdir()
    item = root / "Cable holder.stl"
    item.write_text("solid model\nendsolid model\n")

    def application():
        return create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: UploadClient(),
        )

    with TestClient(application()) as owner:
        login(owner)
        owner.post(
            "/api/setup/client", json={"client": "qbittorrent", "host": "https://client.example"}
        )
        owner.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/models", "kind": "3d-model"},
        )
        owner.post(
            "/api/setup/indexer",
            json={"url": "https://c411.org/api/torznab", "api_key": "fake-key"},
        )
        owner.post("/api/setup/announce", json={"value": "https://c411.org/announce/fake"})
        scan = owner.post("/api/jobs", json={"kind": "scan"}).json()
        assert finished(owner, scan["id"])["status"] == "completed"
        saved = owner.post(
            "/api/jobs",
            json={
                "kind": "upload-queue",
                "path": str(item),
                "upload": {
                    "title": "Cable.Holder.NOTAG.STL",
                    "description": "[b]A small cable holder[/b]",
                    "image": "https://images.example/holder.png",
                },
            },
        ).json()
        assert finished(owner, saved["id"])["status"] == "completed"
    app = application()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(
                viewport={"width": viewport[0], "height": viewport[1]}, locale="en-US"
            )
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.locator("#navigation-toggle").click()
            shell_navigate(page, "upload")
            upload = page.frame_locator("#upload-frame")
            upload.locator("[data-tab=drafts]").click()
            expect(upload.locator(".item")).to_contain_text("Cable.Holder.NOTAG.STL")
            upload.locator(".item").first.focus()
            upload.locator(".item").first.press("Enter")
            upload.locator("[data-action=edit]").click()
            expect(upload.locator(".inspector.open")).to_have_count(0)
            upload.locator("[data-step='4']").click()
            expect(upload.locator(".editor pre").first).to_contain_text("A small cable holder")
            expect(upload.locator("#reviewed")).to_be_disabled()
            expect(upload.locator(".editor")).to_contain_text(
                "c411 forbids files from independent creators who live off them"
            )
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            shell_close_drawer(page)
            expect(upload.locator(".editor")).to_contain_text(
                "c411 interdit les fichiers de créateurs indépendants"
            )
            expect(upload.locator(".editor")).to_contain_text("Remplissez la section")
            expect(upload.locator(".editor")).not_to_contain_text("paid-creators:")
            shell_open_navigation(page)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            shell_close_drawer(page)
            # Edit through the same preparation dialog used by desktop.
            upload.locator("[data-step='2']").click()
            upload.locator("[data-action=advanced]").click()
            upload.locator("[data-prep-tab=description]").click()
            expect(upload.locator("#prep-description")).to_have_value(
                re.compile("A small cable holder")
            )
            upload.locator("#prep-description").fill(
                complete_description(
                    text="Reviewed cable holder description for a generated test object."
                )
            )
            expect(upload.locator("#prep-description-preview")).to_contain_text(
                "Reviewed cable holder description"
            )
            expect(page.locator("#upload-frame")).to_have_class(re.compile("has-open-dialog"))
            expect(upload.locator("[data-prep=save]")).to_be_in_viewport()
            if folder := os.getenv("TL_POLISH_SCREENSHOTS"):
                Path(folder).mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(Path(folder) / f"upload-save-{viewport[0]}x{viewport[1]}.png")
                )
            upload.locator("[data-prep=save]").click()
            expect(upload.locator("#prep-status")).to_contain_text("Saved")
            upload.locator("[data-prep=close]").last.click()
            upload.locator("[data-step='4']").click()
            expect(upload.locator(".editor pre").first).to_contain_text(
                "Reviewed cable holder description"
            )
            assert posted == []
            assert not list((tmp_path / "config" / "uploads").glob("**/*.torrent"))
            page.set_viewport_size({"width": 600, "height": 800})
            assert upload.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
            for language in ("fr", "en"):
                shell_open_navigation(page)
                page.frame_locator("#shell-navigation-frame").locator("#language").select_option(
                    language
                )
                shell_close_drawer(page)
                expect(upload.locator(".editor pre").first).to_contain_text(
                    "Reviewed cable holder description"
                )
            page.on("dialog", lambda dialog: dialog.accept())
            upload.locator("#reviewed").check()
            upload.locator("[data-action=next]").click()
            upload.locator("[data-action=send]").click()
            upload.locator("[data-action=confirm-send]").click()
            expect(upload.locator(".track")).to_contain_text("c411 draft", timeout=10000)
            assert len(posted) == 1
            assert "Reviewed cable holder description" in posted[0].content.decode()
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
