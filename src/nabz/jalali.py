"""تاریخ شمسی (جلالی).

همهٔ تاریخ‌هایی که در برنامه به کاربر نشان داده می‌شود از این ماژول
می‌گذرد تا یکدست و شمسی باشد. عمداً به کتابخانهٔ بیرونی وابسته نیست:
الگوریتم تبدیل کوتاه و شناخته‌شده است (الگوریتم ۳۳ ساله‌ای که در
jalaali-js هم به کار رفته) و یک وابستگی کمتر یعنی یک چیز کمتر برای
شکستن هنگام بسته‌بندی exe.
"""

from __future__ import annotations

import datetime as _dt
import time as _time

MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)

#: نام روزهای هفته به ترتیب ``datetime.weekday()`` (دوشنبه = ۰).
WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(value: object) -> str:
    """ارقام انگلیسی را فارسی می‌کند.

    >>> fa_digits("1403/01/05")
    '۱۴۰۳/۰۱/۰۵'
    """
    return str(value).translate(_FA_DIGITS)


def _div(a: int, b: int) -> int:
    return int(a / b)  # تقسیم با گرد کردن به سمت صفر (مثل JS)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """تاریخ میلادی را به شمسی تبدیل می‌کند.

    >>> gregorian_to_jalali(2024, 3, 20)
    (1403, 1, 1)
    >>> gregorian_to_jalali(2026, 9, 30)
    (1405, 7, 8)
    >>> gregorian_to_jalali(2025, 3, 20)
    (1403, 12, 30)
    """
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666 + 365 * gy + _div(gy2 + 3, 4) - _div(gy2 + 99, 100)
        + _div(gy2 + 399, 400) + gd + g_d_m[gm - 1]
    )
    jy = -1595 + 33 * _div(days, 12053)
    days %= 12053
    jy += 4 * _div(days, 1461)
    days %= 1461
    if days > 365:
        jy += _div(days - 1, 365)
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + _div(days, 31)
        jd = 1 + days % 31
    else:
        jm = 7 + _div(days - 186, 30)
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """تاریخ شمسی را به میلادی تبدیل می‌کند.

    >>> jalali_to_gregorian(1403, 1, 1)
    (2024, 3, 20)
    >>> jalali_to_gregorian(1405, 7, 8)
    (2026, 9, 30)
    """
    jy += 1595
    days = -355668 + 365 * jy + _div(jy, 33) * 8 + _div(jy % 33 + 3, 4) + jd
    days += (jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186
    gy = 400 * _div(days, 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * _div(days, 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * _div(days, 1461)
    days %= 1461
    if days > 365:
        gy += _div(days - 1, 365)
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    month_days = (0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    gm = 1
    while gm <= 12 and gd > month_days[gm]:
        gd -= month_days[gm]
        gm += 1
    return gy, gm, gd


# -- قالب‌بندی --------------------------------------------------------


def format_date(value: _dt.date | _dt.datetime, *, persian_digits: bool = True) -> str:
    """تاریخ را به‌صورت ``۱۴۰۵/۰۷/۰۸`` برمی‌گرداند.

    >>> format_date(_dt.date(2026, 9, 30))
    '۱۴۰۵/۰۷/۰۸'
    >>> format_date(_dt.date(2026, 9, 30), persian_digits=False)
    '1405/07/08'
    """
    jy, jm, jd = gregorian_to_jalali(value.year, value.month, value.day)
    text = f"{jy:04d}/{jm:02d}/{jd:02d}"
    return fa_digits(text) if persian_digits else text


def format_datetime(value: _dt.datetime, *, persian_digits: bool = True,
                    seconds: bool = False) -> str:
    """تاریخ و ساعت شمسی: ``۱۴۰۵/۰۷/۰۸  ۱۴:۰۵``.

    >>> format_datetime(_dt.datetime(2026, 9, 30, 14, 5))
    '۱۴۰۵/۰۷/۰۸  ۱۴:۰۵'
    """
    clock = value.strftime("%H:%M:%S" if seconds else "%H:%M")
    text = f"{format_date(value, persian_digits=False)}  {clock}"
    return fa_digits(text) if persian_digits else text


def format_long(value: _dt.date | _dt.datetime) -> str:
    """شکل خوانای کامل: ``چهارشنبه ۸ مهر ۱۴۰۵``.

    >>> format_long(_dt.date(2026, 9, 30))
    'چهارشنبه ۸ مهر ۱۴۰۵'
    """
    jy, jm, jd = gregorian_to_jalali(value.year, value.month, value.day)
    return fa_digits(f"{WEEKDAYS[value.weekday()]} {jd} {MONTHS[jm - 1]} {jy}")


def format_ts(ts: float | None, *, empty: str = "—", seconds: bool = False) -> str:
    """یک timestamp یونیکس (زمان محلی) را شمسی قالب‌بندی می‌کند."""
    if not ts:
        return empty
    return format_datetime(_dt.datetime.fromtimestamp(ts), seconds=seconds)


def parse_iso(value: str | None) -> _dt.datetime | None:
    """رشتهٔ ISO (مثل ``date_created`` ووکامرس) را به datetime تبدیل می‌کند.

    >>> parse_iso("2026-09-30T14:05:00")
    datetime.datetime(2026, 9, 30, 14, 5)
    >>> parse_iso("") is None
    True
    """
    if not value:
        return None
    try:
        return _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def format_iso(value: str | None, *, empty: str = "—", with_time: bool = True) -> str:
    """تاریخ ISO ووکامرس را شمسی نشان می‌دهد.

    ووکامرس ``date_created`` را به وقت محلی فروشگاه می‌دهد، پس بدون تبدیل
    منطقهٔ زمانی نمایش داده می‌شود.

    >>> format_iso("2026-09-30T14:05:00")
    '۱۴۰۵/۰۷/۰۸  ۱۴:۰۵'
    >>> format_iso("2026-09-30T14:05:00", with_time=False)
    '۱۴۰۵/۰۷/۰۸'
    """
    parsed = parse_iso(value)
    if parsed is None:
        return empty
    return format_datetime(parsed) if with_time else format_date(parsed)


def today() -> str:
    """تاریخ امروز به شمسی (با ارقام انگلیسی؛ برای نام فایل)."""
    return format_date(_dt.date.today(), persian_digits=False).replace("/", "-")


def now_str() -> str:
    """الان، به شمسی و با ارقام فارسی."""
    return format_datetime(_dt.datetime.fromtimestamp(_time.time()))
