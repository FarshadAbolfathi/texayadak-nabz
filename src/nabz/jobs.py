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

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import CredentialStore
from .db import Database
from .engine import SyncPlan, build_plan
from .runner import ApplyResult, apply_plan
from .sources.haseb_dbf import load_products as load_haseb
from .sources.isaco_excel import load as load_isaco
from .targets.woocommerce import WooClient

_log = logging.getLogger("nabz.jobs")


@dataclass(slots=True)
class AutoSyncResult:
    ok: bool
    message: str
    apply_result: ApplyResult | None = None
    #: کالاهای حاسب که روی سایت نیستند (کل / تازه‌کشف‌شده در همین اجرا)
    missing_on_site: int = 0
    newly_missing: int = 0


def record_missing_products(
    db: Database,
    haseb: dict,
    products: list,
    woo: WooClient | None = None,
    isaco: dict | None = None,
) -> tuple[int, int]:
    """کالاهای حاسب که روی سایت نیستند را (با شرط انتخابی کارفرما در تب
    «محصولات جدید حاسب»: موجودی/قیمت/هر دو) پیدا و ذخیره می‌کند.

    فقط «خبر» می‌دهد؛ هیچ محصولی نمی‌سازد. کدهایی که قبلاً اعلام شده‌اند
    یا کارفرما نادیده‌شان گرفته، دوباره «تازه» حساب نمی‌شوند.

    :returns: ``(تعداد کل جاافتاده‌ها، تعداد تازه‌ها)``
    """
    from .new_products import DEFAULT_CRITERIA, select_missing, site_skus

    extra: list[str] = []
    if woo is not None:
        for p in products:
            if p.type == "variable":
                try:
                    extra.extend(woo.fetch_variation_skus(p.id))
                except Exception as exc:  # noqa: BLE001
                    _log.warning("متغیرهای محصول %s خوانده نشد: %s", p.id, exc)
    # انبارهایی که کارفرما در تب «محصولات جدید حاسب» انتخاب کرده
    chosen_wh = db.get_setting("new_products_warehouses", None)
    haseb_path = db.get_setting("haseb_cal_path", "")
    if chosen_wh and haseb_path and Path(haseb_path).is_file():
        haseb = load_haseb(haseb_path, warehouses={int(i) for i in chosen_wh})

    ignored = db.get_setting("new_products_ignored", []) or []
    criteria = db.get_setting("new_products_criteria", DEFAULT_CRITERIA)
    if criteria != "stock" and not isaco:
        isaco = _load_isaco_quietly(db)
    missing = select_missing(
        haseb, site_skus(products, extra),
        criteria=criteria, isaco=isaco, price_rules=_price_rules(db), ignored=ignored,
    )
    codes = [m.code for m in missing]
    seen = set(db.get_setting("new_products_seen", []) or [])
    fresh = [c for c in codes if c not in seen]
    db.set_setting("new_products_pending", codes)
    db.set_setting("new_products_seen", sorted(seen | set(codes)))
    if fresh:
        db.set_setting("new_products_unread", True)
        db.log("info", f"{len(fresh)} کالای جدید در حاسب پیدا شد که روی سایت نیست.")
    return len(codes), len(fresh)


def _load_isaco_quietly(db: Database) -> dict:
    """لیست ایساکو فقط برای تشخیص «قیمت دارد»؛ خطا سینک را خراب نمی‌کند."""
    path = db.get_setting("isaco_excel_path", "")
    if not (path and Path(path).is_file()):
        return {}
    try:
        return load_isaco(path)
    except Exception as exc:  # noqa: BLE001
        _log.warning("لیست ایساکو برای محصولات جدید خوانده نشد: %s", exc)
        return {}


def _price_rules(db: Database):
    from .ui.services import price_rules_from_db
    return price_rules_from_db(db)


def _stock_rules(db: Database):
    from .ui.services import stock_rules_from_db
    return stock_rules_from_db(db)


def build_woo(store: CredentialStore) -> WooClient | None:
    from .ui.services import woo_client_from_store
    return woo_client_from_store(store)


def try_auto_download_isaco(
    db: Database,
    store: CredentialStore,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> str | None:
    """لیست قیمت ایساکو را با مرورگر داخلی دانلود می‌کند (اگر ممکن بود).

    ⚠️ باید در **نخِ اصلیِ Qt** فراخوانی شود، چون از ``QWebEngineView``
    استفاده می‌کند که فقط در نخ رابط کاربری قابل استفاده است. برای سینکِ
    زمان‌بندی‌شده (که روی نخ APScheduler اجرا می‌شود)، فراخوانیِ این تابع
    باید با یک سیگنال Qt به نخ اصلی منتقل شود؛ نمونه‌اش در
    ``MainWindow._run_scheduled_sync`` است.

    موفق یا ناموفق، هیچ استثنایی به بیرون درز نمی‌کند — اگر دانلود نشد،
    ``None`` برمی‌گرداند و ``run_auto_sync`` به فایل تنظیم‌شده برمی‌گردد.
    """
    creds = store.load_isaco()
    if not (creds.scus and creds.username and creds.password):
        return None
    try:
        from .sources.isaco_browser import IsacoDownloader
    except ImportError as exc:
        _log.warning("موتور مرورگر در دسترس نیست: %s", exc)
        return None
    # دانلود اول در یک فایل جدا انجام و بررسی می‌شود؛ فقط اگر سالم و کامل
    # بود جای لیست قبلی را می‌گیرد. قبلاً مستقیم روی همان فایل (در پوشهٔ
    # موقت ویندوز) دانلود می‌شد و یک دانلود نیمه‌کاره لیست سالم را خراب
    # می‌کرد → همهٔ کالاها «بی‌قیمت» می‌شدند.
    folder = isaco_dir()
    staging = folder / "isaco_pricelist.downloading.xlsx"
    final = folder / "isaco_pricelist.xlsx"
    try:
        staging.unlink(missing_ok=True)
        downloader = IsacoDownloader(
            creds.scus, creds.username, creds.password, on_progress=on_progress
        )
        path = Path(downloader.download(str(staging)))
        if on_progress:
            on_progress("در حال بررسی سالم بودن فایل لیست قیمت ...")
        items = load_isaco(path)          # محافظ تعداد ردیف و قیمت داخل load است
        os.replace(path, final)
        db.set_setting("isaco_excel_path", str(final))
        _log.info("دانلود خودکار ایساکو موفق: %s (%s قلم)", final, len(items))
        return str(final)
    except Exception as exc:  # noqa: BLE001 - هرگز نباید سینک را متوقف کند
        _log.warning("دانلود خودکار ایساکو نشد (لیست قبلی حفظ شد): %s", exc,
                     exc_info=True)
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def isaco_dir() -> Path:
    """پوشهٔ دائمی لیست قیمت ایساکو (نه پوشهٔ موقت ویندوز که پاک‌سازی می‌شود)."""
    from .logging_setup import LOG_DIR_NAME
    path = Path.home() / LOG_DIR_NAME / "isaco"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_auto_sync(
    db: Database,
    store: CredentialStore,
    *,
    mode: str = "auto",
    woo: WooClient | None = None,
    update_price: bool | None = None,
    update_stock: bool | None = None,
) -> AutoSyncResult:
    """یک اجرای کامل سینک بر اساس تنظیمات ذخیره‌شده.

    :param woo: برای تست می‌توان کلاینت جعلی تزریق کرد.
    :param update_price: اگر داده نشود از تنظیمات خوانده می‌شود؛ هر ساعت
        زمان‌بندی می‌تواند مقدار خودش را بدهد.
    """
    if update_price is None:
        update_price = bool(db.get_setting("schedule_price", True))
    if update_stock is None:
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
    missing = fresh = 0
    if haseb:
        try:
            # همان داده‌های همین اجرا؛ فقط برای خبر دادن، بدون ساخت محصول
            missing, fresh = record_missing_products(
                db, haseb, products, woo, isaco=isaco)
        except Exception as exc:  # noqa: BLE001 - نباید سینک را خراب کند
            _log.warning("بررسی محصولات جدید حاسب نشد: %s", exc, exc_info=True)

    message = f"{result.applied_count} محصول به‌روز شد."
    if fresh:
        message += f" {fresh} کالای جدید حاسب روی سایت نیست."
    return AutoSyncResult(
        True,
        message,
        apply_result=result,
        missing_on_site=missing,
        newly_missing=fresh,
    )
