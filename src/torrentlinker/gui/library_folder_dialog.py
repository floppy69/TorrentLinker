"""Configure a Library Folder without leaving the Library."""

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QSpinBox

AUTOMATIC = -1  # the spin box value shown as "Automatic"


def grouping_box(depth: int | None) -> QSpinBox:
    """Scan grouping: Automatic, or a fixed depth for layouts detection gets wrong."""
    box = QSpinBox()
    box.setRange(AUTOMATIC, 10)
    box.setSpecialValueText(QCoreApplication.translate("LibraryFolderDialog", "Automatic"))
    box.setPrefix(QCoreApplication.translate("LibraryFolderDialog", "Depth "))
    box.setValue(AUTOMATIC if depth is None else depth)
    return box


def grouping(box: QSpinBox) -> int | None:
    return None if box.value() == AUTOMATIC else box.value()
