"""Members 2 (#129): the sign-in card and Paramètres → Utilisateurs in an actual browser."""

import os
import socket
import threading
import time

import pytest

from tests.shell_support import shell_navigate
from tests.test_web_plan_execution import prepared
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


def test_the_owner_creates_edits_and_disables_a_member_who_signs_in_by_name(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                expect(page.get_by_label("Sign-in name")).to_be_visible()
                page.get_by_role("button", name="I am the owner").click()
                expect(page.get_by_label("Sign-in name")).to_be_hidden()
                page.get_by_label("Server password").fill("wrong-password-long")
                page.locator("#login-form button.primary").click()
                expect(page.locator("#login-error")).to_have_text("Incorrect password.")
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                panel.get_by_role("button", name="Users", exact=True).click()
                expect(panel.get_by_text("every right, cannot be restricted")).to_be_visible()

                panel.get_by_role("button", name="Create an account with a password").click()
                dialog = panel.locator("dialog[open]")
                dialog.get_by_label("Display name").fill("Léa")
                dialog.get_by_label("Preset").select_option(label="Family")
                dialog.get_by_label("Sign-in name").fill("lea")
                dialog.get_by_label("Password").fill("lea-password-long")
                dialog.get_by_role("button", name="Create the account").click()
                expect(
                    panel.locator(".tl-toast").get_by_text("Léa can now sign in")
                ).to_be_visible()
                card = panel.locator(".client-card", has=panel.get_by_role("heading", name="Léa"))
                expect(card.get_by_text("Active · Family")).to_be_visible()
                caps = card.locator(".member-cap input[type=number]")
                expect(caps.nth(0)).to_have_value("5")
                expect(caps.nth(1)).to_have_value("100")

                # Without Request, the caps go; the Owner-only rights stay locked.
                card.get_by_label("Request films").uncheck()
                expect(card.locator(".member-cap input[type=checkbox]").first).to_be_disabled()
                expect(card.get_by_label("Upload")).to_be_disabled()
                card.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator(".tl-toast").get_by_text("Member saved")).to_be_visible()
                expect(card.get_by_text("Active · Custom")).to_be_visible()
                lea = app.state.accounts.members()[0]
                assert "request" not in lea["permissions"]
                assert lea["caps"]["requests_per_week"] is None

                # A Member signs in by name; disabling ends their session at once.
                other = browser.new_context(locale="fr-FR").new_page()
                other.goto(page.url.split("#")[0])
                other.get_by_label("Identifiant").fill("lea")
                other.get_by_label("Mot de passe", exact=True).fill("wrong-password-long")
                other.locator("#login-form button.primary").click()
                expect(other.locator("#login-error")).to_have_text(
                    "Identifiant ou mot de passe incorrect."
                )
                other.get_by_label("Mot de passe", exact=True).fill("lea-password-long")
                with other.expect_response("**/api/login") as signed:
                    other.locator("#login-form button.primary").click()
                assert signed.value.ok
                assert other.evaluate("fetch('api/shell').then(r => r.status)") == 200

                page.once("dialog", lambda prompt: prompt.accept())
                card.get_by_role("button", name="Disable").click()
                expect(card.get_by_text("Disabled · Custom")).to_be_visible()
                assert other.evaluate("fetch('api/shell').then(r => r.status)") == 401
                page.once("dialog", lambda prompt: prompt.accept())
                card.get_by_role("button", name="Delete").click()
                expect(panel.get_by_role("heading", name="Léa")).to_have_count(0)
                assert app.state.accounts.members() == []
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_an_invitation_link_with_its_qr_code_lets_the_person_join(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_role("button", name="I am the owner").click()
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                panel.get_by_role("button", name="Users", exact=True).click()
                panel.get_by_role("button", name="Invite someone").click()
                dialog = panel.locator("dialog[open]")
                dialog.get_by_label("Display name").fill("Karim")
                dialog.get_by_label("Preset").select_option(label="Family")
                dialog.get_by_label("Message (optional)").fill("Voici les films")
                dialog.get_by_label("Link valid for").select_option(label="7 days")
                dialog.get_by_role("button", name="Create the link").click()
                expect(dialog.get_by_role("heading", name="Invitation for Karim")).to_be_visible()
                expect(dialog.get_by_role("img", name="QR code of the link")).to_be_visible()
                url = dialog.get_by_label("Invitation link").input_value()
                assert "/join#" in url
                dialog.get_by_role("button", name="Close").click()
                card = panel.locator(".client-card", has=panel.get_by_role("heading", name="Karim"))
                expect(card.get_by_text("Invitation sent, expires in 7 d · Family")).to_be_visible()
                card.get_by_role("button", name="Show the link").click()
                expect(panel.locator("dialog[open]").get_by_label("Invitation link")).to_have_value(
                    url
                )
                panel.locator("dialog[open]").get_by_role("button", name="Close").click()

                other = browser.new_context(locale="fr-FR").new_page()
                other.on("pageerror", lambda error: errors.append(str(error)))
                other.goto(url)
                expect(
                    other.get_by_role("heading", name="Le propriétaire vous invite")
                ).to_be_visible()
                expect(other.get_by_text("« Voici les films »")).to_be_visible()
                expect(
                    other.get_by_text("Demander des films, jusqu’à 5 par semaine")
                ).to_be_visible()
                join = other.get_by_role("button", name="Rejoindre")
                other.get_by_label("Identifiant de connexion").fill("karim")
                other.get_by_label("Mot de passe", exact=True).fill("karim-password")
                other.get_by_label("Confirmer le mot de passe").fill("karim-passwor")
                expect(other.get_by_text("Les deux mots de passe diffèrent.")).to_be_visible()
                expect(join).to_be_disabled()
                other.get_by_label("Confirmer le mot de passe").fill("karim-password")
                join.click()
                expect(other.get_by_role("heading", name="Bienvenue, Karim")).to_be_visible()
                assert other.evaluate("fetch('api/shell').then(r => r.status)") == 200

                other.goto("about:blank")
                other.goto(url)
                expect(other.get_by_role("heading", name="Ce lien a déjà servi")).to_be_visible()
                assert app.state.accounts.verify("karim", "karim-password")
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_a_member_has_medias_without_the_owners_tools(tmp_path):
    """Members 4 (#131): the age limit in the editor, and a Member's shell in Médias."""
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.accounts import Permission

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    app.state.accounts.create(
        "Léa", "lea", {Permission.FILMS, Permission.ADULT}, password="lea-password-long"
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_role("button", name="I am the owner").click()
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                panel.get_by_role("button", name="Users", exact=True).click()
                card = panel.locator(".client-card", has=panel.get_by_role("heading", name="Léa"))
                card.get_by_role("button", name="Edit").click()
                expect(card.get_by_label("Adult content (XXX)")).to_be_checked()
                card.get_by_label("Age limit").select_option(label="Under 12")
                expect(card.get_by_label("Adult content (XXX)")).to_be_disabled()
                card.get_by_role("button", name="Save", exact=True).click()
                expect(panel.locator(".tl-toast").get_by_text("Member saved")).to_be_visible()
                expect(card.get_by_text("Limit Under 12")).to_be_visible()
                lea = app.state.accounts.members()[0]
                assert lea["age_limit"] == "12" and "adult" not in lea["permissions"]

                other = browser.new_context(locale="en-US").new_page()
                other.on("pageerror", lambda error: errors.append(str(error)))
                other.goto(page.url.split("#")[0])
                other.get_by_label("Sign-in name").fill("lea")
                other.get_by_label("Password", exact=True).fill("lea-password-long")
                other.locator("#login-form button.primary").click()
                other.wait_for_url("**#/media/video")
                navigation = other.frame_locator("#shell-navigation-frame")
                # Settings hold only "My account" for a Member (#135).
                expect(navigation.locator("#pages button")).to_have_text(
                    ["Media", "Documentation", "Notifications", "Settings"]
                )
                frame = other.frame_locator("#media-frame")
                expect(frame.locator("#media-center-mode")).to_be_visible()
                expect(frame.locator("#media-toolbar-refresh")).to_be_hidden()
                expect(frame.locator("#media-toolbar-chat")).to_be_hidden()
                expect(frame.locator("#media-client")).to_be_hidden()
                other.wait_for_timeout(2500)  # the jobs poll would have run by now
                expect(other.locator(".tl-toast")).to_be_hidden()
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_a_member_asks_for_a_tracker_film_and_follows_it_in_the_bell(tmp_path):
    """Members 6 (#133): "Ask the owner" on a tracker film, a Wish, and the bell's drawer."""
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.accounts import Caps, Permission

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    lea = app.state.accounts.create(
        "Léa",
        "lea",
        {Permission.FILMS, Permission.REQUEST, Permission.WISH},
        password="lea-password-long",
    )
    app.state.accounts.set_caps(lea, Caps(requests_per_week=3, bytes_per_week=100 * 10**9))
    dune = "d" * 40
    best = {"hash": dune, "name": "Dune.Part.Two.2024.1080p", "size": 7 * 10**9, "seeders": 80}
    item = {
        "id": "tracker-" + dune,
        "kind": "video",
        "title": "Dune",
        "year": "2024",
        "artwork_url": "",
        "available": True,
        "tracker": {**best, "score": 81, "color": "green", "published_at": None},
    }
    library = app.state.agent_service.media
    library.tracker_rows = lambda *_: {
        "tracker": {
            "key": "tracker",
            "title": "",
            "filters": {"tracker": "tracker"},
            "total": 1,
            "rows": [item],
            "state": "ready",
        }
    }
    library.tracker_entry = lambda *_: {"facts": {"title": "Dune", "year": 2024}, "release": best}
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_label("Sign-in name").fill("lea")
                page.get_by_label("Password", exact=True).fill("lea-password-long")
                page.locator("#login-form button.primary").click()
                page.wait_for_url("**#/media/video")
                frame = page.frame_locator("#media-frame")
                feature = frame.locator("#media-feature")
                expect(feature.get_by_text("You have 3 Requests and 100 GB left")).to_be_visible(
                    timeout=15000
                )
                feature.get_by_role("button", name="Ask the owner").click()
                expect(feature.get_by_text("Pending", exact=True)).to_be_visible()
                [asked] = app.state.requests.mine(lea)
                assert asked["state"] == "pending" and asked["size"] == 7 * 10**9

                frame.get_by_role("button", name="Make a wish").first.click()
                dialog = frame.locator("#media-wish")
                dialog.get_by_label("Title").fill("Ponyo")
                dialog.get_by_role("button", name="Send the wish").click()
                expect(dialog).to_be_hidden()

                app.state.requests.move(asked["id"], "refused", "owner", "Already in 4K")
                frame.locator("#media-requests-bell").evaluate(
                    "bell => bell.ownerDocument.defaultView.requestsLoad()"
                )
                expect(frame.locator("#media-requests-bell b")).to_have_text("1")
                frame.locator("#media-requests-bell").click()
                drawer = frame.locator("#media-requests")
                expect(drawer.get_by_text("« Already in 4K »")).to_be_visible()
                expect(drawer.get_by_text("Wish · pending")).to_be_visible()
                expect(frame.locator("#media-requests-bell b")).to_be_hidden()
                drawer.get_by_role("button", name="Cancel the Request").click()
                expect(drawer.get_by_text("Cancelled")).to_be_visible()
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_who_watches_on_a_shared_screen_and_mon_compte(tmp_path):
    """Members 8 (#135): "Cet écran est partagé", "Qui regarde ?" with a PIN, Mon compte."""
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.accounts import Permission

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    accounts = app.state.accounts
    lea = accounts.create(
        "Léa", "lea", {Permission.FILMS, Permission.ANIME}, password="lea-password-long"
    )
    accounts.set_pin(lea, "", "2468")
    accounts.add_viewer(lea, "Hugo", {Permission.FILMS}, 1)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_label("Sign-in name").fill("lea")
                page.get_by_label("Password", exact=True).fill("lea-password-long")
                page.get_by_label("This screen is shared").check()
                page.get_by_label("Name of this screen").fill("Living room TV")
                page.locator("#login-form button.primary").click()

                picker = page.locator("#who-screen")
                expect(picker.get_by_role("heading", name="Who's watching?")).to_be_visible()
                expect(picker.get_by_text("Living room TV")).to_be_visible()
                expect(picker.get_by_role("button", name="Léa, PIN needed")).to_be_focused()
                page.keyboard.press("ArrowRight")
                expect(picker.get_by_role("button", name="Hugo")).to_be_focused()
                page.keyboard.press("Enter")
                expect(picker.get_by_role("heading", name="Enjoy, Hugo")).to_be_visible()
                picker.get_by_role("button", name="Open Media").click()
                page.wait_for_url("**#/media/video")
                navigation = page.frame_locator("#shell-navigation-frame")
                expect(navigation.locator("#pages button")).to_have_text(["Media", "Documentation"])

                navigation.get_by_role("button", name="Change profile").click()
                picker.get_by_role("button", name="Léa, PIN needed").click()
                pad = page.locator("#who-pin")
                for digit in "1111":
                    pad.get_by_role("button", name=digit, exact=True).click()
                pad.get_by_role("button", name="OK").click()
                expect(pad.get_by_text("Incorrect PIN.")).to_be_visible()
                page.keyboard.type("2468")
                page.keyboard.press("Enter")
                expect(picker.get_by_role("heading", name="Enjoy, Léa")).to_be_visible()
                picker.get_by_role("button", name="Open Media").click()
                expect(navigation.locator("#pages button")).to_have_text(
                    ["Media", "Documentation", "Notifications", "Settings"]
                )
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                expect(panel.locator("#settings-navigation button")).to_have_text(
                    ["My account", "Notifications"]
                )
                expect(panel.get_by_text("Living room TV")).to_be_visible()
                expect(panel.get_by_role("heading", name="Hugo")).to_be_visible()
                panel.get_by_role("button", name="Add a profile").click()
                form = panel.locator(".household-form")
                form.get_by_label("Name").fill("Mamie")
                # As broad as Léa, she would need a PIN of her own: Hugo is narrower.
                form.get_by_role("button", name="Save").click()
                expect(panel.locator("#settings-error")).to_contain_text("PIN for Mamie")
                form.get_by_label("Anime").uncheck()
                form.get_by_label("Age limit").select_option(label="Under 10")
                form.get_by_role("button", name="Save").click()
                expect(panel.get_by_role("heading", name="Mamie")).to_be_visible()
                assert [p["name"] for p in accounts.profiles(lea)] == ["Léa", "Hugo", "Mamie"]
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_single_user_server_hides_members_controls(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                expect(page.get_by_label("Sign-in name")).to_be_hidden()
                expect(page.locator("#login-owner")).to_be_hidden()
                expect(page.locator("#login-shared")).to_be_hidden()
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                expect(panel.get_by_role("button", name="Users", exact=True)).to_have_count(0)
                expect(panel.get_by_role("button", name="My account", exact=True)).to_have_count(0)
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_approver_accepts_a_request_and_sees_it_in_history(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.accounts import Permission
    from torrentlinker.member_requests import Release

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    lea = app.state.accounts.create("Lea", "lea", {Permission.REQUEST})
    app.state.requests.ask(
        lea, Release("a" * 40, "Example.2025.1080p", 2 * 1024**3, "Example", "2025")
    )
    app.state.request_approval.send = lambda _hash: None
    app.state.request_approval.release = lambda _hash: Release(
        "a" * 40, "Example.2025.1080p", 2 * 1024**3, "Example", "2025"
    )
    app.state.request_approval.refresh = lambda _requests: None
    app.state.request_approval.margin = lambda pending: {
        "capacity": 20 * 1024**3,
        "downloading": 0,
        "pending": pending,
        "stale": False,
    }
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_role("button", name="I am the owner").click()
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "requests")
                expect(page.locator(".request-inspector h3").first).to_have_text("Example 2025")
                page.screenshot(path="/tmp/tl-requests-approval.png", full_page=True)
                page.get_by_role("button", name="Accept", exact=True).click()
                expect(page.get_by_text("No Requests here.")).to_be_visible()
                page.get_by_role("button", name="History", exact=True).click()
                expect(page.locator(".request-inspector")).to_contain_text("Sent")
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_member_search_can_request_but_cannot_download_directly(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.accounts import Permission

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    app.state.accounts.create(
        "Lea",
        "lea",
        {Permission.FILMS, Permission.SEARCH, Permission.REQUEST, Permission.QUEUE},
        password="lea-password-long",
    )
    app.state.request_approval.choices = lambda q: [
        {"hash": "a" * 40, "name": "Example.2025", "size": 100, "score": 80}
    ]
    app.state.agent_service.media.tracker_entry = lambda client, infohash: {
        "title": "Example",
        "year": "2025",
        "release": {"hash": "a" * 40, "name": "Example.2025", "size": 100},
    }
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_label("Sign-in name").fill("lea")
                page.get_by_label("Password", exact=True).fill("lea-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "member-search")
                page.get_by_label("Film title").fill("Example")
                page.locator("#view-member-search").get_by_role(
                    "button", name="Search", exact=True
                ).click()
                expect(page.get_by_text("Example.2025", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="Download", exact=True)).to_have_count(0)
                page.get_by_role("button", name="Request", exact=True).click()
                expect(page.get_by_role("button", name="Requested", exact=True)).to_be_disabled()
                assert len(app.state.requests.review()) == 1
                shell_navigate(page, "member-queue")
                expect(
                    page.get_by_text("No matching items within your Permissions.")
                ).to_be_visible()
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_member_assistant_shows_private_chat_and_daily_limit(tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tests.test_members_assistant import configured
    from torrentlinker.accounts import Caps, Permission

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    lea = app.state.accounts.create(
        "Lea", "lea", {Permission.ASSISTANT}, password="lea-password-long"
    )
    app.state.accounts.set_caps(lea, Caps(assistant_per_day=1))
    configured(app, monkeypatch)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_label("Sign-in name").fill("lea")
                page.get_by_label("Password", exact=True).fill("lea-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "member-assistant")
                page.get_by_label("Message", exact=True).fill("Hello")
                page.get_by_role("button", name="Send", exact=True).click()
                expect(page.get_by_text("Hello Member", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="Send", exact=True)).to_be_disabled()
                expect(
                    page.get_by_text("0 of 1 messages left today. Resets at server midnight.")
                ).to_be_visible()
                expect(page.get_by_role("button", name="Providers", exact=True)).to_have_count(0)
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_notification_settings_and_private_unread_badge(tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.accounts import Permission

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    lea = app.state.accounts.create(
        "Lea", "lea", {Permission.REQUEST}, password="lea-password-long"
    )
    deliveries = []
    monkeypatch.setattr(
        app.state.notifications, "send_email", lambda *args: deliveries.append(args)
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1400, "height": 1000})
                url = f"http://127.0.0.1:{listener.getsockname()[1]}/"
                page.goto(url)
                page.get_by_role("button", name="I am the owner").click()
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                shell_navigate(page, "setup")
                panel = page.frame_locator("#settings-frame")
                panel.get_by_role("button", name="Notifications", exact=True).click()
                panel.get_by_label("Mail preset").select_option("ovh")
                expect(panel.get_by_label("SMTP server")).to_have_value("ssl0.ovh.net")
                expect(panel.get_by_label("Port", exact=True)).to_have_value("465")
                panel.get_by_label("Enable email", exact=True).check()
                panel.get_by_label("Sender", exact=True).fill("noreply@example.test")
                panel.get_by_label("Public app address").fill("https://app.example.test")
                panel.get_by_label("Test recipient").fill("owner@example.test")
                panel.get_by_role("button", name="Send test email", exact=True).click()
                expect(
                    panel.locator(".tl-toast").get_by_text("Test email sent", exact=True)
                ).to_be_visible()
                assert len(deliveries) == 1
                page.screenshot(path="/tmp/tl-notifications-settings.png", full_page=True)
                app.state.notifications.emit(lea, "accepted", "Private film", "accepted")
                member_page = browser.new_page()
                member_page.goto(url)
                member_page.get_by_label("Sign-in name").fill("lea")
                member_page.get_by_label("Password", exact=True).fill("lea-password-long")
                member_page.locator("#login-form button.primary").click()
                expect(member_page.locator("#notice-count")).to_have_text("Notifications (1)")
                member_page.locator("#notice-count").click()
                expect(
                    member_page.get_by_role("heading", name="Private film", exact=True)
                ).to_be_visible()
                member_page.get_by_role("button", name="Mark as read", exact=True).click()
                expect(member_page.locator("#notice-count")).to_have_text("Notifications")
                member_page.get_by_role("button", name="Notification settings", exact=True).click()
                member_panel = member_page.frame_locator("#settings-frame")
                expect(member_panel.get_by_label("My email address")).to_be_visible()
                expect(member_panel.get_by_label("SMTP server")).to_have_count(0)
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)
