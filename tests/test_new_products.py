"""تست کشف کالاهای حاسب که روی سایت نیستند."""

from decimal import Decimal

from nabz.categorize import Categorizer
from nabz.new_products import build_candidates, clean_title, find_missing, site_skus, to_woo_create
from nabz.pricing import PriceRules
from nabz.sources.haseb_dbf import HasebItem
from nabz.sources.isaco_excel import IsacoItem
from nabz.stock import StockRules
from nabz.targets.woocommerce import WooCategory, WooProduct


def haseb(code, name="کالا", qty=3, price=0):
    return HasebItem(code, code.lstrip("0"), name, Decimal(qty), 1, "انبار ایساکو",
                     sale_price=Decimal(price))


def product(sku):
    return WooProduct(id=1, name="x", sku=sku, regular_price="", stock_quantity=1,
                      stock_status="instock", manage_stock=True, type="simple",
                      status="draft")


def test_only_in_stock_and_not_on_site():
    items = {
        "0050102699": haseb("0050102699", qty=2),      # جدید و موجود
        "0921900699": haseb("0921900699", qty=5),      # روی سایت هست (بدون صفر)
        "0000000011": haseb("0000000011", qty=0),      # موجودی ندارد
    }
    existing = site_skus([product("921900699")])
    missing = find_missing(items, existing)
    assert [m.code for m in missing] == ["0050102699"]


def test_variation_skus_count_as_on_site():
    items = {"0050102699": haseb("0050102699")}
    assert find_missing(items, site_skus([], ["50102699"])) == []


def test_price_from_isaco_then_haseb():
    isaco = {"0050102699": IsacoItem("0050102699", "سپر", "پژو 405", "عدد", 1,
                                      retail=10_000_000, vat=11_000_000, wholesale=9_000_000)}
    missing = [haseb("0050102699", "سپر عقب", qty=7), haseb("0000012345", "پیچ", price=254_000)]
    cands = build_candidates(
        missing, isaco=isaco,
        price_rules=PriceRules(markup_percent=Decimal("10")),
        stock_rules=StockRules(max_on_site=2),
        categorizer=Categorizer([WooCategory(2, "پژو ۴۰۵")]),
    )
    bumper, screw = cands
    assert bumper.price == 1_210_000 and bumper.price_source == "ایساکو"
    assert bumper.stock == 2 and bumper.haseb_quantity == 7
    assert bumper.category_ids == [2]           # از ستون «مصرف خودرو»
    assert screw.price == 25_000 and screw.price_source == "حاسب"


def test_no_price_when_no_source():
    (c,) = build_candidates([haseb("0000012345")])
    assert c.price is None
    assert "regular_price" not in to_woo_create(c)


def test_create_payload():
    (c,) = build_candidates([haseb("0050102699", "سپر  عقب ي", qty=1, price=10_000)])
    c.category_ids = [5, 6]
    payload = to_woo_create(c, status="draft")
    assert payload["sku"] == "0050102699"
    assert payload["name"] == "سپر عقب ی"
    assert payload["status"] == "draft"
    assert payload["regular_price"] == "1000"
    assert payload["stock_quantity"] == 1 and payload["manage_stock"] is True
    assert payload["categories"] == [{"id": 5}, {"id": 6}]


def test_clean_title():
    assert clean_title("كيسه  هوا") == "کیسه هوا"
