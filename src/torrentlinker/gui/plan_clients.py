"""Choose one target or distribute a Plan across named clients."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from torrentlinker.config import Settings
from torrentlinker.gui.controls import ScrollDoubleSpinBox as QDoubleSpinBox


class PlanClientsDialog(QDialog):
    def __init__(self, settings: Settings, selected: dict[str, int], parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Plan destinations"))
        self.resize(620, 360)
        layout = QVBoxLayout(self)
        label = QLabel(
            self.tr(
                "Select one client, or several for automatic distribution. "
                "A budget of 0 uses available space after the free-space margin."
            )
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        profiles = [p for p in settings.client_profiles if p.enabled]
        self.table = QTableWidget(len(profiles), 3)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Use"), self.tr("Client"), self.tr("Budget · GiB")]
        )
        self.controls = {}
        for row, profile in enumerate(profiles):
            check = QCheckBox()
            check.setChecked(profile.id in selected)
            budget = QDoubleSpinBox()
            budget.setRange(0, 1_000_000)
            budget.setValue(selected.get(profile.id, 0) / 1024**3)
            self.controls[profile.id] = (check, budget)
            name = QTableWidgetItem(profile.name)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setCellWidget(row, 0, check)
            self.table.setItem(row, 1, name)
            self.table.setCellWidget(row, 2, budget)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self) -> dict[str, int]:
        return {
            identifier: int(budget.value() * 1024**3)
            for identifier, (check, budget) in self.controls.items()
            if check.isChecked()
        }
