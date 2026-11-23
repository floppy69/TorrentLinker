import pytest

from torrentlinker import documentation as docs
from torrentlinker.config import Settings
from torrentlinker.gui.documentation import DocumentationTab
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def test_offline_guides_links_history_language_and_images(qtbot):
    from tests.test_community_interfaces import js, wait_js

    tab = DocumentationTab("en")
    qtbot.addWidget(tab)
    tab.resize(1100, 750)
    tab.show()
    wait_js(
        qtbot,
        tab,
        "document.querySelector('#guide-content')?.textContent.includes('Install and configure')",
    )
    js(qtbot, tab, "document.querySelector('[data-guide-path=\"guide/en/torrents.md\"]').click()")
    wait_js(
        qtbot, tab, "document.querySelector('#guide-content h1')?.textContent==='Manage torrents'"
    )
    wait_js(
        qtbot,
        tab,
        "[...document.querySelectorAll('#guide-content img')]"
        ".some(i=>i.complete&&i.naturalWidth>0)",
    )
    assert js(
        qtbot,
        tab,
        "[...document.querySelectorAll('#guide-content img')].every(i=>i.width<=innerWidth)",
    )
    js(qtbot, tab, "document.querySelector('#guide-back').click()")
    wait_js(
        qtbot,
        tab,
        "document.querySelector('#guide-content h1')?.textContent==='Install and configure'",
    )
    js(qtbot, tab, "document.querySelector('#guide-forward').click()")
    wait_js(
        qtbot, tab, "document.querySelector('#guide-content h1')?.textContent==='Manage torrents'"
    )
    js(
        qtbot,
        tab,
        "document.querySelector('#guide-language').value='fr';"
        "document.querySelector('#guide-language').dispatchEvent(new Event('change'))",
    )
    wait_js(
        qtbot,
        tab,
        "document.querySelector('#guide-content h1')?.textContent==='Gérer les torrents'",
    )
    js(
        qtbot,
        tab,
        "document.querySelector('#guide-filter').value='torrents';"
        "document.querySelector('#guide-filter').dispatchEvent(new Event('input'))",
    )
    assert js(
        qtbot, tab, "document.querySelector('[data-guide-path=\"guide/fr/demarrage.md\"]').hidden"
    )
    assert js(
        qtbot, tab, "!document.querySelector('[data-guide-path=\"guide/fr/torrents.md\"]').hidden"
    )


def test_documentation_navigation_without_connections(qtbot, tmp_path):
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "store.db"))
    qtbot.addWidget(window)
    window.shell_host.command("navigate", {"view": "documentation"})
    guide = window.documentation_tab
    assert window.tabs.currentWidget() is guide
    assert window.shell_host.page() == "documentation"
    assert window.shell_host.page() != "reading"
    assert window.reading_room is None
    window.tabs.setCurrentIndex(1)
    assert window.shell_host.page() != "documentation"
    window.shell_host.command("navigate", {"view": "documentation"})
    assert window.documentation_tab is guide
    window._lock_reading_room()
    assert window.tabs.currentWidget() is guide


@pytest.mark.parametrize("name", ["../pyproject.toml", "research/secrets.md", "/etc/passwd"])
def test_documentation_rejects_non_public_paths(name):
    with pytest.raises(ValueError):
        docs.document_path(name)


def test_installed_documentation_lookup(monkeypatch, tmp_path):
    guide = tmp_path / "share/torrentlinker/docs/guide/en/getting-started.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("# Installed guide")
    monkeypatch.setattr(docs.sys, "_MEIPASS", tmp_path / "missing", raising=False)
    monkeypatch.setattr(docs.sys, "prefix", str(tmp_path))
    assert docs.document_path("guide/en/getting-started.md") == guide


def test_guide_keeps_scroll_and_content_after_resizing(qtbot):
    from tests.test_community_interfaces import js, wait_js

    tab = DocumentationTab("en")
    qtbot.addWidget(tab)
    tab.resize(1070, 735)
    tab.show()
    tab.open_guide("guide/en/web-docker.md")
    wait_js(qtbot, tab, "document.querySelector('#guide-content')?.textContent.includes('Docker')")
    js(qtbot, tab, "window.scrollTo(0,300)")
    tab.resize(760, 620)
    qtbot.wait(700)
    assert js(qtbot, tab, "window.scrollY>0")
    assert js(qtbot, tab, "document.querySelector('#guide-content').textContent.includes('Docker')")
