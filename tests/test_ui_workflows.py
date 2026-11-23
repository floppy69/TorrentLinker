"""Interaction regressions: sorting must never change which item an action operates on."""

from pathlib import Path

from PySide6.QtCore import Qt

from torrentlinker.config import Settings
from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.indexer import Candidate
from torrentlinker.library import LibraryEntry
from torrentlinker.review import CheckedCandidate
from torrentlinker.store import Store


def test_sorted_candidates_keep_their_identity_for_replacement_and_rejection(qtbot, tmp_path):
    store = Store(tmp_path / "s.db")
    window = MainWindow(Settings(), tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    panel = window.review
    entry = LibraryEntry(LibraryFolder(tmp_path), LocalItem(tmp_path / "Film"), ItemState.ORPHAN)
    panel.set_entry(entry)
    large = CheckedCandidate(Candidate("A large", 1024**3, "https://example.test/large", 20))
    small = CheckedCandidate(Candidate("Z small", 9 * 1024**2, "https://example.test/small", 3))
    panel._show(entry, [large, small])
    panel.candidates.sortItems(1, Qt.SortOrder.AscendingOrder)
    panel.candidates.selectRow(0)
    assert panel.selected() is small
    assert panel.selected_all() == [small]

    # Checking a Candidate can change both its displayed data and its sorted position.
    replacement = CheckedCandidate(
        Candidate("Z updated", 2 * 1024**3, small.candidate.download_url, 3)
    )
    panel._replace(entry, small, replacement)
    assert panel.selected() is replacement
    assert panel.candidates.currentRow() == 1
    panel.reject_button.click()
    assert list(store.rejections(entry.item.path)) == [small.candidate.download_url]
    assert panel.checked == [large]
    assert panel.candidates.rowCount() == 1
    assert panel.candidates.item(0, 0).text() == large.candidate.title


def test_search_shortcut_returns_to_shared_library(qtbot, tmp_path):
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "s.db"))
    qtbot.addWidget(window)
    folder = LibraryFolder(tmp_path)
    entries = [
        LibraryEntry(folder, LocalItem(tmp_path / "Amelie.mkv"), ItemState.ORPHAN),
        LibraryEntry(folder, LocalItem(tmp_path / "Amelie.2001.mkv"), ItemState.SEEDED),
        LibraryEntry(folder, LocalItem(tmp_path / "Other.mkv"), ItemState.ORPHAN),
    ]
    window.library_model.set_entries(entries)
    window.tabs.setCurrentIndex(2)
    assert window.tabs.currentIndex() == 2
    window._focus_search()
    assert window.tabs.currentIndex() == 1


def test_seeding_filter_and_numeric_order_survive_refresh(qtbot):
    from torrentlinker.domain import Torrent
    from torrentlinker.gui.zen_view import SeedingView
    from torrentlinker.seeding import Seeding, SeedingRow
    from torrentlinker.zen import ZenDay

    view = SeedingView(lambda: lambda: Seeding([], ZenDay(), []))
    qtbot.addWidget(view)
    rows = [
        SeedingRow(Torrent("a", "Small film", Path("/data"), size=1024**2), 0.1),
        SeedingRow(Torrent("b", "Large film", Path("/data"), size=1024**3), 0.2),
    ]
    seeding = Seeding(rows, ZenDay([0.1, 0.2]), [])
    view.show_seeding(seeding)
    from tests.test_community_interfaces import js, wait_js

    view.show()
    wait_js(qtbot, view, "document.querySelectorAll('#seeding-result tbody tr').length===2")
    js(
        qtbot,
        view,
        "document.querySelector('[data-sort=size]').click();"
        "document.querySelector('#seeding-query').value=' LARGE ';"
        "document.querySelector('#seeding-query').dispatchEvent(new Event('input',{bubbles:true}))",
    )
    wait_js(qtbot, view, "document.querySelectorAll('#seeding-result tbody tr').length===1")
    view.show_seeding(seeding)
    wait_js(qtbot, view, "document.querySelectorAll('#seeding-result tbody tr').length===1")
    assert js(
        qtbot,
        view,
        "document.querySelector('#seeding-result tbody').textContent.includes('Large film')",
    )
