"""Desktop uses the same achievement controls and the running owner's service."""

from tests.test_community_interfaces import js, wait_js
from tests.test_web_plan_execution import prepared
from torrentlinker.gui.settings_view import SettingsView
from torrentlinker.settings_workspace import SettingsWorkspace


def test_native_collection_and_missing_consent_error(qtbot, tmp_path, request, monkeypatch):
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    _, setup, _, _ = prepared(tmp_path)
    view = SettingsView(SettingsWorkspace(setup), section="community_site")
    qtbot.addWidget(view)
    view.resize(1200, 850)
    view.show()
    wait_js(qtbot, view, "Boolean(document.querySelector('.achievement-grid'))")
    assert js(qtbot, view, "document.querySelectorAll('.achievement-grid > div').length") == 8
    js(
        qtbot,
        view,
        "[...document.querySelectorAll('button')].find("
        "b=>b.textContent==='Share future achievements').click()",
    )
    wait_js(
        qtbot,
        view,
        "document.querySelector('#settings-error').textContent.includes('Link this app')",
    )
    assert (
        js(
            qtbot,
            view,
            "Boolean([...document.querySelectorAll('button')].find("
            "b=>b.textContent==='Share earned achievements too'))",
        )
        is False
    )
    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    js(
        qtbot,
        view,
        "communitySiteSettings(document.querySelector('.achievement-grid').parentElement, "
        "{linked:true, site:'https://torrentlinker.fr', expires:1800000000})",
    )
    wait_js(qtbot, view, "Boolean(document.querySelector('a[href$=\"/space/account\"]'))")
    js(qtbot, view, "document.querySelector('a[href$=\"/space/account\"]').click()")
    qtbot.waitUntil(lambda: bool(opened))
    assert opened == ["https://torrentlinker.fr/en/space/account"]
