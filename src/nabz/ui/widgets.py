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


# -- جدول‌ها -------------------------------------------------------------


def fa(value) -> str:
    """ارقام را فارسی می‌کند."""
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def money(value, unit: str = "تومان") -> str:
    """۱۲۳۴۵۰۰ → «۱٬۲۳۴٬۵۰۰ تومان»."""
    if value in (None, ""):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{int(number):,}" if number == int(number) else f"{number:,.2f}"
    return fa(text.replace(",", "٬")) + (f" {unit}" if unit else "")


def selected_text(table) -> str:
    """متن خانه‌های انتخاب‌شده، به شکل جدول (tab/خط جدید) برای paste در اکسل."""
    ranges = table.selectedRanges()
    if not ranges:
        item = table.currentItem()
        return item.text() if item else ""
    lines = []
    for rng in ranges:
        for r in range(rng.topRow(), rng.bottomRow() + 1):
            if table.isRowHidden(r):
                continue
            cells = []
            for c in range(rng.leftColumn(), rng.rightColumn() + 1):
                if table.isColumnHidden(c):
                    continue
                item = table.item(r, c)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))
    return "\n".join(lines)


def make_copyable(table, *, code_columns: tuple[int, ...] = (), on_copied=None) -> None:
    """کپی با Ctrl+C و منوی راست‌کلیک به یک QTableWidget اضافه می‌کند.

    :param code_columns: ستون‌های «کد»؛ در منو گزینهٔ «کپی کد» می‌گیرند.
    :param on_copied: تابعی که پیام کوتاه «کپی شد» را نمایش دهد.
    """
    from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
    from PySide6.QtWidgets import QMenu

    def copy(text: str) -> None:
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        if on_copied:
            on_copied(f"کپی شد: {text if len(text) < 60 else text[:60] + '…'}")

    action = QAction("کپی", table)
    action.setShortcut(QKeySequence.StandardKey.Copy)
    action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    action.triggered.connect(lambda: copy(selected_text(table)))
    table.addAction(action)

    def menu(pos) -> None:
        item = table.itemAt(pos)
        m = QMenu(table)
        if item is not None:
            if item.column() in code_columns:
                m.addAction("📋  کپی کد", lambda: copy(item.text()))
            m.addAction("📋  کپی این خانه", lambda: copy(item.text()))
            r = item.row()

            def row_text() -> str:
                return "\t".join(
                    table.item(r, c).text() if table.item(r, c) else ""
                    for c in range(table.columnCount())
                    if not table.isColumnHidden(c)
                )

            m.addAction("📋  کپی کل ردیف", lambda: copy(row_text()))
        m.addAction("📋  کپی انتخاب‌شده‌ها (Ctrl+C)", lambda: copy(selected_text(table)))
        m.exec(table.viewport().mapToGlobal(pos))

    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(menu)
