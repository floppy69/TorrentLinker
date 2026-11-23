import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from torrentlinker.config import Settings
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


@pytest.fixture
def window(qtbot, tmp_path):
    settings = Settings()
    settings.indexer_categories = {
        2000: IndexerCategory("Films"),
        2030: IndexerCategory("Film", 2000),
        6000: IndexerCategory("XXX"),
        6060: IndexerCategory("Images", 6000),
    }
    settings.plan_categories = [6060]
    settings.download_folders = DownloadFolders({2030: str(tmp_path / "films")})
    widget = MainWindow(settings, tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(widget)
    return widget


@pytest.mark.parametrize("answer,path_chosen", [(False, False), (True, False), (True, True)])
def test_make_plan_prompts_for_missing_category_and_cancel_does_not_start(
    window, tmp_path, monkeypatch, answer, path_chosen
):
    prompts, builds = [], []

    def prompt(parent, title, text):
        prompts.append(text)
        return QMessageBox.StandardButton.Yes if answer else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", prompt)
    monkeypatch.setattr(
        "torrentlinker.gui.main_window.choose_directory",
        lambda *args: str(tmp_path / "images") if path_chosen else "",
    )
    monkeypatch.setattr(window, "_build_plan", lambda then=None: builds.append(True))
    window.zen_tab.plan_view.make_requested.emit()
    assert len(prompts) == 1 and "XXX / Images" in prompts[0]
    assert bool(builds) == (answer and path_chosen)
    folders = window.settings.download_folders
    assert folders.default == ""
    assert folders.by_category[2030] == str(tmp_path / "films")
    if path_chosen:
        assert folders.by_category[6060] == str(tmp_path / "images")
        saved = Settings.load(tmp_path / "settings.json")
        assert saved.download_folders == folders
    else:
        assert 6060 not in folders.by_category
        assert not window.zen_tab.plan_view.state()["busy"]


def test_existing_parent_folder_does_not_prompt(window, tmp_path, monkeypatch):
    window.settings.download_folders.by_category[6000] = str(tmp_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("Unexpected prompt"))
    assert window._ensure_plan_download_folders()


def test_all_categories_without_any_folder_asks_for_a_category_not_a_default(
    window, tmp_path, monkeypatch
):
    window.settings.download_folders = DownloadFolders()
    window.settings.plan_categories = None
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: ("Films / Film", True))
    monkeypatch.setattr(
        "torrentlinker.gui.main_window.choose_directory", lambda *args: str(tmp_path / "films")
    )
    assert window._ensure_plan_download_folders()
    assert window.settings.download_folders == DownloadFolders({2030: str(tmp_path / "films")})


def test_plan_on_another_client_configures_only_that_clients_category(
    window, tmp_path, monkeypatch
):
    other = window.settings.add_client("Other")
    window._plan_destinations = {other.id: 0}
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        "torrentlinker.gui.main_window.choose_directory", lambda *args: str(tmp_path / "images")
    )
    assert window._ensure_plan_download_folders()
    assert window.settings.download_folders.default == ""
    assert 6060 not in window.settings.download_folders.by_category
    saved = Settings.load(tmp_path / "settings.json")
    assert saved.profile(other.id).download_folders.by_category[6060] == str(tmp_path / "images")
    assert saved.profile(other.id).download_folders.default == ""
