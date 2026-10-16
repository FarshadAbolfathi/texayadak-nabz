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
import time
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
    استفاده می‌کند که فقط در نخ رابط کاربری قابل استفاده است؛ نمونه‌اش در
    ``MainWindow._run_scheduled_sync`` است. هم‌زمان فقط یک دانلود مجاز است.

    موفق یا ناموفق، هیچ استثنایی به بیرون درز نمی‌کند — اگر دانلود نشد،
    ``None`` برمی‌گرداند و ``run_auto_sync`` به فایل تنظیم‌شده برمی‌گردد.
    """
    creds = store.load_isaco()
    if not (creds.scus and creds.username and creds.password):
        return None
    global _downloading
    if _downloading:
        # محافظ دوم (قفل اصلی sync_gate است): دو دانلود روی یک پروفایل
        # مرورگر هم‌زمان هرگز نباید شروع شود
        _log.warning("دانلود ایساکو در حال انجام است؛ درخواست دوم رد شد.")
        return None
    _downloading = True
    try:
        return _download_isaco(db, creds, on_progress)
    finally:
        _downloading = False


_downloading = False


def _download_isaco(db: Database, creds, on_progress) -> str | None:
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
        db.set_setting("isaco_downloaded_at", time.time())
        _log.info("دانلود خودکار ایساکو موفق: %s (%s قلم)", final, len(items))
        try:
            diff = record_isaco_diff(db, items, folder)
            _log.info("لیست ایساکو نسبت به دانلود قبلی: %s قلم تغییر قیمت، %s جدید، %s حذف",
                      diff["changed"], diff["added"], diff["removed"])
            if not diff.get("first"):
                db.log("info", f"لیست ایساکو دانلود شد ({len(items):,} قلم): "
                               f"{diff['changed']:,} قلم تغییر قیمت نسبت به دانلود قبلی.")
        except Exception:  # noqa: BLE001 - فقط گزارش است
            _log.warning("مقایسهٔ لیست ایساکو با قبلی نشد", exc_info=True)
        return str(final)
    except Exception as exc:  # noqa: BLE001 - هرگز نباید سینک را متوقف کند
        _log.warning("دانلود خودکار ایساکو نشد (لیست قبلی حفظ شد): %s", exc,
                     exc_info=True)
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def _fingerprint(items: dict) -> dict[str, str]:
    """اثر قیمت هر کالا (خرده/با ارزش افزوده/عمده) برای مقایسه با دانلود بعدی."""
    return {code: f"{i.retail}|{i.vat}|{i.wholesale}" for code, i in items.items()}


def record_isaco_diff(db: Database, items: dict, folder: Path | None = None) -> dict:
    """لیست تازهٔ ایساکو را با دانلود قبلی مقایسه و نتیجه را ذخیره می‌کند.

    تا بشود به کارفرما گفت «امروز ایساکو N قلم را تغییر قیمت داده» و اگر سینک
    تغییری پیدا نکرد، معلوم باشد که چرا (مثلاً سینک خودکار قبلاً اعمال کرده).
    """
    import json

    folder = folder or isaco_dir()
    fp_file = folder / "isaco_prices.json"
    new = _fingerprint(items)
    old: dict[str, str] | None = None
    if fp_file.is_file():
        try:
            old = json.loads(fp_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = None
    if old is None:
        diff = {"at": time.time(), "first": True, "changed": 0, "added": 0,
                "removed": 0, "codes": []}
    else:
        changed = sorted(c for c, v in new.items() if c in old and old[c] != v)
        diff = {
            "at": time.time(),
            "first": False,
            "changed": len(changed),
            "added": sum(1 for c in new if c not in old),
            "removed": sum(1 for c in old if c not in new),
            "codes": changed[:20000],
        }
        # تغییرهای قبلیِ همان روز گم نشوند: اگر دانلود دوم امروز است، تجمیع
        prev = db.get_setting("isaco_diff", None) or {}
        if prev and not prev.get("first") and _same_day(prev.get("at"), diff["at"]):
            merged = sorted(set(prev.get("codes", [])) | set(changed))
            diff["today_codes"] = merged[:20000]
        else:
            diff["today_codes"] = changed[:20000]
    tmp = fp_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(new), encoding="utf-8")
    os.replace(tmp, fp_file)
    db.set_setting("isaco_diff", diff)
    return diff


def _same_day(a, b) -> bool:
    import datetime as _dt
    try:
        return _dt.date.fromtimestamp(float(a)) == _dt.date.fromtimestamp(float(b))
    except (TypeError, ValueError, OSError):
        return False


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
        code_map=db.get_code_map(),
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


def isaco_freshness(db: Database, site_skus: set[str], pending_codes: set[str],
                    *, downloaded_now: bool, now: float | None = None) -> tuple[str, bool]:
    """یک خط توضیح دربارهٔ لیست ایساکوی استفاده‌شده در سینک.

    :param site_skus: کدهای نرمال‌شدهٔ محصولات سایت
    :param pending_codes: کدهایی که همین الان تغییر قیمتِ اعمال‌نشده دارند
    :returns: ``(متن، هشدار است؟)`` — هشدار یعنی لیست تازه نیست.
    """
    import datetime as _dt

    from .jalali import format_datetime

    now = now or time.time()
    at = db.get_setting("isaco_downloaded_at", None)
    if not at:
        return "لیست ایساکو: زمان دانلود نامعلوم (فایل دستی یا قدیمی).", True
    when = format_datetime(_dt.datetime.fromtimestamp(float(at)))
    stale = not downloaded_now
    text = (f"لیست ایساکو: دانلود {when}." if not stale else
            f"⚠️ دانلود لیست تازهٔ ایساکو این بار نشد؛ مقایسه با لیست قبلی "
            f"(دانلود {when}) انجام شد.")
    diff = db.get_setting("isaco_diff", None) or {}
    if diff and not diff.get("first") and _same_day(diff.get("at"), now):
        codes = set(diff.get("today_codes") or diff.get("codes") or [])
        on_site = codes & site_skus
        waiting = on_site & pending_codes
        text += (f"  امروز ایساکو قیمت {len(codes):,} قلم را عوض کرده؛ "
                 f"{len(on_site):,} قلم آن روی سایت شماست: "
                 f"{len(waiting):,} قلم منتظر اعمال، "
                 f"{len(on_site) - len(waiting):,} قلم قبلاً اعمال شده.")
    elif diff.get("first"):
        text += "  (اولین دانلود؛ از دانلود بعدی تغییرات روزانهٔ ایساکو هم گزارش می‌شود.)"
    elif diff:
        text += "  امروز هنوز تغییری نسبت به لیست دیروز ثبت نشده."
    fa_digits = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬")
    return text.translate(fa_digits), stale
