"""زمان‌بندی اجرای خودکار سینک.

دو نیاز کلیدی کارفرما را حل می‌کند:

1. هر روز در یک یا چند ساعت مشخص، سینک خودکار انجام شود (هر زمان‌بندی
   می‌تواند فقط قیمت، فقط موجودی یا هر دو را به‌روز کند).
2. اگر آن لحظه سیستم خاموش بود، اجرای از دست رفته در اولین فرصت
   روشن‌شدن جبران شود (catch-up).

منطق زمان‌بندی از اجرای واقعی جدا شده تا بدون شبکه و بدون صبر کردن
تا نیمه‌شب قابل تست باشد: توابع خالص تصمیم می‌گیرند «الان باید اجرا
شود یا نه»، و :class:`SyncScheduler` آن‌ها را با APScheduler به کار می‌بندد.
"""

from __future__ import annotations

import datetime as _dt
import inspect
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    """یک ساعت اجرای روزانه و اینکه در آن ساعت چه چیزی سینک شود."""

    hour: int = 3
    minute: int = 0
    price: bool = True
    stock: bool = True
    enabled: bool = True

    @property
    def hhmm(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"

    @property
    def key(self) -> str:
        """شناسهٔ یکتای job در APScheduler."""
        return f"sync_{self.hour:02d}{self.minute:02d}"

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleEntry":
        """از شکل ذخیره‌شده در تنظیمات می‌سازد.

        >>> ScheduleEntry.from_dict({"time": "14:30", "price": False})
        ScheduleEntry(hour=14, minute=30, price=False, stock=True, enabled=True)
        """
        hour, minute = (int(x) for x in str(data.get("time", "03:00")).split(":"))
        return cls(
            hour=hour,
            minute=minute,
            price=bool(data.get("price", True)),
            stock=bool(data.get("stock", True)),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict:
        return {"time": self.hhmm, "price": self.price, "stock": self.stock,
                "enabled": self.enabled}


@dataclass(frozen=True, slots=True, init=False)
class ScheduleConfig:
    """کل تنظیمات زمان‌بندی: کلید اصلی + فهرست ساعت‌های اجرا.

    برای سازگاری با نسخهٔ قبل (که فقط یک ساعت داشت) هنوز می‌توان با
    ``ScheduleConfig(enabled=True, hour=3, minute=0)`` ساخت.
    """

    enabled: bool
    entries: tuple[ScheduleEntry, ...]

    def __init__(self, enabled: bool = False, hour: int | None = None,
                 minute: int = 0, entries=None) -> None:
        if entries is None:
            entries = (ScheduleEntry(hour=3 if hour is None else hour, minute=minute),)
        # مرتب و بدون تکرار ساعت (دو اجرا در یک دقیقه معنا ندارد)
        unique: dict[str, ScheduleEntry] = {}
        for entry in entries:
            unique.setdefault(entry.hhmm, entry)
        ordered = tuple(sorted(unique.values(), key=lambda e: (e.hour, e.minute)))
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "entries", ordered)

    @property
    def active_entries(self) -> tuple[ScheduleEntry, ...]:
        return tuple(e for e in self.entries if e.enabled)

    # سازگاری با کدی که فقط یک ساعت می‌شناخت
    @property
    def hour(self) -> int:
        return self.entries[0].hour if self.entries else 3

    @property
    def minute(self) -> int:
        return self.entries[0].minute if self.entries else 0

    @classmethod
    def from_hhmm(cls, enabled: bool, hhmm: str) -> "ScheduleConfig":
        hour, minute = (int(x) for x in hhmm.split(":"))
        return cls(enabled=enabled, hour=hour, minute=minute)

    @classmethod
    def from_settings(cls, get_setting) -> "ScheduleConfig":
        """از تنظیمات ذخیره‌شده می‌خواند (با مهاجرت از قالب تک‌ساعته).

        :param get_setting: همان ``Database.get_setting``.
        """
        enabled = bool(get_setting("schedule_enabled", False))
        raw = get_setting("schedule_entries", None)
        if isinstance(raw, list):
            entries = tuple(ScheduleEntry.from_dict(d) for d in raw)
        else:
            hour, minute = (int(x) for x in
                            str(get_setting("schedule_time", "03:00")).split(":"))
            entries = (ScheduleEntry(
                hour=hour, minute=minute,
                price=bool(get_setting("schedule_price", True)),
                stock=bool(get_setting("schedule_stock", True)),
            ),)
        return cls(enabled=enabled, entries=entries)


def due_entry(
    now: _dt.datetime,
    entries: tuple[ScheduleEntry, ...] | list[ScheduleEntry],
    last_run: _dt.datetime | None,
) -> ScheduleEntry | None:
    """آخرین زمان‌بندیِ امروز که گذشته ولی اجرا نشده را برمی‌گرداند.

    اگر چند اجرا از دست رفته باشد، فقط جدیدترینش لازم است (اجرای آخر،
    حالت نهایی را روی سایت می‌نشاند).

    >>> import datetime as dt
    >>> es = [ScheduleEntry(3, 0), ScheduleEntry(14, 0)]
    >>> due_entry(dt.datetime(2026,1,2,15,0), es, dt.datetime(2026,1,2,3,1)).hhmm
    '14:00'
    >>> due_entry(dt.datetime(2026,1,2,15,0), es, dt.datetime(2026,1,2,14,1)) is None
    True
    >>> due_entry(dt.datetime(2026,1,2,2,0), es, None) is None
    True
    """
    passed = [
        e for e in entries
        if e.enabled and now >= now.replace(
            hour=e.hour, minute=e.minute, second=0, microsecond=0)
    ]
    if not passed:
        return None
    latest = max(passed, key=lambda e: (e.hour, e.minute))
    if should_catch_up(now, latest.hour, latest.minute, last_run):
        return latest
    return None


def next_entry_at(
    now: _dt.datetime, entries: tuple[ScheduleEntry, ...] | list[ScheduleEntry]
) -> tuple[_dt.datetime, ScheduleEntry] | None:
    """نزدیک‌ترین اجرای بعدی (برای نمایش به کاربر).

    >>> import datetime as dt
    >>> es = [ScheduleEntry(3, 0), ScheduleEntry(14, 0)]
    >>> next_entry_at(dt.datetime(2026,1,2,10,0), es)[0]
    datetime.datetime(2026, 1, 2, 14, 0)
    """
    active = [e for e in entries if e.enabled]
    if not active:
        return None
    return min(
        ((next_run_at(now, e.hour, e.minute), e) for e in active),
        key=lambda pair: pair[0],
    )


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


def _accepts_argument(func: Callable) -> bool:
    try:
        params = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
        for p in params
    )


class SyncScheduler:
    """اجرای خودکار روزانه را با APScheduler مدیریت می‌کند.

    :param job: تابعی که سینک واقعی را انجام می‌دهد (تزریق می‌شود تا
        این کلاس مستقل و تست‌پذیر بماند). اگر یک پارامتر بپذیرد،
        :class:`ScheduleEntry` مربوط به همان اجرا به آن داده می‌شود.
    :param last_run_getter: زمان آخرین اجرای موفق را می‌دهد (برای catch-up).
    """

    def __init__(
        self,
        job: Callable[..., None],
        last_run_getter: Callable[[], _dt.datetime | None],
    ) -> None:
        self._job = job
        self._job_takes_entry = _accepts_argument(job)
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

        اگر غیرفعال شده، متوقف می‌شود. اگر فعال است، برای هر ساعت یک job
        روزانه می‌گذارد و در صورت لزوم اجرای از دست رفته را جبران می‌کند.
        """
        self._config = config
        scheduler = self._ensure_scheduler()

        # پاک کردن jobهای قبلی
        scheduler.remove_all_jobs()

        if not config.enabled:
            if scheduler.running:
                scheduler.pause()
            return

        from apscheduler.triggers.cron import CronTrigger

        for entry in config.active_entries:
            scheduler.add_job(
                self._run_job,
                CronTrigger(hour=entry.hour, minute=entry.minute),
                args=[entry],
                id=entry.key,
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
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
        entry = due_entry(now, self._config.entries, self._last_run_getter())
        if entry is not None:
            self._run_job(entry)
            return True
        return False

    def _run_job(self, entry: ScheduleEntry | None = None) -> None:
        try:
            if self._job_takes_entry:
                self._job(entry)
            else:
                self._job()
        except Exception:  # noqa: BLE001 - نباید کل زمان‌بند را بخواباند
            pass

    def shutdown(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._scheduler = None
