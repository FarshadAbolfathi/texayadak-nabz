"""قفل سراسری سینک: در هر لحظه فقط یک سینک/دانلود ایساکو در کل برنامه.

دانلود ایساکو یک حلقهٔ رویداد تودرتو (nested event loop) روی نخ اصلی
اجرا می‌کند؛ در آن چند دقیقه رابط کاربری و زمان‌بند زنده‌اند. بدون این
قفل، یک اجرای زمان‌بندی‌شده، دکمهٔ «تست همین حالا»، منوی tray یا دکمهٔ
«دریافت و مقایسه» می‌توانست وسط یک دانلود، دانلود و سینک دیگری را درون
همان حلقه شروع کند — دانلودهای موازی روی یک پروفایل مرورگر، ده‌ها اجرای
پشت‌سرهم در گزارش‌ها و در نهایت قفل شدن برنامه.

همه‌چیز روی نخ اصلی Qt صدا زده می‌شود، ولی برای اطمینان یک Lock هم دارد.
"""

from __future__ import annotations

import logging
import threading
import time

_log = logging.getLogger("nabz.sync")


class SyncGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: str | None = None
        self._since = 0.0

    def try_acquire(self, owner: str) -> bool:
        """اگر آزاد بود قفل را برای ``owner`` می‌گیرد؛ وگرنه ``False``."""
        with self._lock:
            if self._owner is not None:
                _log.info("«%s» رد شد؛ «%s» از %d ثانیه پیش در حال اجراست",
                          owner, self._owner, time.monotonic() - self._since)
                return False
            self._owner = owner
            self._since = time.monotonic()
            _log.info("شروع «%s»", owner)
            return True

    def release(self, owner: str | None = None) -> None:
        with self._lock:
            if self._owner is None:
                return
            if owner is not None and owner != self._owner:
                return  # قفل مال کار دیگری است
            _log.info("پایان «%s» (%d ثانیه)", self._owner,
                      time.monotonic() - self._since)
            self._owner = None

    @property
    def busy(self) -> bool:
        return self._owner is not None

    @property
    def owner(self) -> str | None:
        return self._owner

    def reset(self) -> None:
        """فقط برای تست."""
        with self._lock:
            self._owner = None


#: نمونهٔ واحد برنامه
gate = SyncGate()
