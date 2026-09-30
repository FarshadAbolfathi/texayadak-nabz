"""تست ساخت فاکتور."""

from nabz.invoice import ShopInfo, customer_name, format_amount, render_invoice_html, status_name

ORDER = {
    "id": 1520, "number": "1520", "status": "processing", "currency": "IRT",
    "date_created": "2026-09-30T10:15:00", "total": "1740000",
    "shipping_total": "40000", "discount_total": "100000", "total_tax": "0",
    "payment_method_title": "زرین‌پال", "customer_note": "لطفاً زنگ بزنید",
    "billing": {"first_name": "علی", "last_name": "رضایی", "phone": "09120000000",
                "city": "تهران", "state": "تهران", "address_1": "خیابان آزادی"},
    "shipping": {},
    "coupon_lines": [{"code": "off10"}],
    "shipping_lines": [{"method_title": "پست پیشتاز"}],
    "line_items": [
        {"name": "سپر عقب ۴۰۵", "sku": "0050102699", "quantity": 2,
         "subtotal": "1800000", "total": "1700000",
         "meta_data": [{"display_key": "رنگ", "display_value": "مشکی"},
                       {"key": "_hidden", "value": "x"}]},
    ],
}


def test_invoice_contains_key_parts():
    html = render_invoice_html(ORDER, ShopInfo(name="تکسایدک", phone="02112345678"))
    assert "فاکتور فروش" in html
    assert "۱۴۰۵/۰۷/۰۸" in html                  # تاریخ شمسی
    assert "علی رضایی" in html and "خیابان آزادی" in html
    assert "سپر عقب ۴۰۵" in html and "رنگ: مشکی" in html and "_hidden" not in html
    assert "۱٬۷۴۰٬۰۰۰ تومان" in html              # مبلغ قابل پرداخت
    assert "off10" in html and "پست پیشتاز" in html
    assert "۹۰۰٬۰۰۰" in html                      # فی واحد = 1,800,000 / 2
    assert "در حال انجام" in html
    assert "لطفاً زنگ بزنید" in html


def test_html_is_escaped():
    order = dict(ORDER, line_items=[{"name": "<script>x</script>", "quantity": 1,
                                     "total": "1"}])
    assert "<script>" not in render_invoice_html(order)


def test_helpers():
    assert customer_name({"billing": {}}) == "مهمان"
    assert status_name("wc-completed") == "تکمیل‌شده"
    assert status_name("custom", {"custom": "ارسال شده"}) == "ارسال شده"
    assert format_amount("1500", "IRR") == "۱٬۵۰۰ ریال"
