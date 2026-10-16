"""به‌روزرسانی نام محصولات از حاسب (اختیاری، فقط دستی، قابل بازگرداندن)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from nabz.config import CredentialStore, MemoryBackend, WooCredentials
from nabz.db import Database, Snapshot
from nabz.engine import build_plan
from nabz.pricing import PriceRules
from nabz.sources.haseb_dbf import HasebItem
from nabz.stock import StockRules
from nabz.targets.woocommerce import WooProduct


def product(pid, sku, name):
    return WooProduct(id=pid, name=name, sku=sku, regular_price="1000",
                      stock_quantity=1, stock_status="instock", manage_stock=True,
                      type="simple", status="publish")


def haseb(code, name, qty=1):
    return HasebItem(code, code, name, Decimal(qty), 1, "انبار")


PRODUCTS = [product(1, "0000000001", "سپر عقب"),
            product(2, "0000000002", "چراغ جلو پژو ی"),
            product(3, "0000000003", "لنت")]
HASEB = {"0000000001": haseb("0000000001", "سپر  عقب پژو 405 ايساكو"),
         "0000000002": haseb("0000000002", "چراغ جلو  پژو ي"),   # فقط ي/فاصله
         "0000000003": haseb("0000000003", "لنت")}


def plan(compare_names=True):
    return build_plan(PRODUCTS, {}, HASEB, PriceRules(), StockRules(max_on_site=1),
                      update_price=False, compare_names=compare_names)


class TestEngine:
    def test_only_real_name_differences(self):
        items = {i.product_id: i for i in plan().items}
        assert items[1].new_name == "سپر عقب پژو 405 ایساکو"
        assert items[1].name_changes and items[1].changes
        assert not items[2].name_changes        # فقط ي/ك عربی و فاصله
        assert not items[3].name_changes

    def test_off_by_default_and_never_in_auto(self):
        p = build_plan(PRODUCTS, {}, HASEB, PriceRules(), StockRules(max_on_site=1),
                       update_price=False)
        assert not any(i.name_changes for i in p.items)
        assert all("name" not in u for u in plan().to_woo_updates())

    def test_rollback_restores_name(self, tmp_path):
        db = Database(tmp_path / "t.db")
        rid = db.start_run("manual")
        db.record_snapshot(rid, Snapshot(product_id=1, sku="1", old_name="سپر عقب",
                                         new_name="سپر عقب پژو", applied=True))
        (snap,) = db.rollback_data(rid)
        assert snap.to_woo_revert()["name"] == "سپر عقب"
        db.close()

    def test_old_database_is_migrated(self, tmp_path):
        import sqlite3
        path = tmp_path / "old.db"
        Database(path).close()
        conn = sqlite3.connect(path)          # دیتابیس قدیمی بدون ستون نام
        conn.execute("DROP TABLE snapshots")
        conn.execute("""CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL, sku TEXT, old_price TEXT, new_price TEXT,
            old_stock INTEGER, new_stock INTEGER, old_status TEXT, new_status TEXT,
            applied INTEGER NOT NULL DEFAULT 0, reverted INTEGER NOT NULL DEFAULT 0)""")
        conn.commit()
        conn.close()
        db = Database(path)                   # نباید خطا بدهد و ستون‌ها اضافه شوند
        rid = db.start_run("manual")
        db.record_snapshot(rid, Snapshot(product_id=1, sku="1", old_name="a",
                                         new_name="b", applied=True))
        assert db.rollback_data(rid)[0].old_name == "a"
        db.close()


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


class TestSyncTab:
    def tab(self, db, store, on=True):
        from nabz.ui.tabs.sync import SyncTab
        db.set_setting("sync_compare_names", on)
        t = SyncTab(db, store)
        t._on_compared((plan(on), False, True, 0))
        return t

    def test_column_hidden_when_off(self, qapp, db, store):
        t = self.tab(db, store, on=False)
        assert t.table.isColumnHidden(t.COL_NEW_NAME)
        assert not t.names_check.isChecked()

    def test_apply_sends_name_with_snapshot(self, qapp, db, store):
        t = self.tab(db, store)
        assert not t.table.isColumnHidden(t.COL_NEW_NAME)
        updates, snaps = t._collect_rows(t.rows_to_apply())
        by_id = {u["id"]: u for u in updates}
        assert by_id[1]["name"] == "سپر عقب پژو 405 ایساکو"
        assert 2 not in by_id and 3 not in by_id
        snap = next(s for s in snaps if s.product_id == 1)
        assert snap.old_name == "سپر عقب"
        r = next(r for r, i in enumerate(t._row_items) if i.product_id == 1)
        assert "نام" in t.table.item(r, t.COL_STATUS).text()

    def test_edit_suggested_name(self, qapp, db, store):
        t = self.tab(db, store)
        r = next(r for r, i in enumerate(t._row_items) if i.product_id == 3)
        t.table.item(r, t.COL_NEW_NAME).setText("لنت ترمز جلو")
        updates, _ = t._collect_rows(t.rows_to_apply())
        assert {u["id"]: u.get("name") for u in updates}[3] == "لنت ترمز جلو"

    def test_toggle_saves_setting(self, qapp, db, store):
        t = self.tab(db, store, on=False)
        t.names_check.setChecked(True)
        assert db.get_setting("sync_compare_names") is True
        assert not t.table.isColumnHidden(t.COL_NEW_NAME)
