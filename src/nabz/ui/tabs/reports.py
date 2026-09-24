"""تب گزارش‌ها — تاریخچهٔ اجراها و لاگ."""

from __future__ import annotations

import json
import time

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

from ...db import Database
from ..widgets import Card

_STATUS_FA = {
    "running": "در حال اجرا",
    "done": "انجام شد",
    "failed": "ناموفق",
    "rolled_back": "بازگردانده شد",
}
_MODE_FA = {"auto": "خودکار", "manual": "دستی", "excel": "اکسل"}


def _fa(s) -> str:
    return str(s).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _fmt_time(ts) -> str:
    if not ts:
        return "—"
    return _fa(time.strftime("%Y/%m/%d  %H:%M", time.localtime(ts)))


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
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
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
