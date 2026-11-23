"""Horizon, the Media interface inspired by Kodi's Aeon Nox, and its view chosen in Settings."""

import json


def test_horizon_view_reaches_the_shared_media_view(qtbot):
    from torrentlinker.gui.media import MediaTab

    tab = MediaTab(lambda: None, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    assert tab.media_horizon == "home"
    tab.set_media_layout("collection")  # a Collection choice saved before Horizon
    assert tab.media_layout == "horizon"
    tab.set_media_horizon("unknown")
    assert tab.media_horizon == "home"
    tab.set_media_horizon("wall")
    # The shared view asks its host for both choices when it loads.
    browser = tab._ensure_browser()
    answers = []
    browser.bridge.response.connect(lambda _, value: answers.append(json.loads(value)))
    browser.bridge.requestAsync(1, "preferences", "{}")
    assert answers == [{"data": {"layout": "horizon", "horizon": "wall"}}]


def test_horizon_view_chosen_in_media_options_is_saved(qtbot):
    from torrentlinker.gui.media import MediaTab

    tab = MediaTab(lambda: None, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    saved = []
    tab.horizon_changed.connect(saved.append)
    browser = tab._ensure_browser()
    answers = []
    browser.bridge.response.connect(lambda _, value: answers.append(json.loads(value)))
    # The view's own switch reaches the host through its preferences.
    browser.bridge.requestAsync(1, "preferences", json.dumps({"horizon": "showcase"}))
    assert saved == ["showcase"] and tab.media_horizon == "showcase"
    assert answers[-1]["data"]["horizon"] == "showcase"
    browser.bridge.requestAsync(2, "preferences", json.dumps({"horizon": "elsewhere"}))
    assert saved == ["showcase"]
