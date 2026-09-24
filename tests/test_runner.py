"""تست لایهٔ اجرا و رول‌بک — قلب ایمنی برنامه."""

from decimal import Decimal

import pytest

from nabz.db import Database
from nabz.engine import build_plan
from nabz.pricing import PriceRules
from nabz.runner import apply_plan, rollback_run
from nabz.sources.haseb_dbf import HasebItem
from nabz.sources.isaco_excel import IsacoItem
from nabz.stock import StockRules
from nabz.targets.woocommerce import WooClient, WooConfig, WooProduct


class RecordingWoo(WooClient):
    """ووکامرس جعلی که به‌روزرسانی‌ها را ثبت می‌کند."""

    def __init__(self, fail_ids=frozenset()):
        self.batches = []
        self._fail_ids = set(fail_ids)

    def batch_update(self, updates):
        from nabz.targets.woocommerce import BatchOutcome
        self.batches.append(updates)
        outcome = BatchOutcome()
        for u in updates:
            if u["id"] in self._fail_ids:
                outcome.failed[u["id"]] = "شبیه‌سازی خطا"
            else:
                outcome.updated.append(u["id"])
        return outcome


def woo_product(pid, sku, price="", stock=3):
    return WooProduct(id=pid, name=f"م{pid}", sku=sku, regular_price=price,
                      stock_quantity=stock, stock_status="instock",
                      manage_stock=True, type="simple", status="publish")


def isaco(code, vat):
    return IsacoItem(code=code, name="کالا", car="پژو", unit="عدد",
                     pack_size=1, retail=vat, vat=vat, wholesale=vat)


def haseb(code, qty):
    return HasebItem(code=code, raw_code=code, name="کالا",
                     quantity=Decimal(qty), warehouse_id=1, warehouse_name="ا")


STARTER = "0050102699"


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def plan_with_changes():
    return build_plan(
        products=[woo_product(1, "50102699", price="5000000", stock=10)],
        isaco={STARTER: isaco(STARTER, 68_992_000)},
        haseb={STARTER: haseb(STARTER, "5")},
        price_rules=PriceRules(markup_percent=Decimal("15"),
                               max_change_percent=Decimal("0")),
        stock_rules=StockRules(max_on_site=2),
    )


class TestApply:
    def test_applies_changes_to_woo(self, plan_with_changes, db):
        woo = RecordingWoo()
        result = apply_plan(plan_with_changes, woo, db)
        assert result.applied_count == 1
        assert len(woo.batches) == 1
        assert woo.batches[0][0]["id"] == 1

    def test_records_run(self, plan_with_changes, db):
        woo = RecordingWoo()
        result = apply_plan(plan_with_changes, woo, db, mode="auto")
        runs = db.recent_runs()
        assert runs[0]["id"] == result.run_id
        assert runs[0]["mode"] == "auto"
        assert runs[0]["status"] == "done"

    def test_no_changes_still_records_run(self, db):
        empty = build_plan(
            products=[woo_product(1, "50102699", price="7934000", stock=2)],
            isaco={STARTER: isaco(STARTER, 68_992_000)},
            haseb={STARTER: haseb(STARTER, "2")},
            price_rules=PriceRules(markup_percent=Decimal("15")),
            stock_rules=StockRules(max_on_site=2),
        )
        woo = RecordingWoo()
        result = apply_plan(empty, woo, db)
        assert result.applied_count == 0
        assert len(woo.batches) == 0
        assert db.recent_runs()[0]["status"] == "done"

    def test_snapshots_saved_for_rollback(self, plan_with_changes, db):
        woo = RecordingWoo()
        result = apply_plan(plan_with_changes, woo, db)
        snaps = db.rollback_data(result.run_id)
        assert len(snaps) == 1
        assert snaps[0].old_price == "5000000"
        assert snaps[0].new_price == "7934000"


class TestRollback:
    def test_full_round_trip(self, plan_with_changes, db):
        woo = RecordingWoo()
        result = apply_plan(plan_with_changes, woo, db)

        # اعمال شد: قیمت جدید
        assert woo.batches[0][0]["regular_price"] == "7934000"

        # حالا برگردان
        revert = rollback_run(result.run_id, woo, db)
        assert 1 in revert.updated
        # آخرین batch باید قیمت قبلی را برگردانده باشد
        assert woo.batches[-1][0]["regular_price"] == "5000000"

    def test_rollback_marks_run(self, plan_with_changes, db):
        woo = RecordingWoo()
        result = apply_plan(plan_with_changes, woo, db)
        rollback_run(result.run_id, woo, db)
        assert db.recent_runs()[0]["status"] == "rolled_back"

    def test_cannot_rollback_twice(self, plan_with_changes, db):
        woo = RecordingWoo()
        result = apply_plan(plan_with_changes, woo, db)
        rollback_run(result.run_id, woo, db)
        second = rollback_run(result.run_id, woo, db)
        assert second.updated == []

    def test_last_applied_run_points_to_it(self, plan_with_changes, db):
        woo = RecordingWoo()
        result = apply_plan(plan_with_changes, woo, db)
        assert db.last_applied_run() == result.run_id


class TestPartialFailure:
    def test_failed_products_not_snapshotted_as_applied(self, db):
        plan = build_plan(
            products=[
                woo_product(1, "50102699", price="5000000", stock=10),
                woo_product(2, "921900699", price="100", stock=10),
            ],
            isaco={STARTER: isaco(STARTER, 68_992_000),
                   "0921900699": isaco("0921900699", 12_936_000)},
            haseb={STARTER: haseb(STARTER, "5"),
                   "0921900699": haseb("0921900699", "5")},
            price_rules=PriceRules(markup_percent=Decimal("15"),
                                   max_change_percent=Decimal("0")),
            stock_rules=StockRules(max_on_site=2),
        )
        woo = RecordingWoo(fail_ids={2})
        result = apply_plan(plan, woo, db)
        assert result.applied_count == 1
        # فقط محصول موفق در رول‌بک باشد
        rollback_ids = [s.product_id for s in db.rollback_data(result.run_id)]
        assert rollback_ids == [1]
