"""The app's button roles. A page picks a role; the theme decides how it looks.

- primary: the one main action of an area (Play, Send).
- secondary: an ordinary bordered action; the default for any button.
- quiet: a low-weight text action inside a panel.
- icon: a square glyph button; it always has a tooltip and an accessible name.

`tab` is the matching style for in-page navigation (Video / Music, Home / Films).
A dark page such as the Media Center may recolor a role, never reshape it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractButton, QDoubleSpinBox, QSpinBox, QToolButton

ROLES = {"primary", "secondary", "quiet", "icon", "tab"}


def set_role(button: QAbstractButton, role: str) -> QAbstractButton:
    if role not in ROLES:
        raise ValueError(f"Unknown button role: {role}")
    button.setProperty("role", role)
    # A property change only restyles a widget that is polished again.
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    return button


def icon_button(glyph: str, tooltip: str, *, parent=None) -> QToolButton:
    button = QToolButton(parent)
    button.setText(glyph)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    set_role(button, "icon")
    return button


class ScrollSpinBox(QSpinBox):
    """Wheel gestures scroll the form; arrows and typing still edit the value."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class ScrollDoubleSpinBox(QDoubleSpinBox):
    """A decimal input that never turns a scrolling gesture into an edit."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()
