"""ویجت‌های کوچک و پرکاربرد مشترک بین تب‌ها."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .theme import COLORS


class Card(QFrame):
    """یک پنل سفید با گوشهٔ گرد؛ ظرف عمومی محتوا."""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 16, 18, 16)
        self._layout.setSpacing(12)
        if title:
            label = QLabel(title)
            label.setObjectName("CardTitle")
            self._layout.addWidget(label)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)


class StatCard(QFrame):
    """کارت آمار: یک عدد بزرگ و یک برچسب — برای داشبورد."""

    def __init__(self, label: str, value: str = "—", color: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)

        self._value = QLabel(value)
        self._value.setObjectName("StatNumber")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if color:
            self._value.setStyleSheet(f"color: {color};")

        self._label = QLabel(label)
        self._label.setObjectName("StatLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._value)
        layout.addWidget(self._label)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


def h_line() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {COLORS['border']};")
    return line


def row(*widgets: QWidget, stretch_last: bool = False) -> QWidget:
    """چند ویجت را در یک ردیف افقی می‌چیند."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for i, widget in enumerate(widgets):
        layout.addWidget(widget)
        if stretch_last and i == len(widgets) - 1:
            layout.setStretchFactor(widget, 1)
    return container


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label
