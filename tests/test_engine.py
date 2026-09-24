"""تست موتور سینک — با دادهٔ واقعی سه سیستم.

سناریوها از محصولات و قیمت‌های واقعی تکسایدک/ایساکو/حاسب ساخته شده‌اند.
"""

from decimal import Decimal

import pytest

from nabz.engine import MatchStatus, build_plan
from nabz.pricing import PriceRules
from nabz.sources.haseb_dbf import HasebItem
from nabz.sources.isaco_excel import IsacoItem
from nabz.stock import StockRules
from nabz.targets.woocommerce import WooProduct


def woo(pid, sku, price="", stock=3):
    return WooProduct(
        id=pid, name=f"محصول {pid}", sku=sku, regular_price=price,
        stock_quantity=stock, stock_status="instock", manage_stock=True,
        type="simple", status="publish",
    )


def isaco(code, retail, vat, wholesale, name="کالا"):
    return IsacoItem(code=code, name=name, car="پژو", unit="عدد",
                     pack_size=1, retail=retail, vat=vat, wholesale=wholesale)


def haseb(code, qty):
    return HasebItem(code=code, raw_code=code.lstrip("0"), name="کالا",
                     quantity=Decimal(qty), warehouse_id=1,
                     warehouse_name="انبار ايساکو")


# استارت EF7 — کد 0050102699، قیمت‌های واقعی
STARTER_CODE = "0050102699"
STARTER_ISACO = {STARTER_CODE: isaco(STARTER_CODE, 62_720_000, 68_992_000, 56_000_000)}


class TestMatching:
    def test_fully_matched_product(self):
        plan = build_plan(
            products=[woo(1, "50102699")],
            isaco=STARTER_ISACO,
            haseb={STARTER_CODE: haseb(STARTER_CODE, "5")},
            price_rules=PriceRules(markup_percent=Decimal("15")),
            stock_rules=StockRules(max_on_site=2),
        )
        item = plan.items[0]
        assert item.match is MatchStatus.OK
        assert item.sku == STARTER_CODE
        assert item.new_price == 7_934_000   # ۱۵٪ سود، رند ۱۰۰۰
        assert item.new_stock == 2           # سقف ۲

    def test_product_without_sku(self):
        plan = build_plan(
            products=[woo(1, "")],
            isaco=STARTER_ISACO, haseb={},
            price_rules=PriceRules(), stock_rules=StockRules(),
        )
        assert plan.items[0].match is MatchStatus.NO_SKU

    def test_product_not_in_isaco(self):
        plan = build_plan(
            products=[woo(1, "999999999")],
            isaco=STARTER_ISACO,
            haseb={"0999999999": haseb("0999999999", "5")},
            price_rules=PriceRules(), stock_rules=StockRules(),
        )
        item = plan.items[0]
        assert item.match is MatchStatus.NO_ISACO_PRICE
        assert item.new_price is None
        # موجودی هنوز سینک می‌شود چون در حاسب هست
        assert item.new_stock == 2

    def test_product_not_in_haseb(self):
        plan = build_plan(
            products=[woo(1, "50102699")],
            isaco=STARTER_ISACO, haseb={},
            price_rules=PriceRules(markup_percent=Decimal("15")),
            stock_rules=StockRules(max_on_site=2),
        )
        item = plan.items[0]
        assert item.match is MatchStatus.NO_HASEB_STOCK
        assert item.new_price == 7_934_000   # قیمت سینک می‌شود
        assert item.new_stock is None        # موجودی نه


class TestChangeDetection:
    def test_no_change_when_price_already_correct(self):
        plan = build_plan(
            products=[woo(1, "50102699", price="7934000", stock=2)],
            isaco=STARTER_ISACO,
            haseb={STARTER_CODE: haseb(STARTER_CODE, "2")},
            price_rules=PriceRules(markup_percent=Decimal("15")),
            stock_rules=StockRules(max_on_site=2),
        )
        item = plan.items[0]
        assert not item.price_changes
        assert not item.stock_changes
        assert not item.changes

    def test_price_change_detected(self):
        plan = build_plan(
            products=[woo(1, "50102699", price="5000000")],
            isaco=STARTER_ISACO,
            haseb={STARTER_CODE: haseb(STARTER_CODE, "2")},
            price_rules=PriceRules(markup_percent=Decimal("15"),
                                   max_change_percent=Decimal("0")),
            stock_rules=StockRules(max_on_site=2),
        )
        assert plan.items[0].price_changes


class TestGuardsFlowThrough:
    def test_big_jump_is_marked_for_review_not_auto_applied(self):
        plan = build_plan(
            products=[woo(1, "50102699", price="500000")],   # قیمت فعلی خیلی کم
            isaco=STARTER_ISACO,
            haseb={STARTER_CODE: haseb(STARTER_CODE, "2")},
            price_rules=PriceRules(markup_percent=Decimal("15"),
                                   max_change_percent=Decimal("50")),
            stock_rules=StockRules(max_on_site=2),
        )
        item = plan.items[0]
        assert item.needs_review
        assert item not in plan.with_changes()
        assert item in plan.needing_review()
        # نباید در خروجی خودکار باشد
        assert item.to_woo_update() is None


class TestWooUpdatePayload:
    def test_builds_batch_payload_for_changed_item(self):
        plan = build_plan(
            products=[woo(1, "50102699", price="5000000", stock=10)],
            isaco=STARTER_ISACO,
            haseb={STARTER_CODE: haseb(STARTER_CODE, "5")},
            price_rules=PriceRules(markup_percent=Decimal("15"),
                                   max_change_percent=Decimal("0")),
            stock_rules=StockRules(max_on_site=2),
        )
        payload = plan.items[0].to_woo_update()
        assert payload["id"] == 1
        assert payload["regular_price"] == "7934000"
        assert payload["stock_quantity"] == 2
        assert payload["stock_status"] == "instock"
        assert payload["manage_stock"] is True

    def test_stock_only_mode_omits_price(self):
        plan = build_plan(
            products=[woo(1, "50102699", price="5000000", stock=10)],
            isaco=STARTER_ISACO,
            haseb={STARTER_CODE: haseb(STARTER_CODE, "5")},
            price_rules=PriceRules(markup_percent=Decimal("15")),
            stock_rules=StockRules(max_on_site=2),
            update_price=False,
        )
        payload = plan.items[0].to_woo_update()
        assert "regular_price" not in payload
        assert payload["stock_quantity"] == 2

    def test_out_of_stock_status_propagates(self):
        plan = build_plan(
            products=[woo(1, "50102699", price="7934000", stock=5)],
            isaco=STARTER_ISACO,
            haseb={STARTER_CODE: haseb(STARTER_CODE, "0")},
            price_rules=PriceRules(markup_percent=Decimal("15")),
            stock_rules=StockRules(max_on_site=2),
        )
        payload = plan.items[0].to_woo_update()
        assert payload["stock_quantity"] == 0
        assert payload["stock_status"] == "outofstock"


class TestSummary:
    def test_counts_are_correct(self):
        products = [
            woo(1, "50102699", price="5000000", stock=10),   # کامل، تغییر دارد
            woo(2, ""),                                       # بدون SKU
            woo(3, "999999999"),                              # نه در ایساکو
        ]
        plan = build_plan(
            products=products,
            isaco=STARTER_ISACO,
            haseb={STARTER_CODE: haseb(STARTER_CODE, "5")},
            price_rules=PriceRules(markup_percent=Decimal("15"),
                                   max_change_percent=Decimal("0")),
            stock_rules=StockRules(max_on_site=2),
        )
        s = plan.summary()
        assert s["total"] == 3
        assert s["matched"] == 1
        assert s["no_sku"] == 1
        assert s["no_isaco_price"] == 1

    def test_to_woo_updates_skips_unchanged_and_review(self):
        products = [
            woo(1, "50102699", price="5000000", stock=10),   # تغییر دارد
            woo(2, "50102699", price="7934000", stock=2),    # بدون تغییر
        ]
        plan = build_plan(
            products=products,
            isaco=STARTER_ISACO,
            haseb={STARTER_CODE: haseb(STARTER_CODE, "5")},
            price_rules=PriceRules(markup_percent=Decimal("15"),
                                   max_change_percent=Decimal("0")),
            stock_rules=StockRules(max_on_site=2),
        )
        updates = plan.to_woo_updates()
        assert len(updates) == 1
        assert updates[0]["id"] == 1
