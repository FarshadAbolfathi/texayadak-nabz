"""تست اجرای سینک بدون رابط (auto sync)."""

from decimal import Decimal

import pytest

from nabz.config import (
    CredentialStore,
    IsacoCredentialsConfig,
    MemoryBackend,
    WooCredentials,
)
from nabz.db import Database
from nabz.jobs import run_auto_sync, try_auto_download_isaco
from nabz.targets.woocommerce import BatchOutcome, WooClient, WooProduct
from tests.conftest import write_dbf, CAL_FIELDS


class FakeWoo(WooClient):
    def __init__(self, products):
        self._products = products
        self.updates = []

    def fetch_products(self, status="any"):
        return self._products

    def batch_update(self, updates):
        self.updates = updates
        out = BatchOutcome()
        out.updated = [u["id"] for u in updates]
        return out


def woo_product(pid, sku, price="", stock=3):
    return WooProduct(id=pid, name=f"م{pid}", sku=sku, regular_price=price,
                      stock_quantity=stock, stock_status="instock",
                      manage_stock=True, type="simple", status="publish")


@pytest.fixture
def db():
    d = Database(":memory:")
    d.set_setting("markup_percent", 15)
    d.set_setting("max_change_percent", 0)
    d.set_setting("max_on_site", 2)
    yield d
    d.close()


@pytest.fixture
def store():
    s = CredentialStore(backend=MemoryBackend())
    s.save_woo(WooCredentials(base_url="https://x.com",
                              consumer_key="ck", consumer_secret="cs"))
    return s


def make_isaco_xlsx(path):
    from openpyxl import Workbook
    from nabz.sources.isaco_excel import EXPECTED_HEADERS
    wb = Workbook()
    ws = wb.active
    ws.title = "لیست قیمت"
    ws.append(list(EXPECTED_HEADERS))
    # 1200 ردیف برای عبور از محافظ حجم
    for i in range(1200):
        code = f"{5010269900 + i:010d}"
        ws.append([code, "کالا", "پژو", "عدد", 1, 56000000, 68992000, 50000000])
    wb.save(path)
    return path


class TestNoSources:
    def test_no_source_configured(self, db, store):
        result = run_auto_sync(db, store, woo=FakeWoo([]))
        assert not result.ok
        assert "منبعی" in result.message


class TestPriceSync:
    def test_price_sync_from_isaco(self, db, store, tmp_path):
        path = make_isaco_xlsx(tmp_path / "p.xlsx")
        db.set_setting("isaco_excel_path", str(path))
        db.set_setting("schedule_stock", False)

        woo = FakeWoo([woo_product(1, "5010269900", price="1000000")])
        result = run_auto_sync(db, store, woo=woo)
        assert result.ok
        assert result.apply_result.applied_count == 1
        # قیمت جدید: 68,992,000 ÷ 10 × 1.15 = 7,934,080 → رند 1000 = 7,934,000
        assert woo.updates[0]["regular_price"] == "7934000"


class TestStockSync:
    def test_stock_sync_from_haseb(self, db, store, tmp_path):
        rows = [{"COD": "5010269900", "NAME": "کالا", "COD_ANB": "1",
                 "NAME_ANB": "ا", "MOJ": "50.00000", "GH_FO": "0"}]
        cal = write_dbf(tmp_path / "cal.DBF", CAL_FIELDS, rows)
        db.set_setting("haseb_cal_path", str(cal))
        db.set_setting("schedule_price", False)

        woo = FakeWoo([woo_product(1, "5010269900", stock=10)])
        result = run_auto_sync(db, store, woo=woo)
        assert result.ok
        # سقف موجودی ۲ اعمال می‌شود
        assert woo.updates[0]["stock_quantity"] == 2


class TestNoWoo:
    def test_missing_woo_credentials(self, db):
        empty_store = CredentialStore(backend=MemoryBackend())
        result = run_auto_sync(db, empty_store)
        assert not result.ok
        assert "ووکامرس" in result.message


class TestAutoDownload:
    """این توابع باید روی نخ اصلی Qt فراخوانی شوند (QWebEngineView)؛
    اینجا فقط منطقِ فراخوانی/فالبک تست می‌شود، بدون تماس شبکه‌ای واقعی."""

    def test_no_isaco_credentials_returns_none_without_import(self, db):
        empty_store = CredentialStore(backend=MemoryBackend())
        # نباید حتی سعی کند isaco_browser را import کند
        assert try_auto_download_isaco(db, empty_store) is None

    def test_download_failure_returns_none_and_does_not_raise(self, db, monkeypatch):
        store = CredentialStore(backend=MemoryBackend())
        store.save_isaco(IsacoCredentialsConfig(
            scus="1", username="2", password="3"))

        class BoomDownloader:
            def __init__(self, *a, **k):
                pass

            def download(self, dest, timeout_s=240):
                raise RuntimeError("شبکه در دسترس نیست")

        monkeypatch.setattr(
            "nabz.sources.isaco_browser.IsacoDownloader", BoomDownloader
        )
        assert try_auto_download_isaco(db, store) is None
        # تنظیمات نباید با مسیر نامعتبر خراب شده باشد
        assert db.get_setting("isaco_excel_path") is None

    def test_successful_download_saves_path_setting(self, db, monkeypatch, tmp_path):
        store = CredentialStore(backend=MemoryBackend())
        store.save_isaco(IsacoCredentialsConfig(
            scus="1", username="2", password="3"))
        fake_file = tmp_path / "downloaded.xlsx"
        fake_file.write_bytes(b"fake")

        class FakeDownloader:
            def __init__(self, *a, **k):
                pass

            def download(self, dest, timeout_s=240):
                return str(fake_file)

        monkeypatch.setattr(
            "nabz.sources.isaco_browser.IsacoDownloader", FakeDownloader
        )
        result = try_auto_download_isaco(db, store)
        assert result == str(fake_file)
        assert db.get_setting("isaco_excel_path") == str(fake_file)

    def test_progress_callback_is_forwarded(self, db, monkeypatch):
        store = CredentialStore(backend=MemoryBackend())
        store.save_isaco(IsacoCredentialsConfig(
            scus="1", username="2", password="3"))
        seen = []

        class FakeDownloader:
            def __init__(self, scus, username, password, on_progress=None):
                self.on_progress = on_progress

            def download(self, dest, timeout_s=240):
                self.on_progress("در حال کار ...")
                return dest

        monkeypatch.setattr(
            "nabz.sources.isaco_browser.IsacoDownloader", FakeDownloader
        )
        try_auto_download_isaco(db, store, on_progress=seen.append)
        assert seen == ["در حال کار ..."]


class TestAutoSyncMode:
    """اگر منبعی تنظیم نشده باشد run_auto_sync زودتر برمی‌گردد، پس برای
    رسیدن به apply_plan (و ثبت run) باید حداقل یک منبع بدهیم."""

    def _with_haseb_source(self, db, tmp_path):
        rows = [{"COD": "5010269900", "NAME": "کالا", "COD_ANB": "1",
                 "NAME_ANB": "ا", "MOJ": "5.00000", "GH_FO": "0"}]
        cal = write_dbf(tmp_path / "cal.DBF", CAL_FIELDS, rows)
        db.set_setting("haseb_cal_path", str(cal))
        db.set_setting("schedule_price", False)

    def test_mode_is_recorded_on_run(self, db, store, tmp_path):
        self._with_haseb_source(db, tmp_path)
        woo = FakeWoo([woo_product(1, "5010269900", stock=1)])
        run_auto_sync(db, store, woo=woo, mode="auto")
        assert db.recent_runs(limit=1)[0]["mode"] == "auto"

    def test_manual_mode_is_recorded(self, db, store, tmp_path):
        self._with_haseb_source(db, tmp_path)
        woo = FakeWoo([woo_product(1, "5010269900", stock=1)])
        run_auto_sync(db, store, woo=woo, mode="manual")
        assert db.recent_runs(limit=1)[0]["mode"] == "manual"


class TestNewProductsNotice:
    def test_sync_reports_haseb_items_missing_on_site(self, db, store, tmp_path):
        rows = [
            {"COD": "5010269900", "NAME": "روی سایت", "COD_ANB": "1",
             "NAME_ANB": "ا", "MOJ": "5", "GH_FO": "0"},
            {"COD": "5010269911", "NAME": "جدید", "COD_ANB": "1",
             "NAME_ANB": "ا", "MOJ": "3", "GH_FO": "0"},
            {"COD": "5010269922", "NAME": "بدون موجودی", "COD_ANB": "1",
             "NAME_ANB": "ا", "MOJ": "0", "GH_FO": "0"},
        ]
        cal = write_dbf(tmp_path / "cal.DBF", CAL_FIELDS, rows)
        db.set_setting("haseb_cal_path", str(cal))
        db.set_setting("schedule_price", False)
        woo = FakeWoo([woo_product(1, "5010269900", stock=10)])

        result = run_auto_sync(db, store, woo=woo)
        assert result.ok
        assert result.missing_on_site == 1 and result.newly_missing == 1
        assert db.get_setting("new_products_pending") == ["5010269911"]
        assert db.get_setting("new_products_unread") is True
        assert "کالای جدید" in result.message

        # اجرای دوم: همان کالا دیگر «تازه» نیست
        again = run_auto_sync(db, store, woo=woo)
        assert again.missing_on_site == 1 and again.newly_missing == 0

    def test_sync_never_creates_products(self, db, store, tmp_path):
        rows = [{"COD": "5010269911", "NAME": "جدید", "COD_ANB": "1",
                 "NAME_ANB": "ا", "MOJ": "3", "GH_FO": "0"}]
        db.set_setting("haseb_cal_path", str(write_dbf(tmp_path / "c.DBF", CAL_FIELDS, rows)))

        class NoCreateWoo(FakeWoo):
            def batch_create(self, products):
                raise AssertionError("سینک خودکار نباید محصول بسازد")

        result = run_auto_sync(db, store, woo=NoCreateWoo([]))
        assert result.newly_missing == 1

    def test_schedule_entry_can_limit_to_stock(self, db, store, tmp_path):
        path = make_isaco_xlsx(tmp_path / "p.xlsx")
        db.set_setting("isaco_excel_path", str(path))
        woo = FakeWoo([woo_product(1, "5010269900", price="1000000")])
        result = run_auto_sync(db, store, woo=woo, update_price=False)
        # قیمت خاموش و حاسبی هم نیست → منبعی برای سینک نیست
        assert not result.ok
