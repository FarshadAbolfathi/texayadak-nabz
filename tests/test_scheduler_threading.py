"""تست ایمنیِ نخیِ اتصال زمان‌بند به رابط کاربری.

مهم‌ترین ریسک زمان‌بندی خودکار این بود که APScheduler روی نخ پس‌زمینهٔ
خودش اجرا می‌شود، در حالی که دانلود خودکار ایساکو (QWebEngineView) فقط
روی نخ اصلی Qt مجاز است. این تست تأیید می‌کند که صدور سیگنال از یک نخ
دیگر، بلافاصله و هم‌زمان اجرا نمی‌شود — بلکه با QueuedConnection به صف
رویدادهای نخ اصلی می‌رود و فقط با پردازش آن صف اجرا می‌شود.
"""

from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from nabz.config import CredentialStore, MemoryBackend
from nabz.db import Database


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from nabz.ui.main_window import MainWindow

    db = Database(":memory:")
    store = CredentialStore(backend=MemoryBackend())
    w = MainWindow(db, store)
    yield w
    w._allow_close = True
    if w._scheduler:
        w._scheduler.shutdown()
    db.close()


class TestSchedulerThreadSafety:
    def test_emit_from_background_thread_is_deferred_not_direct(
        self, window, monkeypatch
    ):
        """صدور از نخ دیگر نباید بلافاصله (هم‌زمان با آن نخ) اجرا شود."""
        called = threading.Event()
        monkeypatch.setattr(
            window, "run_auto_sync_async", lambda *a, **k: called.set()
        )

        def emit_from_thread():
            window.auto_sync_requested.emit(None)

        t = threading.Thread(target=emit_from_thread)
        t.start()
        t.join(timeout=5)

        # بلافاصله پس از پیوستن نخ، هنوز اجرا نشده — فقط در صف نخ اصلی
        # قرار گرفته و منتظر پردازش رویداد است.
        assert not called.is_set(), (
            "سیگنال باید Queued باشد؛ اگر اینجا True شود یعنی مستقیم/هم‌زمان "
            "اجرا شده که برای QWebEngineView ناامن است."
        )

        # حالا رویدادهای نخ اصلی را پردازش می‌کنیم تا slot واقعاً اجرا شود
        deadline = time.monotonic() + 3
        while not called.is_set() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.02)

        assert called.is_set(), "سیگنال هرگز روی نخ اصلی تحویل داده نشد."

    def test_scheduled_job_only_emits_never_blocks(self, window, monkeypatch):
        """_scheduled_job (که مستقیم روی نخ APScheduler صدا زده می‌شود)
        نباید هیچ کار سنگینی انجام دهد — فقط باید سیگنال را صادر کند."""
        called = threading.Event()
        monkeypatch.setattr(
            window, "run_auto_sync_async", lambda *a, **k: called.set()
        )

        start = time.monotonic()
        window._scheduled_job()
        elapsed = time.monotonic() - start

        # emit صرف باید بسیار سریع برگردد (کمتر از چند میلی‌ثانیه)
        assert elapsed < 0.5
        assert not called.is_set()  # هنوز روی نخ اصلی پردازش نشده
