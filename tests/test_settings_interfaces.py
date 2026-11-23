"""The desktop embeds the same owner Settings editor as the browser."""

import json

from tests.test_community_interfaces import js, wait_js
from tests.test_web_plan_execution import prepared
from torrentlinker.gui.settings_view import SettingsView
from torrentlinker.settings_workspace import SettingsWorkspace


def test_desktop_connections_keep_drafts_and_save_without_exposing_saved_secrets(qtbot, tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    setup.secrets.update({"tmdb-api-key": "private-existing-key"})
    view = SettingsView(SettingsWorkspace(setup))
    qtbot.addWidget(view)
    view.resize(1200, 800)
    view.show()
    wait_js(qtbot, view, "Boolean(document.querySelector('[aria-label=\"Client name\"]'))")
    js(
        qtbot,
        view,
        """
        const input = document.querySelector('[aria-label="Client name"]');
        input.value='Desktop draft';input.dispatchEvent(new Event('input'));
        [...document.querySelectorAll('nav button')].find(b=>b.textContent==='Clients').click();
    """,
    )
    js(
        qtbot,
        view,
        "[...document.querySelectorAll('nav button')].find("
        "b=>b.textContent==='Connections').click()",
    )
    assert (
        js(qtbot, view, "document.querySelector('[aria-label=\"Client name\"]').value")
        == "Desktop draft"
    )
    tmdb = "document.querySelector('[aria-label=\"TMDb API key\"]')"
    assert js(qtbot, view, f"{tmdb}.value") == "••••••••"
    # The eye asks the desktop bridge for the one saved value, and hides it again.
    js(qtbot, view, "document.querySelector('[aria-label=\"Show TMDb API key\"]').click()")
    wait_js(qtbot, view, f"{tmdb}.value==={json.dumps(setup.secrets.get('tmdb-api-key'))}")
    assert setup.secrets.get("tmdb-api-key")
    js(qtbot, view, "document.querySelector('[aria-label=\"Hide TMDb API key\"]').click()")
    wait_js(qtbot, view, f"{tmdb}.value==='••••••••' && {tmdb}.type==='password'")
    js(
        qtbot,
        view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Save').click()",
    )
    wait_js(
        qtbot, view, "document.querySelector('#settings-status').textContent==='Settings saved'"
    )
    assert SettingsWorkspace(setup).snapshot()["connections"]["client"]["name"] == "Desktop draft"


def test_native_settings_service_sections_use_shared_controls(qtbot, tmp_path):
    from torrentlinker.web.app import create_app

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    view = SettingsView(
        SettingsWorkspace(setup),
        assistant_service=lambda: app.state.assistant,
        agent_service=lambda: app.state.agent_service,
        agent_endpoint="http://127.0.0.1:9999/mcp/",
        companion_action=lambda body: {"paired": False, "downloads": {}},
    )
    qtbot.addWidget(view)
    view.resize(1200, 800)
    view.show()
    wait_js(qtbot, view, "Boolean(document.querySelector('[aria-label=\"Client name\"]'))")
    for section, selector in (
        ("Assistant", "#assistant-connections-body button"),
        ("Companion", ".settings-card button"),
        ("Agent access", "#agent-clients input"),
    ):
        js(
            qtbot,
            view,
            "[...document.querySelectorAll('#settings-navigation button')]"
            f".find(b=>b.textContent==='{section}').click()",
        )
        wait_js(qtbot, view, f"Boolean(document.querySelector('{selector}'))")
        assert js(qtbot, view, "document.querySelector('#settings-error').textContent") == ""
    assert js(qtbot, view, "document.querySelector('#agents-endpoint').textContent").endswith(
        "/mcp/"
    )


def test_settings_page_fits_work_area_and_renders_both_themes(qtbot, tmp_path, request):
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return

    import os
    from pathlib import Path

    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from torrentlinker.config import Settings
    from torrentlinker.gui.settings_view import SettingsPage
    from torrentlinker.store import Store

    class Host(QWidget):
        def __init__(self):
            super().__init__()
            self.settings = Settings(language="en", theme="dark")
            self.settings_path = tmp_path / "settings.json"
            self.store = Store(tmp_path / "state.db")

        def _export_diagnostics(self, parent):
            pass

    owner = Host()
    qtbot.addWidget(owner)
    dialog = SettingsPage(owner)
    QVBoxLayout(owner).addWidget(dialog)
    owner.resize(1200, 850)
    owner.show()
    view = dialog.view
    wait_js(qtbot, view, "Boolean(document.querySelector('[aria-label=\"Client name\"]'))")
    wait_js(
        qtbot,
        view,
        "document.querySelector('.settings-form > .settings-actions')"
        ".getBoundingClientRect().bottom <= innerHeight",
    )
    output = os.getenv("TL_SETTINGS_SCREENSHOTS")
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
        qtbot.wait(250)
        dialog.grab().save(str(Path(output) / "settings-desktop-en-dark.png"))
    dialog.setup.settings.language = "fr"
    dialog.setup.settings.theme = "light"
    view.refresh()
    wait_js(
        qtbot,
        view,
        "document.documentElement.lang==='fr' && document.documentElement.dataset.theme==='light'",
    )
    assert js(qtbot, view, "document.querySelector('#settings-title').textContent") == "Paramètres"
    if output:
        qtbot.wait(250)
        dialog.grab().save(str(Path(output) / "settings-desktop-fr-light.png"))


def test_automatic_library_grouping_survives_editing_another_field(qtbot, tmp_path):
    from tests.settings_support import edit_field, settings_page
    from torrentlinker.config import Settings
    from torrentlinker.domain import LibraryFolder

    folder = tmp_path / "library"
    folder.mkdir()
    settings = Settings(language="en", library_folders=[LibraryFolder(folder, None)])
    dialog = settings_page(qtbot, tmp_path, settings, section="library")
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Edit').click()",
    )
    assert (
        js(qtbot, dialog.view, "document.querySelector('[aria-label=\"Grouping depth\"]').value")
        == "auto"
    )
    edit_field(qtbot, dialog.view, "Content kind", "ebook")
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='Save folder').click()",
    )
    qtbot.waitUntil(lambda: dialog.setup.path.exists())
    qtbot.waitUntil(lambda: dialog.view.pending == 0)
    assert Settings.load(dialog.setup.path).library_folders[0].depth is None


def test_native_settings_file_access_uses_transfer_service(qtbot, tmp_path):
    from tests.test_settings_file_access import access_body
    from torrentlinker.web.app import create_app

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    service = app.state.agent_service.torrents_workspace
    body = access_body()
    service.request("transfer-access-save", {"client_id": "default", **body})
    view = SettingsView(SettingsWorkspace(setup), agent_service=lambda: app.state.agent_service)
    qtbot.addWidget(view)
    view.resize(1200, 900)
    view.show()
    wait_js(
        qtbot,
        view,
        "document.querySelector('#file-access-card')?.textContent.includes('seedbox.invalid')",
    )
    js(qtbot, view, "document.querySelector('#file-access-card button').click()")
    wait_js(qtbot, view, "document.querySelector('#remote-host')?.value === 'seedbox.invalid'")
    assert js(qtbot, view, "document.querySelector('#remote-credential').value") == ""
    js(
        qtbot,
        view,
        "document.querySelector('#remote-credential').value = 'discard-this'; "
        "document.querySelector('#remote-done').click()",
    )
    wait_js(qtbot, view, "!document.querySelector('#file-access-editor')")
    js(qtbot, view, "document.querySelector('#file-access-card button').click()")
    wait_js(qtbot, view, "Boolean(document.querySelector('#remote-credential'))")
    assert js(qtbot, view, "document.querySelector('#remote-credential').value") == ""
    service.remote.close()


def test_desktop_release_score_editor_persists_custom_profile(qtbot, tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    view = SettingsView(SettingsWorkspace(setup))
    qtbot.addWidget(view)
    view.resize(1200, 900)
    view.show()
    wait_js(qtbot, view, "Boolean(document.querySelector('#settings-navigation button'))")
    js(
        qtbot,
        view,
        "[...document.querySelectorAll('#settings-navigation button')].fin"
        "d(b=>b.textContent==='ReleaseScore').click()",
    )
    wait_js(qtbot, view, "Boolean(document.querySelector('[aria-label=\"Edit profile\"]'))")
    js(
        qtbot,
        view,
        "document.querySelector('[aria-label=\"Profile name\"]').value='Desk"
        "top cinema';[...document.querySelectorAll('button')].find(b=>b.te"
        "xtContent==='New').click()",
    )
    js(
        qtbot,
        view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==="
        "'Save ReleaseScore').click()",
    )
    wait_js(
        qtbot, view, "document.querySelector('#settings-status').textContent==='ReleaseScore saved'"
    )
    assert "Desktop cinema" in setup.settings.release_score["profiles"]
    js(
        qtbot,
        view,
        'const select=document.querySelector(\'[aria-label="Active profile"'
        "]');select.value='Desktop cinema';select.dispatchEvent(new Event("
        "'change'))",
    )
    qtbot.waitUntil(lambda: setup.settings.release_score["active"] == "Desktop cinema")
    from torrentlinker.config import Settings

    assert Settings.load(setup.path).release_score["active"] == "Desktop cinema"
