"""موتور همگام‌سازی: قلب برنامه.

سه منبع را به هم وصل می‌کند و تصمیم می‌گیرد هر محصول سایت چه قیمت و
موجودی جدیدی بگیرد:

    محصولات سایت (ووکامرس)
        ×  لیست قیمت ایساکو   (بر اساس SKU نرمال‌شده)
        ×  موجودی حاسب        (بر اساس همان SKU)
        →  قیمت جدید (قواعد pricing) + موجودی جدید (قواعد stock)

خروجی یک «برنامهٔ سینک» است: فهرستی از تغییرات پیشنهادی که در حالت
دستی به کارفرما نشان داده می‌شود و در حالت خودکار مستقیم اعمال می‌شود.
موتور خودش چیزی روی سایت نمی‌نویسد؛ فقط برنامه را می‌سازد. اعمال آن
کار جداگانه‌ای است تا پیش‌نمایش و رول‌بک ممکن باشد.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .pricing import GuardReason, PriceResult, PriceRules, compute as compute_price
from .skucode import normalize
from .sources.haseb_dbf import HasebItem
from .sources.isaco_excel import IsacoItem
from .stock import StockResult, StockRules, compute as compute_stock
from .targets.woocommerce import WooProduct


class MatchStatus(enum.StrEnum):
    """وضعیت تطبیق یک محصول سایت با منابع."""

    OK = "ok"                          # هم قیمت ایساکو، هم موجودی حاسب
    NO_SKU = "no_sku"                  # محصول سایت SKU ندارد
    NO_ISACO_PRICE = "no_isaco_price"  # کد در لیست ایساکو نیست
    NO_HASEB_STOCK = "no_haseb_stock"  # کد در حاسب نیست


@dataclass(frozen=True, slots=True)
class SyncItem:
    """یک ردیف از برنامهٔ سینک؛ همان چیزی که در جدول پیش‌نمایش می‌بینیم."""

    product_id: int
    sku: str                    # SKU نرمال‌شده
    name: str
    match: MatchStatus

    current_price: int | None = None
    new_price: int | None = None
    price_result: PriceResult | None = None

    current_stock: int | None = None
    new_stock: int | None = None
    stock_result: StockResult | None = None

    isaco: IsacoItem | None = None
    haseb: HasebItem | None = None

    @property
    def price_changes(self) -> bool:
        return (
            self.new_price is not None
            and self.current_price is not None
            and self.new_price != self.current_price
        )

    @property
    def stock_changes(self) -> bool:
        return (
            self.new_stock is not None
            and self.current_stock is not None
            and self.new_stock != self.current_stock
        )

    @property
    def changes(self) -> bool:
        return self.price_changes or self.stock_changes

    @property
    def needs_review(self) -> bool:
        """آیا این تغییر باید دستی تأیید شود (محافظ فعال شده)؟"""
        return self.price_result is not None and self.price_result.needs_review

    def to_woo_update(
        self, *, include_price: bool = True, include_stock: bool = True
    ) -> dict | None:
        """این ردیف را به شکل قابل‌فهم برای ``products/batch`` درمی‌آورد.

        اگر تغییری ندارد یا نیاز به بازبینی دارد، ``None`` برمی‌گرداند تا
        به‌طور خودکار اعمال نشود.
        """
        if self.needs_review or not self.changes:
            return None
        payload: dict = {"id": self.product_id}
        if include_price and self.price_changes:
            payload["regular_price"] = str(self.new_price)
        if include_stock and self.stock_changes and self.stock_result is not None:
            payload["manage_stock"] = True
            payload["stock_quantity"] = self.new_stock
            payload["stock_status"] = self.stock_result.status.value
        return payload if len(payload) > 1 else None


@dataclass(slots=True)
class SyncPlan:
    """کل برنامهٔ سینک به‌همراه آمار خلاصه."""

    items: list[SyncItem] = field(default_factory=list)

    def matched(self) -> list[SyncItem]:
        return [i for i in self.items if i.match is MatchStatus.OK]

    def with_changes(self) -> list[SyncItem]:
        return [i for i in self.items if i.changes and not i.needs_review]

    def needing_review(self) -> list[SyncItem]:
        return [i for i in self.items if i.needs_review]

    def unmatched(self) -> list[SyncItem]:
        return [i for i in self.items if i.match is not MatchStatus.OK]

    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.items),
            "matched": len(self.matched()),
            "price_changes": sum(1 for i in self.items if i.price_changes),
            "stock_changes": sum(1 for i in self.items if i.stock_changes),
            "changes": len(self.with_changes()),
            "needs_review": len(self.needing_review()),
            "no_isaco_price": sum(
                1 for i in self.items if i.match is MatchStatus.NO_ISACO_PRICE
            ),
            "no_haseb_stock": sum(
                1 for i in self.items if i.match is MatchStatus.NO_HASEB_STOCK
            ),
            "no_sku": sum(1 for i in self.items if i.match is MatchStatus.NO_SKU),
        }

    def to_woo_updates(
        self, *, include_price: bool = True, include_stock: bool = True
    ) -> list[dict]:
        updates = []
        for item in self.items:
            payload = item.to_woo_update(
                include_price=include_price, include_stock=include_stock
            )
            if payload is not None:
                updates.append(payload)
        return updates


def build_plan(
    products: list[WooProduct],
    isaco: dict[str, IsacoItem],
    haseb: dict[str, HasebItem],
    price_rules: PriceRules,
    stock_rules: StockRules,
    *,
    update_price: bool = True,
    update_stock: bool = True,
) -> SyncPlan:
    """برنامهٔ سینک را از سه منبع می‌سازد.

    :param products: محصولات سایت (فقط این‌ها؛ محصول جدید ساخته نمی‌شود).
    :param isaco: لیست قیمت ایساکو، «کد نرمال‌شده → کالا».
    :param haseb: موجودی حاسب، «کد نرمال‌شده → کالا».
    :param update_price: اگر خاموش باشد فقط موجودی سینک می‌شود.
    :param update_stock: اگر خاموش باشد فقط قیمت سینک می‌شود.
    """
    plan = SyncPlan()

    for product in products:
        sku = normalize(product.sku)

        if not sku:
            plan.items.append(
                SyncItem(
                    product_id=product.id,
                    sku="",
                    name=product.name,
                    match=MatchStatus.NO_SKU,
                    current_price=product.price_toman,
                    current_stock=product.stock_quantity,
                )
            )
            continue

        isaco_item = isaco.get(sku)
        haseb_item = haseb.get(sku)

        # --- قیمت ---
        price_result: PriceResult | None = None
        new_price: int | None = None
        if update_price and isaco_item is not None:
            price_result = compute_price(
                isaco_retail=isaco_item.retail,
                isaco_vat=isaco_item.vat,
                isaco_wholesale=isaco_item.wholesale,
                rules=price_rules,
                current_site_price=product.price_toman,
            )
            if price_result.guard is not GuardReason.NO_SOURCE_PRICE:
                new_price = price_result.price

        # --- موجودی ---
        stock_result: StockResult | None = None
        new_stock: int | None = None
        if update_stock and haseb_item is not None:
            stock_result = compute_stock(sku, haseb_item.quantity, stock_rules)
            new_stock = stock_result.quantity

        # --- وضعیت تطبیق ---
        if isaco_item is None:
            match = MatchStatus.NO_ISACO_PRICE
        elif haseb_item is None:
            match = MatchStatus.NO_HASEB_STOCK
        else:
            match = MatchStatus.OK

        plan.items.append(
            SyncItem(
                product_id=product.id,
                sku=sku,
                name=product.name,
                match=match,
                current_price=product.price_toman,
                new_price=new_price,
                price_result=price_result,
                current_stock=product.stock_quantity,
                new_stock=new_stock,
                stock_result=stock_result,
                isaco=isaco_item,
                haseb=haseb_item,
            )
        )

    return plan
