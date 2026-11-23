from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from torrentlinker.client_folders import ClientFolder, client_path, qbit_folders
from torrentlinker.config import Settings
from torrentlinker.deluge import DelugeApi
from torrentlinker.domain import PathMapping
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.gui.folder_import import FolderImportDialog
from torrentlinker.qbit import QbitApi
from torrentlinker.transmission import TransmissionApi


def test_qbit_explicit_relative_paths_use_default_but_implicit_children_inherit():
    folders = qbit_folders(
        "/downloads",
        {
            "Books": {"savePath": "/library"},
            "Books/Comics": {"savePath": ""},
            "Books/Audio": {"savePath": "audio"},
        },
        True,
    )
    assert {f.name: f.path for f in folders} == {
        "": "/downloads",
        "Books": "/library",
        "Books/Comics": "/library/Comics",
        "Books/Audio": "/downloads/audio",
    }
    assert (
        qbit_folders("/downloads", {"Books/Comics": {}}, False)[1].path == "/downloads/Books/Comics"
    )


def test_qbit_windows_paths_are_resolved_using_server_syntax():
    folders = qbit_folders(
        "D:/Downloads",
        {
            "Books": {"savePath": "E:/Library"},
            "Books/Comics": {},
            "Audio": {"savePath": "music"},
        },
        True,
    )
    assert {f.name: f.path for f in folders if f.name} == {
        "Books": r"E:\Library",
        "Books/Comics": r"E:\Library\Comics",
        "Audio": r"D:\Downloads\music",
    }
    assert client_path(r"\\nas\books", "D:/Downloads") == r"\\nas\books"


def test_qbit_reads_only_preferences_and_categories():
    api = QbitApi("http://localhost:1", "", "")
    prefs = {"save_path": "/downloads", "temp_path_enabled": True, "temp_path": "/partial"}
    client = Mock(spec=["app_preferences", "torrents_categories"])
    client.app_preferences.return_value = prefs
    client.torrents_categories.return_value = {"Books": {"savePath": "/books"}, "Books/Comics": {}}
    api._client = client
    assert api.folder_settings() == [
        ClientFolder("", "/downloads", "default"),
        ClientFolder("Books", "/books"),
        ClientFolder("Books/Comics", "/books/Comics"),
        ClientFolder("", "/partial", "incomplete"),
    ]
    prefs["temp_path_enabled"] = False
    prefs["subcategories_enabled"] = False
    assert api.folder_settings()[-1] == ClientFolder("Books/Comics", "/downloads/Books/Comics")
    assert {c[0] for c in client.mock_calls} == {"app_preferences", "torrents_categories"}


@pytest.mark.parametrize("labels", [False, True])
def test_deluge_reads_enabled_completed_folders_without_requiring_label(monkeypatch, labels):
    api = DelugeApi("http://localhost:1", "")
    calls = []

    def rpc(method, *args):
        calls.append(method)
        if method == "core.get_config_values":
            return {
                "download_location": "/downloads",
                "move_completed": True,
                "move_completed_path": "/done",
            }
        if method == "core.get_enabled_plugins":
            return ["Label"] if labels else []
        if method == "label.get_labels":
            return ["books", "disabled", "inherit"]
        assert method == "label.get_options"
        return {
            "apply_move_completed": args[0] != "inherit",
            "move_completed": args[0] != "disabled",
            "move_completed_path": "/books",
        }

    monkeypatch.setattr(api, "_call", rpc)
    assert api.folder_settings() == [
        ClientFolder("", "/downloads", "default"),
        ClientFolder("", "/done", "completed"),
        *([ClientFolder("books", "/books", "completed")] if labels else []),
    ]
    assert all(".get_" in call for call in calls)
    assert ("label.get_labels" in calls) is labels


@pytest.mark.parametrize("enabled", [False, True])
def test_transmission_only_reports_enabled_incomplete_folder(monkeypatch, enabled):
    api = TransmissionApi("http://localhost:1", "", "")
    get = Mock(
        return_value={
            "download-dir": "/downloads",
            "incomplete-dir": "/partial",
            "incomplete-dir-enabled": enabled,
        }
    )
    monkeypatch.setattr(api, "_session_get", get)
    assert api.folder_settings() == [
        ClientFolder("", "/downloads", "default"),
        *([ClientFolder("", "/partial", "incomplete")] if enabled else []),
    ]
    get.assert_called_once_with("download-dir", "incomplete-dir", "incomplete-dir-enabled")


def test_preview_preserves_existing_and_applies_mapping_only_after_selection(qtbot):
    current = DownloadFolders({10: "/old/books"}, "/old/default")
    dialog = FolderImportDialog(
        [
            ClientFolder("", "/data/downloads", "default"),
            ClientFolder("Books", "/data/books"),
            ClientFolder("", "/data/partial", "incomplete"),
        ],
        {10: IndexerCategory("Books")},
        current,
        [PathMapping("/mounted", "/data")],
    )
    qtbot.addWidget(dialog)
    assert all(c.currentData() is None for c in dialog.choices)
    assert not dialog.choices[2].isEnabled()
    assert not dialog.apply_button.isEnabled()
    dialog.choices[1].setCurrentIndex(dialog.choices[1].findData(10))
    assert dialog.table.item(1, 2).text() == "/mounted/books"
    assert dialog.table.item(1, 4).text() == "/old/books"
    assert "1 existing values" in dialog.status.text()
    dialog._apply()
    assert dialog.result_folders == DownloadFolders({10: "/mounted/books"}, "/old/default")
    assert current == DownloadFolders({10: "/old/books"}, "/old/default")


def test_preview_does_not_guess_ambiguous_category_names(qtbot):
    dialog = FolderImportDialog(
        [ClientFolder("Audio", "/audio")],
        {
            1: IndexerCategory("Books"),
            2: IndexerCategory("Music"),
            3: IndexerCategory("Audio", 1),
            4: IndexerCategory("Audio", 2),
        },
        DownloadFolders(),
        [],
    )
    qtbot.addWidget(dialog)
    assert dialog.choices[0].currentData() is None
    dialog.reject()
    assert dialog.result_folders is None


def test_preview_blocks_duplicate_destinations(qtbot):
    dialog = FolderImportDialog(
        [ClientFolder("", "/download", "default"), ClientFolder("books", "/books")],
        {},
        DownloadFolders(),
        [],
    )
    qtbot.addWidget(dialog)
    assert dialog.apply_button.isEnabled()
    dialog.choices[1].setCurrentIndex(1)
    assert not dialog.apply_button.isEnabled()
    dialog._apply()
    assert dialog.result_folders is None


@pytest.mark.parametrize(
    "source,mappings",
    [
        ("relative/folder", []),
        ("/data/books", [PathMapping("/data", "/remote")]),
    ],
)
def test_preview_blocks_relative_or_conflicting_mapped_paths(qtbot, source, mappings):
    dialog = FolderImportDialog(
        [ClientFolder("", source, "default")], {}, DownloadFolders(), mappings
    )
    qtbot.addWidget(dialog)
    assert not dialog.apply_button.isEnabled()


def test_windows_mapping_roundtrip_ignores_drive_case(qtbot):
    dialog = FolderImportDialog(
        [ClientFolder("", "D:/Books", "default")],
        {},
        DownloadFolders(),
        [PathMapping("/books", "d:/books")],
    )
    qtbot.addWidget(dialog)
    assert dialog.apply_button.isEnabled()
    dialog._apply()
    assert dialog.result_folders.default == "/books"


def test_settings_import_requires_save_and_uses_saved_mappings(qtbot, tmp_path):
    from tests.settings_support import settings_page
    from tests.test_community_interfaces import js, wait_js

    local = tmp_path / "local"
    (local / "books").mkdir(parents=True)
    settings = Settings(language="en", path_mappings=[PathMapping(str(local), "/remote")])
    dialog = settings_page(qtbot, tmp_path, settings, section="downloads")
    dialog.setup.connector = lambda *a, **kw: SimpleNamespace(
        folder_settings=lambda: [ClientFolder("", "/remote/books", "default")]
    )
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent"
        "==='Read folders from client').click()",
    )
    wait_js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].some(b=>b.textContent"
        "==='Default · /remote/books')",
    )
    js(
        qtbot,
        dialog.view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent"
        "==='Default · /remote/books').click()",
    )
    assert js(
        qtbot,
        dialog.view,
        "document.querySelector('[aria-label=\"Folder on the TorrentLinker host\"]').value",
    ) == str(local / "books")
    assert dialog.setup.settings.download_folders.default == ""
    assert not dialog.setup.path.exists()
    dialog.close()  # leave without saving
    assert settings.download_folders.default == ""


@pytest.mark.parametrize("finish", ["changed", "error"])
def test_settings_import_ignores_stale_results_and_recovers_from_errors(qtbot, tmp_path, finish):
    import threading

    from tests.settings_support import settings_page
    from tests.test_community_interfaces import js, wait_js

    started, release = threading.Event(), threading.Event()

    def folders():
        started.set()
        assert release.wait(5)
        if finish == "error":
            raise RuntimeError("Connection failed")
        return [ClientFolder("", "/download", "default")]

    dialog = settings_page(qtbot, tmp_path, section="downloads")
    dialog.setup.connector = lambda *a, **kw: SimpleNamespace(folder_settings=folders)
    try:
        js(
            qtbot,
            dialog.view,
            "[...document.querySelectorAll('button')].find(b=>b.textCon"
            "tent==='Read folders from client').click()",
        )
        qtbot.waitUntil(started.is_set)
        if finish == "changed":
            js(
                qtbot,
                dialog.view,
                "[...document.querySelectorAll('nav button')].find(b=>b"
                ".textContent==='General').click()",
            )
        release.set()
        qtbot.waitUntil(lambda: dialog.view.pending == 0)
        if finish == "error":
            wait_js(
                qtbot,
                dialog.view,
                "document.querySelector('#settings-error').textContent."
                "includes('Connection failed')",
            )
            assert (
                js(
                    qtbot,
                    dialog.view,
                    "[...document.querySelectorAll('button')].find(b=>b"
                    ".textContent==='Read folders from client').disable"
                    "d",
                )
                is False
            )
        else:
            assert (
                js(qtbot, dialog.view, "document.querySelector('.settings-form h2').textContent")
                == "General"
            )
            assert not js(
                qtbot, dialog.view, "document.body.textContent.includes('Default · /download')"
            )
        assert dialog.setup.settings.download_folders.default == ""
    finally:
        release.set()


def test_implicit_paths_with_version_dependent_sanitization_are_not_guessed():
    folders = qbit_folders(
        "C:/Downloads",
        {
            "Books": {},
            "Books/CON": {},
            "Books/CON/Comics": {},
            "Books/Audio?": {},
            "Explicit": {"savePath": "D:/Chosen"},
        },
        True,
    )
    paths = {folder.name: folder.path for folder in folders}
    assert paths["Books"] == r"C:\Downloads\Books"
    assert paths["Explicit"] == r"D:\Chosen"
    assert paths["Books/CON"] == paths["Books/CON/Comics"] == paths["Books/Audio?"] == ""
