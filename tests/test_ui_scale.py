"""A desktop interface size, for screens where the system's scaling does not suit."""

from torrentlinker.app import apply_ui_scale
from torrentlinker.config import Settings, ui_scale


def test_the_interface_size_is_saved_and_old_settings_keep_the_system_size(tmp_path, qtbot):
    from tests.settings_support import edit_field, save_group, settings_page
    from tests.test_community_interfaces import js

    path = tmp_path / "settings.json"
    path.write_text("{}")
    settings = Settings.load(path)
    assert settings.ui_scale == 1.0
    dialog = settings_page(qtbot, tmp_path, settings, section="general")
    assert "Restart TorrentLinker" in js(qtbot, dialog.view, "document.body.textContent")
    edit_field(qtbot, dialog.view, "Interface size", "1.25")
    save_group(qtbot, dialog)
    assert Settings.load(path).ui_scale == 1.25


def test_odd_saved_sizes_stay_within_the_offered_range() -> None:
    assert ui_scale("2") == 2.0
    assert ui_scale(9) == 2.0
    assert ui_scale(0.1) == 0.75
    assert ui_scale("big") == 1.0


def test_the_size_reaches_qt_unless_the_user_set_it_already() -> None:
    environ: dict[str, str] = {}
    apply_ui_scale(1.0, environ)
    assert environ == {}  # the system size: nothing to tell Qt
    apply_ui_scale(1.25, environ)
    assert environ == {"QT_SCALE_FACTOR": "1.25"}
    mine = {"QT_SCALE_FACTOR": "2"}
    apply_ui_scale(0.75, mine)
    assert mine == {"QT_SCALE_FACTOR": "2"}
