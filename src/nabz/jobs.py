"""اجرای سینک بدون رابط کاربری — برای زمان‌بند و «سینک فوری».

این تابع منطق کامل یک اجرای خودکار را بدون هیچ UI‌ای انجام می‌دهد تا هم
زمان‌بند شبانه و هم دکمهٔ سینک فوری از یک مسیر واحد استفاده کنند.

منابع از تنظیمات خوانده می‌شوند:
- ``haseb_cal_path``  : مسیر فایل ``cal.DBF`` حاسب (برای موجودی)
- ``isaco_excel_path``: مسیر آخرین فایل لیست قیمت ایساکو (برای قیمت)
- ``isaco_warehouses``: کدهای انبار ایساکو در حاسب (فیلتر موجودی)

هر منبعی که تنظیم نشده باشد، آن بخش سینک نادیده گرفته می‌شود؛ مثلاً اگر
فقط مسیر حاسب باشد، فقط موجودی سینک می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import CredentialStore
from .db import Database
from .engine import SyncPlan, build_plan
from .runner import ApplyResult, apply_plan
from .sources.haseb_dbf import load_products as load_haseb
from .sources.isaco_excel import load as load_isaco
from .targets.woocommerce import WooClient, WooConfig


@dataclass(slots=True)
class AutoSyncResult:
    ok: bool
    message: str
    apply_result: ApplyResult | None = None


def _price_rules(db: Database):
    from .ui.services import price_rules_from_db
    return price_rules_from_db(db)


def _stock_rules(db: Database):
    from .ui.services import stock_rules_from_db
    return stock_rules_from_db(db)


def build_woo(store: CredentialStore) -> WooClient | None:
    creds = store.load_woo()
    if not (creds.base_url and creds.consumer_key and creds.consumer_secret):
        return None
    return WooClient(WooConfig(
        base_url=creds.base_url,
        consumer_key=creds.consumer_key,
        consumer_secret=creds.consumer_secret,
    ))


def run_auto_sync(
    db: Database,
    store: CredentialStore,
    *,
    mode: str = "auto",
    woo: WooClient | None = None,
) -> AutoSyncResult:
    """یک اجرای کامل سینک بر اساس تنظیمات ذخیره‌شده.

    :param woo: برای تست می‌توان کلاینت جعلی تزریق کرد.
    """
    update_price = bool(db.get_setting("schedule_price", True))
    update_stock = bool(db.get_setting("schedule_stock", True))
    isaco_path = db.get_setting("isaco_excel_path", "")
    haseb_path = db.get_setting("haseb_cal_path", "")
    warehouses = db.get_setting("isaco_warehouses", None)

    woo = woo or build_woo(store)
    if woo is None:
        db.log("error", "سینک خودکار: اطلاعات اتصال ووکامرس کامل نیست.")
        return AutoSyncResult(False, "اطلاعات اتصال ووکامرس کامل نیست.")

    # --- بارگذاری منابع ---
    isaco: dict = {}
    if update_price and isaco_path and Path(isaco_path).is_file():
        try:
            isaco = load_isaco(isaco_path)
        except Exception as exc:  # noqa: BLE001
            db.log("error", f"سینک خودکار: خطا در خواندن فایل ایساکو: {exc}")
            return AutoSyncResult(False, f"خطا در فایل ایساکو: {exc}")

    haseb: dict = {}
    if update_stock and haseb_path and Path(haseb_path).is_file():
        try:
            wh = set(warehouses) if warehouses else None
            haseb = load_haseb(haseb_path, warehouses=wh)
        except Exception as exc:  # noqa: BLE001
            db.log("error", f"سینک خودکار: خطا در خواندن حاسب: {exc}")
            return AutoSyncResult(False, f"خطا در دیتابیس حاسب: {exc}")

    if not isaco and not haseb:
        db.log("warn", "سینک خودکار: منبعی برای سینک تنظیم نشده است.")
        return AutoSyncResult(False, "هیچ منبعی (ایساکو یا حاسب) تنظیم نشده است.")

    try:
        products = woo.fetch_products()
    except Exception as exc:  # noqa: BLE001
        db.log("error", f"سینک خودکار: خطا در خواندن محصولات سایت: {exc}")
        return AutoSyncResult(False, f"خطا در خواندن محصولات: {exc}")

    plan = build_plan(
        products=products,
        isaco=isaco,
        haseb=haseb,
        price_rules=_price_rules(db),
        stock_rules=_stock_rules(db),
        update_price=bool(isaco),
        update_stock=bool(haseb),
    )

    result = apply_plan(
        plan, woo, db,
        mode=mode,
        include_price=bool(isaco),
        include_stock=bool(haseb),
    )
    return AutoSyncResult(
        True,
        f"{result.applied_count} محصول به‌روز شد.",
        apply_result=result,
    )
