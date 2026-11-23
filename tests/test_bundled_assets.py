"""Packaged data-directory aliases must preserve the strict local asset boundary."""

import pytest

from tests.test_community_interfaces import js, wait_js
from tests.webengine_support import isolated_webengine_render
from torrentlinker.gui.community_view import BundledView, ViewBridge


@pytest.mark.parametrize("symlinked", [False, True])
def test_named_assets_load_through_bundle_alias_and_unnamed_files_stay_blocked(
    qtbot, tmp_path, request, symlinked
):
    if isolated_webengine_render(request):
        return
    static = tmp_path / "Resources" / "static"
    assets = static / "community"
    panel = static / "panel"
    assets.mkdir(parents=True)
    panel.mkdir()
    (assets / "view.html").write_text("""<!doctype html><link rel="stylesheet" href="view.css">
      <link rel="stylesheet" href="../panel/base.css"><main id="proof">Loading</main>
      <script src="../panel/transport.js"></script><script src="view.js"></script>
      <script src="audit.js"></script><script src="inspector.js"></script>
      <script src="unlisted.js"></script><script src="../outside.js"></script>""")
    (assets / "view.css").write_text("#proof {color:rgb(1, 2, 3)}")
    (panel / "base.css").write_text("#proof {background-color:rgb(4, 5, 6)}")
    (panel / "transport.js").write_text("window.sharedAssetLoaded = true;")
    (assets / "view.js").write_text("document.querySelector('#proof').textContent='Rendered';")
    (assets / "audit.js").write_text("window.auditAssetLoaded = true;")
    (assets / "unlisted.js").write_text("window.forbiddenAsset = true;")
    (static / "outside.js").write_text("window.forbiddenAsset = true;")
    supplied = assets
    if symlinked:
        frameworks = tmp_path / "Frameworks"
        frameworks.mkdir()
        alias = frameworks / "static"
        try:
            alias.symlink_to(static, target_is_directory=True)
            (assets / "inspector.js").symlink_to(static / "outside.js")
        except OSError:
            pytest.skip("Directory symlinks unavailable on this host")
        supplied = alias / "community"
    view = BundledView(ViewBridge(), supplied, "community")
    qtbot.addWidget(view)
    view.resize(640, 400)
    view.show()
    try:
        wait_js(qtbot, view, "document.querySelector('#proof')?.textContent === 'Rendered'")
        assert js(qtbot, view, "window.sharedAssetLoaded === true")
        assert js(qtbot, view, "window.auditAssetLoaded === true")
        assert (
            js(qtbot, view, "getComputedStyle(document.querySelector('#proof')).color")
            == "rgb(1, 2, 3)"
        )
        assert (
            js(qtbot, view, "getComputedStyle(document.querySelector('#proof')).backgroundColor")
            == "rgb(4, 5, 6)"
        )
        assert js(qtbot, view, "typeof window.forbiddenAsset === 'undefined'")
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineCore import QWebEnginePage

        assert not view.web.page().acceptNavigationRequest(
            QUrl.fromLocalFile(str(supplied / "unlisted.js")),
            QWebEnginePage.NavigationType.NavigationTypeOther,
            True,
        )
    finally:
        view.close()


def test_packaged_smoke_renders_the_real_shared_header(qtbot, request):
    if isolated_webengine_render(request):
        return
    from torrentlinker.webview_smoke import webview_smoke_checks

    webview_smoke_checks()
