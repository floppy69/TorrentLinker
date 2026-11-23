"""RSS operations through the real bundled desktop view."""

import os
import subprocess
import sys


def test_desktop_rss_shared_editor_and_saved_selection(qtbot, tmp_path, monkeypatch, request):
    if not os.getenv("TL_RSS_NATIVE_CHILD"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
            env={
                **os.environ,
                "TL_RSS_NATIVE_CHILD": "1",
                "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu",
                "QT_QUICK_BACKEND": "software",
            },
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from tests.test_community_interfaces import js, wait_js
    from tests.test_feeds import Source, release
    from torrentlinker.downloads import IndexerCategory
    from torrentlinker.feeds import Subscription
    from torrentlinker.gui.feeds import FeedsTab
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path / "config", password="test-password-long")
    control = app.state.agent_service.feed_control
    source = Source()
    source.rows = [release(title="Book", categories=(7020,), metadata={"format": "EPUB"})]
    control.feeds.indexer = lambda: source
    control.service.setup.settings.language = "en"
    control.service.setup.settings.indexer_categories = {7020: IndexerCategory("Books")}
    saved = control.feeds.save(Subscription(name="Books", categories=[7020]))
    control.feeds.refresh(saved.id)
    tab = FeedsTab(lambda: control)
    qtbot.addWidget(tab)
    tab.resize(1280, 900)
    tab.show()
    wait_js(qtbot, tab, "document.querySelector('#feeds-results').textContent.includes('Book')")
    js(qtbot, tab, "document.querySelector('#feeds-results tbody input').click()")
    wait_js(qtbot, tab, "document.querySelector('#feeds-count').textContent.includes('1 selected')")
    tab.edit(query="book")
    wait_js(qtbot, tab, "document.querySelector('.feed-editor')!==null")
    js(qtbot, tab, "document.querySelector('[aria-controls=criteria-legend]').click()")
    wait_js(qtbot, tab, "!document.querySelector('#criteria-legend').hidden")
    assert "Require" in js(qtbot, tab, "document.querySelector('#criteria-legend').textContent")
    if folder := os.getenv("TL_RSS_SCREENSHOTS"):
        from pathlib import Path

        Path(folder).mkdir(parents=True, exist_ok=True)
        tab.grab().save(str(Path(folder) / "rss-desktop.png"))
    tab.close()
    control.close()
