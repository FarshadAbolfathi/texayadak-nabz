"""لایهٔ دیتابیس محلی (SQLite).

همه‌چیزی که برنامه باید بین اجراها نگه دارد اینجاست:

- تنظیمات (درصد سود، رند، سقف موجودی، زمان‌بندی، ...)
- رمز ورود به برنامه (به‌صورت hash، نه plaintext)
- **snapshot قیمت/موجودی پیش از هر اجرا** ← ستون فقرات رول‌بک
- تاریخچهٔ اجراها و لاگ
- نگاشت دستی کدهای بی‌تطابق (کد سایت → کد ایساکو)

هیچ‌کدام از این‌ها به سرور نمی‌رود؛ فایل دیتابیس روی سیستم کارفرماست.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1


class _Result:
    """نتیجهٔ کاملاً خوانده‌شدهٔ یک کوئری (تا خواندن ردیف‌ها بیرون از قفل نباشد)."""

    __slots__ = ("_rows", "lastrowid", "rowcount")

    def __init__(self, cursor: sqlite3.Cursor):
        self._rows = cursor.fetchall()
        self.lastrowid = cursor.lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _LockedConnection:
    """اتصال SQLite مشترک بین نخ اصلی و نخ‌های سینک، با یک قفل.

    نخ سینک (پس‌زمینه) و رابط کاربری (داشبورد، لاگ، تنظیمات) هم‌زمان از
    یک اتصال استفاده می‌کنند؛ بدون قفل، استفادهٔ هم‌زمان از یک اتصال
    پایتون می‌تواند برنامه را بی‌صدا (بدون لاگ) کرش کند.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.lock = threading.RLock()

    def execute(self, sql: str, params=()) -> _Result:
        with self.lock:
            return _Result(self._conn.execute(sql, params))

    def executemany(self, sql: str, seq) -> _Result:
        with self.lock:
            return _Result(self._conn.executemany(sql, seq))

    def executescript(self, script: str) -> None:
        with self.lock:
            self._conn.executescript(script)

    def commit(self) -> None:
        with self.lock:
            self._conn.commit()

    def rollback(self) -> None:
        with self.lock:
            self._conn.rollback()

    def close(self) -> None:
        with self.lock:
            self._conn.close()


class Database:
    """پوشش نازک روی SQLite با کمکِ کاربردی برای این برنامه.

    از چند نخ قابل استفاده است: همهٔ دسترسی‌ها پشت یک قفل‌اند و هر تراکنش
    تا commit قفل را نگه می‌دارد.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        is_memory = self.path == ":memory:"
        if not is_memory:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(self.path, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        self._conn = _LockedConnection(raw)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """یک تراکنش؛ در صورت خطا rollback می‌شود."""
        with self._conn.lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # -- ساخت جدول‌ها --------------------------------------------------

    def _migrate(self) -> None:
        with self._tx() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                -- هر اجرای سینک یک ردیف اینجا دارد
                CREATE TABLE IF NOT EXISTS runs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at  REAL NOT NULL,
                    finished_at REAL,
                    mode        TEXT NOT NULL,      -- auto | manual | excel
                    status      TEXT NOT NULL,      -- running | done | failed | rolled_back
                    summary     TEXT,              -- JSON: تعداد تغییرات و ...
                    note        TEXT
                );

                -- snapshot قیمت/موجودی هر محصول پیش از تغییر ← برای رول‌بک
                CREATE TABLE IF NOT EXISTS snapshots (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    product_id  INTEGER NOT NULL,
                    sku         TEXT,
                    old_price   TEXT,
                    new_price   TEXT,
                    old_stock   INTEGER,
                    new_stock   INTEGER,
                    old_status  TEXT,
                    new_status  TEXT,
                    applied     INTEGER NOT NULL DEFAULT 0,
                    reverted    INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_snap_run ON snapshots(run_id);

                -- نگاشت دستی کد سایت به کد ایساکو (برای ۵۱ کد یتیم)
                CREATE TABLE IF NOT EXISTS code_map (
                    site_sku   TEXT PRIMARY KEY,
                    isaco_code TEXT NOT NULL,
                    note       TEXT,
                    created_at REAL NOT NULL
                );

                -- لاگ عمومی برنامه
                CREATE TABLE IF NOT EXISTS logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    at         REAL NOT NULL,
                    level      TEXT NOT NULL,       -- info | warn | error
                    message    TEXT NOT NULL,
                    run_id     INTEGER REFERENCES runs(id) ON DELETE SET NULL
                );
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # -- تنظیمات -------------------------------------------------------

    def set_setting(self, key: str, value: Any) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def all_settings(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    # -- رمز ورود برنامه ----------------------------------------------

    def set_app_password(self, password: str) -> None:
        """رمز ورود برنامه را به‌صورت hash با salt ذخیره می‌کند."""
        salt = secrets.token_hex(16)
        digest = self._hash_password(password, salt)
        self.set_setting("app_password", {"salt": salt, "hash": digest})

    def verify_app_password(self, password: str) -> bool:
        stored = self.get_setting("app_password")
        if not stored:
            return False
        expected = self._hash_password(password, stored["salt"])
        return secrets.compare_digest(expected, stored["hash"])

    def has_app_password(self) -> bool:
        return self.get_setting("app_password") is not None

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), 200_000
        ).hex()

    # -- اجراها و رول‌بک -----------------------------------------------

    def start_run(self, mode: str, note: str | None = None) -> int:
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO runs(started_at, mode, status, note) "
                "VALUES(?, ?, 'running', ?)",
                (time.time(), mode, note),
            )
            return int(cur.lastrowid)

    def finish_run(
        self, run_id: int, status: str, summary: dict | None = None
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE runs SET finished_at=?, status=?, summary=? WHERE id=?",
                (
                    time.time(),
                    status,
                    json.dumps(summary, ensure_ascii=False) if summary else None,
                    run_id,
                ),
            )

    def record_snapshot(self, run_id: int, snap: "Snapshot") -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO snapshots(run_id, product_id, sku, old_price, "
                "new_price, old_stock, new_stock, old_status, new_status, applied) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, snap.product_id, snap.sku, snap.old_price,
                    snap.new_price, snap.old_stock, snap.new_stock,
                    snap.old_status, snap.new_status, int(snap.applied),
                ),
            )

    def record_snapshots(self, run_id: int, snaps: list["Snapshot"]) -> None:
        with self._tx() as conn:
            conn.executemany(
                "INSERT INTO snapshots(run_id, product_id, sku, old_price, "
                "new_price, old_stock, new_stock, old_status, new_status, applied) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        run_id, s.product_id, s.sku, s.old_price, s.new_price,
                        s.old_stock, s.new_stock, s.old_status, s.new_status,
                        int(s.applied),
                    )
                    for s in snaps
                ],
            )

    def rollback_data(self, run_id: int) -> list["Snapshot"]:
        """داده‌های لازم برای بازگرداندن یک اجرا را می‌دهد.

        فقط snapshotهایی که واقعاً اعمال شده و هنوز برنگشته‌اند.
        خودِ فرستادن به ووکامرس بیرون از این لایه است تا تست‌پذیر بماند.
        """
        rows = self._conn.execute(
            "SELECT * FROM snapshots WHERE run_id=? AND applied=1 AND reverted=0",
            (run_id,),
        ).fetchall()
        return [Snapshot.from_row(r) for r in rows]

    def mark_reverted(self, run_id: int) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE snapshots SET reverted=1 WHERE run_id=? AND applied=1",
                (run_id,),
            )
            conn.execute(
                "UPDATE runs SET status='rolled_back' WHERE id=?", (run_id,)
            )

    def recent_runs(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def last_applied_run(self) -> int | None:
        """آخرین اجرایی که اعمال شده و برنگشته — برای دکمهٔ «بازگرداندن»."""
        row = self._conn.execute(
            "SELECT DISTINCT run_id FROM snapshots "
            "WHERE applied=1 AND reverted=0 ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        return int(row["run_id"]) if row else None

    # -- نگاشت دستی کدها ----------------------------------------------

    def set_code_map(self, site_sku: str, isaco_code: str, note: str = "") -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO code_map(site_sku, isaco_code, note, created_at) "
                "VALUES(?,?,?,?) ON CONFLICT(site_sku) DO UPDATE SET "
                "isaco_code=excluded.isaco_code, note=excluded.note",
                (site_sku, isaco_code, note, time.time()),
            )

    def get_code_map(self) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT site_sku, isaco_code FROM code_map"
        ).fetchall()
        return {r["site_sku"]: r["isaco_code"] for r in rows}

    def delete_code_map(self, site_sku: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM code_map WHERE site_sku=?", (site_sku,))

    # -- لاگ -----------------------------------------------------------

    def log(self, level: str, message: str, run_id: int | None = None) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO logs(at, level, message, run_id) VALUES(?,?,?,?)",
                (time.time(), level, message, run_id),
            )

    def clear_history(self, *, keep_rollback: bool = True) -> tuple[int, int]:
        """گزارش اجراها و رویدادها را پاک می‌کند.

        :param keep_rollback: آخرین اجرای اعمال‌شده (و snapshot هایش) نگه
            داشته می‌شود تا «بازگرداندن آخرین تغییر» همچنان کار کند.
        :returns: ``(تعداد اجراهای پاک‌شده، تعداد رویدادهای پاک‌شده)``
        """
        keep = self.last_applied_run() if keep_rollback else None
        with self._tx() as conn:
            logs = conn.execute("DELETE FROM logs").rowcount
            if keep is None:
                runs = conn.execute("DELETE FROM runs").rowcount
            else:
                runs = conn.execute("DELETE FROM runs WHERE id <> ?", (keep,)).rowcount
        # snapshot ها با ON DELETE CASCADE پاک می‌شوند
        return max(runs, 0), max(logs, 0)

    def recent_logs(self, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


@dataclass(slots=True)
class Snapshot:
    """عکس لحظه‌ای قیمت/موجودی یک محصول پیش و پس از تغییر."""

    product_id: int
    sku: str
    old_price: str | None = None
    new_price: str | None = None
    old_stock: int | None = None
    new_stock: int | None = None
    old_status: str | None = None
    new_status: str | None = None
    applied: bool = False

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Snapshot":
        return cls(
            product_id=row["product_id"],
            sku=row["sku"],
            old_price=row["old_price"],
            new_price=row["new_price"],
            old_stock=row["old_stock"],
            new_stock=row["new_stock"],
            old_status=row["old_status"],
            new_status=row["new_status"],
            applied=bool(row["applied"]),
        )

    def to_woo_revert(self) -> dict:
        """payload بازگرداندن به مقدار قبلی برای ووکامرس."""
        payload: dict = {"id": self.product_id}
        if self.old_price is not None:
            payload["regular_price"] = self.old_price
        if self.old_stock is not None:
            payload["manage_stock"] = True
            payload["stock_quantity"] = self.old_stock
        if self.old_status is not None:
            payload["stock_status"] = self.old_status
        return payload
