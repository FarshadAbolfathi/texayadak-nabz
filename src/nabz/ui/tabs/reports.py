"""تب گزارش‌ها — تاریخچهٔ اجراها و لاگ."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import jalali
from ...db import Database
from ..widgets import Card, make_copyable

_STATUS_FA = {
    "running": "در حال اجرا",
    "done": "انجام شد",
    "failed": "ناموفق",
    "rolled_back": "بازگردانده شد",
}
_MODE_FA = {"auto": "سینک خودکار", "manual": "سینک دستی", "excel": "اکسل",
            "create": "ایجاد محصول", "edit": "ویرایش محصولات"}
_LEVEL_FA = {"info": "اطلاع", "warn": "هشدار", "error": "خطا"}


def _fa(s) -> str:
    return str(s).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _fmt_time(ts) -> str:
    """زمان به تاریخ شمسی: ۱۴۰۵/۰۷/۰۸  ۱۴:۰۵"""
    return jalali.format_ts(ts)


class ReportsTab(QWidget):
    HEADERS = ["#", "زمان", "نوع", "وضعیت", "تغییرات", "خطا"]

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QLabel("گزارش اجراها")
        header.setObjectName("H1")
        layout.addWidget(header)

        refresh = QPushButton("🔄  به‌روزرسانی")
        refresh.clicked.connect(self.refresh)
        refresh.setMaximumWidth(160)
        layout.addWidget(refresh)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        make_copyable(self.table)
        layout.addWidget(self.table, 1)

        logs_header = QLabel("رویدادها")
        logs_header.setObjectName("H1")
        layout.addWidget(logs_header)
        self.logs = QTableWidget(0, 3)
        self.logs.setHorizontalHeaderLabels(["زمان", "سطح", "پیام"])
        self.logs.setAlternatingRowColors(True)
        self.logs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.logs.verticalHeader().setVisible(False)
        self.logs.setColumnWidth(0, 150)
        self.logs.setColumnWidth(1, 70)
        self.logs.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.logs.setWordWrap(True)
        make_copyable(self.logs)
        layout.addWidget(self.logs, 1)

    def refresh(self) -> None:
        self._refresh_logs()
        runs = self.db.recent_runs(limit=100)
        self.table.setRowCount(len(runs))
        for r, run in enumerate(runs):
            summary = {}
            if run.get("summary"):
                try:
                    summary = json.loads(run["summary"])
                except (ValueError, TypeError):
                    pass
            cells = [
                _fa(run["id"]),
                _fmt_time(run.get("finished_at") or run.get("started_at")),
                _MODE_FA.get(run["mode"], run["mode"]),
                _STATUS_FA.get(run["status"], run["status"]),
                _fa(summary.get("applied", 0)),
                _fa(summary.get("failed", 0)),
            ]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if c != 1:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, cell)

    def _refresh_logs(self) -> None:
        logs = self.db.recent_logs(200)
        self.logs.setRowCount(len(logs))
        colors = {"error": "#c62828", "warn": "#ef6c00"}
        for r, log in enumerate(logs):
            cells = [
                _fmt_time(log["at"]),
                _LEVEL_FA.get(log["level"], log["level"]),
                _fa(log["message"]),
            ]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if c < 2:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 1 and log["level"] in colors:
                    from PySide6.QtGui import QColor
                    cell.setForeground(QColor(colors[log["level"]]))
                cell.setToolTip(text)
                self.logs.setItem(r, c, cell)
