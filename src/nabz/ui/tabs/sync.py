"""تب سینک — جریان واحد: دریافت خودکار قیمت ایساکو + موجودی حاسب → مقایسه → اعمال.

یک دکمه همه‌چیز را انجام می‌دهد:
۱) لیست قیمت ایساکو را خودکار دانلود می‌کند (اگر نشد، از فایل تنظیم‌شده).
۲) موجودی را از دیتابیس حاسب می‌خواند.
۳) با محصولات سایت مقایسه می‌کند و قیمت/موجودی جدید را حساب می‌کند.
۴) جدول پیش‌نمایش نشان می‌دهد؛ با تأیید، روی سایت اعمال می‌شود.

اعمال خودکار (بدون تأیید) در تب زمان‌بندی تنظیم می‌شود.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

_log = logging.getLogger("nabz.sync")

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config import CredentialStore
from ...db import Database
from ...engine import SyncPlan, build_plan
from ...runner import apply_plan, rollback_run
from ...sources.haseb_dbf import load_products as load_haseb
from ...sources.isaco_excel import load as load_isaco
from ..services import (
    price_rules_from_db,
    stock_rules_from_db,
    woo_client_from_store,
)
from ..widgets import Card, muted


class CompareWorker(QObject):
    """در پس‌زمینه: قیمت ایساکو + موجودی حاسب را می‌گیرد و مقایسه می‌کند."""

    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, db: Database, store: CredentialStore, manual_excel: str | None):
        super().__init__()
        self.db = db
        self.store = store
        self.manual_excel = manual_excel

    def run(self) -> None:
        try:
            isaco = self._load_isaco_prices()
            haseb = self._load_haseb_stock()

            if not isaco and not haseb:
                self.failed.emit(
                    "نه قیمت ایساکو در دسترس است و نه موجودی حاسب.\n"
                    "در تنظیمات مسیر فایل حاسب را بدهید یا فایل ایساکو را دستی انتخاب کنید."
                )
                return

            self.progress.emit("در حال خواندن محصولات سایت ...")
            woo = woo_client_from_store(self.store)
            if woo is None:
                self.failed.emit("اطلاعات اتصال ووکامرس در تنظیمات کامل نیست.")
                return
            products = woo.fetch_products()

            self.progress.emit("در حال مقایسه و محاسبه ...")
            plan = build_plan(
                products=products,
                isaco=isaco,
                haseb=haseb,
                price_rules=price_rules_from_db(self.db),
                stock_rules=stock_rules_from_db(self.db),
                update_price=bool(isaco),
                update_stock=bool(haseb),
            )
            self.done.emit((plan, bool(isaco), bool(haseb)))
        except Exception as exc:  # noqa: BLE001
            _log.exception("خطا در مقایسهٔ سینک")
            self.failed.emit(str(exc))

    def _load_isaco_prices(self) -> dict:
        """قیمت‌ها را از فایل می‌خواند: فایل دستی/دانلودشده → فایل تنظیم‌شده.

        دانلود خودکار (مرورگری) در نخ اصلی انجام می‌شود، نه اینجا؛ نتیجه‌اش
        به‌صورت ``manual_excel`` یا در ``isaco_excel_path`` به این worker می‌رسد.
        """
        if self.manual_excel and Path(self.manual_excel).is_file():
            self.progress.emit("در حال خواندن فایل ایساکو ...")
            return load_isaco(self.manual_excel)

        configured = self.db.get_setting("isaco_excel_path", "")
        if configured and Path(configured).is_file():
            self.progress.emit("در حال خواندن فایل لیست قیمت ایساکو ...")
            return load_isaco(configured)

        return {}

    def _load_haseb_stock(self) -> dict:
        haseb_path = self.db.get_setting("haseb_cal_path", "")
        if not (haseb_path and Path(haseb_path).is_file()):
            return {}
        self.progress.emit("در حال خواندن موجودی از حاسب ...")
        warehouses = self.db.get_setting("isaco_warehouses", None)
        wh = set(warehouses) if warehouses else None
        return load_haseb(haseb_path, warehouses=wh)


class ApplyWorker(QObject):
    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, db, store, plan, include_price, include_stock):
        super().__init__()
        self.db, self.store, self.plan = db, store, plan
        self.include_price, self.include_stock = include_price, include_stock

    def run(self) -> None:
        try:
            self.progress.emit("در حال اعمال روی سایت ...")
            woo = woo_client_from_store(self.store)
            if woo is None:
                self.failed.emit("اطلاعات اتصال ووکامرس کامل نیست.")
                return
            result = apply_plan(
                self.plan, woo, self.db, mode="manual",
                include_price=self.include_price, include_stock=self.include_stock,
            )
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001
            _log.exception("خطا در اعمال سینک")
            self.failed.emit(str(exc))


class SyncTab(QWidget):
    finished_apply = Signal()

    HEADERS = ["کد (SKU)", "نام محصول", "قیمت فعلی", "قیمت جدید",
               "موجودی فعلی", "موجودی جدید", "وضعیت"]

    def __init__(self, db: Database, store: CredentialStore, parent=None):
        super().__init__(parent)
        self.db = db
        self.store = store
        self._plan: SyncPlan | None = None
        self._inc_price = False
        self._inc_stock = False
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        header = QLabel("سینک قیمت و موجودی")
        header.setObjectName("H1")
        layout.addWidget(header)

        toolbar = Card()
        row = QHBoxLayout()
        row.setSpacing(10)

        self.fetch_btn = QPushButton("🔄  دریافت و مقایسه")
        self.fetch_btn.setObjectName("Primary")
        self.fetch_btn.setMinimumHeight(44)
        self.fetch_btn.clicked.connect(self._fetch)
        row.addWidget(self.fetch_btn, 2)

        self.pick_btn = QPushButton("📂  فایل ایساکو دستی")
        self.pick_btn.clicked.connect(self._pick_file)
        row.addWidget(self.pick_btn, 1)

        self.apply_btn = QPushButton("✅  اعمال روی سایت")
        self.apply_btn.setObjectName("Success")
        self.apply_btn.setEnabled(False)
        self.apply_btn.setMinimumHeight(44)
        self.apply_btn.clicked.connect(self._apply)
        row.addWidget(self.apply_btn, 2)

        toolbar.body().addLayout(row)
        self._info = muted(
            "«دریافت و مقایسه» خودکار قیمت را از ایساکو و موجودی را از حاسب می‌گیرد. "
            "اگر دانلود خودکار میسر نشد، از فایل ایساکوی دستی/تنظیم‌شده استفاده می‌شود."
        )
        toolbar.add(self._info)
        layout.addWidget(toolbar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = muted("")
        layout.addWidget(self.status)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table, 1)

        self._manual_path: str | None = None

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل لیست قیمت ایساکو", "", "فایل اکسل (*.xlsx *.xls)"
        )
        if path:
            self._manual_path = path
            self.status.setText(f"فایل دستی انتخاب شد: {path}")

    def _fetch(self) -> None:
        self._set_busy(True)
        # اگر فایل دستی نداریم، تلاش برای دانلود خودکار مرورگری (در نخ اصلی)
        if not self._manual_path:
            self._try_browser_download()
        worker = CompareWorker(self.db, self.store, self._manual_path)
        self._run_worker(worker, self._on_compared)

    def _try_browser_download(self) -> None:
        """دانلود خودکار لیست قیمت با مرورگر داخلی (نخ اصلی).

        اگر موفق شد، مسیر فایل در isaco_excel_path ذخیره می‌شود و worker
        از آن می‌خواند. اگر نشد، بی‌صدا به فایل تنظیم‌شده برمی‌گردیم.
        """
        creds = self.store.load_isaco()
        if not (creds.scus and creds.username and creds.password):
            return
        try:
            from ...sources.isaco_browser import IsacoDownloader
        except ImportError as exc:
            _log.warning("موتور مرورگر در دسترس نیست: %s", exc)
            return
        try:
            self.status.setText("در حال دانلود خودکار لیست قیمت از ایساکو ...")
            dest = str(Path(tempfile.gettempdir()) / "isaco_pricelist.xlsx")
            downloader = IsacoDownloader(
                creds.scus, creds.username, creds.password,
                on_progress=self.status.setText,
            )
            path = downloader.download(dest)
            self.db.set_setting("isaco_excel_path", path)
            _log.info("دانلود خودکار ایساکو موفق: %s", path)
        except Exception as exc:  # noqa: BLE001
            _log.warning("دانلود خودکار مرورگری نشد: %s", exc, exc_info=True)
            self.status.setText(
                f"دانلود خودکار نشد ({exc}). از فایل تنظیم‌شده استفاده می‌شود."
            )

    def _on_compared(self, result) -> None:
        plan, inc_price, inc_stock = result
        self._plan = plan
        self._inc_price, self._inc_stock = inc_price, inc_stock
        self._fill_table(plan)
        self._set_busy(False)
        s = plan.summary()
        self.status.setText(
            f"مقایسه انجام شد — تغییرات: {self._fa(s['changes'])} | "
            f"قیمت: {self._fa(s['price_changes'])} | موجودی: {self._fa(s['stock_changes'])} | "
            f"نیازمند بررسی: {self._fa(s['needs_review'])}"
        )
        self.apply_btn.setEnabled(s["changes"] > 0)

    def _fill_table(self, plan: SyncPlan) -> None:
        rows = [i for i in plan.items if i.changes or i.needs_review]
        self.table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            review = item.needs_review
            cells = [
                item.sku,
                item.name,
                self._money(item.current_price),
                self._money(item.new_price),
                self._num(item.current_stock),
                self._num(item.new_stock),
                "بررسی شود" if review else "آماده",
            ]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if c not in (1,):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if review:
                    cell.setBackground(QBrush(QColor("#fff8e1")))
                self.table.setItem(r, c, cell)

    def _apply(self) -> None:
        if not self._plan:
            return
        confirm = QMessageBox.question(
            self, "اعمال روی سایت",
            "تغییرات روی سایت اعمال شوند؟ (قابل بازگشت است)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        worker = ApplyWorker(self.db, self.store, self._plan,
                             self._inc_price, self._inc_stock)
        self._run_worker(worker, self._on_applied)

    def _on_applied(self, result) -> None:
        self._set_busy(False)
        msg = f"{self._fa(result.applied_count)} محصول به‌روز شد."
        if result.outcome.failed:
            msg += f"\n{self._fa(len(result.outcome.failed))} خطا."
        QMessageBox.information(self, "انجام شد", msg)
        self.apply_btn.setEnabled(False)
        self.finished_apply.emit()

    def do_rollback(self, run_id: int) -> None:
        woo = woo_client_from_store(self.store)
        if woo is None:
            QMessageBox.warning(self, "خطا", "اطلاعات اتصال کامل نیست.")
            return
        try:
            outcome = rollback_run(run_id, woo, self.db)
            QMessageBox.information(
                self, "بازگردانی",
                f"{self._fa(len(outcome.updated))} محصول به حالت قبل برگشت.",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطا", f"بازگردانی ناموفق: {exc}")

    def _run_worker(self, worker: QObject, on_done) -> None:
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status.setText)
        worker.done.connect(on_done)
        worker.failed.connect(self._on_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(self, "خطا", message)
        self.status.setText(f"خطا: {message}")

    def _set_busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.fetch_btn.setEnabled(not busy)
        self.pick_btn.setEnabled(not busy)
        if busy:
            self.apply_btn.setEnabled(False)

    @staticmethod
    def _fa(n) -> str:
        return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    def _money(self, value) -> str:
        return "—" if value is None else self._fa(f"{value:,}") + " ت"

    def _num(self, value) -> str:
        return "—" if value is None else self._fa(value)
