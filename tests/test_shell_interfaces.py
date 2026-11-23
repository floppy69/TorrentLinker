"""Shared shell ownership, keyboard help and rendering."""

import json
import os
from pathlib import Path

import pytest

from torrentlinker.config import Settings
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.gui.shell_view import ShellView
from torrentlinker.store import Store


def test_aggregate_client_scope_ends_before_leaving_torrents(qtbot, tmp_path):
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(window)
    with pytest.raises(ValueError, match="Torrents"):
        window.shell_host.command("client", {"client_id": "all"})
    window.shell_host.command("navigate", {"view": "torrents"})
    window.shell_host.command("client", {"client_id": "all"})
    assert window.torrents_tab.target_client == "all"
    window.shell_host.command("navigate", {"view": "library"})
    assert window.torrents_tab.target_client == window.settings.active_client_id
    assert window.shell_host.snapshot()["client_id"] != "all"
    window.close()


def test_refused_client_switch_preserves_aggregate_scope(qtbot, tmp_path, monkeypatch):
    settings = Settings()
    other = settings.add_client("Seedbox")
    window = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(window)
    window.shell_host.command("navigate", {"view": "torrents"})
    window.shell_host.command("client", {"client_id": "all"})
    monkeypatch.setattr(window, "_select_client", lambda identifier: None)
    window.shell_host.command("client", {"client_id": other.id})
    assert window.shell_host.snapshot()["client_id"] == "all"
    assert window.torrents_tab.target_client == "all"
    window.close()


def test_shell_renders_bilingual_navigation_and_client_selector(qtbot, request):
    from tests.test_community_interfaces import js, wait_js
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    state = {
        "language": "en",
        "theme": "dark",
        "page": "torrents",
        "pages": ["zen", "torrents", "documentation", "setup"],
        "clients": [{"id": "studio", "name": "Studio"}],
        "client_id": "studio",
        "allow_all": True,
    }
    commands = []
    view = ShellView(
        "header", lambda: state, lambda action, values: commands.append((action, values))
    )
    qtbot.addWidget(view)
    view.resize(760, 120)
    view.show()
    wait_js(qtbot, view, "document.querySelector('#target-client option[value=studio]') !== null")
    js(
        qtbot,
        view,
        "document.getElementById('target-client').value='all'; "
        "document.getElementById('target-client').dispatchEvent(new Event('change'))",
    )
    qtbot.waitUntil(lambda: bool(commands))
    assert commands == [("client", {"client_id": "all"})]
    for language, theme, label in [
        ("en", "dark", "Target client"),
        ("fr", "light", "Client cible"),
    ]:
        state.update(language=language, theme=theme)
        view.refresh()
        wait_js(
            qtbot,
            view,
            f"document.getElementById('client-title').textContent === {json.dumps(label)}",
        )
        for width in [760, 390]:
            view.resize(width, view.height())
            qtbot.wait(100)
            assert js(qtbot, view, "document.documentElement.scrollWidth <= innerWidth")
            if folder := os.getenv("TL_SHELL_SCREENSHOTS"):
                Path(folder).mkdir(parents=True, exist_ok=True)
                assert view.grab().save(str(Path(folder) / f"shell-{language}-{theme}-{width}.png"))
    state.update(page="library", allow_all=False)
    view.refresh()
    wait_js(qtbot, view, "document.querySelector('#target-client option[value=all]') === null")
    state.update(profile_problem="missing-scope", language="fr")
    view.refresh()
    wait_js(
        qtbot, view, "document.getElementById('profile-notice').textContent.includes('nécessite')"
    )
    view.close()


def test_desktop_shell_navigation_help_and_band_fit(qtbot, qapp, request, tmp_path):
    from tests.test_community_interfaces import js, wait_js
    from tests.webengine_support import isolated_webengine_render
    from torrentlinker.gui.theme import apply_theme

    if isolated_webengine_render(request):
        return
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(window)
    window.resize(1100, 800)
    window.show()
    wait_js(
        qtbot, window.navigation, "document.querySelector('[data-view=documentation]') !== null"
    )
    js(qtbot, window.navigation, "document.querySelector('[data-view=documentation]').click()")
    qtbot.waitUntil(lambda: window.shell_host.page() == "documentation")
    js(qtbot, window.navigation, "document.getElementById('shortcuts').click()")
    qtbot.waitUntil(lambda: window.shell_host.help_dialog is not None)
    help_view = window.shell_host.help_dialog.findChild(ShellView)
    wait_js(qtbot, help_view, "document.getElementById('help-keys').textContent.includes('Ctrl+8')")
    js(qtbot, help_view, "document.getElementById('help-close').click()")
    qtbot.waitUntil(lambda: not window.shell_host.help_dialog.isVisible())
    # The real Assistant view keeps unsent per-conversation drafts in memory.
    assistant = window.assistant_tab
    assistant._load_view()
    wait_js(qtbot, assistant, "typeof assistantDrafts !== 'undefined'")
    js(qtbot, assistant, "assistantDrafts.set('draft-conversation', 'Keep this unsent message')")
    window.shell_host.command("navigate", {"view": "zen"})
    window.band.set_balance(3080)
    for language, theme in [("en", "dark"), ("fr", "light")]:
        window._change_language(language)
        assert window.assistant_tab is assistant
        assert (
            js(qtbot, assistant, "assistantDrafts.get('draft-conversation')")
            == "Keep this unsent message"
        )
        window.settings.theme = theme
        apply_theme(qapp, theme)
        window.shell_host.refresh()
        window.band.refresh()
        wait_js(qtbot, window.navigation, f"document.documentElement.dataset.theme === '{theme}'")
        for width in (1100, 600):
            window.resize(width, 800)
            qtbot.wait(150)
            wait_js(
                qtbot,
                window.navigation,
                f"document.body.dataset.compact === '{str(width < 650).lower()}'",
            )
            for view in (window.navigation, window.app_header, window.band):
                assert js(qtbot, view, "document.documentElement.scrollWidth <= innerWidth")
                assert view.isVisible()
            assert window.band.width() > 200
            if folder := os.getenv("TL_SHELL_SCREENSHOTS"):
                Path(folder).mkdir(parents=True, exist_ok=True)
                window.grab().save(str(Path(folder) / f"desktop-{language}-{theme}-{width}.png"))
    window._change_language("en")
    window.close()
