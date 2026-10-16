"""جدول کامل سینک (همهٔ محصولات سایت با وضعیت) و پاک کردن گزارش‌ها/لاگ.

درخواست کارفرما: بعد از «دریافت و مقایسه» جدول خالی با «تغییرات ۰» این حس را
می‌داد که مقایسه انجام نشده؛ حالا همهٔ محصولات با وضعیتشان دیده می‌شوند.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from nabz.config import CredentialStore, MemoryBackend, WooCredentials
from nabz.db import Database, Snapshot
from nabz.engine import build_plan
from nabz.pricing import PriceRules, compute as compute_price
from nabz.sources.isaco_excel import IsacoItem
from nabz.stock import StockRules
from nabz.targets.woocommerce import WooProduct

RULES = PriceRules(markup_percent=Decimal("10"))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def store():
    s = CredentialStore(backend=MemoryBackend())
    s.save_woo(WooCredentials(base_url="https://x.com", consumer_key="ck",
                              consumer_secret="cs"))
    return s


@pytest.fixture(autouse=True)
def no_dialogs(monkeypatch):
    yes = QMessageBox.StandardButton.Yes
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: yes))


def isaco(code, vat):
    return IsacoItem(code, "x", "", "عدد", 1, retail=vat, vat=vat, wholesale=vat)


def woo(pid, sku, price, kind="simple"):
    return WooProduct(id=pid, name=f"محصول {pid}", sku=sku, regular_price=price,
                      stock_quantity=1, stock_status="instock", manage_stock=True,
                      type=kind, status="publish")


def site_price(vat) -> str:
    return str(compute_price(isaco_retail=vat, isaco_vat=vat, isaco_wholesale=vat,
                             rules=RULES).price)


def make_plan():
    lst = {
        "0000000001": isaco("0000000001", 10_000_000),   # تغییر
        "0000000002": isaco("0000000002", 20_000_000),   # بدون تغییر
        "0000000005": isaco("0000000005", 30_000_000),   # قیمت سایت خالی
        "0000000006": isaco("0000000006", 90_000_000),   # تغییر خیلی بزرگ → بررسی
        "0000000007": isaco("0000000007", 40_000_000),   # محصول متغیر بی‌قیمت
    }
    products = [
        woo(1, "0000000001", "900000"),
        woo(2, "0000000002", site_price(20_000_000)),
        woo(3, "0000000003", "500000"),                  # در ایساکو نیست
        woo(4, "", "700000"),                            # کد ندارد
        woo(5, "0000000005", ""),                        # ساده و بی‌قیمت → قیمت‌گذاری
        woo(6, "0000000006", "1000000"),
        woo(7, "0000000007", "", kind="variable"),       # قیمت روی حالت‌هاست
    ]
    return build_plan(products=products, isaco=lst, haseb={}, price_rules=RULES,
                      stock_rules=StockRules(), update_price=True, update_stock=False)


def test_row_kind_classification():
    from nabz.ui.tabs.sync import row_kind
    kinds = {i.product_id: row_kind(i) for i in make_plan().items}
    assert kinds == {1: "change", 2: "same", 3: "no_isaco", 4: "other",
                     5: "change", 6: "review", 7: "other"}


@pytest.fixture
def tab(qapp, db, store):
    from nabz.ui.tabs.sync import SyncTab
    t = SyncTab(db, store)
    t._on_compared((make_plan(), True, False, 0))
    return t


def visible_ids(tab):
    return sorted(tab._row_items[r].product_id for r in range(tab.table.rowCount())
                  if not tab.table.isRowHidden(r))


class TestFullList:
    def test_all_site_products_are_listed(self, tab):
        assert tab.table.rowCount() == 7
        assert "۷ محصول سایت بررسی شد" in tab.status.text()

    def test_default_filter_shows_changes_and_counts(self, tab):
        assert tab.current_kind() == "change"
        assert visible_ids(tab) == [1, 5, 6]
        assert "(۱)" in tab.kind_buttons["same"].text()
        assert "(۷)" in tab.kind_buttons["all"].text()

    def test_filters(self, tab):
        tab.kind_buttons["same"].setChecked(True)
        assert visible_ids(tab) == [2]
        tab.kind_buttons["no_isaco"].setChecked(True)
        assert visible_ids(tab) == [3]
        tab.kind_buttons["all"].setChecked(True)
        assert visible_ids(tab) == [1, 2, 3, 4, 5, 6, 7]
        tab.search.setText("محصول 2")
        assert visible_ids(tab) == [2]

    def test_status_column_explains_each_row(self, tab):
        texts = {tab._row_items[r].product_id: tab.table.item(r, tab.COL_STATUS).text()
                 for r in range(tab.table.rowCount())}
        assert "بدون تغییر" in texts[2]
        assert "تغییر قیمت" in texts[1]
        assert "ایساکو نیست" in texts[3]
        assert "کد" in texts[4]
        assert "قیمت‌گذاری" in texts[5] and "نداشت" in texts[5]
        assert "متغیر" in texts[7]
        assert "بررسی" in texts[6]

    def test_no_changes_shows_whole_list(self, qapp, db, store):
        from nabz.ui.tabs.sync import SyncTab
        plan = make_plan()
        plan.items[:] = [i for i in plan.items if i.product_id in (2, 3)]
        t = SyncTab(db, store)
        t._on_compared((plan, True, False, 0))
        assert t.current_kind() == "all" and visible_ids(t) == [2, 3]
        assert not t.apply_btn.isEnabled()

    def test_apply_buttons_only_on_actionable_rows(self, tab):
        def ids(word):
            return sorted(tab._row_items[r].product_id for r in range(tab.table.rowCount())
                          if (w := tab.table.cellWidget(r, tab.COL_APPLY)) is not None
                          and word in w.text())
        assert ids("اعمال") == [1, 5, 6]
        assert ids("تطبیق") == [3]          # «در ایساکو نیست» → دکمهٔ تطبیق


class TestApplySafety:
    def ids_to_apply(self, tab):
        updates, _ = tab._collect_rows(tab.rows_to_apply())
        return sorted(u["id"] for u in updates)

    def test_apply_all_sends_only_real_changes(self, tab):
        # بدون تغییر، محصول متغیر، بدون کد و «در ایساکو نیست» ارسال نمی‌شوند؛
        # محصول ساده‌ای که روی سایت قیمت نداشت قیمت می‌گیرد
        assert self.ids_to_apply(tab) == [1, 5, 6]

    def test_filter_does_not_change_what_is_applied(self, tab):
        tab.kind_buttons["same"].setChecked(True)
        assert self.ids_to_apply(tab) == [1, 5, 6]

    def test_manual_edit_of_unchanged_row_is_applied(self, tab):
        r = next(r for r, i in enumerate(tab._row_items) if i.product_id == 2)
        tab.table.item(r, tab.COL_NEW_PRICE).setText("1234000")
        assert "ویرایش دستی" in tab.table.item(r, tab.COL_STATUS).text()
        assert tab.table.cellWidget(r, tab.COL_APPLY) is not None
        assert self.ids_to_apply(tab) == [1, 2, 5, 6]

    def test_empty_price_rollback_clears_price_again(self, tab):
        r = next(r for r, i in enumerate(tab._row_items) if i.product_id == 5)
        updates, snaps = tab._collect_rows([r])
        assert updates[0]["regular_price"]
        assert snaps[0].old_price == ""
        assert snaps[0].to_woo_revert()["regular_price"] == ""      # دوباره خالی

    def test_stock_only_change_never_clears_price_on_rollback(self, tab):
        r = next(r for r, i in enumerate(tab._row_items) if i.product_id == 2)
        tab.table.item(r, tab.COL_NEW_STOCK).setText("5")
        _, snaps = tab._collect_rows([r])
        # قیمت قبلی (همان مقدار) برمی‌گردد، هرگز خالی نمی‌شود
        assert snaps[0].to_woo_revert().get("regular_price") == "2200000"


class TestClearHistory:
    def test_keeps_last_applied_run_for_rollback(self, db):
        old = db.start_run("auto")
        db.finish_run(old, "done", {})
        applied = db.start_run("manual")
        db.record_snapshot(applied, Snapshot(product_id=1, sku="1", old_price="10",
                                             new_price="20", old_stock=1, applied=True))
        db.finish_run(applied, "done", {})
        db.log("info", "سلام")
        last = db.last_applied_run()
        assert last == applied

        runs, logs = db.clear_history()
        assert logs >= 1 and db.recent_logs() == []
        remaining = [r["id"] for r in db.recent_runs()]
        assert remaining == [last]
        assert db.rollback_data(last)            # بازگرداندن هنوز ممکن است

    def test_full_clear(self, db):
        rid = db.start_run("auto")
        db.finish_run(rid, "done", {})
        db.clear_history(keep_rollback=False)
        assert db.recent_runs() == []

    def test_reports_tab_button(self, qapp, db):
        from nabz.ui.tabs.reports import ReportsTab
        db.log("info", "x")
        t = ReportsTab(db)
        assert t.logs.rowCount() == 1
        t.clear_btn.click()
        assert t.logs.rowCount() == 0


class TestClearLogs:
    def test_truncates_logs_and_crash_file(self, tmp_path, monkeypatch):
        import logging
        from logging.handlers import RotatingFileHandler

        from nabz import logging_setup
        monkeypatch.setattr(logging_setup, "log_dir", lambda: tmp_path)
        main = tmp_path / logging_setup.LOG_FILE_NAME
        handler = RotatingFileHandler(main, encoding="utf-8")
        logger = logging.getLogger("nabz")
        logger.addHandler(handler)
        try:
            logger.warning("خط قدیمی " * 50)
            (tmp_path / "nabz.log.1").write_text("old" * 100)
            (tmp_path / logging_setup.CRASH_FILE_NAME).write_text("crash" * 10)
            monkeypatch.setattr(logging_setup, "_crash_file", None)

            freed = logging_setup.clear_logs()
            assert freed > 300
            assert not (tmp_path / "nabz.log.1").exists()
            assert (tmp_path / logging_setup.CRASH_FILE_NAME).read_text() == ""
            handler.flush()
            assert "خط قدیمی" not in main.read_text(encoding="utf-8")
            logger.warning("خط جدید")            # نوشتن ادامه دارد
            handler.flush()
            assert "خط جدید" in main.read_text(encoding="utf-8")
        finally:
            logger.removeHandler(handler)
            handler.close()
