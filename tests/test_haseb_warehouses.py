"""انتخاب انبار حاسب و گزارش خطای لیست ایساکو در تب «محصولات جدید حاسب»."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from nabz.config import CredentialStore, MemoryBackend, WooCredentials
from nabz.db import Database
from nabz.sources.haseb_dbf import list_warehouses, load_products
from nabz.targets.woocommerce import WooClient, WooProduct
from tests.conftest import CAL_FIELDS, write_dbf

ROWS = [
    {"COD": "5010269900", "NAME": "سپر", "COD_ANB": "1", "NAME_ANB": "انبار ايساكو",
     "MOJ": "3", "GH_FO": "2500000"},
    {"COD": "5010269911", "NAME": "چراغ", "COD_ANB": "1", "NAME_ANB": "انبار ايساكو",
     "MOJ": "0", "GH_FO": "2500000"},
    {"COD": "5010269922", "NAME": "لنت", "COD_ANB": "2", "NAME_ANB": "انبار متفرقه",
     "MOJ": "5", "GH_FO": "1000000"},
    {"COD": "5010269900", "NAME": "سپر", "COD_ANB": "2", "NAME_ANB": "انبار متفرقه",
     "MOJ": "2", "GH_FO": "2500000"},
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cal(tmp_path):
    return write_dbf(tmp_path / "cal.DBF", CAL_FIELDS, ROWS)


@pytest.fixture
def db(cal):
    d = Database(":memory:")
    d.set_setting("haseb_cal_path", str(cal))
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
    shown = []
    yes = QMessageBox.StandardButton.Yes
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: (shown.append((_n, a)), yes)[1]))
    return shown


class FakeWoo(WooClient):
    def __init__(self, products=()):
        self._products = list(products)

    def fetch_products(self, status="any"):
        return self._products

    def fetch_categories(self):
        return []


class TestListWarehouses:
    def test_reads_warehouses_with_counts_read_only(self, cal):
        before = cal.read_bytes()
        whs = list_warehouses(cal)
        assert [(w.id, w.name, w.items, w.in_stock) for w in whs] == [
            (1, "انبار ايساكو", 2, 1), (2, "انبار متفرقه", 2, 2)]
        assert cal.read_bytes() == before      # دیتابیس حاسب دست نخورد

    def test_filter_by_warehouse_sums_only_chosen(self, cal):
        only1 = load_products(cal, warehouses={1})
        assert only1["5010269900"].quantity == 3
        both = load_products(cal)
        assert both["5010269900"].quantity == 5


class TestWarehouseDialog:
    def test_all_checked_means_all(self, qapp, cal):
        from nabz.ui.tabs.new_products import WarehouseDialog
        dlg = WarehouseDialog(list_warehouses(cal), None)
        assert dlg.selected_ids() is None
        assert "انبار ایساکو" in dlg.list.item(0).text()   # ي/ك عربی → فارسی
        dlg.list.item(1).setCheckState(Qt.CheckState.Unchecked)
        assert dlg.selected_ids() == [1]

    def test_previous_selection_is_restored(self, qapp, cal):
        from nabz.ui.tabs.new_products import WarehouseDialog
        dlg = WarehouseDialog(list_warehouses(cal), [2])
        states = [dlg.list.item(i).checkState() for i in range(dlg.list.count())]
        assert states == [Qt.CheckState.Unchecked, Qt.CheckState.Checked]


class TestCompareWithWarehouses:
    def run_compare(self, db, store, monkeypatch, warehouses=None):
        from nabz.ui.tabs import new_products as mod
        monkeypatch.setattr(mod, "woo_client_from_store", lambda s: FakeWoo())
        return mod._compare(db, store, warehouses)

    def test_only_chosen_warehouse_is_compared(self, db, store, monkeypatch):
        db.set_setting("isaco_excel_path", "")
        res = self.run_compare(db, store, monkeypatch, [2])
        assert sorted(c.code for c in res["candidates"]) == ["5010269900", "5010269922"]
        res_all = self.run_compare(db, store, monkeypatch, None)
        assert len(res_all["candidates"]) == 3

    def test_missing_isaco_list_is_reported_not_silent(self, db, store, monkeypatch, tmp_path):
        db.set_setting("isaco_excel_path", str(tmp_path / "gone.xlsx"))
        res = self.run_compare(db, store, monkeypatch)
        assert "پیدا نشد" in res["isaco_error"]

    def test_corrupt_isaco_list_is_reported(self, db, store, monkeypatch, tmp_path):
        bad = tmp_path / "bad.xlsx"
        bad.write_bytes(b"PK\x03\x04 broken")
        db.set_setting("isaco_excel_path", str(bad))
        res = self.run_compare(db, store, monkeypatch)
        assert "خراب یا ناقص" in res["isaco_error"]

    def test_tab_warns_when_price_list_unreadable(self, qapp, db, store, no_dialogs):
        from nabz.new_products import NewProduct
        from nabz.ui.tabs.new_products import NewProductsTab
        tab = NewProductsTab(db, store)
        tab._on_compared({"candidates": [NewProduct("1", "x", 2, 2, None)],
                          "categories": [], "haseb_count": 1, "site_count": 0,
                          "isaco": False, "isaco_error": "فایل لیست قیمت ایساکو پیدا نشد"})
        assert any(kind == "warning" for kind, _ in no_dialogs)
        assert "⚠️" in tab.status.text()


class TestWarehouseButton:
    def test_label_and_persisted_choice(self, qapp, db, store, monkeypatch):
        from nabz.ui.tabs import new_products as mod
        tab = mod.NewProductsTab(db, store)
        assert "همهٔ انبارها" in tab.wh_btn.text()
        assert tab.selected_warehouses() is None

        class Pick(mod.WarehouseDialog):
            def exec(self):
                self.list.item(0).setCheckState(Qt.CheckState.Unchecked)
                return mod.QDialog.DialogCode.Accepted

        monkeypatch.setattr(mod, "WarehouseDialog", Pick)
        monkeypatch.setattr(mod, "run_async",
                            lambda owner, f, *a, on_done=None, **k: on_done(f(*a)))
        tab._pick_warehouses()
        assert tab.selected_warehouses() == [2]
        assert "انبار متفرقه" in tab.wh_btn.text()
        # تب جدید (اجرای بعدی برنامه) همان انتخاب را دارد
        assert "انبار متفرقه" in mod.NewProductsTab(db, store).wh_btn.text()


class TestAutoSyncNoticeUsesWarehouses:
    def test_notice_counts_only_chosen_warehouses(self, db, store):
        from nabz.jobs import record_missing_products
        db.set_setting("new_products_criteria", "stock")
        db.set_setting("new_products_warehouses", [1])
        haseb_all = load_products(db.get_setting("haseb_cal_path"))
        total, fresh = record_missing_products(db, haseb_all, [])
        assert db.get_setting("new_products_pending") == ["5010269900"]
        assert total == 1
