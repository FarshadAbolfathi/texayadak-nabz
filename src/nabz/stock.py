"""قواعد موجودی: از موجودی حاسب تا عددی که روی سایت می‌نشیند.

خواستهٔ کارفرما این است که هیچ‌وقت بیشتر از یک سقف مشخص روی سایت
نمایش داده نشود. اگر انبار ۳۰۰ عدد دارد و سقف ۲ است، سایت ۲ نشان
می‌دهد؛ اینطور مشتری نمی‌تواند ۴ عدد سفارش بدهد در حالی که فقط
۲ تا موجود است.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal


class StockStatus(enum.StrEnum):
    """وضعیت موجودی در ووکامرس."""

    IN_STOCK = "instock"
    OUT_OF_STOCK = "outofstock"
    ON_BACKORDER = "onbackorder"


@dataclass(frozen=True, slots=True)
class StockRules:
    """تنظیمات موجودی که کارفرما در برنامه تعیین می‌کند."""

    #: حداکثر عددی که روی سایت نمایش داده می‌شود. ۰ یعنی بدون سقف.
    max_on_site: int = 2

    #: اگر موجودی انبار کمتر یا مساوی این عدد بود، کالا ناموجود شود.
    #: مثلاً کارفرما نمی‌خواهد آخرین عدد از انبارش فروخته شود ⇒ ۱.
    #: پیش‌فرض ۰ یعنی فقط موجودی صفر ناموجود حساب می‌شود.
    reserve: int = 0

    #: سقف اختصاصی برای کالاهای خاص: کد نرمال‌شده → سقف.
    #: کالای گران سقف ۱، کالای خرد سقف ۱۰.
    per_code_max: dict[str, int] = field(default_factory=dict)

    #: کدهایی که هرگز موجودی‌شان خودکار تغییر نکند.
    excluded: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.max_on_site < 0:
            raise ValueError("max_on_site نمی‌تواند منفی باشد")
        if self.reserve < 0:
            raise ValueError("reserve نمی‌تواند منفی باشد")

    def cap_for(self, code: str) -> int:
        """سقف مؤثر یک کد را برمی‌گرداند (اختصاصی، وگرنه عمومی)."""
        return self.per_code_max.get(code, self.max_on_site)


@dataclass(frozen=True, slots=True)
class StockResult:
    """خروجی محاسبه برای یک کالا."""

    quantity: int
    status: StockStatus
    source_quantity: int   # عددی که در حاسب بود
    capped: bool = False   # آیا سقف اعمال شد؟
    skipped: bool = False  # آیا کالا در لیست استثناها بود؟


def _to_int(value: object) -> int:
    """موجودی حاسب که با پنج رقم اعشار ذخیره شده را به عدد صحیح می‌برد.

    حاسب مقادیری مثل ``"4.00000"`` یا ``"0.20000"`` می‌دهد. کسر واحد
    (نیم لیتر روغن) روی سایت معنا ندارد، پس **به سمت پایین** گرد می‌کنیم
    تا هرگز بیشتر از موجودی واقعی نفروشیم.
    """
    if value is None or value == "":
        return 0
    try:
        return int(Decimal(str(value).strip()).to_integral_value(rounding="ROUND_FLOOR"))
    except (ArithmeticError, ValueError):
        return 0


def compute(code: str, haseb_quantity: object, rules: StockRules) -> StockResult:
    """موجودی سایت را از موجودی حاسب حساب می‌کند.

    >>> r = StockRules(max_on_site=2)
    >>> compute("0270900125", "5.00000", r)
    StockResult(quantity=2, status=<StockStatus.IN_STOCK: 'instock'>, source_quantity=5, capped=True, skipped=False)
    >>> compute("0270900125", "0.00000", r).status
    <StockStatus.OUT_OF_STOCK: 'outofstock'>
    >>> compute("0270900125", "1.00000", r).quantity
    1
    """
    source = _to_int(haseb_quantity)

    if code in rules.excluded:
        return StockResult(
            quantity=source,
            status=StockStatus.IN_STOCK if source > 0 else StockStatus.OUT_OF_STOCK,
            source_quantity=source,
            skipped=True,
        )

    # موجودی رزرو: این تعداد هرگز روی سایت نمی‌رود
    available = max(source - rules.reserve, 0)

    cap = rules.cap_for(code)
    capped = bool(cap) and available > cap
    quantity = min(available, cap) if cap else available

    status = StockStatus.IN_STOCK if quantity > 0 else StockStatus.OUT_OF_STOCK

    return StockResult(
        quantity=quantity,
        status=status,
        source_quantity=source,
        capped=capped,
    )
