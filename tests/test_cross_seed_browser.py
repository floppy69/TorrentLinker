"""The Cross-seed tab and the Indexers Settings section in an actual browser. The Torrent
Client, the Indexers and Prowlarr are all simulated: nothing here reaches a real one."""

import os
import socket
import threading
import time

import pytest

from tests.shell_support import shell_navigate
from tests.test_reseed_workspace_browser import reseed_app
from torrentlinker import indexer_hub
from torrentlinker.config import IndexerSettings
from torrentlinker.indexer import Caps, SearchMode
from torrentlinker.web.setup import Setup

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")


class Served:
    """The app on a free local port, in a thread."""

    def __init__(self, app):
        import uvicorn

        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.listener]}, daemon=True
        )

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.02)
        return f"http://127.0.0.1:{self.listener.getsockname()[1]}/"

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)
        self.listener.close()


def seed_rows(board, original):
    store = board.setup.store
    board.setup.settings.indexers.append(
        IndexerSettings("https://n.example/api", "nebula", "Nebula", True)
    )
    board.setup.secrets.update({"indexer-key-nebula": "KEY"})
    board.setup.save()
    item = str(original)
    base = {"origin": "torrent", "item_path": item, "size": 7 * 1024**3}
    store.save_crossseed(
        "torrent:a",
        "nebula",
        "k-added",
        "added",
        {**base, "name": "Dune", "title": "Dune.Part.Two.2024", "coverage": 1.0, "full": True},
    )
    store.save_crossseed(
        "torrent:b",
        "nebula",
        "k-partial",
        "review",
        {
            **base,
            "name": "The Bear",
            "title": "The.Bear.S03",
            "coverage": 0.88,
            "full": False,
            "missing": ["S03E09.mkv", "S03E10.mkv"],
            "reason": "Partial Match covering 88%, under the 95% threshold",
        },
    )
    store.save_crossseed(
        "item:c",
        "nebula",
        "k-archive",
        "review",
        {
            **base,
            "origin": "item",
            "name": "Monte-Cristo",
            "title": "Le.Comte.de.Monte-Cristo.2024",
            "coverage": 1.0,
            "full": True,
            "archive": True,
            "reason": "The Match is inside an archive",
        },
    )
    store.save_crossseed(
        "torrent:d",
        "nebula",
        "k-failed",
        "failed",
        {**base, "name": "Anora", "title": "Anora.2024", "coverage": 1.0, "reason": "Verified 92%"},
    )
    store.save_crossseed(
        "torrent:e", "nebula", "", "queued", {"name": "Oppenheimer", "origin": "torrent"}
    )


def test_the_cross_seed_tab_filters_inspects_dismisses_and_sends_archives_to_unpack(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    app, board, _, original, _, _ = reseed_app(tmp_path, monitor_verifications=False)
    seed_rows(board, original)
    with Served(app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="fr-FR")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{url}#/library/reseed")
        page.locator("#login-password").fill("test-password-long")
        page.locator("#login-form button").click()
        frame = page.frame_locator("#reseed-frame")
        expect(frame.locator(".torrent")).to_contain_text(original.name)
        tabs = frame.locator(".tabs button[data-tab]")
        assert tabs.all_inner_texts()[:2] == ["Remise en seed", "Cross-seed"]

        frame.get_by_role("button", name="Cross-seed", exact=True).click()
        expect(frame.locator(".running")).to_contain_text("Cross-seed actif")
        expect(frame.locator(".running")).to_contain_text("≥ 95 %")
        expect(frame.locator(".stage").first).to_contain_text("5")
        expect(frame.locator("[data-cross]")).to_have_count(5)
        expect(frame.locator("[data-cross-filter=review] b")).to_have_text("2")

        frame.locator("[data-cross-filter=failed]").click()
        expect(frame.locator("[data-cross]")).to_have_count(1)
        frame.locator("[data-cross]").click()
        expect(frame.locator("[data-cross-do=retry]")).to_be_visible()
        frame.locator("[data-cross-filter=review]").click()
        frame.locator("[data-cross]", has_text="The.Bear.S03").click()
        inspector = frame.locator(".inspector")
        expect(inspector).to_contain_text("88 % présents")
        expect(inspector).to_contain_text("sous le seuil de 95 %")
        expect(inspector.locator(".files .miss")).to_have_count(2)
        expect(inspector.locator(".files")).to_contain_text("absent · ignoré")
        expect(
            inspector.get_by_role("button", name="Ajouter sans les fichiers manquants")
        ).to_be_visible()
        expect(inspector).to_contain_text("Tags « cross-seed » et « Nebula »")

        frame.locator("[data-cross-do=reject]").click()
        expect(frame.locator("[data-cross]")).to_have_count(1)

        archive = frame.locator("[data-cross]", has_text="Monte-Cristo")
        archive.click()
        expect(frame.locator("[data-cross-do=accept]")).to_have_count(0)
        frame.get_by_role("button", name="Décompresser et remettre en seed").click()
        expect(frame.locator(".tabs button.on")).to_have_text("Remise en seed")
        expect(frame.locator(".inspector")).to_contain_text(original.name)

        page.frame_locator("#shell-navigation-frame").locator("#language").select_option("en")
        frame.get_by_role("button", name="Cross-seed", exact=True).click()
        expect(frame.locator(".running")).to_contain_text("Cross-seed active")
        expect(frame.get_by_role("button", name="Dismiss", exact=True)).to_be_visible()
        assert not errors
        browser.close()


def test_cross_seed_and_board_buttons_are_busy_while_they_run(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    app, board, _, original, _, _ = reseed_app(tmp_path, monitor_verifications=False)
    seed_rows(board, original)
    with Served(app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="fr-FR")
        page.goto(f"{url}#/library/reseed")
        page.locator("#login-password").fill("test-password-long")
        page.locator("#login-form button").click()
        frame = page.frame_locator("#reseed-frame")
        expect(frame.locator(".torrent")).to_contain_text(original.name)
        held = []
        holding = [False]
        page.route(
            "**/api/reseed-workspace*",
            lambda route: held.append(route) if holding[0] else route.continue_(),
        )
        refresh = frame.locator('[data-command="refresh"]')
        holding[0] = True
        refresh.click()
        expect(refresh).to_be_disabled()
        expect(refresh).to_have_attribute("aria-busy", "true")
        expect(refresh).to_have_text("En cours…")
        holding[0] = False
        for route in held:
            route.continue_()
        expect(refresh).to_be_enabled()
        expect(refresh).to_have_text("Actualiser")
        frame.get_by_role("button", name="Cross-seed", exact=True).click()
        frame.locator("[data-cross-filter=review]").click()
        frame.locator("[data-cross]", has_text="The.Bear.S03").click()
        held.clear()
        holding[0] = True
        dismiss = frame.locator("[data-cross-do=reject]")
        dismiss.click()
        expect(dismiss).to_be_disabled()
        expect(dismiss).to_have_attribute("aria-busy", "true")
        holding[0] = False
        for route in held:
            route.continue_()
        expect(frame.locator("[data-cross]")).to_have_count(1)
        browser.close()


def test_the_indexers_section_adds_tests_imports_and_sets_the_rules(tmp_path, monkeypatch):
    from playwright.sync_api import expect, sync_playwright

    app, board, _, original, _, _ = reseed_app(tmp_path, monitor_verifications=False)
    caps = Caps({}, {SearchMode.MOVIE: {"q", "imdbid", "tmdbid"}})
    monkeypatch.setattr(Setup, "_probe", lambda self, url, key, name: caps)
    hub = [
        indexer_hub.HubIndexer("1", "Lyra", "http://prowlarr:9696/1/api"),
        indexer_hub.HubIndexer("2", "Altair", "http://prowlarr:9696/2/api"),
    ]
    monkeypatch.setattr(indexer_hub, "list_indexers", lambda *args: hub)
    with Served(app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1000}, locale="fr-FR")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.locator("#login-password").fill("test-password-long")
        page.locator("#login-form button").click()
        shell_navigate(page, "setup")
        panel = page.frame_locator("#settings-frame")
        nav = panel.locator("#settings-navigation button")
        expect(nav.nth(0)).to_be_visible()
        names = nav.all_inner_texts()
        assert names.index("Indexeurs") == names.index("ReleaseScore") + 1
        panel.get_by_role("button", name="Indexeurs", exact=True).click()

        c411 = panel.locator(".indexer-card.locked")
        expect(c411).to_contain_text("Intégré")
        expect(c411.get_by_role("button", name="Retirer")).to_have_count(0)

        panel.get_by_role("button", name="Ajouter un indexeur Torznab").click()
        dialog = panel.locator("#indexer-dialog")
        dialog.get_by_label("Nom", exact=True).fill("Vega")
        dialog.get_by_label("Adresse Torznab", exact=True).fill("https://vega.example/api")
        dialog.get_by_label("Clé API", exact=True).fill("secret")
        dialog.get_by_role("button", name="Tester").click()
        expect(dialog.locator("#indexer-caps")).to_contain_text("IMDb, TMDb")
        assert [i.name for i in board.setup.settings.indexers] == ["c411"]  # a test saves nothing
        dialog.get_by_role("button", name="Ajouter", exact=True).click()
        card = panel.locator(".indexer-card", has_text="Vega")
        expect(card).to_contain_text("Ajouté à la main")
        expect(card).to_contain_text("Connecté")
        card.get_by_label("Chercher sur cet indexeur").uncheck()
        expect(card).to_contain_text("Désactivé")

        panel.locator("#indexer-hub").get_by_label("Adresse").fill("http://prowlarr:9696")
        panel.locator("#indexer-hub").get_by_label("Clé API", exact=True).fill("hubkey")
        panel.get_by_role("button", name="Connecter").click()
        panel.locator("[data-import='1']").check()
        panel.get_by_role("button", name="Importer la sélection").click()
        expect(panel.locator(".indexer-card", has_text="Lyra")).to_contain_text("Prowlarr")
        expect(panel.locator("[data-import='1']")).to_be_disabled()
        panel.get_by_role("button", name="Resynchroniser").click()
        expect(panel.locator("#settings-status")).to_contain_text("Resynchronisé")

        rules = panel.locator("#cross-seed-rules")
        slider = rules.locator("#cross-seed-threshold")
        slider.fill("90")
        expect(rules.locator("#cross-seed-threshold-value")).to_have_text("90 %")
        expect(
            rules.get_by_label("Ajouter automatiquement les correspondances sûres")
        ).to_be_checked()
        rules.get_by_label("Ajouter automatiquement les correspondances sûres").uncheck()
        expect(slider).to_be_disabled()
        rules.get_by_role("button", name="Suspendre le cross-seed").click()
        expect(rules.get_by_role("button", name="Reprendre le cross-seed")).to_be_visible()

        saved = board.setup.settings.cross_seed
        assert (saved.threshold, saved.auto_add, saved.paused) == (0.9, False, True)
        assert {i.name for i in board.setup.settings.indexers} >= {"Vega", "Lyra"}
        assert not errors
        browser.close()
