"""ویجت‌های کوچک و پرکاربرد مشترک بین تب‌ها."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .theme import COLORS


class Card(QFrame):
    """پنل سفید با گوشهٔ گرد و یک نوار نارنجی کوچک کنار عنوان."""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 18, 20, 18)
        self._layout.setSpacing(12)
        if title:
            header = QHBoxLayout()
            header.setSpacing(8)
            accent = QFrame()
            accent.setObjectName("CardAccent")
            accent.setFixedWidth(4)
            accent.setMinimumHeight(20)
            label = QLabel(title)
            label.setObjectName("CardTitle")
            header.addWidget(accent)
            header.addWidget(label)
            header.addStretch(1)
            self._layout.addLayout(header)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)


class StatCard(QFrame):
    """کارت آمار: عدد بزرگ + برچسب، با نوار رنگی بالا."""

    def __init__(self, label: str, value: str = "—", color: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(6)

        self._value = QLabel(value)
        self._value.setObjectName("StatNumber")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if color:
            self._value.setStyleSheet(f"color: {color}; font-size: 32px; font-weight: bold;")

        self._label = QLabel(label)
        self._label.setObjectName("StatLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._value)
        layout.addWidget(self._label)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


def field(label_text: str, widget: QWidget) -> QWidget:
    """یک فیلد با برچسب بالای آن (چیدمان عمودی، مطمئن برای RTL).

    جایگزین QFormLayout که در حالت راست‌به‌چپ گاهی برچسب‌ها را درست
    نشان نمی‌دهد.
    """
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    label = QLabel(label_text)
    label.setObjectName("FieldLabel")
    layout.addWidget(label)
    layout.addWidget(widget)
    return container


def inline_field(label_text: str, widget: QWidget, label_width: int = 180) -> QWidget:
    """فیلد با برچسب کنار آن (افقی)؛ برای فیلدهای کوتاه."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    label = QLabel(label_text)
    label.setObjectName("FieldLabel")
    label.setMinimumWidth(label_width)
    layout.addWidget(label)
    layout.addWidget(widget, 1)
    return container


def scrollable(content: QWidget) -> QScrollArea:
    """محتوای یک تب را در یک ناحیهٔ اسکرول عمودی می‌پیچد."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll


def h_line() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {COLORS['border']};")
    return line


def row(*widgets: QWidget, stretch_last: bool = False) -> QWidget:
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
