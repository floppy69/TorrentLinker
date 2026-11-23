"""Buttons take one of the shared roles; icon buttons always explain themselves."""

import pytest
from PySide6.QtWidgets import QPushButton

from torrentlinker.gui.controls import icon_button, set_role


def test_icon_buttons_have_a_tooltip_and_accessible_name(qtbot):
    button = icon_button("✕", "Close chat")
    qtbot.addWidget(button)
    assert button.property("role") == "icon"
    assert button.toolTip() == button.accessibleName() == "Close chat"


def test_roles_are_a_closed_set(qtbot):
    button = QPushButton("Play")
    qtbot.addWidget(button)
    assert set_role(button, "primary").property("role") == "primary"
    with pytest.raises(ValueError):
        set_role(button, "huge")


def test_media_center_buttons_use_shared_roles(qtbot):
    from torrentlinker.gui.media import MediaTab

    tab = MediaTab(lambda: None, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    assert tab.player_back.property("role") == "icon"
    assert tab.video_controls.channel_name == "player"
    # No page stylesheet in the Media Center gives buttons their own shape any more.
    assert (
        "padding"
        not in tab.styleSheet().split("QWidget#mediaWorkspace QPushButton")[1].split("}")[0]
    )
