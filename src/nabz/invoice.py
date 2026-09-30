"""ساخت فاکتور فروش از یک سفارش ووکامرس (HTML آمادهٔ چاپ و PDF).

خروجی یک HTML راست‌به‌چپ ساده است که هم در ``QTextDocument`` (چاپ و
PDF داخل برنامه) و هم در مرورگر درست نمایش داده می‌شود. عمداً از CSS
پیشرفته استفاده نشده چون موتور متن Qt فقط زیرمجموعه‌ای از CSS را
می‌فهمد.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from . import jalali

#: نام فارسی وضعیت‌های استاندارد سفارش ووکامرس.
ORDER_STATUS_FA = {
    "pending": "در انتظار پرداخت",
    "processing": "در حال انجام",
    "on-hold": "در انتظار بررسی",
    "completed": "تکمیل‌شده",
    "cancelled": "لغوشده",
    "refunded": "مسترد‌شده",
    "failed": "ناموفق",
    "checkout-draft": "پیش‌نویس",
    "trash": "زباله‌دان",
}

#: رنگ هر وضعیت در جدول سفارش‌ها
ORDER_STATUS_COLOR = {
    "pending": "#9e9e9e",
    "processing": "#2e7d32",
    "on-hold": "#ef6c00",
    "completed": "#1565c0",
    "cancelled": "#c62828",
    "refunded": "#6a1b9a",
    "failed": "#c62828",
}

CURRENCY_FA = {"IRT": "تومان", "IRR": "ریال", "IRHT": "هزار تومان", "IRHR": "هزار ریال"}


@dataclass(slots=True)
class ShopInfo:
    """اطلاعات فروشنده که بالای فاکتور چاپ می‌شود (از تنظیمات)."""

    name: str = "تکسایدک"
    address: str = ""
    phone: str = ""
    postal_code: str = ""
    economic_code: str = ""
    website: str = ""
    footer: str = "از خرید شما سپاسگزاریم."
    logo_path: str = ""

    @classmethod
    def from_settings(cls, get_setting) -> "ShopInfo":
        return cls(
            name=get_setting("invoice_shop_name", "تکسایدک") or "تکسایدک",
            address=get_setting("invoice_address", "") or "",
            phone=get_setting("invoice_phone", "") or "",
            postal_code=get_setting("invoice_postal_code", "") or "",
            economic_code=get_setting("invoice_economic_code", "") or "",
            website=get_setting("invoice_website", "") or "",
            footer=get_setting("invoice_footer", "از خرید شما سپاسگزاریم.") or "",
            logo_path=get_setting("invoice_logo_path", "") or "",
        )


def status_name(slug: str, names: dict[str, str] | None = None) -> str:
    """نام فارسی وضعیت؛ وضعیت‌های سفارشیِ افزونه‌ها از ``names``."""
    slug = (slug or "").removeprefix("wc-")
    if names and slug in names:
        return names[slug]
    return ORDER_STATUS_FA.get(slug, slug)


def _num(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def format_amount(value, currency: str = "IRT", *, unit: bool = True) -> str:
    """مبلغ با جداکنندهٔ هزارگان و ارقام فارسی.

    >>> format_amount("1250000")
    '۱٬۲۵۰٬۰۰۰ تومان'
    >>> format_amount("0", unit=False)
    '۰'
    """
    number = _num(value)
    if number == number.to_integral_value():
        text = f"{int(number):,}"
    else:
        text = f"{number:,.2f}"
    text = jalali.fa_digits(text.replace(",", "٬"))
    if unit:
        text += " " + CURRENCY_FA.get(currency, currency)
    return text


def customer_name(order: dict) -> str:
    billing = order.get("billing") or {}
    name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
    if not name:
        shipping = order.get("shipping") or {}
        name = f"{shipping.get('first_name', '')} {shipping.get('last_name', '')}".strip()
    return name or billing.get("company") or "مهمان"


def address_text(part: dict) -> str:
    """نشانی کامل از بخش billing یا shipping."""
    if not part:
        return ""
    bits = [
        part.get("state", ""), part.get("city", ""),
        part.get("address_1", ""), part.get("address_2", ""),
    ]
    text = "، ".join(b.strip() for b in bits if b and b.strip())
    if part.get("postcode"):
        text += f" — کد پستی: {part['postcode']}"
    return text


def _meta_text(item: dict) -> str:
    """ویژگی‌های قلم سفارش (مثلاً رنگ/مدل در محصولات متغیر)."""
    parts = []
    for meta in item.get("meta_data") or []:
        key = str(meta.get("display_key") or meta.get("key") or "")
        if not key or key.startswith("_"):
            continue
        value = meta.get("display_value", meta.get("value", ""))
        if isinstance(value, (dict, list)):
            continue
        parts.append(f"{key}: {value}")
    return "، ".join(parts)


def render_invoice_html(order: dict, shop: ShopInfo | None = None,
                        *, status_names: dict[str, str] | None = None,
                        reverse_columns: bool = False) -> str:
    """HTML فاکتور فروش یک سفارش.

    :param reverse_columns: موتور متن Qt (چاپ/PDF) ستون‌های جدول را هرگز
        راست‌به‌چپ نمی‌چیند؛ با این گزینه ترتیب ستون‌ها در خود HTML برعکس
        می‌شود تا ستون «ردیف» سمت راست بیفتد. برای مرورگر خاموش بماند.

    >>> html_ = render_invoice_html({"id": 12, "number": "12", "currency": "IRT",
    ...     "date_created": "2026-09-30T10:00:00", "total": "500000",
    ...     "line_items": [{"name": "سپر", "quantity": 1, "total": "500000",
    ...                     "sku": "0050102699"}]})
    >>> "۱۴۰۵/۰۷/۰۸" in html_ and "سپر" in html_ and "۵۰۰٬۰۰۰" in html_
    True
    """
    shop = shop or ShopInfo()

    def tr(*cells: str, attrs: str = "") -> str:
        ordered = cells[::-1] if reverse_columns else cells
        return f"<tr{attrs}>" + "".join(ordered) + "</tr>"

    esc = lambda v: html.escape(str(v or ""))  # noqa: E731
    currency = order.get("currency", "IRT")
    amount = lambda v: format_amount(v, currency, unit=False)  # noqa: E731
    unit = CURRENCY_FA.get(currency, currency)
    billing = order.get("billing") or {}
    shipping = order.get("shipping") or {}
    number = order.get("number") or order.get("id")

    rows = []
    subtotal = Decimal(0)
    for i, item in enumerate(order.get("line_items") or [], start=1):
        qty = _num(item.get("quantity"))
        line_subtotal = _num(item.get("subtotal", item.get("total")))
        line_total = _num(item.get("total"))
        unit_price = (line_subtotal / qty) if qty else Decimal(0)
        discount = line_subtotal - line_total
        subtotal += line_subtotal
        meta = _meta_text(item)
        name = esc(item.get("name"))
        if meta:
            name += f"<br><span style='color:#666;font-size:9pt'>{esc(meta)}</span>"
        rows.append(tr(
            f"<td align='center'>{jalali.fa_digits(i)}</td>",
            f"<td align='center' style='font-family:Consolas'>{esc(item.get('sku'))}</td>",
            f"<td align='right'>{name}</td>",
            f"<td align='center'>{jalali.fa_digits(int(qty) if qty == int(qty) else qty)}</td>",
            f"<td align='center'>{amount(unit_price)}</td>",
            f"<td align='center'>{amount(discount) if discount else '—'}</td>",
            f"<td align='center'>{amount(line_total)}</td>",
        ))

    shipping_lines = order.get("shipping_lines") or []
    shipping_title = "، ".join(
        str(s.get("method_title", "")) for s in shipping_lines if s.get("method_title"))
    fee_lines = order.get("fee_lines") or []

    totals = [("جمع اقلام", amount(subtotal))]
    discount_total = _num(order.get("discount_total"))
    if discount_total:
        coupons = "، ".join(c.get("code", "") for c in order.get("coupon_lines") or [])
        label = "تخفیف" + (f" ({esc(coupons)})" if coupons else "")
        totals.append((label, "− " + amount(discount_total)))
    for fee in fee_lines:
        totals.append((esc(fee.get("name", "هزینه")), amount(fee.get("total"))))
    shipping_total = _num(order.get("shipping_total"))
    if shipping_total or shipping_title:
        label = "هزینهٔ ارسال" + (f" ({esc(shipping_title)})" if shipping_title else "")
        totals.append((label, amount(shipping_total) if shipping_total else "رایگان"))
    tax = _num(order.get("total_tax"))
    if tax:
        totals.append(("مالیات بر ارزش افزوده", amount(tax)))
    totals_html = "".join(
        tr(f"<td align='left' colspan='6'>{label}</td>",
           f"<td align='center'>{value}</td>")
        for label, value in totals
    )

    logo = ""
    if shop.logo_path:
        from pathlib import Path
        if Path(shop.logo_path).is_file():
            logo = f"<img src='{esc(Path(shop.logo_path).as_uri())}' height='60'>"

    seller_lines = [f"<b style='font-size:14pt'>{esc(shop.name)}</b>"]
    if shop.address:
        seller_lines.append(f"نشانی: {esc(shop.address)}")
    contact = []
    if shop.phone:
        contact.append(f"تلفن: {esc(jalali.fa_digits(shop.phone))}")
    if shop.postal_code:
        contact.append(f"کد پستی: {esc(jalali.fa_digits(shop.postal_code))}")
    if shop.economic_code:
        contact.append(f"شناسهٔ اقتصادی: {esc(jalali.fa_digits(shop.economic_code))}")
    if contact:
        seller_lines.append(" — ".join(contact))
    if shop.website:
        seller_lines.append(esc(shop.website))

    buyer_address = address_text(shipping) or address_text(billing)
    buyer_lines = [f"<b>{esc(customer_name(order))}</b>"]
    if billing.get("company"):
        buyer_lines.append(esc(billing["company"]))
    if billing.get("phone"):
        buyer_lines.append(f"تلفن: {esc(jalali.fa_digits(billing['phone']))}")
    if billing.get("email"):
        buyer_lines.append(esc(billing["email"]))
    if buyer_address:
        buyer_lines.append(f"نشانی: {esc(jalali.fa_digits(buyer_address))}")

    paid = jalali.format_iso(order.get("date_paid"), empty="")
    info = [
        f"شمارهٔ فاکتور: <b>{jalali.fa_digits(esc(number))}</b>",
        f"تاریخ: {jalali.format_iso(order.get('date_created'))}",
        f"وضعیت: {esc(status_name(order.get('status', ''), status_names))}",
    ]
    if order.get("payment_method_title"):
        info.append(f"روش پرداخت: {esc(order['payment_method_title'])}")
    if paid:
        info.append(f"تاریخ پرداخت: {paid}")
    if order.get("transaction_id"):
        info.append(f"کد پیگیری: {esc(jalali.fa_digits(order['transaction_id']))}")

    br = "<br>"
    header_html = '<table width="100%" cellpadding="4">' + tr(
        f'<td width="25%" align="right">{br.join(info)}</td>',
        '<td width="50%" align="center"><span style="font-size:18pt">'
        '<b>فاکتور فروش</b></span></td>',
        f'<td width="25%" align="left">{logo}</td>',
    ) + "</table>"
    parties_html = tr(
        f'<td width="50%" valign="top" align="right"><b>فروشنده</b>{br}'
        f'{br.join(seller_lines)}</td>',
        f'<td width="50%" valign="top" align="right"><b>خریدار</b>{br}'
        f'{br.join(buyer_lines)}</td>',
    )
    grid_head = tr(
        '<th width="5%">ردیف</th>', '<th width="14%">کد کالا</th>', '<th>شرح کالا</th>',
        '<th width="7%">تعداد</th>', f'<th width="13%">فی ({unit})</th>',
        '<th width="11%">تخفیف</th>', f'<th width="14%">مبلغ ({unit})</th>',
    )
    payable_html = tr(
        '<td align="left" colspan="6"><b>مبلغ قابل پرداخت</b></td>',
        f'<td align="center"><b>{format_amount(order.get("total"), currency)}</b></td>',
    )
    signs_html = '<table width="100%">' + tr(
        '<td align="center" width="50%">مهر و امضای فروشنده</td>',
        '<td align="center" width="50%">امضای خریدار</td>',
    ) + "</table>"

    note = ""
    if order.get("customer_note"):
        note = (f"<p><b>یادداشت مشتری:</b> {esc(order['customer_note'])}</p>")

    return f"""<html dir="rtl"><head><meta charset="utf-8">
<style>
body {{ font-family: 'Vazirmatn', 'Tahoma', sans-serif; font-size: 10pt; color: #222; }}
table.grid {{ border-collapse: collapse; width: 100%; }}
table.grid th {{ background: #263238; color: white; padding: 6px; border: 1px solid #263238; }}
table.grid td {{ border: 1px solid #bbb; padding: 5px; }}
.box {{ border: 1px solid #bbb; padding: 6px; }}
</style></head>
<body dir="rtl">
{header_html}
<br>
<table width="100%" cellspacing="0" cellpadding="6" border="1" style="border-collapse:collapse;border-color:#bbb">
  {parties_html}
</table>
<br>
<table class="grid" width="100%" cellspacing="0" cellpadding="5" border="1">
  {grid_head}
  {''.join(rows)}
  {totals_html}
  {payable_html}
</table>
{note}
<br>
{signs_html}
<br><br>
<p align="center" style="color:#666">{esc(shop.footer)}<br>
تاریخ چاپ: {jalali.now_str()}</p>
</body></html>"""
