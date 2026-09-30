"""کشف کالاهای حاسب که هنوز روی سایت نیستند و ساخت آن‌ها روی سایت.

شرط «محصول جدید»:
    ۱) در حاسب **موجودی بیشتر از صفر** دارد؛ و
    ۲) هیچ محصولی (با هر وضعیتی: منتشرشده، پیش‌نویس، خصوصی ...) و هیچ
       متغیری روی سایت با همان کد (SKU نرمال‌شده) وجود ندارد.

این بخش عمداً **هرگز خودکار** چیزی روی سایت نمی‌سازد و وارد چرخهٔ سینک
خودکار نمی‌شود. سینک فقط فهرست را به‌روز می‌کند و به کارفرما خبر می‌دهد؛
ساخت محصول همیشه با تأیید صریح او انجام می‌شود.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from .categorize import Categorizer
from .pricing import PriceRules, compute as compute_price
from .skucode import normalize
from .sources.haseb_dbf import HasebItem
from .sources.isaco_excel import IsacoItem
from .stock import StockRules, compute as compute_stock
from .targets.woocommerce import WooProduct


@dataclass(slots=True)
class NewProduct:
    """یک کالای حاسب که روی سایت نیست؛ یک ردیف از جدول تب محصولات جدید."""

    code: str                 # کد نرمال‌شده = SKU سایت
    name: str                 # عنوان پیشنهادی (پاک‌سازی‌شده)
    haseb_quantity: int
    stock: int                # موجودی که روی سایت نشان داده می‌شود (با سقف)
    price: int | None         # تومان
    price_source: str = ""    # «ایساکو» / «حاسب» / ""
    car: str = ""             # مصرف خودرو از لیست ایساکو
    category_ids: list[int] = field(default_factory=list)
    category_reason: str = ""
    warehouse: str = ""


def clean_title(name: str) -> str:
    """نام حاسب را برای عنوان سایت مرتب می‌کند.

    حاسب با CP1256 کار می‌کند و «ي/ك» عربی ذخیره می‌کند که در جستجوی
    سایت با «ی/ک» فارسی پیدا نمی‌شود.

    >>> clean_title("  سپر  عقب   پژو ۴۰۵ ي ك ")
    'سپر عقب پژو ۴۰۵ ی ک'
    """
    text = str(name or "").replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    return re.sub(r"\s+", " ", text).strip()


def site_skus(products: Iterable[WooProduct], extra_skus: Iterable[str] = ()) -> set[str]:
    """مجموعهٔ کدهای نرمال‌شدهٔ موجود روی سایت (محصول + متغیرها)."""
    result = {normalize(p.sku) for p in products}
    result.update(normalize(s) for s in extra_skus)
    result.discard("")
    return result


def find_missing(
    haseb: dict[str, HasebItem],
    existing_skus: set[str],
    *,
    ignored: Iterable[str] = (),
    min_quantity: int = 1,
) -> list[HasebItem]:
    """کالاهای موجودِ حاسب که روی سایت نیستند.

    >>> from decimal import Decimal as D
    >>> h = {"0050102699": HasebItem("0050102699", "50102699", "سپر", D(3), 1, "")}
    >>> [i.code for i in find_missing(h, set())]
    ['0050102699']
    >>> find_missing(h, {"0050102699"})
    []
    >>> find_missing(h, set(), ignored=["0050102699"])
    []
    """
    skip = {normalize(c) for c in ignored}
    result = [
        item for code, item in haseb.items()
        if code and code not in existing_skus and code not in skip
        and item.quantity >= min_quantity
    ]
    result.sort(key=lambda i: i.name)
    return result


def build_candidates(
    missing: Iterable[HasebItem],
    *,
    isaco: dict[str, IsacoItem] | None = None,
    price_rules: PriceRules | None = None,
    stock_rules: StockRules | None = None,
    categorizer: Categorizer | None = None,
) -> list[NewProduct]:
    """برای هر کالای جاافتاده قیمت، موجودی و دستهٔ پیشنهادی می‌سازد.

    قیمت: اگر کد در لیست ایساکو بود با همان قواعد قیمت‌گذاری سینک؛
    وگرنه قیمت فروش خودِ حاسب (ریال → تومان)؛ وگرنه خالی تا کارفرما
    دستی وارد کند.
    """
    isaco = isaco or {}
    price_rules = price_rules or PriceRules()
    stock_rules = stock_rules or StockRules()
    result: list[NewProduct] = []

    for item in missing:
        isaco_item = isaco.get(item.code)
        price: int | None = None
        source = ""
        if isaco_item is not None:
            calc = compute_price(
                isaco_retail=isaco_item.retail,
                isaco_vat=isaco_item.vat,
                isaco_wholesale=isaco_item.wholesale,
                rules=price_rules,
            )
            if calc.price > 0:
                price, source = calc.price, "ایساکو"
        if price is None and item.sale_price and item.sale_price > 0:
            from .pricing import round_to_step
            toman = Decimal(item.sale_price) / price_rules.rial_divisor
            price, source = round_to_step(toman, price_rules.round_to), "حاسب"

        stock = compute_stock(item.code, item.quantity, stock_rules)
        car = isaco_item.car if isaco_item is not None else ""
        title = clean_title(item.name) or (
            clean_title(isaco_item.name) if isaco_item is not None else item.code
        )
        suggestion = categorizer.suggest(title, car) if categorizer else None

        result.append(NewProduct(
            code=item.code,
            name=title,
            haseb_quantity=int(item.quantity),
            stock=stock.quantity,
            price=price,
            price_source=source,
            car=car,
            category_ids=list(suggestion.category_ids) if suggestion else [],
            category_reason=suggestion.reason if suggestion else "",
            warehouse=item.warehouse_name,
        ))
    return result


def to_woo_create(product: NewProduct, *, status: str = "publish") -> dict:
    """شکل قابل‌فهم ووکامرس برای ساخت محصول ساده.

    >>> p = NewProduct("0050102699", "سپر", 3, 2, 1_500_000, category_ids=[5])
    >>> to_woo_create(p)["regular_price"], to_woo_create(p)["categories"]
    ('1500000', [{'id': 5}])
    """
    payload: dict = {
        "name": product.name,
        "type": "simple",
        "status": status,
        "sku": product.code,
        "manage_stock": True,
        "stock_quantity": product.stock,
        "stock_status": "instock" if product.stock > 0 else "outofstock",
    }
    if product.price:
        payload["regular_price"] = str(product.price)
    if product.category_ids:
        payload["categories"] = [{"id": cid} for cid in product.category_ids]
    return payload
