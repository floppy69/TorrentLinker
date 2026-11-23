from tests import test_catalogue_selection
from tests.test_agent_access import call

catalogue_app = test_catalogue_selection.catalogue_app


def invoke(browser, token, name, **arguments):
    result = call(browser, token, name, arguments)
    assert not result.get("isError"), result
    return result["structuredContent"]


def test_shared_documentation_search_and_bounded_section_read(catalogue_app):
    _, browser, token = catalogue_app
    result = invoke(
        browser, token, "search_documentation", query="download queue", language="en", limit=3
    )
    assert 0 < len(result["rows"]) <= 3
    assert result["app_version"]
    row = next(r for r in result["rows"] if r["document_id"] == "agents")
    assert row["language"] == "en"
    assert len(row["snippet"]) <= 500
    read = invoke(
        browser,
        token,
        "read_documentation",
        document_id=row["document_id"],
        language="en",
        section_id=row["section_id"],
        limit=250,
    )
    assert len(read["content"]) <= 250
    assert len(read["content_sha256"]) == 64
    assert read["source_kind"] == "source-checkout"
    assert read["reference_url"].endswith("#" + row["section_id"])
    assert read["online_reference_matches_loaded_content"] is False
    assert read["content"]
    if read["next_offset"] is not None:
        continued = invoke(
            browser,
            token,
            "read_documentation",
            document_id=row["document_id"],
            language="en",
            section_id=row["section_id"],
            offset=read["next_offset"],
            limit=250,
        )
        assert continued["content"] != read["content"]


def test_french_docs_no_match_and_path_traversal(catalogue_app):
    _, browser, token = catalogue_app
    french = invoke(
        browser, token, "search_documentation", query="client torrent", language="fr", limit=2
    )
    assert french["rows"]
    assert all(r["language"] == "fr" for r in french["rows"])
    assert (
        invoke(
            browser,
            token,
            "search_documentation",
            query="impossible-synthetic-query-938472",
            language="en",
        )["rows"]
        == []
    )
    for document_id in [
        "../pyproject.toml",
        "/etc/passwd",
        "guide/en/agents.md",
        "%2e%2e%2fsecret",
        "README",
    ]:
        rejected = invoke(
            browser, token, "read_documentation", document_id=document_id, language="en"
        )
        assert "error" in rejected


def test_installed_packaging_fallback_and_missing_docs_are_honest(
    catalogue_app, tmp_path, monkeypatch
):
    from torrentlinker import documentation
    from torrentlinker.agent import documentation as agent_docs

    _, browser, token = catalogue_app
    installed = tmp_path / "share/torrentlinker/docs/guide/en/getting-started.md"
    installed.parent.mkdir(parents=True)
    installed.write_text(
        "# Installed guide\n\n## Connection setup\n\nVersion-matched offline evidence.\n"
    )
    monkeypatch.setattr(documentation.sys, "_MEIPASS", tmp_path / "missing", raising=False)
    monkeypatch.setattr(documentation.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(agent_docs, "app_version", lambda: "0.11.4")
    result = invoke(browser, token, "search_documentation", query="offline evidence", language="en")
    assert result["rows"][0]["source_kind"] == "bundled-installation"
    assert "/blob/v0.11.4/docs/" in result["rows"][0]["online_reference_url"]
    assert result["rows"][0]["online_reference_is_version_specific"] is True
    assert result["rows"][0]["online_reference_matches_loaded_content"] is False
    assert result["unavailable_documents"]
    section = invoke(
        browser,
        token,
        "read_documentation",
        document_id="getting-started",
        section_id="connection-setup",
        language="en",
    )
    assert "Version-matched offline evidence." in section["content"]
    local = browser.get(section["reference_url"])
    assert local.is_success, local.text
    assert 'id="connection-setup"' in local.text
    assert browser.get("/documentation/guide/en/../secret.md").status_code == 404
    installed.unlink()
    unavailable = invoke(
        browser, token, "read_documentation", document_id="getting-started", language="en"
    )
    assert "unavailable" in unavailable["error"].casefold()


def test_documentation_citations_render_and_native_helper_is_nonmodal(catalogue_app, qtbot):
    from PySide6.QtWidgets import QWidget

    from torrentlinker.gui.documentation import DocumentationTab, show_guide

    _, browser, token = catalogue_app
    read = invoke(browser, token, "read_documentation", document_id="agents", language="en")
    assert browser.get(read["reference_url"]).is_success
    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = show_guide(parent, "guide/en/agents.md", "inspect-and-edit-the-download-queue")
    qtbot.addWidget(dialog)
    assert dialog.isModal() is False
    from tests.test_community_interfaces import js, wait_js

    reader = dialog.findChild(DocumentationTab)
    wait_js(qtbot, reader, "!!document.getElementById('inspect-and-edit-the-download-queue')")
    wait_js(qtbot, reader, "window.scrollY>0")
    assert js(
        qtbot,
        reader,
        "document.getElementById('inspect-and-edit-the-download-queue').getBoundingClientRect().top<40",
    )
