"""باگ حیاتی گزارش‌شده توسط کاربر: کادر ساعت در حالت راست‌به‌چپ ساعت و دقیقه
را جابه‌جا نشان می‌داد؛ کارفرما «۰۸:۰۰» می‌دید ولی ۰۰:۰۸ ذخیره می‌شد → همهٔ
اجراهای روز (۸، ۱۰، ۱۲ … ۲۲) بین ۰۰:۰۰ و ۰۰:۲۲ انجام می‌شدند."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTimeEdit

from nabz.config import CredentialStore, MemoryBackend
from nabz.db import Database
from nabz.scheduler import ScheduleConfig, ScheduleEntry, fix_rtl_swapped_entries


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    before = app.layoutDirection()
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)   # مثل برنامهٔ واقعی
    yield app
    app.setLayoutDirection(before)                          # تست‌های دیگر اثر نگیرند


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def no_dialogs(monkeypatch):
    shown = []
    ok = QMessageBox.StandardButton.Ok
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: (shown.append((_n, a)), ok)[1]))
    return shown


class TestTimeEditDisplay:
    def test_plain_qtimeedit_swaps_in_rtl_app(self, qapp):
        """خودِ باگ Qt: در برنامهٔ راست‌به‌چپ، ۸:۰۰ به شکل «00:08» دیده می‌شود
        — حتی اگر جهت خود کادر چپ‌به‌راست باشد. برای همین کنار گذاشته شد."""
        e = QTimeEdit(QTime(8, 0))
        e.setDisplayFormat("HH:mm")
        e.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        assert e.text() == "00:08"

    def test_schedule_tab_uses_labeled_hour_and_minute(self, qapp, db):
        from nabz.ui.tabs.schedule import ScheduleTab
        db.set_setting("schedule_entries", [{"time": "08:00"}, {"time": "20:30"}])
        tab = ScheduleTab(db)
        first, second = tab.time_edit(0), tab.time_edit(1)
        assert (first.hour.value(), first.minute.value()) == (8, 0)
        assert (second.hour.value(), second.minute.value()) == (20, 30)
        assert "QTimeEdit" not in {type(w).__name__ for w in tab.findChildren(QTimeEdit)}

    def test_what_you_see_is_what_is_saved(self, qapp, db, no_dialogs):
        from nabz.ui.tabs.schedule import ScheduleTab
        db.set_setting("schedule_entries", [{"time": "03:00"}])
        tab = ScheduleTab(db)
        edit = tab.time_edit(0)
        edit.hour.setValue(8)
        edit.minute.setValue(0)
        assert tab.entries()[0].hhmm == "08:00"
        tab._save()
        assert db.get_setting("schedule_entries")[0]["time"] == "08:00"
        assert "۰۸:۰۰" in tab.next_label.text() if hasattr(tab, "next_label") else True


class TestMigration:
    def test_pure_swap(self):
        stored = [ScheduleEntry(0, 0), ScheduleEntry(0, 8), ScheduleEntry(0, 22),
                  ScheduleEntry(0, 30)]
        fixed, changed = fix_rtl_swapped_entries(stored)
        assert changed
        assert [e.hhmm for e in fixed] == ["00:00", "08:00", "22:00", "00:30"]

    def employer_db(self, db):
        # همان چیزی که روی سیستم کارفرما ذخیره شده بود
        db.set_setting("schedule_enabled", True)
        db.set_setting("schedule_entries", [
            {"time": f"00:{h:02d}"} for h in (0, 8, 10, 12, 14, 16, 18, 20, 22)])
        db.set_setting("schedule_last_slot", "2026-01-02 00:22")

    def test_window_fixes_once_and_tells_user(self, qapp, db, no_dialogs):
        from nabz.ui.main_window import MainWindow
        self.employer_db(db)
        w = MainWindow(db, CredentialStore(backend=MemoryBackend()))
        try:
            cfg = ScheduleConfig.from_settings(db.get_setting)
            assert [e.hhmm for e in cfg.entries] == [
                f"{h:02d}:00" for h in (0, 8, 10, 12, 14, 16, 18, 20, 22)]
            # نوبتِ ثبت‌شده با ساعت غلط (۰۰:۲۲) پاک شد
            assert db.get_setting("schedule_last_slot") != "2026-01-02 00:22"
            assert any("اصلاح" in r["message"] for r in db.recent_logs(5))
            # تب زمان‌بندی هم ساعت‌های درست را نشان می‌دهد
            shown = [w.schedule.time_edit(r).time().toString("HH:mm")
                     for r in range(w.schedule.table.rowCount())]
            assert "08:00" in shown and "00:08" not in shown
            # زمان‌بند با ساعت‌های درست کار می‌کند
            assert [e.hhmm for e in w._scheduler.config.active_entries][1] == "08:00"
        finally:
            w._schedule_timer.stop()

        # بار دوم (اجرای بعدی برنامه) دوباره جابه‌جا نمی‌کند
        w2 = MainWindow(db, CredentialStore(backend=MemoryBackend()))
        try:
            cfg = ScheduleConfig.from_settings(db.get_setting)
            assert cfg.entries[1].hhmm == "08:00"
        finally:
            w2._schedule_timer.stop()

    def test_fresh_install_is_not_touched(self, qapp, db):
        from nabz.ui.main_window import MainWindow
        w = MainWindow(db, CredentialStore(backend=MemoryBackend()))
        try:
            assert db.get_setting("schedule_entries") is None
            assert db.get_setting("schedule_rtl_fix_v1") is True
        finally:
            w._schedule_timer.stop()
