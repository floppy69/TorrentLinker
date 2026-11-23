"""Guided Upload interactions against the real Web UI and isolated storage."""

import os
import socket
import threading
import time

import pytest

from tests.shell_support import shell_navigate

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


@pytest.mark.parametrize("host_fails", [False, True])
def test_manual_upload_and_postimages_return_preserve_description(tmp_path, host_fails):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_web_library_review import EmptyClient
    from torrentlinker.web.app import create_app
    from torrentlinker.web.security import ServerSecrets
    from torrentlinker.web.setup import Setup

    root = tmp_path / "media"
    root.mkdir()
    model = root / "Sculpture.stl"
    model.write_text(
        "solid sculpture\nfacet normal 0 0 1\nouter loop\n"
        "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid sculpture\n"
    )
    config = tmp_path / "config"
    config.mkdir()
    setup = Setup(config, (root,), ServerSecrets(config), lambda *args: EmptyClient())
    from tests.test_upload_completeness import complete_description
    from tests.upload_fixtures import StubIndexer

    class UploadIndexer(StubIndexer):
        def save_draft(self, body):
            if host_fails:
                raise TimeoutError("Remote draft outcome unknown")
            return super().save_draft(body)

    setup._indexer = UploadIndexer()
    setup.secrets.update({"announce-url": "https://c411.org/announce/test-passkey"})
    setup.configured = True
    setup.save()
    app = create_app(config, password="test-password-long", service_override=setup)
    slow_save = threading.Event()

    @app.middleware("http")
    async def network_latency(request, call_next):
        if slow_save.is_set() and request.url.path.endswith("/workspace/save"):
            import asyncio

            await asyncio.sleep(0.6)
        return await call_next(request)

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
            page = browser.new_page(
                viewport={"width": 1560, "height": 1050},
                color_scheme="light" if host_fails else "dark",
            )
            page.add_init_script("""window.addEventListener('message', event => {
                if (event.data?.type === 'upload-tab') window.uploadTabMessage = event.data;
            });""")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            base = f"http://127.0.0.1:{port}"
            page.goto(base)
            page.locator("#login-password").fill("test-password-long")
            page.locator("#login-form button").click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            shell_navigate(page, "upload")
            frame = page.frame_locator("#upload-frame")
            frame.locator('[data-tab="sources"]').click()
            expect(frame.locator('[data-tab="sources"]')).to_have_class("on")
            page.wait_for_function("() => window.uploadTabMessage?.tab === 'sources'")
            previous_tab_message = page.evaluate("window.uploadTabMessage")
            page.evaluate("location.hash = '#/upload/remote'")
            expect(frame.locator('[data-tab="tracking"]')).to_have_class("on")
            # A panel render queued before navigation must not replace the new route.
            page.evaluate(
                """message => window.dispatchEvent(new MessageEvent('message', {
                source: document.querySelector('#upload-frame').contentWindow,
                origin: location.origin, data: message
            }))""",
                previous_tab_message,
            )
            expect(page).to_have_url(base + "/#/upload/remote")
            expect(frame.locator('[data-tab="tracking"]')).to_have_class("on")
            frame.locator('[data-tab="sources"]').click()
            expect(page).to_have_url(base + "/#/upload/sources")
            page.go_back()
            expect(frame.locator('[data-tab="tracking"]')).to_have_class("on")
            frame.locator('[data-tab="sources"]').click()

            expect(frame.locator("body")).to_have_css("padding-right", "16px")
            assert page.locator("#upload-frame").evaluate(
                "el => el.getBoundingClientRect().bottom <= innerHeight - 16"
            )
            frame.get_by_role("button", name="+ Choisir un fichier", exact=True).click()
            frame.locator("#manual-path").fill(str(model))
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            expect(frame.get_by_role("heading", name="Choose a file", exact=True)).to_be_visible()
            expect(frame.locator("#manual-path")).to_have_value(str(model))
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(
                frame.get_by_role("heading", name="Choisir un fichier", exact=True)
            ).to_be_visible()
            frame.locator("#manual-kind").select_option("10")
            frame.get_by_role("button", name="Ajouter aux sources", exact=True).click()
            expect(frame.locator("#confirm-existing")).to_be_visible()
            frame.locator("#confirm-existing").check()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            expect(frame.locator("#confirm-existing")).to_be_checked()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(frame.locator("#confirm-existing")).to_be_checked()
            frame.get_by_role("button", name="Enregistrer et continuer →").click()
            expect(frame.locator("#release-name")).to_be_visible()
            frame.get_by_role("button", name="Enregistrer et continuer →").click()
            frame.locator("#description").fill("Ma présentation personnelle.\n")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            expect(frame.locator("html")).to_have_attribute("lang", "en")
            expect(frame.get_by_role("button", name="+ Add an image", exact=True)).to_be_visible()
            expect(frame.locator("#description")).to_have_value("Ma présentation personnelle.\n")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(
                frame.get_by_role("button", name="+ Ajouter une image", exact=True)
            ).to_be_visible()
            expect(frame.locator("#description")).to_have_value("Ma présentation personnelle.\n")
            # Host is the external boundary. Its documented popup returns BBCode.
            page.context.route(
                "https://postimages.org/**",
                lambda route: route.fulfill(
                    content_type="text/html",
                    body="""<button id='upload'>Choisir une image</button>
                <script>document.querySelector('button').onclick=()=>opener.postMessage({
                id:new URL(location.href).searchParams.get('areaid'),
                message:encodeURIComponent('[url=https://postimg.cc/abc][img]https://i.postimg.cc/abc/cover.png[/img][/url]')},'*')</script>""",
                ),
            )
            with page.expect_popup() as opened:
                frame.get_by_role("button", name="+ Ajouter une image", exact=True).click()
            popup = opened.value
            popup.locator("#upload").click()
            expect(frame.locator("#description")).to_have_value(
                "Ma présentation personnelle.\n\n[url=https://postimg.cc/abc][img]https://i.postimg.cc/abc/cover.png[/img][/url]"
            )
            expect(frame.locator("#image-url")).to_have_value("https://i.postimg.cc/abc/cover.png")
            frame.get_by_role("button", name="Enregistrer", exact=True).click()
            expect(
                frame.locator(".tl-toast", has_text="Brouillon enregistré localement.")
            ).to_be_visible()
            result = page.request.post(
                base + "/api/upload/workspace/state", data={}, headers={"X-TorrentLinker": "1"}
            ).json()
            assert result["drafts"][0]["form"]["description"].startswith(
                "Ma présentation personnelle."
            )
            assert result["drafts"][0]["form"]["image"] == "https://i.postimg.cc/abc/cover.png"
            frame.locator('[data-step="2"]').click()
            frame.get_by_role("button", name="Outils de préparation", exact=True).click()
            expect(frame.locator("#prep-title-field")).to_have_value("Sculpture.NOTAG.STL")
            expect(frame.locator('[data-prep-field="subcategory"] option').first).not_to_have_text(
                ""
            )
            frame.locator("#prep-source").fill("Création personnelle")
            frame.locator('[data-prep="save"]').click()
            expect(frame.locator("#prep-status")).to_contain_text("Enregistré")
            expect(frame.locator('[data-prep="save"]')).to_be_enabled()
            frame.locator('[data-prep-tab="models"]').click()
            frame.locator('[data-prep="inspect"]').click()
            expect(frame.locator("#prep-mesh polygon")).to_have_count(1)
            frame.locator("#prep-yaw").fill("90")
            frame.locator('[data-prep="render"]').click()
            expect(frame.locator('[data-prep="export-artwork"]')).to_have_count(1)
            expect(frame.locator(".prep-body img")).to_be_visible()
            assert frame.locator(".prep-body img").evaluate(
                "el => el.complete && el.naturalWidth > 0"
            )
            frame.locator('[data-prep="save"]').click()
            expect(frame.locator('[data-prep="save"]')).to_be_enabled()
            page.screenshot(path="/tmp/upload-preparation-model-web.png")
            frame.locator('[data-prep-tab="details"]').click()
            page.screenshot(path="/tmp/upload-preparation-web.png")
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            expect(frame.locator('[data-prep-tab="files"]')).to_have_text("Files & NFO")
            frame.locator('[data-prep-tab="files"]').click()
            frame.locator('[data-prep="reset-nfo"]').click()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            frame.locator("#prep-confirm").click()
            expect(frame.locator("#dialog")).not_to_be_visible()
            frame.locator('[data-prep="save"]').click()
            expect(frame.locator("#prep-status")).to_contain_text("Enregistré")
            page.set_viewport_size({"width": 390, "height": 844})
            expect(frame.locator("#preparation")).to_be_visible()
            assert frame.locator("#preparation").evaluate(
                "el => el.scrollWidth <= el.clientWidth + 1"
            )
            page.screenshot(path=f"/tmp/upload-preparation-narrow-{host_fails}.png")
            page.set_viewport_size({"width": 1560, "height": 1050})
            frame.locator('[data-prep="close"]').first.click()
            frame.locator('[data-step="3"]').click()
            result = page.request.post(
                base + "/api/upload/workspace/state", data={}, headers={"X-TorrentLinker": "1"}
            ).json()
            assert result["drafts"][0]["form"]["manual_source"]
            assert result["drafts"][0]["form"]["workflow_step"] == 3
            slow_save.set()
            frame.locator("#description").fill("Version envoyée pour enregistrement.")
            frame.get_by_role("button", name="Enregistrer", exact=True).click()
            frame.locator("#description").fill("Texte saisi pendant l’enregistrement.")
            expect(
                frame.locator(
                    ".tl-toast",
                    has_text="Version enregistrée. Les nouvelles modifications restent",
                )
            ).to_be_visible()
            expect(frame.locator("#description")).to_have_value(
                "Texte saisi pendant l’enregistrement."
            )
            slow_save.clear()
            result = page.request.post(
                base + "/api/upload/workspace/state", data={}, headers={"X-TorrentLinker": "1"}
            ).json()
            # Jumping directly to review must save the exact content being reviewed.
            before = result["drafts"][0]["revision"]
            frame.locator("#description").fill("Texte modifié avant la relecture.")
            frame.locator('[data-step="4"]').click()
            expect(frame.locator(".editor")).to_contain_text("Texte modifié avant la relecture.")
            reviewed = page.request.post(
                base + "/api/upload/workspace/state", data={}, headers={"X-TorrentLinker": "1"}
            ).json()["drafts"][0]
            assert reviewed["revision"] > before
            assert "Texte modifié avant la relecture." in reviewed["form"]["description"]
            # The external draft API is simulated; the app still creates and hashes a real torrent.
            frame.locator('[data-step="3"]').click()
            frame.locator("#description").fill(complete_description(text="Présentation complète."))
            frame.get_by_role("button", name="Enregistrer et continuer →").click()
            expect(frame.locator("#reviewed")).to_be_enabled()
            frame.locator("#reviewed").check()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
            expect(frame.locator("#reviewed")).to_be_checked()
            page.frame_locator("#shell-navigation-frame").locator("#language").select_option("fr")
            expect(frame.locator("#reviewed")).to_be_checked()
            frame.get_by_role("button", name="Enregistrer et continuer →").click()
            frame.get_by_role("button", name="Créer le brouillon c411…").click()
            frame.get_by_role("button", name="Confirmer l’envoi", exact=True).click()
            expect(frame.locator(".track")).to_have_count(1)
            expect(frame.locator(".track")).to_contain_text(
                "Envoi à vérifier" if host_fails else "Brouillon c411"
            )
            if host_fails:
                frame.get_by_role("button", name="Voir le détail →").click()
                expect(
                    frame.get_by_role("button", name="J’ai vérifié c411, autoriser un nouvel essai")
                ).to_be_visible()
                frame.locator("button[data-action=close]").click()
            page.screenshot(path="/tmp/upload-guided-web.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            expect(frame.locator(".track")).to_have_count(1)
            # Resize propagates asynchronously to the embedded document.
            page.wait_for_function("""() => {
                const frame = document.getElementById('upload-frame').contentWindow;
                return frame.document.documentElement.scrollWidth <= frame.innerWidth;
            }""")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
