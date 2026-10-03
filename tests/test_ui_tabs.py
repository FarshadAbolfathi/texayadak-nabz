"""تست دودِ (smoke) تب‌های جدید با دادهٔ جعلی و بدون شبکه."""

from __future__ import annotations

from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from nabz.config import CredentialStore, MemoryBackend, WooCredentials
from nabz.db import Database
from nabz.new_products import NewProduct
from nabz.targets.woocommerce import WooCategory, WooProduct


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
    """پنجره‌های پیام در تست بلافاصله «بله» برمی‌گردانند."""
    yes = QMessageBox.StandardButton.Yes
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: yes))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: yes))


@pytest.fixture
def captured(monkeypatch):
    """run_async را جایگزین می‌کند تا کار پس‌زمینه ضبط شود نه اجرا."""
    calls = []

    def fake(owner, func, *args, on_done=None, on_failed=None, **kwargs):
        calls.append({"func": func, "args": args, "on_done": on_done})

    for mod in ("products", "new_products", "orders"):
        monkeypatch.setattr(f"nabz.ui.tabs.{mod}.run_async", fake)
    return calls


CATS = [WooCategory(1, "پژو"), WooCategory(2, "پژو ۴۰۵", parent=1)]


def woo_product(pid, **kw):
    base = dict(id=pid, name=f"محصول {pid}", sku=f"00501026{pid:02d}",
                regular_price="1000000", stock_quantity=2, stock_status="instock",
                manage_stock=True, type="simple", status="publish",
                categories=((1, "پژو"),), image_url="", gallery_ids=(77,))
    base.update(kw)
    return WooProduct(**base)


class TestScheduleTab:
    def test_add_save_and_reload_entries(self, qapp, db):
        from nabz.ui.tabs.schedule import ScheduleTab
        tab = ScheduleTab(db)
        assert len(tab.entries()) == 1           # پیش‌فرض ۰۳:۰۰
        tab._add_row(tab._suggest_next_entry())
        tab.enabled.setChecked(True)
        tab._save()
        saved = db.get_setting("schedule_entries")
        assert [e["time"] for e in saved] == ["03:00", "06:00"]
        assert db.get_setting("schedule_enabled") is True
        again = ScheduleTab(db)
        assert [e.hhmm for e in again.entries()] == ["03:00", "06:00"]

    def test_duplicate_times_are_rejected(self, qapp, db):
        from nabz.scheduler import ScheduleEntry
        from nabz.ui.tabs.schedule import ScheduleTab
        tab = ScheduleTab(db)
        tab._add_row(ScheduleEntry(3, 0))
        tab._save()
        assert db.get_setting("schedule_entries") is None


class TestProductsTab:
    def make(self, db, store):
        from nabz.ui.tabs.products import ProductsTab
        tab = ProductsTab(db, store)
        tab._on_loaded(([woo_product(1), woo_product(2, stock_quantity=None,
                                                    manage_stock=False)], CATS))
        return tab

    def test_edits_become_payload(self, qapp, db, store, captured):
        tab = self.make(db, store)
        assert not tab.save_btn.isEnabled()
        tab.table.item(0, tab.COL_PRICE).setText("۱۲۰۰۰۰۰")   # ارقام فارسی
        tab.table.item(0, tab.COL_NAME).setText("نام جدید")
        tab.table.item(1, tab.COL_STOCK).setText("5")
        tab._set_row_categories(0, [2, 1])
        tab._img_changes[1] = ("url", "https://x/new.jpg")
        assert tab.table.item(0, tab.COL_PRICE).text() == "1200000"
        assert tab.save_btn.isEnabled()

        tab._save()
        (call,) = captured
        updates, uploads = call["args"][1], call["args"][2]
        by_id = {u["id"]: u for u in updates}
        assert by_id[1]["regular_price"] == "1200000"
        assert by_id[1]["name"] == "نام جدید"
        assert by_id[1]["categories"] == [{"id": 2}, {"id": 1}]
        assert by_id[1]["images"] == [{"src": "https://x/new.jpg"}, {"id": 77}]
        assert by_id[2]["stock_quantity"] == 5 and by_id[2]["manage_stock"] is True
        assert uploads == {}
        # snapshot برای رول‌بک قیمت/موجودی
        assert {s.product_id for s in tab._pending_snapshots} == {1, 2}

    def test_sale_price_must_be_lower(self, qapp, db, store, captured):
        tab = self.make(db, store)
        tab.table.item(0, tab.COL_SALE).setText("2000000")
        tab._save()
        assert captured == []

    def test_filters(self, qapp, db, store):
        tab = self.make(db, store)
        tab.search.setText("محصول 2")
        assert tab.table.isRowHidden(0) and not tab.table.isRowHidden(1)
        tab.search.setText("")
        tab.cat_filter.setCurrentIndex(tab.cat_filter.findData(2))
        assert tab.table.isRowHidden(0) and tab.table.isRowHidden(1)

    def test_status_combo_values(self, qapp, db, store):
        tab = self.make(db, store)
        tab._bulk_set([0], tab.COL_STATUS, "draft", "پیش‌نویس")
        assert tab._row_payload(0) == {"status": "draft"}


class TestNewProductsTab:
    def candidates(self):
        return [
            NewProduct("0050102699", "سپر عقب ۴۰۵", 5, 2, 1_500_000, "ایساکو",
                       category_ids=[2, 1]),
            NewProduct("0000012345", "پیچ", 3, 2, None),
        ]

    def test_compare_result_and_send(self, qapp, db, store, captured):
        from nabz.ui.tabs.new_products import NewProductsTab
        db.set_setting("new_products_pending", ["0050102699", "0000012345"])
        db.set_setting("new_products_unread", True)
        db.set_setting("new_products_criteria", "stock")
        tab = NewProductsTab(db, store)
        assert tab.unread_count() == 2
        tab._on_compared({"candidates": self.candidates(), "categories": CATS,
                          "haseb_count": 10, "site_count": 8, "isaco": True})
        assert tab.table.rowCount() == 2
        assert "پژو ۴۰۵" in tab.table.item(0, tab.COL_CATS).text()

        tab.table.item(1, tab.COL_PRICE).setText("25000")
        assert tab._candidates[1].price == 25000
        assert tab._candidates[1].price_source == "دستی"

        tab._send()
        (call,) = captured
        payloads = call["args"][1]
        assert [p["sku"] for p in payloads] == ["0050102699", "0000012345"]
        assert payloads[1]["regular_price"] == "25000"

        call["on_done"](({0: 501}, {1: "SKU تکراری"}))
        assert tab.table.rowCount() == 1
        assert db.get_setting("new_products_pending") == ["0000012345"]
        assert db.recent_runs()[0]["mode"] == "create"

    def test_ignore_removes_rows(self, qapp, db, store):
        from nabz.ui.tabs.new_products import NewProductsTab
        db.set_setting("new_products_criteria", "stock")
        tab = NewProductsTab(db, store)
        tab._on_compared({"candidates": self.candidates(), "categories": CATS,
                          "haseb_count": 2, "site_count": 0, "isaco": False})
        tab.table.item(0, tab.COL_CHECK).setCheckState(Qt.CheckState.Unchecked)
        tab._ignore_selected()
        assert db.get_setting("new_products_ignored") == ["0000012345"]
        assert tab.table.rowCount() == 1

    def test_criteria_radio_filters_without_recompare(self, qapp, db, store, captured):
        from nabz.ui.tabs.new_products import NewProductsTab
        cands = self.candidates() + [
            NewProduct("0000099999", "فقط قیمت", 0, 0, 90_000, "ایساکو")]
        tab = NewProductsTab(db, store)
        assert tab.criteria() == "both"                     # پیش‌فرض: هر دو شرط
        tab._on_compared({"candidates": cands, "categories": CATS,
                          "haseb_count": 3, "site_count": 0, "isaco": True})
        visible = lambda: [tab._candidates[r].code for r in range(tab.table.rowCount())
                           if not tab.table.isRowHidden(r)]
        assert visible() == ["0050102699"]
        assert "(۱)" in tab.criteria_buttons["both"].text()
        assert "(۲)" in tab.criteria_buttons["stock"].text()

        tab.criteria_buttons["price"].setChecked(True)
        assert visible() == ["0050102699", "0000099999"]
        assert db.get_setting("new_products_criteria") == "price"
        assert db.get_setting("new_products_pending") == ["0050102699", "0000099999"]

        tab.criteria_buttons["stock"].setChecked(True)
        assert visible() == ["0050102699", "0000012345"]
        # ارسال فقط ردیف‌های قابل‌مشاهدهٔ تیک‌خورده
        tab._send()
        payloads = captured[-1]["args"][1]
        assert [p["sku"] for p in payloads] == ["0050102699", "0000012345"]

        # جستجو با شرط ترکیب می‌شود
        tab.search.setText("پیچ")
        assert visible() == ["0000012345"]

    def test_columns_resizable_and_remembered(self, qapp, db, store):
        from PySide6.QtWidgets import QHeaderView
        from nabz.ui.tabs.new_products import NewProductsTab
        tab = NewProductsTab(db, store)
        head = tab.table.horizontalHeader()
        assert head.sectionResizeMode(tab.COL_NAME) == QHeaderView.ResizeMode.Interactive
        assert tab.table.columnWidth(tab.COL_NAME) >= 400
        tab.table.setColumnWidth(tab.COL_NAME, 555)
        db.set_setting("cols_new_products",
                       [tab.table.columnWidth(c) for c in range(tab.table.columnCount())])
        again = NewProductsTab(db, store)
        assert again.table.columnWidth(again.COL_NAME) == 555


ORDER = {
    "id": 9, "number": "9", "status": "processing", "currency": "IRT",
    "date_created": "2026-09-30T10:15:00", "total": "500000",
    "billing": {"first_name": "علی", "phone": "0912"}, "shipping": {},
    "line_items": [{"name": "سپر", "sku": "1", "quantity": 1, "total": "500000"}],
    "payment_method_title": "کارت",
}


class TestOrdersTab:
    def test_list_detail_and_pdf(self, qapp, db, store, captured, tmp_path, monkeypatch):
        from nabz.ui.tabs.orders import OrdersTab
        tab = OrdersTab(db, store)
        tab._on_loaded(([ORDER], 1, 1,
                        [{"slug": "processing", "name": "Processing", "total": 1},
                         {"slug": "shipped", "name": "ارسال شده", "total": 0}]), 1)
        assert tab.table.rowCount() == 1
        assert tab.table.item(0, tab.COL_DATE).text() == "۱۴۰۵/۰۷/۰۸  ۱۰:۱۵"
        assert tab.status_filter.findData("shipped") > 0
        tab.table.selectRow(0)
        assert tab._order["id"] == 9
        assert "علی" in tab.detail.toPlainText()

        pdf = tmp_path / "f.pdf"
        monkeypatch.setattr("nabz.ui.tabs.orders.QFileDialog.getSaveFileName",
                            staticmethod(lambda *a, **k: (str(pdf), "")))
        monkeypatch.setattr("nabz.ui.tabs.orders.QDesktopServices.openUrl",
                            staticmethod(lambda *a: True))
        tab._save_pdf()
        assert pdf.read_bytes().startswith(b"%PDF")

        tab.new_status.setCurrentIndex(tab.new_status.findData("completed"))
        tab._save_status()
        assert captured[-1]["args"][1:3] == (9, "completed")


def test_copy_helper(qapp):
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
    from nabz.ui.widgets import selected_text
    t = QTableWidget(2, 2)
    for r in range(2):
        for c in range(2):
            t.setItem(r, c, QTableWidgetItem(f"{r}{c}"))
    t.selectAll()
    assert selected_text(t) == "00\t01\n10\t11"
