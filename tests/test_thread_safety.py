"""تست‌های ایمنی نخ — بازسازی کرش‌های بی‌صدای گزارش‌شده.

۱) تب سفارش‌ها: کلیک روی سفارش → جزئیات در پس‌زمینه خوانده می‌شد و callback
   (یک lambda) روی نخ پس‌زمینه ویجت را عوض می‌کرد → کرش بومی بدون لاگ.
۲) «تست همین حالا» زمان‌بندی: پس از پایان سینک، ارجاع QThread رها می‌شد
   و دیتابیس هم‌زمان از دو نخ بدون قفل استفاده می‌شد.
"""

from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from nabz.config import CredentialStore, MemoryBackend, WooCredentials
from nabz.db import Database

MAIN = threading.main_thread().ident


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
    yes = QMessageBox.StandardButton.Yes
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: yes))


def pump(cond, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    return cond()


class TestRunAsync:
    def test_lambda_and_closure_callbacks_run_on_main_thread(self, qapp):
        from nabz.ui.workers import run_async
        owner = QWidget()
        seen = {}

        def closure(_):
            seen["closure"] = threading.get_ident()

        run_async(owner, lambda: time.sleep(0.05) or 1,
                  on_done=lambda _: seen.__setitem__("lambda", threading.get_ident()))
        run_async(owner, lambda: 1, on_done=closure)
        run_async(owner, lambda: 1 / 0,
                  on_failed=lambda _: seen.__setitem__("failed", threading.get_ident()))
        assert pump(lambda: len(seen) == 3)
        assert set(seen.values()) == {MAIN}

    def test_threads_are_released_only_after_finishing(self, qapp):
        from nabz.ui.workers import run_async
        owner = QWidget()
        for _ in range(20):
            run_async(owner, lambda: time.sleep(0.01))
        assert pump(lambda: not owner.__dict__.get("_async_jobs"))

    def test_error_in_callback_is_logged_not_fatal(self, qapp, caplog):
        from nabz.ui.workers import run_async
        owner = QWidget()
        done = threading.Event()

        def boom(_):
            done.set()
            raise ValueError("خطای رابط")

        run_async(owner, lambda: 1, on_done=boom)
        assert pump(done.is_set)
        pump(lambda: "خطای رابط" in caplog.text, 1)
        assert "خطا در پردازش نتیجه" in caplog.text


class TestOrdersClickCrash:
    def test_order_detail_is_applied_on_main_thread(self, qapp, db, store, monkeypatch):
        from nabz.ui.tabs import orders as mod

        order = {"id": 9, "number": "9", "status": "processing", "total": "1",
                 "billing": {"first_name": "علی"}, "line_items": []}

        def slow_detail(_store, order_id):
            time.sleep(0.05)
            return dict(order, customer_note="جزئیات کامل"), []

        monkeypatch.setattr(mod, "_fetch_detail", slow_detail)
        tab = mod.OrdersTab(db, store)
        tab._on_loaded(([order], 1, 1, []), 1)

        threads = []
        real_show = tab._show_order

        def spy(o, notes):
            threads.append(threading.get_ident())
            real_show(o, notes)

        tab._show_order = spy
        tab.table.selectRow(0)
        # جزئیات کامل از پس‌زمینه می‌رسد
        assert pump(lambda: "جزئیات کامل" in tab.detail.toPlainText())
        assert threads and set(threads) == {MAIN}

    def test_fast_clicking_many_orders_does_not_crash(self, qapp, db, store, monkeypatch):
        from nabz.ui.tabs import orders as mod
        orders = [{"id": i, "number": str(i), "status": "processing", "total": "1",
                   "billing": {}, "line_items": []} for i in range(1, 30)]
        monkeypatch.setattr(mod, "_fetch_detail",
                            lambda _s, oid: (time.sleep(0.01), (orders[oid - 1], []))[1])
        tab = mod.OrdersTab(db, store)
        tab._on_loaded((orders, len(orders), 1, []), 1)
        for r in range(len(orders)):
            tab.table.selectRow(r)
            QApplication.processEvents()
        assert pump(lambda: not tab.__dict__.get("_async_jobs"), 10)
        assert "#۲۹" in tab.order_title.text()


class TestScheduleTestCrash:
    @pytest.fixture
    def window(self, qapp, db, store):
        from nabz.ui.main_window import MainWindow
        w = MainWindow(db, store)
        yield w
        w._allow_close = True
        if w._scheduler:
            w._scheduler.shutdown()

    def test_run_now_completes_and_cleans_up_on_main_thread(self, window, monkeypatch):
        from nabz.jobs import AutoSyncResult
        from nabz.ui import main_window as mw

        def fake_sync(db, store, **kw):
            # مثل سینک واقعی هم‌زمان با رابط در دیتابیس می‌نویسد
            for i in range(200):
                db.log("info", f"ردیف {i}")
            return AutoSyncResult(True, "۵ محصول به‌روز شد.")

        monkeypatch.setattr("nabz.jobs.run_auto_sync", fake_sync)
        monkeypatch.setattr("nabz.jobs.try_auto_download_isaco", lambda *a, **k: None)
        done_threads = []
        real = window._on_auto_sync_done
        monkeypatch.setattr(window, "_on_auto_sync_done",
                            lambda r: (done_threads.append(threading.get_ident()), real(r)))

        window.run_auto_sync_async(mode="auto", update_price=False)
        # هم‌زمان رابط هم دیتابیس را می‌خواند (داشبورد/گزارش‌ها)
        for _ in range(100):
            window.db.recent_logs(20)
            window.dashboard.refresh()
            QApplication.processEvents()
        assert pump(lambda: window._sync_thread is None, 10)
        assert done_threads == [MAIN]
        assert "۵ محصول" in window.statusBar().currentMessage()

    def test_second_run_is_skipped_while_first_runs(self, window, monkeypatch):
        from nabz.jobs import AutoSyncResult
        gate = threading.Event()
        monkeypatch.setattr("nabz.jobs.run_auto_sync",
                            lambda *a, **k: (gate.wait(5), AutoSyncResult(True, "ok"))[1])
        window.run_auto_sync_async(update_price=False)
        window.run_auto_sync_async(update_price=False)
        assert "اجرا نشد" in window.statusBar().currentMessage()
        gate.set()
        assert pump(lambda: window._sync_thread is None, 10)


class TestDatabaseConcurrency:
    def test_parallel_reads_and_writes(self, tmp_path):
        db = Database(tmp_path / "t.db")
        errors = []

        def writer(n):
            try:
                for i in range(300):
                    db.set_setting(f"k{n}", i)
                    db.log("info", f"{n}-{i}")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def reader():
            try:
                for _ in range(300):
                    db.recent_logs(10)
                    db.all_settings()
                    db.get_setting("k0")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        db.close()
        assert errors == []

    def test_run_id_still_returned(self, db):
        assert db.start_run("manual") >= 1


class TestCrashLog:
    def test_faulthandler_writes_to_crash_log(self, tmp_path, monkeypatch):
        import faulthandler

        from nabz import logging_setup
        monkeypatch.setattr(logging_setup, "log_dir", lambda: tmp_path)
        import logging
        logging_setup._enable_crash_log(logging.getLogger("t"))
        try:
            assert faulthandler.is_enabled()
            assert (tmp_path / "crash.log").read_text(encoding="utf-8").strip()
        finally:
            faulthandler.disable()
