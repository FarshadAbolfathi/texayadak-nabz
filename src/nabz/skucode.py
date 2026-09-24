"""نرمال‌سازی کد کالا.

کد تدارکاتی ایساکو همیشه ۱۰ رقم است، ولی همین کد در سه جای مختلف
به سه شکل ذخیره شده:

    ایساکو (اکسل)  :  "0050102699"   ← همیشه ۱۰ رقمی
    حاسب  (cal.DBF):  "50102699"     ← فیلد عددی، صفر ابتدایی می‌افتد
    سایت  (SKU)    :  "921900699"    ← موقع ورود دستی صفر جا افتاده

این ماژول هر سه را به یک فرم واحد ۱۰ رقمی می‌رساند تا تطبیق ممکن شود.
"""

from __future__ import annotations

import re

#: طول استاندارد کد تدارکاتی ایساکو
CODE_LEN = 10

#: فقط کدهایی با این طول‌ها با صفر پر می‌شوند. کدهای کوتاه‌تر احتمالاً
#: کد داخلی تأمین‌کننده‌های دیگرند و کدهای بلندتر (مثلاً ۱۲ رقمی جهان‌پارت)
#: اصلاً ایساکویی نیستند.
PADDABLE_LENGTHS = frozenset({8, 9, 10})

#: طول پیشوندی که «خودِ قطعه» را مشخص می‌کند. دو رقم آخر کد
#: تأمین‌کننده/ویرایش است، پس دو قطعه با پیشوند یکسان معمولاً
#: یک کالا با گارانتی یا سازندهٔ متفاوت‌اند.
PREFIX_LEN = 8

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ASCII_DIGITS = "0123456789"

_DIGIT_TABLE = str.maketrans(
    _PERSIAN_DIGITS + _ARABIC_DIGITS,
    _ASCII_DIGITS + _ASCII_DIGITS,
)

_NON_DIGIT = re.compile(r"\D+")


def to_ascii_digits(value: str) -> str:
    """ارقام فارسی و عربی را به انگلیسی تبدیل می‌کند."""
    return value.translate(_DIGIT_TABLE)


def digits_only(value: object) -> str:
    """هر چیزی جز رقم را حذف می‌کند (فاصله، نیم‌فاصله، خط تیره، حروف)."""
    if value is None:
        return ""
    return _NON_DIGIT.sub("", to_ascii_digits(str(value)))


def normalize(value: object) -> str:
    """کد خام را به فرم استاندارد ۱۰ رقمی برمی‌گرداند.

    اگر کد قابل نرمال‌سازی نباشد رشتهٔ خالی برمی‌گردد. کدهایی که طولشان
    در :data:`PADDABLE_LENGTHS` نیست بدون تغییر (ولی پاک‌سازی‌شده) برمی‌گردند،
    چون کد ایساکو نیستند و نباید به‌زور ۱۰ رقمی شوند.

    >>> normalize("921900699")
    '0921900699'
    >>> normalize("۰۵۰۱۰۲۶۹۹")
    '0050102699'
    >>> normalize(" 50102699 ")
    '0050102699'
    >>> normalize("612311206560")     # کد ۱۲ رقمی جهان‌پارت
    '612311206560'
    >>> normalize("")
    ''
    """
    digits = digits_only(value)
    if not digits:
        return ""
    if len(digits) not in PADDABLE_LENGTHS:
        return digits
    return digits.zfill(CODE_LEN)


def is_isaco_code(value: object) -> bool:
    """آیا این کد می‌تواند یک کد تدارکاتی ایساکو باشد؟

    >>> is_isaco_code("921900699")
    True
    >>> is_isaco_code("612311206560")
    False
    """
    return len(normalize(value)) == CODE_LEN


def prefix(value: object, length: int = PREFIX_LEN) -> str:
    """پیشوند کد را برمی‌گرداند؛ برای پیدا کردن کالاهای هم‌خانواده.

    وقتی کد دقیق در لیست ایساکو نیست، با این پیشوند دنبال نسخه‌های
    دیگر همان قطعه می‌گردیم (گارانتی پایه / طلایی / تأمین‌کنندهٔ دیگر).

    >>> prefix("0921900804")
    '09219008'
    >>> prefix("612311206560")
    ''
    """
    code = normalize(value)
    if len(code) != CODE_LEN:
        return ""
    return code[:length]


def same_family(a: object, b: object, length: int = PREFIX_LEN) -> bool:
    """آیا دو کد، دو نسخه از یک قطعه‌اند؟

    >>> same_family("0921900804", "0921900811")
    True
    >>> same_family("0921900804", "0920906605")
    False
    """
    pa = prefix(a, length)
    return bool(pa) and pa == prefix(b, length)
