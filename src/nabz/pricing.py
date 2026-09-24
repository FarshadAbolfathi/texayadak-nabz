"""قواعد قیمت‌گذاری: از قیمت ایساکو تا قیمتی که روی سایت می‌نشیند.

زنجیرهٔ محاسبه:

    قیمت ایساکو (ریال)
        ↓  انتخاب ستون مبنا (با ارزش افزوده / خرده‌فروشی / عمده)
        ↓  تقسیم بر ۱۰   (ریال → تومان، چون ووکامرس روی IRT است)
        ↓  اعمال درصد سود کارفرما
        ↓  رند کردن
        ↓  بررسی محافظ‌ها (سقف تغییر، کف و سقف قیمت)
    قیمت نهایی (تومان)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


class PriceBase(enum.StrEnum):
    """کدام ستون لیست ایساکو مبنای قیمت‌گذاری باشد."""

    VAT = "vat"              # قیمت با ارزش افزوده — ستون G
    RETAIL = "retail"        # قیمت مصرف‌کننده / خرده‌فروشی — ستون F
    WHOLESALE = "wholesale"  # فی فروش / عمده — ستون H


class GuardReason(enum.StrEnum):
    """دلیل اینکه یک قیمت به‌صورت خودکار اعمال نشد."""

    NONE = "none"
    TOO_BIG_CHANGE = "too_big_change"   # تغییر بیش از سقف مجاز
    BELOW_MIN = "below_min"             # کمتر از کف قیمت
    ABOVE_MAX = "above_max"             # بیشتر از سقف قیمت
    NO_SOURCE_PRICE = "no_source_price"  # ایساکو قیمتی نداده


@dataclass(frozen=True, slots=True)
class PriceRules:
    """تنظیمات قیمت‌گذاری که کارفرما در برنامه تعیین می‌کند."""

    #: درصد سود روی قیمت مبنا. ۱۵ یعنی ۱۵٪ اضافه، -۵ یعنی ۵٪ تخفیف.
    markup_percent: Decimal = Decimal("0")

    #: کدام ستون ایساکو مبنا باشد.
    base: PriceBase = PriceBase.VAT

    #: ضریب تبدیل واحد. ایساکو ریال می‌دهد و ووکامرس تومان است ⇒ ۱۰.
    #: اگر روزی سایت به ریال تغییر کرد، این را ۱ می‌کنیم.
    rial_divisor: int = 10

    #: قیمت نهایی به نزدیک‌ترین مضرب این عدد رند می‌شود. ۰ یعنی بدون رند.
    round_to: int = 1_000

    #: اگر قیمت جدید بیش از این درصد با قیمت فعلی سایت فرق داشت،
    #: خودکار اعمال نشود و برای تأیید دستی علامت بخورد. ۰ یعنی بدون محافظ.
    max_change_percent: Decimal = Decimal("50")

    #: کف و سقف مطلق قیمت (تومان). ۰ یعنی بدون محدودیت.
    min_price: int = 0
    max_price: int = 0

    def __post_init__(self) -> None:
        if self.rial_divisor <= 0:
            raise ValueError("rial_divisor باید بزرگ‌تر از صفر باشد")
        if self.round_to < 0:
            raise ValueError("round_to نمی‌تواند منفی باشد")
        if self.max_price and self.min_price > self.max_price:
            raise ValueError("min_price نمی‌تواند از max_price بیشتر باشد")


@dataclass(frozen=True, slots=True)
class PriceResult:
    """خروجی محاسبه برای یک کالا."""

    price: int                       # قیمت نهایی به تومان
    base_rial: int                   # قیمتی که از ایساکو مبنا قرار گرفت
    before_round: Decimal            # قیمت پیش از رند شدن (تومان)
    guard: GuardReason = GuardReason.NONE
    change_percent: Decimal | None = None  # درصد تغییر نسبت به قیمت فعلی سایت

    @property
    def needs_review(self) -> bool:
        """آیا این قیمت باید دستی تأیید شود؟"""
        return self.guard is not GuardReason.NONE


def round_to_step(value: Decimal, step: int) -> int:
    """به نزدیک‌ترین مضرب ``step`` رند می‌کند.

    >>> round_to_step(Decimal("7934080"), 1000)
    7934000
    >>> round_to_step(Decimal("7934080"), 5000)
    7935000
    >>> round_to_step(Decimal("7934080"), 0)
    7934080
    """
    if step <= 0:
        return int(value.to_integral_value(rounding=ROUND_HALF_UP))
    steps = (value / step).to_integral_value(rounding=ROUND_HALF_UP)
    return int(steps) * step


def compute(
    isaco_retail: int | None,
    isaco_vat: int | None,
    isaco_wholesale: int | None,
    rules: PriceRules,
    current_site_price: int | None = None,
) -> PriceResult:
    """قیمت نهایی سایت را از قیمت‌های ایساکو حساب می‌کند.

    سه قیمت ایساکو به ریال گرفته می‌شود و بسته به :attr:`PriceRules.base`
    یکی مبنا قرار می‌گیرد. ``current_site_price`` فقط برای سنجیدن محافظ
    «سقف تغییر» لازم است و اگر ندهیم آن محافظ غیرفعال می‌ماند.

    >>> r = PriceRules(markup_percent=Decimal("15"))
    >>> compute(62_720_000, 68_992_000, 56_000_000, r).price
    7934000
    """
    source = {
        PriceBase.VAT: isaco_vat,
        PriceBase.RETAIL: isaco_retail,
        PriceBase.WHOLESALE: isaco_wholesale,
    }[rules.base]

    if not source or source <= 0:
        return PriceResult(
            price=0,
            base_rial=0,
            before_round=Decimal(0),
            guard=GuardReason.NO_SOURCE_PRICE,
        )

    toman = Decimal(source) / rules.rial_divisor
    with_markup = toman * (Decimal(100) + rules.markup_percent) / Decimal(100)
    price = round_to_step(with_markup, rules.round_to)

    guard = GuardReason.NONE
    change: Decimal | None = None

    if rules.min_price and price < rules.min_price:
        guard = GuardReason.BELOW_MIN
    elif rules.max_price and price > rules.max_price:
        guard = GuardReason.ABOVE_MAX

    if current_site_price and current_site_price > 0:
        change = (
            (Decimal(price) - Decimal(current_site_price))
            / Decimal(current_site_price)
            * Decimal(100)
        )
        if (
            guard is GuardReason.NONE
            and rules.max_change_percent > 0
            and abs(change) > rules.max_change_percent
        ):
            guard = GuardReason.TOO_BIG_CHANGE

    return PriceResult(
        price=price,
        base_rial=source,
        before_round=with_markup,
        guard=guard,
        change_percent=change,
    )
