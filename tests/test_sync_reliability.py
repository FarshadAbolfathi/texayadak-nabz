"""قابلیت اطمینان سینک: قفل سراسری، اجرای تک‌نسخه‌ای و گزارش تغییرات ایساکو.

مشکلات واقعی گزارش‌شده:
- زمان‌بندی هر ۲ ساعت: بعضی اجرا نمی‌شد و نیمه‌شب ده‌ها اجرای پشت‌سرهم ثبت شد
  (دانلودهای تودرتو + چند نسخهٔ هم‌زمان برنامه)
- سینک دستی «تغییرات ۰» نشان می‌داد و معلوم نبود لیست ایساکو تازه است یا نه
"""

from __future__ import annotations

import datetime as dt
import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from nabz.config import CredentialStore, MemoryBackend, WooCredentials
from nabz.db import Database
from nabz.sources.isaco_excel import IsacoItem
from nabz.sync_gate import gate


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def store():
    s = CredentialStore(backend=MemoryBackend())
    s.save_woo(WooCredentials(base_url="https://x.com", consumer_key="ck",
                              consumer_secret="cs"))
    return s


@pytest.fixture(autouse=True)
def no_dialogs(monkeypatch):
    shown = []
    yes = QMessageBox.StandardButton.Yes
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: (shown.append(_n), yes)[1]))
    return shown


def pump(cond, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    return cond()


@pytest.fixture
def window(qapp, db, store):
    from nabz.ui.main_window import MainWindow
    w = MainWindow(db, store)
    yield w
    w._allow_close = True
    w._schedule_timer.stop()


class TestGate:
    def test_only_one_owner(self):
        assert gate.try_acquire("الف")
        assert not gate.try_acquire("ب")
        gate.release("ب")                 # آزادسازیِ صاحب دیگر اثری ندارد
        assert gate.busy
        gate.release("الف")
        assert not gate.busy

    def test_nested_request_during_download_is_refused(self, window, monkeypatch):
        """وسط دانلود (حلقهٔ تودرتو) درخواست دوم نباید دانلود/سینک دیگری شروع کند."""
        from nabz.jobs import AutoSyncResult
        downloads = []
        syncs = []

        def fake_download(*a, **k):
            downloads.append(1)
            # مثل حلقهٔ رویداد تودرتوی دانلود: درخواست‌های دیگر همین‌جا می‌رسند
            window.run_auto_sync_async(mode="auto")
            window._run_schedule_test()
            return None

        monkeypatch.setattr("nabz.jobs.try_auto_download_isaco", fake_download)
        monkeypatch.setattr("nabz.jobs.run_auto_sync",
                            lambda *a, **k: (syncs.append(1), AutoSyncResult(True, "ok"))[1])
        window.run_auto_sync_async(mode="auto", update_price=True)
        assert pump(lambda: not gate.busy, 10)
        assert downloads == [1] and syncs == [1]

    def test_scheduled_run_waits_while_sync_tab_busy(self, window, monkeypatch):
        from nabz.scheduler import ScheduleConfig, ScheduleEntry
        started = []
        monkeypatch.setattr(window, "run_auto_sync_async",
                            lambda *a, **k: started.append(k))
        window._scheduler._config = ScheduleConfig(
            enabled=True, entries=[ScheduleEntry(8, 0)])
        window.db.set_setting("schedule_last_slot", None)

        assert window.sync._set_busy(True, "دریافت و مقایسه")
        assert window._scheduler.tick(dt.datetime(2026, 1, 2, 8, 1)) is None
        window.sync._set_busy(False)
        assert window._scheduler.tick(dt.datetime(2026, 1, 2, 8, 2)) is not None
        assert pump(lambda: started, 2)

    def test_sync_tab_refuses_while_auto_sync_runs(self, window, no_dialogs):
        assert gate.try_acquire("سینک خودکار")
        window.sync._fetch()
        assert "information" in no_dialogs
        assert window.sync.fetch_btn.isEnabled()
        gate.release()

    def test_schedule_timer_runs_on_main_window(self, window):
        assert window._schedule_timer.isActive()
        assert window._schedule_timer.interval() <= 60_000


class TestLastRunCountsOnlyAutoSync:
    def test_row_manual_and_create_runs_do_not_satisfy_slot(self, window):
        db = window.db
        for mode in ("row", "manual", "create", "edit"):
            rid = db.start_run(mode)
            db.finish_run(rid, "done", {})
        assert window._last_successful_run_time() is None
        rid = db.start_run("auto")
        db.finish_run(rid, "done", {})
        assert window._last_successful_run_time() is not None

    def test_single_row_apply_is_recorded_as_row(self, window):
        src = __import__("inspect").getsource(type(window.sync)._apply_single)
        assert 'mode="row"' in src


def item(code, vat):
    return IsacoItem(code, "x", "", "عدد", 1, retail=vat - 10, vat=vat, wholesale=vat - 20)


class TestIsacoDiff:
    def test_first_then_daily_changes(self, db, tmp_path):
        from nabz.jobs import record_isaco_diff
        first = record_isaco_diff(db, {"1": item("1", 100), "2": item("2", 200)}, tmp_path)
        assert first["first"]
        second = record_isaco_diff(
            db, {"1": item("1", 150), "2": item("2", 200), "3": item("3", 5)}, tmp_path)
        assert second["changed"] == 1 and second["added"] == 1 and second["codes"] == ["1"]

    def test_same_day_changes_accumulate(self, db, tmp_path):
        from nabz.jobs import record_isaco_diff
        record_isaco_diff(db, {"1": item("1", 100), "2": item("2", 200)}, tmp_path)
        record_isaco_diff(db, {"1": item("1", 110), "2": item("2", 200)}, tmp_path)
        third = record_isaco_diff(db, {"1": item("1", 110), "2": item("2", 210)}, tmp_path)
        assert third["changed"] == 1
        assert sorted(third["today_codes"]) == ["1", "2"]

    def test_freshness_explains_zero_changes(self, db, tmp_path):
        """«تغییرات ۰»: امروز ایساکو عوض کرده ولی سینک خودکار قبلاً اعمال کرده."""
        from nabz.jobs import isaco_freshness, record_isaco_diff
        record_isaco_diff(db, {"1": item("1", 100), "2": item("2", 200)}, tmp_path)
        record_isaco_diff(db, {"1": item("1", 150), "2": item("2", 250)}, tmp_path)
        db.set_setting("isaco_downloaded_at", time.time())
        text, stale = isaco_freshness(db, {"1", "2", "9"}, pending_codes=set(),
                                      downloaded_now=True)
        assert not stale
        assert "قیمت ۲ قلم را عوض کرده" in text
        assert "۰ قلم منتظر اعمال" in text and "۲ قلم قبلاً اعمال شده" in text

    def test_failed_download_is_flagged(self, db):
        from nabz.jobs import isaco_freshness
        db.set_setting("isaco_downloaded_at", time.time() - 86400 * 2)
        text, stale = isaco_freshness(db, set(), set(), downloaded_now=False)
        assert stale and "⚠️" in text and "لیست قبلی" in text

    def test_download_records_diff_and_report_event(self, db, monkeypatch, tmp_path):
        from nabz.config import IsacoCredentialsConfig
        from nabz.jobs import try_auto_download_isaco
        from tests.test_jobs import make_isaco_xlsx

        monkeypatch.setattr("nabz.jobs.isaco_dir", lambda: tmp_path)
        store = CredentialStore(backend=MemoryBackend())
        store.save_isaco(IsacoCredentialsConfig(scus="1", username="2", password="3"))

        class FakeDownloader:
            def __init__(self, *a, **k):
                pass

            def download(self, dest, timeout_s=240):
                make_isaco_xlsx(dest)
                return dest

        monkeypatch.setattr("nabz.sources.isaco_browser.IsacoDownloader", FakeDownloader)
        assert try_auto_download_isaco(db, store)
        assert try_auto_download_isaco(db, store)
        assert db.get_setting("isaco_diff")["changed"] == 0
        assert db.get_setting("isaco_downloaded_at")
        assert any("لیست ایساکو دانلود شد" in r["message"] for r in db.recent_logs(10))


class TestSingleInstance:
    def test_second_instance_activates_first(self, qapp, tmp_path):
        from nabz.ui.single_instance import SingleInstance
        key = f"nabz-test-{int(time.time() * 1000)}"
        first = SingleInstance(key=key, lock_path=tmp_path / "a.lock")
        assert first.acquire()
        hits = []
        first.activated.connect(lambda: hits.append(1))

        second = SingleInstance(key=key, lock_path=tmp_path / "a.lock")
        assert not second.acquire()
        assert pump(lambda: hits, 3)

        first.release()
        third = SingleInstance(key=key, lock_path=tmp_path / "a.lock")
        assert third.acquire()            # پس از بسته شدن اولی، دوباره می‌شود
        third.release()
