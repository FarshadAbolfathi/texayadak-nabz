"""تب داشبورد — نمای کلی و دکمه‌های سریع."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import jalali
from ...db import Database
from ..theme import COLORS
from ..widgets import Card, StatCard, muted, scrollable


def _jalali_ago(ts: float | None) -> str:
    if not ts:
        return "هنوز اجرا نشده"
    delta = time.time() - ts
    if delta < 60:
        return "لحظاتی پیش"
    if delta < 3600:
        return jalali.fa_digits(f"{int(delta // 60)} دقیقه پیش")
    if delta < 86400:
        return jalali.fa_digits(f"{int(delta // 3600)} ساعت پیش")
    # بیش از یک روز: تاریخ شمسی دقیق خواناتر است
    return jalali.format_ts(ts)


class DashboardTab(QWidget):
    sync_requested = Signal()
    rollback_requested = Signal()
    new_products_requested = Signal()
    orders_requested = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._build()
        self.refresh()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)
        self._outer = outer
        self._content = content

        title_row = QHBoxLayout()
        header = QLabel("داشبورد")
        header.setObjectName("H1")
        title_row.addWidget(header)
        title_row.addStretch(1)
        import datetime as _dt
        self.today = QLabel(f"📅  امروز: {jalali.format_long(_dt.date.today())}")
        self.today.setObjectName("Muted")
        title_row.addWidget(self.today)
        layout.addLayout(title_row)

        # کارت‌های آمار
        stats = QGridLayout()
        stats.setSpacing(14)
        self.stat_last = StatCard("آخرین به‌روزرسانی", "—")
        self.stat_changes = StatCard("تغییرات آخرین اجرا", "۰", COLORS["success"])
        self.stat_runs = StatCard("کل اجراها", "۰")
        self.stat_errors = StatCard("خطاهای اخیر", "۰", COLORS["danger"])
        stats.addWidget(self.stat_last, 0, 0)
        stats.addWidget(self.stat_changes, 0, 1)
        stats.addWidget(self.stat_runs, 0, 2)
        stats.addWidget(self.stat_errors, 0, 3)
        layout.addLayout(stats)

        # اقدامات سریع
        actions = Card("اقدامات سریع")
        row = QHBoxLayout()
        row.setSpacing(12)

        sync_btn = QPushButton("🔄  سینک فوری قیمت و موجودی")
        sync_btn.setObjectName("Primary")
        sync_btn.clicked.connect(self.sync_requested.emit)
        row.addWidget(sync_btn)

        self.rollback_btn = QPushButton("↩️  بازگرداندن آخرین اجرا")
        self.rollback_btn.setObjectName("Danger")
        self.rollback_btn.clicked.connect(self.rollback_requested.emit)
        row.addWidget(self.rollback_btn)

        actions.body().addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self.new_btn = QPushButton("🆕  محصولات جدید حاسب")
        self.new_btn.setObjectName("Accent")
        self.new_btn.clicked.connect(self.new_products_requested.emit)
        row2.addWidget(self.new_btn)
        orders_btn = QPushButton("🧾  سفارش‌های سایت")
        orders_btn.clicked.connect(self.orders_requested.emit)
        row2.addWidget(orders_btn)
        actions.body().addLayout(row2)
        actions.add(muted(
            "«سینک فوری» لیست قیمت ایساکو و موجودی حاسب را می‌گیرد و بعد از نمایش "
            "پیش‌نمایش، روی سایت اعمال می‌کند. «بازگرداندن» همه‌چیز را به قبل برمی‌گرداند."
        ))
        layout.addWidget(actions)
        layout.addStretch(1)
        self._outer.addWidget(scrollable(self._content))

    def refresh(self) -> None:
        runs = self.db.recent_runs(limit=100)
        self.stat_runs.set_value(self._fa(len(runs)))

        if runs:
            last = runs[0]
            ts = last.get("finished_at") or last.get("started_at")
            self.stat_last.set_value(_jalali_ago(ts))
            self.stat_last.setToolTip(jalali.format_ts(ts))
            summary = last.get("summary")
            if summary:
                import json
                try:
                    changes = json.loads(summary).get("applied", 0)
                    self.stat_changes.set_value(self._fa(changes))
                except (ValueError, TypeError):
                    pass

        errors = sum(1 for log in self.db.recent_logs(100) if log["level"] == "error")
        self.stat_errors.set_value(self._fa(errors))
        self.rollback_btn.setEnabled(self.db.last_applied_run() is not None)
        pending = len(self.db.get_setting("new_products_pending", []) or [])
        self.new_btn.setText(
            f"🆕  محصولات جدید حاسب ({self._fa(pending)})" if pending
            else "🆕  محصولات جدید حاسب")

    @staticmethod
    def _fa(n: int) -> str:
        return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
