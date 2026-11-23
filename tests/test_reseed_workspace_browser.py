"""Browser acceptance of the real workflow; only the Torrent Client is simulated."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.shell_support import shell_close_drawer, shell_open_navigation
from tests.test_reseed_workspace import CheckingClient, workspace
from torrentlinker.web.app import create_app
from torrentlinker.web.operations import Operations


def reseed_app(root, client=None, **options):
    board, client, original, links, meta = workspace(root, client)
    board.setup.save()

    def operations(setup):
        result = Operations(setup)
        result.library.entries = board.library.entries
        return result

    app = create_app(
        root / "config",
        password="test-password-long",
        service_override=board.setup,
        operation_factory=operations,
        **options,
    )
    return app, board, client, original, links, meta


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
@pytest.mark.parametrize("layout", ["auto", "links"])
def test_reseed_board_runs_pauses_and_preserves_original_on_small_screen(tmp_path, layout):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    class SlowCheck(CheckingClient):
        release = threading.Event()

        def torrent(self, hash, **kwargs):
            if not self.release.is_set():
                return self.by_hash.get(hash)
            return super().torrent(hash, **kwargs)

    client = SlowCheck()
    app, board, _, original, links, meta = reseed_app(tmp_path, client)
    before = original.read_bytes(), original.stat().st_ino
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
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("localStorage.setItem('tl-theme','dark')")
            page.goto(f"http://127.0.0.1:{port}/#/library/reseed")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            frame = page.frame_locator("#reseed-frame")
            expect(frame.locator(".torrent")).to_contain_text(original.name)
            expect(frame.locator("body")).to_have_css("padding-right", "16px")
            assert page.locator("#reseed-frame").evaluate(
                "el => el.getBoundingClientRect().bottom <= innerHeight - 16"
            )

            frame.get_by_label("Folder", exact=True).select_option(str(original.parent))
            frame.get_by_label("Seed state", exact=True).select_option("seeded")
            expect(frame.locator(".torrent")).to_have_count(0)
            frame.get_by_label("Seed state", exact=True).select_option("orphan")
            expect(frame.locator(".torrent")).to_contain_text(original.name)
            frame.get_by_role("button", name="Select the list", exact=True).click()
            expect(
                frame.get_by_role("button", name="Combine selection", exact=True)
            ).to_be_disabled()
            frame.get_by_role("button", name="Clear selection", exact=True).click()

            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            expect(frame.get_by_role("button", name="Run all", exact=True)).to_be_visible()
            expect(frame.locator("html")).to_have_attribute("lang", "en")
            frame.get_by_role("button", name="Folders", exact=True).click()
            frame.get_by_role("button", name="Edit", exact=True).first.click()
            expect(frame.get_by_role("heading", name="Edit folder")).to_be_visible()
            expect(frame.locator("#folder-live")).to_contain_text(original.name)
            frame.get_by_label("Item grouping", exact=True).select_option("1")
            frame.get_by_label("Scan after saving", exact=True).uncheck()
            frame.get_by_role("button", name="Save", exact=True).click()
            expect(frame.locator("#dialog")).not_to_be_visible()
            expect(frame.locator(".folder-entry").first).to_contain_text("Depth 1")
            frame.get_by_role("button", name="Activity", exact=True).click()
            expect(frame.get_by_text("Upcoming transitions will appear here.")).to_be_visible()
            frame.get_by_role("button", name="Reseed", exact=True).click()
            frame.locator(".guided button").nth(1).click()
            expect(frame.get_by_role("heading", name="Browse my folders")).to_be_visible()
            frame.get_by_role("button", name="Close", exact=True).click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(frame.get_by_role("button", name="Tout enchaîner", exact=True)).to_be_visible()
            frame.locator(".guided button").first.click()
            frame.locator("#root-form [name=layout]").select_option(layout)
            if layout == "links":
                frame.get_by_role("button", name="Parcourir…").click()
                frame.get_by_role("button", name=str(links), exact=True).click()
                frame.get_by_role("button", name="Choisir ce dossier", exact=True).click()
                expect(frame.locator("#root-form [name=path]")).to_have_value(str(links))
            else:
                expect(frame.locator("#root-form [name=path]")).not_to_be_visible()
            frame.get_by_role("button", name="Enregistrer", exact=True).click()
            expect(frame.locator("#dialog")).not_to_be_visible()
            page.reload()
            expect(frame.locator(".guided button").first).to_contain_text(
                "Dossier de liens configuré" if layout == "links" else "sans dossier de liens"
            )
            page.on("dialog", lambda dialog: dialog.accept())
            frame.get_by_role("button", name="Tout enchaîner", exact=True).click()
            expect(frame.locator(".torrent .badge")).to_contain_text("Vérifier", timeout=20000)
            frame.get_by_role("button", name="Suspendre le parcours", exact=True).click()
            expect(frame.get_by_role("button", name="Reprendre le parcours")).to_be_visible(
                timeout=10000
            )
            client.release.set()
            assert not client.started
            page.reload()
            expect(frame.get_by_role("button", name="Reprendre le parcours")).to_be_visible(
                timeout=10000
            )
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            frame.get_by_role("button", name="Reprendre le parcours", exact=True).click()
            expect(frame.locator(".torrent .badge")).to_contain_text("En partage", timeout=20000)
            assert client.started == [meta.infohash]
            frame.locator(".torrent").click()
            expect(frame.locator(".inspector")).to_contain_text("Release.mkv")
            expect(frame.locator(".inspector")).to_contain_text(str(original))
            frame.locator(".inspector").get_by_role("button", name="Fermer", exact=True).click()
            shell_open_navigation(page)  # a phone keeps the preferences in its drawer
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("light")
            expect(frame.locator("html")).to_have_attribute("data-theme", "light")
            page.frame_locator("#shell-navigation-frame").locator("#theme").select_option("dark")
            shell_close_drawer(page)
            expect(frame.locator("html")).to_have_attribute("data-theme", "dark")
            destination = os.getenv("TL_WEB_SCREENSHOTS")
            if destination:
                Path(destination).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(destination) / "reseed-mobile.png"), full_page=True)
                page.set_viewport_size({"width": 1560, "height": 1000})
                frame.locator("body").evaluate("() => window.scrollTo(0,0)")
                page.screenshot(path=str(Path(destination) / "reseed-web.png"), full_page=True)
            assert not errors
            assert (original.read_bytes(), original.stat().st_ino) == before
            browser.close()
    finally:
        client.release.set()
        server.should_exit = True
        thread.join(15)


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_shared_list_expands_packs_filters_children_and_combines_without_copying(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.domain import ContentKind, ItemState, LibraryFolder, LocalItem
    from torrentlinker.library import LibraryEntry
    from torrentlinker.scan import scan_item

    app, board, _, original, _, _ = reseed_app(tmp_path)
    root = original.parent
    pack = root / "Show.S01"
    pack.mkdir()
    episodes = [pack / "Show.S01E01.mkv", pack / "Show.S01E02.mkv"]
    for path in episodes:
        path.write_bytes(b"episode" * 100)
    folder = LibraryFolder(root, 1, ContentKind.SERIES)
    board.setup.settings.library_folders = [folder]
    board.library.entries[:] = [LibraryEntry(folder, scan_item(pack), ItemState.ORPHAN)] + [
        LibraryEntry(folder, LocalItem(path, {path.name: 700}, within=pack), ItemState.ORPHAN)
        for path in episodes
    ]
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
            page = browser.new_page(viewport={"width": 1600, "height": 1000}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#/library/reseed")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            frame = page.frame_locator("#reseed-frame")
            expect(frame.locator(".torrent")).to_have_count(1)
            frame.get_by_role("button", name="Episodes in Show.S01", exact=True).click()
            expect(frame.locator(".torrent")).to_have_count(3)
            frame.get_by_label("Select Show.S01E01.mkv", exact=True).check()
            frame.get_by_label("Select Show.S01E02.mkv", exact=True).check()
            frame.get_by_role("button", name="Combine selection", exact=True).click()
            frame.get_by_label("Group name").fill("My series")
            frame.get_by_role("button", name="Create group", exact=True).click()
            expect(frame.locator("#dialog")).not_to_be_visible(timeout=15000)
            expect(frame.locator(".inspector h2")).to_have_text("My series")
            page.reload()
            expect(frame.locator(".torrent").filter(has_text="My series")).to_have_count(1)
            frame.get_by_role("textbox", name="Search", exact=True).fill("S01E02")
            expect(frame.locator(".torrent")).to_have_count(2)
            expect(frame.get_by_label("Select Show.S01", exact=True)).to_be_disabled()
            frame.get_by_role("button", name="Select the list", exact=True).click()
            expect(frame.get_by_label("Select Show.S01E02.mkv", exact=True)).to_be_checked()
            board.library.entries.extend(
                LibraryEntry(
                    folder,
                    LocalItem(root / f"Book-{i:05}.epub", {f"Book-{i:05}.epub": 400}),
                    ItemState.ORPHAN,
                )
                for i in range(5000)
            )
            frame.get_by_role("textbox", name="Search", exact=True).fill("")
            expect(frame.locator(".stage").first).to_contain_text("5004", timeout=5000)
            assert frame.locator(".torrent").count() < 300
            frame.get_by_label("Folder", exact=True).select_option(str(root))
            frame.get_by_label("Seed state", exact=True).select_option("orphan")
            frame.get_by_role("textbox", name="Search", exact=True).fill(" Book-04999 ")
            expect(frame.locator(".torrent")).to_have_count(1, timeout=5000)
            expect(frame.locator(".torrent")).to_contain_text("Book-04999.epub")
            frame.get_by_role("textbox", name="Search", exact=True).fill("S01E02")
            page.set_viewport_size({"width": 390, "height": 844})
            frame.locator(".episode").click()
            expect(frame.locator(".inspector")).to_be_visible()
            assert frame.locator("body").evaluate("el=>el.scrollWidth <= innerWidth")
            assert all(path.read_bytes() == b"episode" * 100 for path in episodes)
            assert sorted(p.name for p in pack.iterdir()) == [p.name for p in episodes]
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_candidate_inspector_reviews_files_imports_and_rejects_in_place(tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.torrents import make_torrent

    app, board, client, original, _, _ = reseed_app(tmp_path)
    from torrentlinker.indexer import Indexer

    monkeypatch.setattr(
        Indexer,
        "torrent_json",
        lambda self, hash: {
            "description": '<h2>Fixture synopsis</h2><a href="https://example.test/info">Reference</a><script>window.evil=1</script>',
            "metadata": {"hasNfo": True, "nfoContent": "Fixture NFO <plain>"},
        },
    )
    historical = tmp_path / "historical.torrent"
    historical.write_bytes(make_torrent(original))
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
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1000}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#/library/reseed")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            frame = page.frame_locator("#reseed-frame")
            expect(frame.get_by_label("Candidate", exact=True)).to_be_visible(timeout=15000)
            frame.get_by_role("tab", name="Files", exact=True).click()
            expect(frame.locator(".review-content")).to_contain_text("Release.mkv")
            expect(frame.locator(".review-content")).to_contain_text(original.name)
            frame.get_by_role("tab", name="Description", exact=True).click()
            expect(frame.locator(".review-description")).to_contain_text("Fixture synopsis")
            expect(frame.locator(".review-description script")).to_have_count(0)
            page.context.route(
                "https://example.test/**", lambda route: route.fulfill(body="Reference")
            )
            with page.expect_popup() as opened:
                frame.get_by_role("link", name="Reference").click()
            opened.value.close()
            expect(frame.locator(".review-description")).to_contain_text("Fixture synopsis")
            frame.get_by_role("tab", name="NFO", exact=True).click()
            expect(frame.locator(".review-content pre")).to_have_text("Fixture NFO <plain>")
            frame.get_by_role("tab", name="Evidence", exact=True).click()
            expect(frame.locator("#provenance-file")).to_be_enabled()
            frame.locator("#provenance-file").set_input_files(historical)
            expect(frame.locator(".review-content")).to_contain_text(
                "Verified association", timeout=15000
            )
            page.reload()
            frame.get_by_role("tab", name="Evidence", exact=True).click()
            expect(frame.locator(".review-content")).to_contain_text(
                "Verified association", timeout=15000
            )
            original.write_bytes(b"changed")
            frame.get_by_role("button", name="Refresh provenance", exact=True).click()
            expect(frame.locator(".review-content")).to_contain_text("Stale", timeout=15000)
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(frame.get_by_role("tab", name="Preuves", exact=True)).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            frame.locator(".torrent").click()
            expect(frame.locator(".inspector.open")).to_be_visible()
            assert frame.locator("body").evaluate("el=>el.scrollWidth <= innerWidth")
            frame.locator(".inspector").evaluate("el=>el.scrollTop=350")
            scroll = frame.locator(".inspector").evaluate("el=>el.scrollTop")
            board.library.entries.append(board.library.entries[0])
            expect(frame.locator(".stage").first).to_contain_text("2", timeout=5000)
            assert frame.locator(".inspector").evaluate("el=>el.scrollTop") == scroll
            board.library.entries.pop()
            page.on("dialog", lambda dialog: dialog.accept())
            frame.get_by_role("button", name="Écarter", exact=True).click()
            expect(frame.locator(".review-header")).to_contain_text("Aucun candidat", timeout=15000)
            page.reload()
            expect(frame.locator(".review-header")).to_contain_text("Aucun candidat", timeout=15000)
            frame.locator(".torrent").click()
            frame.get_by_role("button", name="Historique des réparations…", exact=True).click()
            expect(frame.locator("#recovery-dialog")).to_contain_text(
                "Aucune réparation enregistrée."
            )
            assert not client.calls
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)


@pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")
def test_external_jobs_progress_queue_and_completion_survive_browser_reload(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    app, board, _, original, _, _ = reseed_app(tmp_path)
    jobs = app.state.agent_service.jobs
    release = threading.Event()
    started = threading.Event()

    def held(stop, report):
        report({"done": 1, "total": 3})
        started.set()
        release.wait(15)
        report({"done": 3, "total": 3})
        return {}

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
            page = browser.new_page(locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#/library/reseed")
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            frame = page.frame_locator("#reseed-frame")
            expect(frame.locator(".torrent")).to_contain_text(original.name)
            # A second tab/API caller checks the selected Candidate. The open
            # inspector must reload its cached result without changing selection.
            frame.locator(".torrent .title").click()
            expect(frame.locator("#review-candidate")).to_be_visible()
            key = frame.locator("#review-candidate").input_value()
            response = page.request.post(
                f"http://127.0.0.1:{port}/api/jobs",
                headers={"X-TorrentLinker": "1"},
                data={
                    "kind": "candidate-inspector",
                    "path": str(original),
                    "inspector_action": "check",
                    "candidate_key": key,
                },
            )
            assert response.ok
            expect(frame.locator(".inspector")).to_contain_text("Full Match", timeout=10000)
            first = jobs.submit("scan", held)
            assert started.wait(2)
            jobs.submit("reseed", lambda *_: {}, parameters={"path": str(original)})
            expect(frame.locator("#library-jobs")).to_contain_text("1/3")
            expect(frame.locator(".torrent .badge")).to_contain_text("waiting for Folder scan")
            page.screenshot(path="/tmp/tl65-library-jobs.png")
            page.reload()
            expect(frame.locator("#library-jobs")).to_contain_text("1/3")
            frame.get_by_role("button", name="Activity", exact=True).click()
            expect(frame.locator("#content")).to_contain_text("1/3")
            release.set()
            expect(frame.locator("#content")).to_contain_text("3/3")
            expect(frame.locator("#library-jobs")).to_contain_text("Done")
            page.locator("#work-status").click()
            expect(page.locator("#view-jobs")).to_be_visible()
            expect(page.locator("#job-list")).to_contain_text(str(original))
            assert jobs.get(first)["status"] == "completed"
            assert not errors
            browser.close()
    finally:
        release.set()
        server.should_exit = True
        thread.join(5)
