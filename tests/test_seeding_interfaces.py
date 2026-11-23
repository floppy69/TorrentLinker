"""Shared Seeding owner workflow; introduced before its renderer replacement."""

from pathlib import Path

from PySide6.QtCore import QSettings

from tests.test_community_interfaces import js, wait_js
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.gui.zen_view import SeedingView
from torrentlinker.seeding import Seeding, SeedingRow
from torrentlinker.zen import ZenDay


def test_ten_thousand_torrents_are_browsable_without_expanding_rows(qtbot, tmp_path):
    data = Seeding(
        [
            SeedingRow(
                Torrent(str(i), f"Release {i:05d}", Path("/data"), size=i + 1),
                0.1,
                7010 if i % 2 else 7020,
            )
            for i in range(10001)
        ],
        ZenDay([0.1] * 10001),
        [],
        {
            7000: IndexerCategory("Books"),
            7010: IndexerCategory("Comics", 7000),
            7020: IndexerCategory("Fiction", 7000),
        },
    )
    view = SeedingView(
        lambda: lambda: data,
        preferences=QSettings(str(tmp_path / "owner.ini"), QSettings.Format.IniFormat),
    )
    qtbot.addWidget(view)
    view.language = "en"
    view.resize(1280, 900)
    view.show_seeding(data)
    view.show()
    wait_js(qtbot, view, "document.querySelectorAll('#seeding-result tbody tr').length===100")
    assert js(qtbot, view, "document.querySelector('#seeding-page').textContent.includes('10001')")
    js(qtbot, view, "document.querySelector('#seeding-last').click()")
    wait_js(qtbot, view, "document.querySelectorAll('#seeding-result tbody tr').length===1")
    js(
        qtbot,
        view,
        "const input=document.querySelector('#seeding-query');input.value='Release 10000';"
        "input.dispatchEvent(new Event('input'))",
    )
    wait_js(
        qtbot,
        view,
        "document.querySelector('#seeding-result').textContent.includes('Release 10000')",
    )
    assert js(qtbot, view, "document.querySelectorAll('#seeding-result tbody tr').length") == 1


def test_shared_seeding_sort_filter_and_expansion_survive_reopening(qtbot, tmp_path):
    data = Seeding(
        [
            SeedingRow(Torrent("a", "Small", Path("/data"), size=9000), 0.1, 7010),
            SeedingRow(Torrent("b", "Large", Path("/data"), size=1000000), 0.2, 7010),
            SeedingRow(Torrent("c", "Broad", Path("/data"), size=100), 0.3, 7000),
        ],
        ZenDay([0.1, 0.2, 0.3]),
        [],
        {7000: IndexerCategory("Books"), 7010: IndexerCategory("Comics", 7000)},
    )
    settings = QSettings(str(tmp_path / "owner.ini"), QSettings.Format.IniFormat)
    view = SeedingView(lambda: lambda: data, preferences=settings)
    qtbot.addWidget(view)
    view.show_seeding(data)
    view.resize(1200, 800)
    view.show()
    wait_js(qtbot, view, "document.querySelectorAll('.seeding-category').length===2")
    js(qtbot, view, "document.querySelector('#seeding-expand').click()")
    wait_js(qtbot, view, "document.querySelectorAll('tbody tr').length===3")
    js(
        qtbot,
        view,
        "document.querySelector('[data-sort=\"name\"]').click()",
    )
    wait_js(
        qtbot,
        view,
        "document.querySelector('#seeding-result tbody tr').textContent.includes('Broad')",
    )
    view.close()
    reopened = SeedingView(lambda: lambda: data, preferences=settings)
    qtbot.addWidget(reopened)
    reopened.show_seeding(data)
    reopened.show()
    wait_js(qtbot, reopened, "document.querySelectorAll('.seeding-category[open]').length===2")
    js(
        qtbot,
        reopened,
        "document.querySelector('#seeding-query').value='Large';document.q"
        "uerySelector('#seeding-query').dispatchEvent(new Event('input',{b"
        "ubbles:true}))",
    )
    wait_js(qtbot, reopened, "document.querySelectorAll('tbody tr').length===1")
    assert js(qtbot, reopened, "document.querySelector('tbody').textContent.includes('Large')")
