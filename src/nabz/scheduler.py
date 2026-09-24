"""زمان‌بندی اجرای خودکار سینک.

دو نیاز کلیدی کارفرما را حل می‌کند:

1. هر روز در ساعت مشخص، سینک خودکار انجام شود.
2. اگر آن لحظه سیستم خاموش بود، اجرای از دست رفته در اولین فرصت
   روشن‌شدن جبران شود (catch-up).

منطق زمان‌بندی از اجرای واقعی جدا شده تا بدون شبکه و بدون صبر کردن
تا نیمه‌شب قابل تست باشد: توابع خالص تصمیم می‌گیرند «الان باید اجرا
شود یا نه»، و :class:`SyncScheduler` آن‌ها را با APScheduler به کار می‌بندد.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    enabled: bool = False
    hour: int = 3
    minute: int = 0

    @classmethod
    def from_hhmm(cls, enabled: bool, hhmm: str) -> "ScheduleConfig":
        hour, minute = (int(x) for x in hhmm.split(":"))
        return cls(enabled=enabled, hour=hour, minute=minute)


def next_run_at(now: _dt.datetime, hour: int, minute: int) -> _dt.datetime:
    """زمان بعدی که ساعت تعیین‌شده فرا می‌رسد را برمی‌گرداند.

    اگر ساعت امروز گذشته باشد، فردا همان ساعت.

    >>> import datetime as dt
    >>> next_run_at(dt.datetime(2026, 1, 1, 10, 0), 3, 0)
    datetime.datetime(2026, 1, 2, 3, 0)
    >>> next_run_at(dt.datetime(2026, 1, 1, 2, 0), 3, 0)
    datetime.datetime(2026, 1, 1, 3, 0)
    """
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += _dt.timedelta(days=1)
    return candidate


def should_catch_up(
    now: _dt.datetime,
    hour: int,
    minute: int,
    last_run: _dt.datetime | None,
) -> bool:
    """آیا اجرای امروز از دست رفته و باید همین حالا جبران شود؟

    اگر ساعت مقررِ امروز گذشته باشد و آخرین اجرای موفق پیش از آن بوده
    (یا اصلاً اجرایی نبوده)، یعنی سیستم آن موقع خاموش بوده و باید جبران شود.

    >>> import datetime as dt
    >>> # ساعت مقرر ۳ صبح، الان ۱۰ صبح، آخرین اجرا دیروز → جبران لازم است
    >>> should_catch_up(dt.datetime(2026,1,2,10,0), 3, 0, dt.datetime(2026,1,1,3,0))
    True
    >>> # همین امروز بعد از ۳ اجرا شده → جبران لازم نیست
    >>> should_catch_up(dt.datetime(2026,1,2,10,0), 3, 0, dt.datetime(2026,1,2,3,5))
    False
    >>> # ساعت مقرر امروز هنوز نرسیده → جبران لازم نیست
    >>> should_catch_up(dt.datetime(2026,1,2,1,0), 3, 0, dt.datetime(2026,1,1,3,0))
    False
    """
    scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled_today:
        return False  # هنوز به ساعت امروز نرسیده‌ایم
    if last_run is None:
        return True   # هیچ‌وقت اجرا نشده و ساعت گذشته
    return last_run < scheduled_today


class SyncScheduler:
    """اجرای خودکار روزانه را با APScheduler مدیریت می‌کند.

    :param job: تابعی که سینک واقعی را انجام می‌دهد (تزریق می‌شود تا
        این کلاس مستقل و تست‌پذیر بماند).
    :param last_run_getter: زمان آخرین اجرای موفق را می‌دهد (برای catch-up).
    """

    def __init__(
        self,
        job: Callable[[], None],
        last_run_getter: Callable[[], _dt.datetime | None],
    ) -> None:
        self._job = job
        self._last_run_getter = last_run_getter
        self._scheduler = None
        self._config = ScheduleConfig()

    def _ensure_scheduler(self):
        if self._scheduler is None:
            from apscheduler.schedulers.background import BackgroundScheduler

            self._scheduler = BackgroundScheduler(daemon=True)
        return self._scheduler

    @property
    def is_running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    def apply_config(self, config: ScheduleConfig) -> None:
        """زمان‌بندی را با تنظیمات جدید بازتنظیم می‌کند.

        اگر غیرفعال شده، متوقف می‌شود. اگر فعال است، job روزانه را
        می‌گذارد و در صورت لزوم اجرای از دست رفته را جبران می‌کند.
        """
        self._config = config
        scheduler = self._ensure_scheduler()

        # پاک کردن job قبلی
        scheduler.remove_all_jobs()

        if not config.enabled:
            if scheduler.running:
                scheduler.pause()
            return

        from apscheduler.triggers.cron import CronTrigger

        scheduler.add_job(
            self._run_job,
            CronTrigger(hour=config.hour, minute=config.minute),
            id="daily_sync",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        if not scheduler.running:
            scheduler.start()
        else:
            scheduler.resume()

        self.catch_up_if_needed()

    def catch_up_if_needed(self, now: _dt.datetime | None = None) -> bool:
        """اگر اجرای امروز از دست رفته، همین حالا اجرا می‌کند."""
        if not self._config.enabled:
            return False
        now = now or _dt.datetime.now()
        if should_catch_up(
            now, self._config.hour, self._config.minute, self._last_run_getter()
        ):
            self._run_job()
            return True
        return False

    def _run_job(self) -> None:
        try:
            self._job()
        except Exception:  # noqa: BLE001 - نباید کل زمان‌بند را بخواباند
            pass

    def shutdown(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._scheduler = None
