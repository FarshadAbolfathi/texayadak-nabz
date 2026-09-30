"""تب زمان‌بندی — تنظیم اجراهای خودکار روزانه (چند ساعت در روز).

خودِ اجرای زمان‌بندی‌شده در لایهٔ scheduler انجام می‌شود؛ این تب فقط
تنظیمات را ذخیره می‌کند: کلید اصلی و فهرست ساعت‌ها. هر ساعت جداگانه
تعیین می‌کند قیمت، موجودی یا هر دو به‌روز شوند؛ مثلاً موجودی هر چند
ساعت یک‌بار و قیمت فقط شب‌ها.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ... import jalali
from ...db import Database
from ...scheduler import ScheduleConfig, ScheduleEntry, next_entry_at
from ..widgets import Card, muted, scrollable


def _centered(widget: QWidget) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(4, 0, 4, 0)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(widget)
    return box


class ScheduleTab(QWidget):
    schedule_changed = Signal()
    run_now_requested = Signal()

    HEADERS = ["فعال", "ساعت اجرا", "قیمت", "موجودی", "حذف"]
    COL_ON, COL_TIME, COL_PRICE, COL_STOCK, COL_DEL = range(5)

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

        card = Card("اجراهای خودکار روزانه")
        self.enabled = QCheckBox("اجرای خودکار فعال باشد")
        card.add(self.enabled)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setMinimumHeight(240)
        head = self.table.horizontalHeader()
        for c in range(len(self.HEADERS)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        card.add(self.table)

        buttons = QHBoxLayout()
        add = QPushButton("➕  افزودن ساعت اجرا")
        add.setObjectName("Accent")
        add.clicked.connect(lambda: self._add_row(self._suggest_next_entry()))
        buttons.addWidget(add)
        buttons.addStretch(1)
        card.body().addLayout(buttons)

        self.next_label = muted("")
        card.add(self.next_label)
        card.add(muted(
            "در هر ساعت تعیین‌شده، برنامه به‌صورت خودکار لیست قیمت را از ایساکو "
            "دانلود می‌کند، موجودی را از حاسب می‌خواند و روی سایت اعمال "
            "می‌کند. برای هر ساعت می‌توانید مشخص کنید فقط قیمت، فقط موجودی یا "
            "هر دو به‌روز شوند (مثلاً موجودی هر ۳ ساعت، قیمت فقط شب‌ها). اگر در "
            "آن لحظه سیستم خاموش باشد، آخرین اجرای جاافتاده در اولین فرصت "
            "انجام می‌شود. کافی است برنامه در حال اجرا (یا در System Tray) باشد."
        ))
        layout.addWidget(card)

        save = QPushButton("💾  ذخیرهٔ زمان‌بندی")
        save.setObjectName("Primary")
        save.setMinimumHeight(46)
        save.clicked.connect(self._save)
        layout.addWidget(save)

        test_card = Card("آزمایش زمان‌بندی")
        test_card.add(muted(
            "برای اطمینان از اینکه سینک خودکار درست کار می‌کند، بدون نیاز "
            "به صبر کردن تا ساعت تعیین‌شده، همین حالا آن را اجرا کنید. "
            "دقیقاً همان کاری انجام می‌شود که زمان‌بندی انجام می‌دهد."
        ))
        run_now = QPushButton("▶️  تست همین حالا")
        run_now.setObjectName("Accent")
        run_now.clicked.connect(self._run_now)
        test_card.add(run_now)
        layout.addWidget(test_card)

        layout.addStretch(1)
        outer.addWidget(scrollable(content))

    # -- ردیف‌ها -------------------------------------------------------

    def _add_row(self, entry: ScheduleEntry) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)

        on = QCheckBox()
        on.setChecked(entry.enabled)
        self.table.setCellWidget(r, self.COL_ON, _centered(on))

        time_edit = QTimeEdit(QTime(entry.hour, entry.minute))
        time_edit.setDisplayFormat("HH:mm")
        time_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setCellWidget(r, self.COL_TIME, time_edit)

        price = QCheckBox()
        price.setChecked(entry.price)
        self.table.setCellWidget(r, self.COL_PRICE, _centered(price))

        stock = QCheckBox()
        stock.setChecked(entry.stock)
        self.table.setCellWidget(r, self.COL_STOCK, _centered(stock))

        delete = QPushButton("🗑")
        delete.setObjectName("Danger")
        delete.setToolTip("حذف این ساعت")
        delete.clicked.connect(lambda _=False, w=delete: self._delete_row(w))
        self.table.setCellWidget(r, self.COL_DEL, _centered(delete))

        for w in (on, price, stock):
            w.toggled.connect(self._refresh_next)
        time_edit.timeChanged.connect(self._refresh_next)
        self._refresh_next()

    def _delete_row(self, button: QPushButton) -> None:
        for r in range(self.table.rowCount()):
            cell = self.table.cellWidget(r, self.COL_DEL)
            if cell is not None and button in cell.findChildren(QPushButton):
                self.table.removeRow(r)
                break
        self._refresh_next()

    def _check(self, r: int, col: int) -> bool:
        box = self.table.cellWidget(r, col).findChild(QCheckBox)
        return bool(box and box.isChecked())

    def entries(self) -> list[ScheduleEntry]:
        result = []
        for r in range(self.table.rowCount()):
            t = self.table.cellWidget(r, self.COL_TIME).time()
            result.append(ScheduleEntry(
                hour=t.hour(),
                minute=t.minute(),
                price=self._check(r, self.COL_PRICE),
                stock=self._check(r, self.COL_STOCK),
                enabled=self._check(r, self.COL_ON),
            ))
        return result

    def _suggest_next_entry(self) -> ScheduleEntry:
        """ساعت پیشنهادی برای ردیف جدید: ۳ ساعت بعد از آخرین ردیف."""
        existing = self.entries()
        if not existing:
            return ScheduleEntry(3, 0)
        last = max(existing, key=lambda e: (e.hour, e.minute))
        return ScheduleEntry((last.hour + 3) % 24, last.minute)

    def _refresh_next(self, *_args) -> None:
        nxt = next_entry_at(_dt.datetime.now(), self.entries())
        if nxt is None:
            self.next_label.setText("هیچ ساعت فعالی تعریف نشده است.")
            return
        when, entry = nxt
        what = " و ".join(
            x for x, on in (("قیمت", entry.price), ("موجودی", entry.stock)) if on
        ) or "هیچ‌چیز"
        self.next_label.setText(
            f"اجرای بعدی: {jalali.format_long(when)} — ساعت "
            f"{jalali.fa_digits(entry.hhmm)} ({what})"
        )

    # -- ذخیره/بارگذاری -------------------------------------------------

    def _load(self) -> None:
        config = ScheduleConfig.from_settings(self.db.get_setting)
        self.enabled.setChecked(config.enabled)
        self.table.setRowCount(0)
        for entry in config.entries:
            self._add_row(entry)

    def _save(self) -> None:
        entries = self.entries()
        times = [e.hhmm for e in entries]
        duplicates = sorted({t for t in times if times.count(t) > 1})
        if duplicates:
            QMessageBox.warning(
                self, "ساعت تکراری",
                "این ساعت‌ها بیش از یک بار تعریف شده‌اند: "
                + jalali.fa_digits("، ".join(duplicates)),
            )
            return
        if any(e.enabled and not (e.price or e.stock) for e in entries):
            QMessageBox.warning(
                self, "ناقص",
                "برای هر ساعت فعال، دست‌کم یکی از «قیمت» یا «موجودی» را انتخاب کنید.",
            )
            return
        self.db.set_setting("schedule_enabled", self.enabled.isChecked())
        self.db.set_setting("schedule_entries", [e.to_dict() for e in entries])
        # سازگاری: کلیدهای قدیمی تک‌ساعته هم به‌روز بمانند
        if entries:
            self.db.set_setting("schedule_time", entries[0].hhmm)
        self.schedule_changed.emit()
        self._load()
        QMessageBox.information(self, "ذخیره شد", "تنظیمات زمان‌بندی ذخیره شد.")

    def _run_now(self) -> None:
        self.run_now_requested.emit()
