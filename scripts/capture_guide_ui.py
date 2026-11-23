"""Capture the current shared Settings and Plan UI with isolated example data.

Run .venv/bin/python scripts/capture_guide_ui.py from the repository root.
Requires development dependencies and Playwright Chromium. No real accounts or
clients are used; outbound connections are blocked. Output is English, dark theme.
"""

import ipaddress
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import uvicorn
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.shell_support import shell_navigate  # noqa: E402
from tests.test_web_plan_execution import prepared, second_client  # noqa: E402
from torrentlinker.web.app import create_app  # noqa: E402


def main():
    output = Path(__file__).resolve().parents[1] / "docs/guide/images/en"
    output.mkdir(parents=True, exist_ok=True)
    connect = socket.socket.connect

    def local_only(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0]
            if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
                raise OSError("Documentation capture blocks external connections")
        return connect(sock, address)

    with TemporaryDirectory(prefix="tl-guide-") as temp:
        config, setup, client, _ = prepared(Path(temp))
        second_client(Path(temp), setup, client)
        setup.settings.language = "en"
        setup.settings.theme = "dark"
        setup.save()
        app = create_app(
            config,
            password="documentation-only-password",
            service_override=setup,
            monitor_verifications=False,
        )
        with patch.object(socket.socket, "connect", local_only), socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
            worker = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            worker.start()
            try:
                for _ in range(200):
                    if server.started:
                        break
                    time.sleep(0.025)
                assert server.started
                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    page = browser.new_page(viewport={"width": 1440, "height": 1100})
                    page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                    page.locator("#login-password").fill("documentation-only-password")
                    page.locator("#login-form button").click()
                    shell_navigate(page, "setup")
                    nav = page.frame_locator("#shell-navigation-frame")
                    nav.locator("#language").select_option("en")
                    nav.locator("#theme").select_option("dark")
                    panel = page.frame_locator("#settings-frame")
                    expect(panel.locator("#settings-navigation button")).to_have_count(12)
                    for section in (
                        "Connections",
                        "Clients",
                        "Download Folders",
                        "Client Paths",
                        "ReleaseScore",
                    ):
                        panel.get_by_role("button", name=section, exact=True).click()
                        expect(panel.locator(".settings-form")).to_be_visible()
                        if section == "Client Paths":
                            panel.get_by_label("Folder on the TorrentLinker host", exact=True).fill(
                                "/mnt/nas/media"
                            )
                            panel.get_by_label("Torrent Client path", exact=True).fill("/data")
                        panel.locator("body").evaluate("()=>scrollTo(0,0)")
                        name = {
                            "Connections": "settings-connections",
                            "Clients": "settings-clients",
                            "Download Folders": "settings-downloads",
                            "Client Paths": "settings-paths",
                            "ReleaseScore": "settings-search",
                        }[section]
                        if section == "ReleaseScore":
                            panel.locator(".settings-card").filter(
                                has=panel.get_by_role("heading", name="ReleaseScore", exact=True)
                            ).screenshot(path=str(output / "settings-search.png"))
                            continue
                        page.locator("#settings-frame").screenshot(path=str(output / f"{name}.png"))
                    equipment = panel.locator("details").filter(
                        has=panel.locator("summary", has_text="Your equipment")
                    )
                    equipment.locator("summary").click()
                    equipment.get_by_label("Screen diagonal (inches)", exact=True).fill("55")
                    equipment.get_by_label("Viewing distance (m)", exact=True).fill("2.5")
                    equipment.get_by_label("Screen definition", exact=True).select_option("4k")
                    equipment.get_by_label("Sound system", exact=True).select_option("barre")
                    equipment.get_by_label("Priority", exact=True).select_option("equilibre")
                    equipment.screenshot(path=str(output / "release-score-equipment.png"))
                    shell_navigate(page, "zen")
                    page.locator("#zen-plan-tab").click()
                    plan = page.frame_locator("#plan-frame")
                    expect(plan.locator("#plan-cached")).to_be_enabled()
                    plan.locator("#plan-cached").check()
                    plan.locator("#plan-min-count").fill("2")
                    plan.locator("#plan-min-seeders").fill("1")
                    plan.locator("body").evaluate("()=>scrollTo(0,0)")
                    page.locator("#plan-frame").screenshot(path=str(output / "plan-controls.png"))
                    shell_navigate(page, "documentation")
                    docs = page.frame_locator("#documentation-frame")
                    for guide in (
                        "getting-started",
                        "clients",
                        "zen",
                        "release-score",
                        "rss",
                        "media",
                        "search",
                        "upload",
                    ):
                        docs.locator(f'[data-guide-path="guide/en/{guide}.md"]').click()
                        expect(docs.locator("#guide-content")).to_have_attribute(
                            "data-path", f"guide/en/{guide}.md"
                        )
                        expect(docs.locator("#guide-content h1")).to_be_visible()
                        docs.locator("#guide-content").evaluate("""async root => {
                            const until = Date.now() + 10000;
                            const pending = () => [...root.querySelectorAll('img')]
                                .some(img => !img.getAttribute('src'));
                            while (pending()) {
                                if (Date.now() > until) throw Error('Guide image did not load');
                                await new Promise(resolve => setTimeout(resolve, 50));
                            }
                        }""")
                        docs.locator("#guide-content").evaluate("""async root => {
                            await Promise.all([...root.querySelectorAll('img')].map(img =>
                                img.decode()));
                        }""")
                    browser.close()
            finally:
                server.should_exit = True
                worker.join(5)
    revision = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    print(f"Captured Settings and Plan from {revision} working tree, 1440x1100, English/dark.")


if __name__ == "__main__":
    main()
