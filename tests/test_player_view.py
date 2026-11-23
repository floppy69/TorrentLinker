"""The bundled transport keeps stale actions away from the host player."""

import json
import os
from pathlib import Path

from torrentlinker.gui.player_view import PlayerView


def test_player_bridge_rejects_replaced_sources_and_queues(qtbot):
    current = {
        "client_id": "studio",
        "media_id": "film",
        "source_token": "new",
        "queue_revision": 2,
    }
    commands = []
    view = PlayerView(lambda: current, lambda action, values: commands.append((action, values)))
    qtbot.addWidget(view)
    responses = []
    view.bridge.response.connect(lambda identifier, value: responses.append(json.loads(value)))
    for stale in ({"source_token": "old"}, {"client_id": "seedbox"}, {"queue_revision": 1}):
        view.bridge.requestAsync(
            1,
            "command",
            json.dumps({**current, "action": "queue-remove", "values": {"index": 0}, **stale}),
        )
        assert "changed" in responses[-1]["error"]
    assert commands == []
    view.bridge.requestAsync(2, "command", json.dumps({**current, "action": "toggle"}))
    assert commands == [("toggle", {})]
    view.close()


def test_player_controls_render_in_both_languages_and_themes(qtbot, request):
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    from tests.test_community_interfaces import js, wait_js

    current = {
        "client_id": "studio",
        "media_id": "film",
        "source_token": "one",
        "queue_revision": 1,
        "kind": "video",
        "mode": "desktop",
        "language": "en",
        "theme": "dark",
        "position": 60,
        "duration": 3600,
        "volume": 0.5,
        "playing": False,
        "queue": [{"id": "film", "title": "Sample film"}],
        "index": 0,
        "tracks": {
            "audio_supported": True,
            "subtitle_supported": True,
            "audio": [{"id": "audio:0", "label": "English", "selected": True}],
            "subtitles": [],
        },
        "available_height": 380,
    }
    view = PlayerView(lambda: current, lambda *_: None)
    qtbot.addWidget(view)
    view.resize(760, 80)
    view.show()
    view.refresh()
    wait_js(qtbot, view, "typeof request === 'function' && state.media_id === 'film'")
    for language, theme, label in [
        ("en", "dark", "Player options"),
        ("fr", "light", "Options du lecteur"),
    ]:
        current.update(language=language, theme=theme)
        view.refresh()
        wait_js(qtbot, view, f"document.documentElement.lang === {json.dumps(language)}")
        js(qtbot, view, "setMenu(true)")
        qtbot.waitUntil(lambda: view.height() > 80)
        assert js(qtbot, view, "document.getElementById('player-menu-title').textContent") == label
        assert js(qtbot, view, "document.documentElement.scrollWidth <= innerWidth")
        assert js(
            qtbot,
            view,
            "document.getElementById('player-controls').getBoundingClientRect().bottom "
            "<= innerHeight + 1",
        )
        view.resize(326, view.height())
        qtbot.wait(100)
        assert js(qtbot, view, "document.documentElement.scrollWidth <= innerWidth")
        view.resize(760, view.height())
        qtbot.wait(100)
        if folder := os.getenv("TL_PLAYER_SCREENSHOTS"):
            Path(folder).mkdir(parents=True, exist_ok=True)
            assert view.grab().save(str(Path(folder) / f"player-{language}-{theme}.png"))
    current.update(
        available_height=1080, queue=[{"id": str(i), "title": f"Film {i}"} for i in range(30)]
    )
    view.refresh()
    js(qtbot, view, "setMenu(true); document.getElementById('player-queue-details').open=true")
    qtbot.wait(100)
    assert view.height() <= 380
    assert js(
        qtbot,
        view,
        "document.getElementById('player-controls').getBoundingClientRect().bottom "
        "<= innerHeight + 1",
    )
    view.close()


def test_track_selection_rechecks_source_after_host_report(qtbot, monkeypatch):
    import pytest

    from torrentlinker.gui.media import MediaTab

    tab = MediaTab(lambda: None, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.last_source, tab.track_source_token = "film-a", "a"
    commands = []
    monkeypatch.setattr(tab, "command", lambda *args, **kwargs: commands.append(args))
    monkeypatch.setattr(tab, "report", lambda: setattr(tab, "track_source_token", "b"))
    with pytest.raises(ValueError, match="source changed"):
        tab._player_control("select_track", {"kind": "audio", "track_id": "audio:1"})
    assert commands == []
