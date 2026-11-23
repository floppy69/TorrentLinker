from zipfile import ZipFile

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPainter, QPdfWriter, QTextDocument

from tests.test_ebooks import ebook_view, make_epub
from torrentlinker.config import Settings
from torrentlinker.gui.ebook_reader import BookReader, EpubText, ReadingRoom, _BookHtml
from torrentlinker.gui.main_window import MainWindow
from torrentlinker.store import Store


def wait_book(qtbot, reader):
    qtbot.waitUntil(lambda: not reader._loading and reader.path is not None, timeout=5000)


def test_gate_hides_room_below_threshold_and_closes_it_when_seeding_drops(qtbot, tmp_path):
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(window)
    window.show()
    assert not window._reader_unlocked
    assert window.reading_room is None
    ordinary_tabs = window.tabs.count()
    window._open_reading_room()
    assert window.tabs.count() == ordinary_tabs
    window._update_reading_room(ebook_view(9999, tmp_path))
    assert not window._reader_unlocked
    window._update_reading_room(ebook_view(10000, tmp_path))
    assert window._reader_unlocked
    window.shell_host.command("navigate", {"view": "reading"})
    qtbot.waitUntil(lambda: window.reading_room._scanned)
    assert window.tabs.currentWidget() is window.reading_room
    assert window.shell_host.page() == "reading"
    assert window.shell_host.page() == "reading"
    window._update_reading_room(ebook_view(9999, tmp_path))
    assert not window._reader_unlocked
    assert window.tabs.count() == ordinary_tabs
    assert window.tabs.currentIndex() == 0
    window._open_reading_room()
    assert window.tabs.count() == ordinary_tabs
    window._update_reading_room(ebook_view(10000, tmp_path))
    window._open_reading_room()
    qtbot.waitUntil(lambda: window.reading_room._scanned)
    assert window.tabs.count() == ordinary_tabs + 1
    window.zen_tab.seeding_view.unavailable.emit()
    assert not window._reader_unlocked
    assert window.tabs.count() == ordinary_tabs


def test_epub_navigation_zoom_and_saved_reading_position(qtbot, tmp_path):
    path = make_epub(tmp_path / "book.epub")
    original = path.read_bytes()
    reader = BookReader(tmp_path / "progress.json")
    qtbot.addWidget(reader)
    reader.resize(850, 600)
    reader.show()
    reader.open_book(path)
    wait_book(qtbot, reader)
    assert reader.title.text() == "A quiet library"
    assert "Chapter 1" in reader.text.toPlainText()
    assert reader.chapters.itemText(1) == "Chapter 2"
    assert reader.next.isEnabled()
    reader.go(1)
    wait_book(qtbot, reader)
    assert "Chapter 2" in reader.text.toPlainText()
    assert reader.previous.isEnabled() and reader.next.isEnabled()
    assert reader.paper.count > 1
    old = reader.text.font().pointSize()
    reader.zoom(1)
    assert reader.text.font().pointSize() == old + 1
    reader.paper.leaf = reader.paper.count // 2
    fraction = reader.paper.fraction
    reader.save_position()
    reader.clear()
    reader.open_book(path)
    wait_book(qtbot, reader)
    assert reader.page == 1
    assert abs(reader.paper.fraction - fraction) < 0.1
    assert path.read_bytes() == original
    reader.clear()


def test_epub_markup_cannot_load_external_or_local_resources(qtbot, tmp_path):
    text = EpubText()
    qtbot.addWidget(text)
    from torrentlinker.ebooks import EpubBook

    text.book = EpubBook(make_epub(tmp_path / "book.epub"))
    source = (
        '<script>secret</script><style>body{color:red}</style><img src="file:///etc/passwd">'
        '<img src="https://example.com/track"><a href="#hello">Read</a><p id="hello">Safe</p>'
    )
    rendered = "".join(_BookHtml(source, "OEBPS/chapter0.xhtml").parts)
    assert "secret" not in rendered and "color:red" not in rendered
    assert "file:" not in rendered and "https:" not in rendered
    assert "book:/OEBPS/chapter0.xhtml#hello" in rendered
    for url in ["file:///etc/passwd", "https://example.com/track"]:
        assert text.loadResource(QTextDocument.ResourceType.ImageResource, QUrl(url)).isEmpty()


def test_comic_displays_image_and_navigates(qtbot, tmp_path):
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image = QImage(200, 300, QImage.Format.Format_RGB32)
    image.fill(QColor("steelblue"))
    image.save(buffer, "PNG")
    path = tmp_path / "comic.cbz"
    with ZipFile(path, "w") as archive:
        archive.writestr("page2.png", bytes(raw))
        archive.writestr("page1.png", bytes(raw))
    reader = BookReader(tmp_path / "progress.json")
    qtbot.addWidget(reader)
    reader.show()
    reader.open_book(path)
    wait_book(qtbot, reader)
    assert not reader.comic.image.isNull()
    assert reader.position.maximum() == 2
    reader.go(1)
    wait_book(qtbot, reader)
    assert reader.page == 1 and not reader.next.isEnabled()
    reader.clear()


def test_pdf_loads_and_restores_page(qtbot, tmp_path):
    path = tmp_path / "book.pdf"
    writer = QPdfWriter(str(path))
    painter = QPainter(writer)
    painter.drawText(100, 100, "Page one")
    writer.newPage()
    painter.drawText(100, 100, "Page two")
    painter.end()
    del writer
    original = path.read_bytes()
    reader = BookReader(tmp_path / "progress.json")
    qtbot.addWidget(reader)
    reader.show()
    reader.open_book(path)
    wait_book(qtbot, reader)
    assert reader.pdf_document.pageCount() == 2
    reader.go(1)
    wait_book(qtbot, reader)
    reader.clear()
    reader.open_book(path)
    wait_book(qtbot, reader)
    assert reader.page == 1
    assert path.read_bytes() == original
    reader.clear()


def test_library_scan_filter_and_open(qtbot, tmp_path):
    make_epub(tmp_path / "Quiet.epub")
    make_epub(tmp_path / "Other.epub")
    room = ReadingRoom(tmp_path / "progress.json")
    qtbot.addWidget(room)
    room.show()
    room.set_roots((tmp_path,))
    room.activate()
    qtbot.waitUntil(lambda: room._scanned)
    assert len(room.book_items) == 2
    room.filter.setText("quiet")
    visible = [item for item in room.book_items if not item.isHidden()]
    assert len(visible) == 1
    room._open(visible[0])
    wait_book(qtbot, room.reader)
    assert room.reader.path.name == "Quiet.epub"
    room.stop()


def test_corrupt_book_can_be_followed_by_valid_book(qtbot, tmp_path):
    bad = tmp_path / "bad.epub"
    bad.write_text("not a zip")
    reader = BookReader(tmp_path / "progress.json")
    qtbot.addWidget(reader)
    reader.open_book(bad)
    qtbot.waitUntil(lambda: "Could not open" in reader.notice.text())
    assert not reader.next.isEnabled()
    reader.open_book(make_epub(tmp_path / "good.epub"))
    wait_book(qtbot, reader)
    assert reader.next.isEnabled()
    reader.clear()


def test_closed_reader_ignores_late_loading_results(qtbot, tmp_path, monkeypatch):
    jobs = []
    monkeypatch.setattr(
        "torrentlinker.gui.ebook_reader.run_in_background",
        lambda work, done, failed: jobs.append((work, done)),
    )
    reader = BookReader(tmp_path / "progress.json")
    qtbot.addWidget(reader)
    reader.open_book(make_epub(tmp_path / "book.epub"))
    reader.clear()
    work, done = jobs.pop()
    done(work())
    assert reader.path is None
    assert reader.text.toPlainText() == ""


def test_reading_room_fits_small_screen_and_returns_to_normal_navigation(qtbot, tmp_path):
    window = MainWindow(Settings(), tmp_path / "settings.json", Store(tmp_path / "state.db"))
    qtbot.addWidget(window)
    window.show()
    window._update_reading_room(ebook_view(10000, tmp_path))
    window._open_reading_room()
    qtbot.waitUntil(lambda: window.reading_room._scanned)
    window.resize(800, 560)
    qtbot.wait(20)
    assert window.size().width() == 800
    assert window.workspace_scroll.horizontalScrollBar().maximum() == 0
    assert not window.band.isVisible()
    window.shell_host.command("navigate", {"view": "zen"})
    assert window.tabs.currentIndex() == 0
    assert window.band.isVisible()
    assert not window.shell_host.page() == "reading"


def test_page_turns_reach_every_chapter_and_return_to_previous_last_page(qtbot, tmp_path):
    reader = BookReader(tmp_path / "progress.json")
    qtbot.addWidget(reader)
    reader.resize(1400, 700)
    reader.show()
    reader.open_book(make_epub(tmp_path / "book.epub"))
    wait_book(qtbot, reader)
    assert reader.paper.spread == 2
    count = reader.paper.count
    reader.turn(1)
    assert reader.paper.leaf == 2
    assert reader.paper.animation.state() == reader.paper.animation.State.Running
    while reader.paper.leaf + reader.paper.spread < count:
        reader.turn(1)
    reader.turn(1)
    wait_book(qtbot, reader)
    assert reader.page == 1 and reader.paper.leaf == 0
    reader.turn(-1)
    wait_book(qtbot, reader)
    assert reader.page == 0 and reader.paper.leaf == reader.paper.count - 1
    reader.resize(600, 700)
    qtbot.wait(30)
    assert reader.paper.spread == 1
    assert reader.paper.leaf == reader.paper.count - 1
    qtbot.keyClick(reader.paper, Qt.Key.Key_Left)
    assert reader.paper.leaf == reader.paper.count - 2
    reader.clear()


def test_epub_cover_is_centered_and_fits_after_resize(qtbot, tmp_path):
    path = make_epub(tmp_path / "cover.epub")
    image = QImage(300, 800, QImage.Format.Format_RGB32)
    image.fill(QColor("steelblue"))
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["OEBPS/chapter0.xhtml"] = (
        b'<html><body><svg><image xlink:href="cover.png"/></svg></body></html>'
    )
    entries["OEBPS/cover.png"] = bytes(raw)
    with ZipFile(path, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    reader = BookReader(tmp_path / "progress.json")
    qtbot.addWidget(reader)
    reader.resize(850, 700)
    reader.show()
    reader.open_book(path)
    wait_book(qtbot, reader)
    for size in [(850, 700), (600, 400), (1200, 900)]:
        reader.resize(*size)
        qtbot.wait(30)
        block = reader.text.document().begin()
        assert block.blockFormat().alignment() == Qt.AlignmentFlag.AlignCenter
        fmt = block.begin().fragment().charFormat().toImageFormat()
        assert fmt.height() <= reader.paper.page_size.height() - 80
        assert fmt.height() >= reader.paper.page_size.height() - 110
        assert reader.paper.count == 1
    reader.clear()


def test_bookshelf_can_be_hidden_without_losing_book(qtbot, tmp_path):
    room = ReadingRoom(tmp_path / "progress.json")
    qtbot.addWidget(room)
    room.show()
    room.reader.open_book(make_epub(tmp_path / "book.epub"))
    wait_book(qtbot, room.reader)
    qtbot.mouseClick(room.reader.library_toggle, Qt.MouseButton.LeftButton)
    assert room.bookshelf.isHidden()
    assert room.reader.path is not None
    qtbot.mouseClick(room.reader.library_toggle, Qt.MouseButton.LeftButton)
    assert room.bookshelf.isVisible()
    room.stop()


def test_bookshelf_tree_counts_and_filters_subcategories(qtbot, tmp_path):
    fiction = make_epub(tmp_path / "Novel.epub")
    comic = make_epub(tmp_path / "Comic.epub")
    make_epub(tmp_path / "Unknown.epub")
    room = ReadingRoom(tmp_path / "progress.json")
    qtbot.addWidget(room)
    room.show()
    room.set_roots((tmp_path,), {fiction: ("Ebook", "Books"), comic: ("Ebook", "Comics")})
    room.activate()
    qtbot.waitUntil(lambda: room._scanned)
    assert room.branches[("Ebook",)].text(0) == "Ebook (2)"
    assert room.branches[("Ebook", "Comics")].text(0) == "Comics (1)"
    assert len(room.book_items) == 3
    room._open(room.branches[("Ebook",)])
    assert room.reader.path is None
    room.filter.setText("Comics")
    assert not room.branches[("Ebook", "Comics")].isHidden()
    assert room.branches[("Ebook", "Books")].isHidden()
    assert room.branches[("Ebook", "Comics")].isExpanded()
    assert len([item for item in room.book_items if not item.isHidden()]) == 1
    room.filter.clear()
    assert not room.branches[("Ebook", "Books")].isHidden()
    assert not room.branches[("Ebook", "Comics")].isExpanded()
    room.stop()


def test_epub_page_counter_tracks_visible_pages_not_chapter_number(qtbot, tmp_path):
    reader = BookReader(tmp_path / "progress.json")
    qtbot.addWidget(reader)
    reader.resize(1400, 700)
    reader.show()
    reader.open_book(make_epub(tmp_path / "book.epub"))
    wait_book(qtbot, reader)
    reader.turn(1)
    assert reader.page == 0
    assert reader.paper.leaf == 2
    assert reader.position.value() == 3
    assert reader.position.maximum() == reader.paper.count
    reader.position.setValue(5)
    assert reader.page == 0
    assert reader.paper.leaf == 4
    reader.go(1)
    wait_book(qtbot, reader)
    assert reader.page == 1
    assert reader.position.value() == 1
    assert "2" in reader.notice.text()
    reader.clear()


def test_hidden_bookshelf_does_not_keep_old_categories_when_scan_finishes_late(
    qtbot, tmp_path, monkeypatch
):
    from torrentlinker.ebooks import Book, BookLibrary

    callbacks = []
    monkeypatch.setattr(
        "torrentlinker.gui.ebook_reader.run_in_background",
        lambda work, done, failed: callbacks.append(done),
    )
    room = ReadingRoom(tmp_path / "progress.json")
    qtbot.addWidget(room)
    path = tmp_path / "book.epub"
    room.set_roots((tmp_path,), {path: ("Ebook",)})
    room.activate()
    room.set_roots((tmp_path,), {path: ("Ebook", "Comics")})
    callbacks[0](BookLibrary([Book(path, ("Ebook",))], 0))
    room.activate()
    assert len(callbacks) == 2, "Returning to the room must fetch the updated subcategories"
    callbacks[1](BookLibrary([Book(path, ("Ebook", "Comics"))], 0))
    assert ("Ebook", "Comics") in room.branches
    room.stop()


def test_books_with_only_parent_category_have_other_branch(qtbot, tmp_path):
    book = make_epub(tmp_path / "book.epub")
    room = ReadingRoom(tmp_path / "progress.json")
    qtbot.addWidget(room)
    room.set_roots((tmp_path,), {book: ("Ebook",)})
    room.activate()
    qtbot.waitUntil(lambda: room._scanned)
    assert ("Ebook", "Other / unspecified") in room.branches
    assert room.branches[("Ebook",)].childCount() == 1
    assert room.book_items[0].parent() is room.branches[("Ebook", "Other / unspecified")]
    room.filter.setText("Other")
    assert not room.book_items[0].isHidden()
    assert room.branches[("Ebook",)].text(0) == "Ebook (1)"
    room.stop()
