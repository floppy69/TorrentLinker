from types import SimpleNamespace

import pytest
from qbittorrentapi import LoginFailed


@pytest.mark.parametrize(
    "error", [LoginFailed(), TimeoutError(), RuntimeError("connection refused")]
)
def test_connection_warning_always_explains_failure(qtbot, tmp_path, monkeypatch, error):
    from tests.settings_support import settings_page
    from tests.test_community_interfaces import js, wait_js

    dialog = settings_page(qtbot, tmp_path)

    def fail():
        raise error

    monkeypatch.setattr(dialog.setup, "connector", lambda *args: SimpleNamespace(check=fail))
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent"
        "==='Test connection').click()",
    )
    wait_js(qtbot, dialog.view, "Boolean(document.querySelector('#settings-error').textContent)")
    message = js(qtbot, dialog.view, "document.querySelector('#settings-error').textContent")
    assert "Cannot connect" in message
    assert "address" in message and "port" in message
