"""تست لایهٔ دیتابیس — با تمرکز روی رول‌بک که حیاتی‌ترین بخش است."""

import pytest

from nabz.db import Database, Snapshot


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


class TestSettings:
    def test_set_and_get(self, db):
        db.set_setting("markup", 15)
        assert db.get_setting("markup") == 15

    def test_default_when_missing(self, db):
        assert db.get_setting("nope", "def") == "def"

    def test_overwrites(self, db):
        db.set_setting("x", 1)
        db.set_setting("x", 2)
        assert db.get_setting("x") == 2

    def test_stores_complex_values(self, db):
        db.set_setting("rules", {"a": [1, 2], "b": "سلام"})
        assert db.get_setting("rules") == {"a": [1, 2], "b": "سلام"}

    def test_all_settings(self, db):
        db.set_setting("a", 1)
        db.set_setting("b", 2)
        assert db.all_settings() == {"a": 1, "b": 2}


class TestAppPassword:
    def test_no_password_initially(self, db):
        assert not db.has_app_password()

    def test_set_and_verify(self, db):
        db.set_app_password("1234")
        assert db.has_app_password()
        assert db.verify_app_password("1234")

    def test_wrong_password_rejected(self, db):
        db.set_app_password("1234")
        assert not db.verify_app_password("0000")

    def test_password_not_stored_plaintext(self, db):
        db.set_app_password("secret-pass")
        stored = db.get_setting("app_password")
        assert "secret-pass" not in str(stored)
        assert "hash" in stored and "salt" in stored

    def test_verify_when_no_password_set(self, db):
        assert not db.verify_app_password("anything")

    def test_changing_password(self, db):
        db.set_app_password("old")
        db.set_app_password("new")
        assert db.verify_app_password("new")
        assert not db.verify_app_password("old")


class TestRuns:
    def test_start_and_finish(self, db):
        run_id = db.start_run("manual")
        db.finish_run(run_id, "done", {"changes": 5})
        runs = db.recent_runs()
        assert runs[0]["id"] == run_id
        assert runs[0]["status"] == "done"

    def test_recent_runs_newest_first(self, db):
        a = db.start_run("auto")
        b = db.start_run("manual")
        runs = db.recent_runs()
        assert [r["id"] for r in runs] == [b, a]


class TestRollback:
    """ستون فقرات ایمنی برنامه."""

    def test_snapshots_recorded(self, db):
        run_id = db.start_run("manual")
        snaps = [
            Snapshot(product_id=1, sku="0050102699", old_price="5000000",
                     new_price="7934000", applied=True),
            Snapshot(product_id=2, sku="0921900699", old_stock=3,
                     new_stock=2, applied=True),
        ]
        db.record_snapshots(run_id, snaps)
        data = db.rollback_data(run_id)
        assert len(data) == 2

    def test_rollback_returns_old_values(self, db):
        run_id = db.start_run("manual")
        db.record_snapshot(run_id, Snapshot(
            product_id=1, sku="x", old_price="5000000", new_price="7934000",
            old_stock=10, new_stock=2, old_status="instock",
            new_status="instock", applied=True))
        snap = db.rollback_data(run_id)[0]
        revert = snap.to_woo_revert()
        assert revert["id"] == 1
        assert revert["regular_price"] == "5000000"   # قیمت قبلی
        assert revert["stock_quantity"] == 10          # موجودی قبلی

    def test_unapplied_snapshots_not_in_rollback(self, db):
        run_id = db.start_run("manual")
        db.record_snapshots(run_id, [
            Snapshot(product_id=1, sku="x", applied=True),
            Snapshot(product_id=2, sku="y", applied=False),  # فقط پیش‌نمایش
        ])
        assert len(db.rollback_data(run_id)) == 1

    def test_mark_reverted_removes_from_rollback(self, db):
        run_id = db.start_run("manual")
        db.record_snapshot(run_id, Snapshot(product_id=1, sku="x", applied=True))
        db.mark_reverted(run_id)
        assert db.rollback_data(run_id) == []

    def test_reverting_sets_run_status(self, db):
        run_id = db.start_run("manual")
        db.record_snapshot(run_id, Snapshot(product_id=1, sku="x", applied=True))
        db.mark_reverted(run_id)
        assert db.recent_runs()[0]["status"] == "rolled_back"

    def test_last_applied_run(self, db):
        r1 = db.start_run("manual")
        db.record_snapshot(r1, Snapshot(product_id=1, sku="x", applied=True))
        r2 = db.start_run("manual")
        db.record_snapshot(r2, Snapshot(product_id=2, sku="y", applied=True))
        assert db.last_applied_run() == r2

    def test_last_applied_run_skips_reverted(self, db):
        r1 = db.start_run("manual")
        db.record_snapshot(r1, Snapshot(product_id=1, sku="x", applied=True))
        r2 = db.start_run("manual")
        db.record_snapshot(r2, Snapshot(product_id=2, sku="y", applied=True))
        db.mark_reverted(r2)
        assert db.last_applied_run() == r1

    def test_no_applied_run_returns_none(self, db):
        assert db.last_applied_run() is None


class TestSnapshotRevertPayload:
    def test_price_only(self):
        snap = Snapshot(product_id=5, sku="x", old_price="1000")
        assert snap.to_woo_revert() == {"id": 5, "regular_price": "1000"}

    def test_stock_only(self):
        snap = Snapshot(product_id=5, sku="x", old_stock=7, old_status="instock")
        payload = snap.to_woo_revert()
        assert payload["stock_quantity"] == 7
        assert payload["manage_stock"] is True
        assert payload["stock_status"] == "instock"


class TestCodeMap:
    def test_set_and_get(self, db):
        db.set_code_map("270500109", "0270500107", "گارانتی طلایی")
        assert db.get_code_map()["270500109"] == "0270500107"

    def test_overwrite(self, db):
        db.set_code_map("x", "a")
        db.set_code_map("x", "b")
        assert db.get_code_map()["x"] == "b"

    def test_delete(self, db):
        db.set_code_map("x", "a")
        db.delete_code_map("x")
        assert "x" not in db.get_code_map()


class TestLogs:
    def test_log_and_read(self, db):
        db.log("info", "شروع سینک")
        db.log("error", "خطای اتصال")
        logs = db.recent_logs()
        assert len(logs) == 2
        assert logs[0]["message"] == "خطای اتصال"  # newest first

    def test_log_tied_to_run(self, db):
        run_id = db.start_run("auto")
        db.log("info", "x", run_id=run_id)
        assert db.recent_logs()[0]["run_id"] == run_id


class TestPersistence:
    def test_survives_reopen(self, tmp_path):
        path = tmp_path / "nabz.db"
        db1 = Database(path)
        db1.set_setting("markup", 20)
        db1.set_app_password("pass")
        db1.close()

        db2 = Database(path)
        assert db2.get_setting("markup") == 20
        assert db2.verify_app_password("pass")
        db2.close()
