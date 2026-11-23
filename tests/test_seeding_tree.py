"""Category hierarchy and owner expansion through the shared Seeding interface."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings

from tests.test_community_interfaces import js, wait_js
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.gui.seeding_view import SeedingView
from torrentlinker.seeding import Seeding, SeedingRow
from torrentlinker.web.seeding import seeding_page
from torrentlinker.zen import ZenDay, ZenProfile


def sample():
    rows = [
        SeedingRow(Torrent("a", "Small", Path("/data"), size=9 * 1024**2), 0.1, 7010),
        SeedingRow(Torrent("b", "Large", Path("/data"), size=1024**3), 0.2, 7010),
        SeedingRow(Torrent("c", "Broad", Path("/data"), size=100), 0.3, 7000, True),
        SeedingRow(Torrent("d", "Unknown", Path("/data"), size=100), None),
    ]
    return Seeding(
        rows,
        ZenDay([0.1, 0.2, 0.3]),
        [],
        {7000: IndexerCategory("Books"), 7010: IndexerCategory("Comics", 7000)},
    )


def opened(qtbot, tmp_path, data=None):
    view = SeedingView(
        lambda: lambda: sample(),
        preferences=QSettings(str(tmp_path / "owner.ini"), QSettings.Format.IniFormat),
    )
    qtbot.addWidget(view)
    view.show_seeding(data or sample())
    view.show()
    wait_js(qtbot, view, "document.querySelectorAll('.seeding-category').length===3")
    return view


def test_tree_groups_categories_and_numeric_rows(qtbot, tmp_path):
    view = opened(qtbot, tmp_path)
    assert js(
        qtbot,
        view,
        'document.querySelector(\'[data-group="7000"] [data-group="7000/7010"]\')!==null',
    )
    js(qtbot, view, "document.querySelector('#seeding-expand').click()")
    wait_js(qtbot, view, "document.querySelectorAll('tbody tr').length===4")
    assert js(
        qtbot,
        view,
        "document.querySelector('#seeding-result tbody').textContent.includes('Unknown')",
    )
    js(
        qtbot,
        view,
        "document.querySelector('[data-category=\"7000/7010\"]').click()",
    )
    wait_js(qtbot, view, "document.querySelectorAll('tbody tr').length===2")
    js(
        qtbot,
        view,
        "document.querySelector('[data-sort=\"size\"]').click()",
    )
    wait_js(
        qtbot,
        view,
        "document.querySelector('#seeding-result tbody tr')?.textContent.includes('Small')",
    )


def test_owner_expansion_uses_category_identity_after_rename(qtbot, tmp_path):
    view = opened(qtbot, tmp_path)
    js(qtbot, view, "document.querySelector('#seeding-expand').click()")
    wait_js(qtbot, view, "document.querySelectorAll('tbody tr').length===4")
    js(qtbot, view, "document.querySelector('[data-group=\"7000\"]').open=false")
    qtbot.waitUntil(
        lambda: "7000" not in view.preferences.value(view.preference_key(), [], type=list)
    )
    view.close()
    renamed = replace(
        sample(),
        categories={7000: IndexerCategory("Livres"), 7010: IndexerCategory("Comics", 7000)},
    )
    reopened = opened(qtbot, tmp_path, renamed)
    assert js(qtbot, reopened, "!document.querySelector('[data-group=\"7000\"]').open")
    assert js(qtbot, reopened, "document.querySelector('[data-group=\"7000/7010\"]').open")


def test_filter_does_not_persist_automatic_expansion(qtbot, tmp_path):
    view = opened(qtbot, tmp_path)
    js(qtbot, view, "document.querySelector('[data-group=\"7000\"]').open=true")
    wait_js(qtbot, view, "document.querySelectorAll('tbody tr').length===4")
    js(
        qtbot,
        view,
        "document.querySelector('#seeding-query').value='small';document.q"
        "uerySelector('#seeding-query').dispatchEvent(new Event('input'))",
    )
    wait_js(
        qtbot,
        view,
        "document.querySelectorAll('tbody tr').length===1&&document.queryS"
        "elector('tbody').textContent.includes('Small')",
    )
    view.show_seeding(sample())
    view.close()
    reopened = opened(qtbot, tmp_path)
    assert js(qtbot, reopened, "document.querySelector('[data-group=\"7000\"]').open")
    assert js(qtbot, reopened, "!document.querySelector('[data-group=\"7000/7010\"]').open")
    js(qtbot, reopened, "document.querySelector('#seeding-collapse').click()")
    qtbot.waitUntil(
        lambda: not reopened.preferences.value(reopened.preference_key(), [], type=list)
    )
    reopened.close()
    final = opened(qtbot, tmp_path)
    assert js(qtbot, final, "document.querySelectorAll('.seeding-category[open]').length===0")


def test_note_aggregates_weight_torrents_and_unknowns_sort_last():
    data = sample()
    data = replace(
        data,
        rows=[
            replace(row, note=value)
            for row, value in zip(data.rows, [2.0, 10.0, 0.0, None], strict=True)
        ],
    )
    page = seeding_page(data, ZenProfile(), 0, group="7000/7010", sort="note", descending=False)
    assert [row["name"] for row in page["rows"]] == ["Small", "Large"]
    assert next(group for group in page["groups"] if group["id"] == "7000")["note"] == 4.0
    assert next(group for group in page["groups"] if group["id"] == "7000/7010")["note"] == 6.0
    assert next(group for group in page["groups"] if group["id"] == "unknown")["note"] is None


def test_previous_native_expansion_migrates_once(qtbot, tmp_path):
    preferences = QSettings(str(tmp_path / "owner.ini"), QSettings.Format.IniFormat)
    preferences.setValue("zen/expanded_categories", ["category:7000", "category:7000/7010"])
    view = opened(qtbot, tmp_path)
    wait_js(qtbot, view, "document.querySelectorAll('.seeding-category[open]').length===2")
    js(qtbot, view, "document.querySelector('#seeding-collapse').click()")
    qtbot.waitUntil(lambda: not preferences.value(view.preference_key(), [], type=list))
    view.close()
    reopened = opened(qtbot, tmp_path)
    assert js(qtbot, reopened, "document.querySelectorAll('.seeding-category[open]').length===0")
