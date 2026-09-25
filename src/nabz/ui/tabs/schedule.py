"""تب زمان‌بندی — تنظیم اجرای خودکار روزانه.

خودِ اجرای زمان‌بندی‌شده در لایهٔ scheduler انجام می‌شود؛ این تب فقط
تنظیمات را ذخیره می‌کند (ساعت اجرا، فعال/غیرفعال).
"""

from __future__ import annotations

from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ...db import Database
from ..widgets import Card, muted, scrollable


class ScheduleTab(QWidget):
    schedule_changed = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._build()
        self._load()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        header = QLabel("زمان‌بندی خودکار")
        header.setObjectName("H1")
        layout.addWidget(header)

        card = Card("اجرای خودکار روزانه")
        self.enabled = QCheckBox("اجرای خودکار فعال باشد")
        card.add(self.enabled)

        form = QFormLayout()
        form.setSpacing(12)
        self.time = QTimeEdit()
        self.time.setDisplayFormat("HH:mm")
        form.addRow("ساعت اجرا:", self.time)

        self.sync_price = QCheckBox("به‌روزرسانی قیمت")
        self.sync_price.setChecked(True)
        self.sync_stock = QCheckBox("به‌روزرسانی موجودی")
        self.sync_stock.setChecked(True)
        form.addRow("موارد سینک:", self.sync_price)
        form.addRow("", self.sync_stock)

        card.body().addLayout(form)
        card.add(muted(
            "در ساعت تعیین‌شده، برنامه به‌صورت خودکار قیمت و موجودی را به‌روز "
            "می‌کند. اگر در آن لحظه سیستم خاموش باشد، در اولین فرصت روشن‌شدن "
            "اجرا می‌شود. برای اجرای خودکار، برنامه باید در حال اجرا (یا در "
            "System Tray) باشد."
        ))
        layout.addWidget(card)

        save = QPushButton("💾  ذخیرهٔ زمان‌بندی")
        save.setObjectName("Primary")
        save.setMinimumHeight(46)
        save.clicked.connect(self._save)
        layout.addWidget(save)
        layout.addStretch(1)
        outer.addWidget(scrollable(content))

    def _load(self) -> None:
        self.enabled.setChecked(bool(self.db.get_setting("schedule_enabled", False)))
        hhmm = self.db.get_setting("schedule_time", "03:00")
        h, m = (int(x) for x in hhmm.split(":"))
        self.time.setTime(QTime(h, m))
        self.sync_price.setChecked(bool(self.db.get_setting("schedule_price", True)))
        self.sync_stock.setChecked(bool(self.db.get_setting("schedule_stock", True)))

    def _save(self) -> None:
        self.db.set_setting("schedule_enabled", self.enabled.isChecked())
        self.db.set_setting("schedule_time", self.time.time().toString("HH:mm"))
        self.db.set_setting("schedule_price", self.sync_price.isChecked())
        self.db.set_setting("schedule_stock", self.sync_stock.isChecked())
        self.schedule_changed.emit()
        QMessageBox.information(self, "ذخیره شد", "تنظیمات زمان‌بندی ذخیره شد.")
