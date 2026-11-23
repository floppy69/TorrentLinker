"""Visible folder verification and category inheritance on desktop and WebUI."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.shell_support import shell_navigate
from tests.test_folder_probe import ProbeClient
from torrentlinker.config import Settings
from torrentlinker.domain import PathMapping
from torrentlinker.downloads import DownloadFolders, IndexerCategory


def categories():
    return {
        2000: IndexerCategory("Films & Videos"),
        2030: IndexerCategory("Animation", 2000),
        2031: IndexerCategory("Series", 2030),
        3000: IndexerCategory("Audio"),
        3010: IndexerCategory("Audio", 3000),
        7000: IndexerCategory("Ebook"),
    }


def test_desktop_checks_empty_mapping_and_shows_category_branches(qtbot, tmp_path, monkeypatch):
    from tests.settings_support import settings_page
    from tests.test_community_interfaces import js, wait_js

    root = tmp_path / "media"
    root.mkdir()
    client = ProbeClient(root)
    client.default_save_path = lambda: "/downloads"
    settings = Settings(language="en")
    settings.path_mappings = [PathMapping(str(root), "/downloads")]
    settings.indexer_categories = categories()
    dialog = settings_page(qtbot, tmp_path, settings, section="paths")
    dialog.setup.connector = lambda *a, **kw: client
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Edit').click()",
    )
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Test mapping').click()",
    )
    qtbot.waitUntil(lambda: dialog.view.pending == 0)
    qtbot.wait(100)
    assert js(qtbot, dialog.view, "document.querySelector('#settings-error').textContent") == ""
    wait_js(qtbot, dialog.view, "document.body.textContent.includes('Mapping verified')")
    assert len(client.added) == 1 and len(client.removed) == 1
    assert list(root.iterdir()) == []
    dialog.view.section = "downloads"
    dialog.view.refresh()
    wait_js(
        qtbot,
        dialog.view,
        "document.querySelector('.settings-form h2').textContent==='Download Folders'",
    )
    labels = js(
        qtbot,
        dialog.view,
        "[...document.querySelector('[aria-label=Category]').options].m"
        "ap(o=>o.textContent).join(' | ')",
    )
    assert "Films & Videos › Animation › Series" in labels
    assert "Audio › Audio" in labels


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_browser_category_tree_and_empty_folder_save(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.web.app import create_app
    from torrentlinker.web.security import ServerSecrets
    from torrentlinker.web.setup import Setup

    config, root = tmp_path / "config", tmp_path / "media"
    config.mkdir()
    root.mkdir()
    client = ProbeClient(root)
    setup = Setup(config, (root,), ServerSecrets(config), lambda *a, **kw: client)
    setup.configured = True
    setup.settings.indexer_categories = categories()
    setup.settings.path_mappings = [PathMapping(str(root), "/downloads")]
    setup.settings.download_folders = DownloadFolders({2000: str(root)})
    setup.save()
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1050}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            shell_navigate(page, "setup")
            panel = page.frame_locator("#settings-frame")
            panel.get_by_role("button", name="Download Folders", exact=True).click()
            picker = panel.get_by_label("Category", exact=True)
            expect(picker.locator("option").filter(has_text="Audio › Audio")).to_have_count(1)
            picker.select_option("2031")
            expect(picker.locator("option:checked")).to_have_text(
                "Films & Videos › Animation › Series"
            )
            expect(panel.locator(".settings-form")).to_contain_text(str(root))
            panel.get_by_label("Folder on the TorrentLinker host", exact=True).fill(str(root))
            panel.get_by_role("button", name="Save folder", exact=True).click()
            expect(panel.locator(".client-card").filter(has_text="Series")).to_be_visible(
                timeout=15000
            )
            assert setup.settings.download_folders.by_category[2031] == str(root)
            assert len(client.added) == 1 and len(client.removed) == 1
            assert list(root.iterdir()) == []
            if output := os.getenv("TL_WEB_SCREENSHOTS"):
                Path(output).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(output) / "folder-settings-web.png"), full_page=True)
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
