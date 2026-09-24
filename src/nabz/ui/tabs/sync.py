"""تب سینک ایساکو — دانلود، مقایسه، پیش‌نمایش، اعمال.

کارهای شبکه‌ای (دانلود لیست قیمت، خواندن محصولات، اعمال) روی یک نخ جدا
انجام می‌شوند تا رابط کاربری هنگ نکند.
"""

from __future__ import annotations

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
from ...sources.isaco_excel import load as load_isaco
from ..services import (
    price_rules_from_db,
    stock_rules_from_db,
    woo_client_from_store,
)
from ..theme import COLORS
from ..widgets import Card, muted


class CompareWorker(QObject):
    """در پس‌زمینه: محصولات سایت را می‌خواند و با فایل ایساکو مقایسه می‌کند."""

    progress = Signal(str)
    done = Signal(object)      # SyncPlan
    failed = Signal(str)

    def __init__(self, db: Database, store: CredentialStore, isaco_path: str):
        super().__init__()
        self.db = db
        self.store = store
        self.isaco_path = isaco_path

    def run(self) -> None:
        try:
            self.progress.emit("در حال خواندن فایل لیست قیمت ایساکو ...")
            isaco = load_isaco(self.isaco_path)

            self.progress.emit("در حال اتصال به سایت و خواندن محصولات ...")
            woo = woo_client_from_store(self.store)
            if woo is None:
                self.failed.emit("اطلاعات اتصال ووکامرس در تنظیمات کامل نیست.")
                return
            products = woo.fetch_products()

            self.progress.emit("در حال مقایسه و محاسبهٔ قیمت‌ها ...")
            plan = build_plan(
                products=products,
                isaco=isaco,
                haseb={},   # موجودی حاسب در ایمپورت جدا سینک می‌شود
                price_rules=price_rules_from_db(self.db),
                stock_rules=stock_rules_from_db(self.db),
                update_stock=False,
            )
            self.done.emit(plan)
        except Exception as exc:  # noqa: BLE001 - می‌خواهیم هر خطا به UI برسد
            self.failed.emit(str(exc))


class ApplyWorker(QObject):
    progress = Signal(str)
    done = Signal(object)      # ApplyResult
    failed = Signal(str)

    def __init__(self, db: Database, store: CredentialStore, plan: SyncPlan):
        super().__init__()
        self.db = db
        self.store = store
        self.plan = plan

    def run(self) -> None:
        try:
            self.progress.emit("در حال اعمال روی سایت ...")
            woo = woo_client_from_store(self.store)
            if woo is None:
                self.failed.emit("اطلاعات اتصال ووکامرس کامل نیست.")
                return
            result = apply_plan(self.plan, woo, self.db, mode="manual")
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class SyncTab(QWidget):
    finished_apply = Signal()

    HEADERS = ["کد (SKU)", "نام محصول", "قیمت فعلی", "قیمت جدید", "٪ تغییر", "وضعیت"]

    def __init__(self, db: Database, store: CredentialStore, parent=None):
        super().__init__(parent)
        self.db = db
        self.store = store
        self._plan: SyncPlan | None = None
        self._thread: QThread | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QLabel("سینک قیمت از ایساکو")
        header.setObjectName("H1")
        layout.addWidget(header)

        # نوار ابزار
        toolbar = Card()
        row = QHBoxLayout()
        row.setSpacing(10)

        self.pick_btn = QPushButton("📂  انتخاب فایل اکسل ایساکو")
        self.pick_btn.clicked.connect(self._pick_file)
        row.addWidget(self.pick_btn)

        self.compare_btn = QPushButton("🔍  مقایسه با سایت")
        self.compare_btn.setObjectName("Primary")
        self.compare_btn.setEnabled(False)
        self.compare_btn.clicked.connect(self._compare)
        row.addWidget(self.compare_btn)

        self.apply_btn = QPushButton("✅  اعمال روی سایت")
        self.apply_btn.setObjectName("Success")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        row.addWidget(self.apply_btn)

        row.addStretch(1)
        toolbar.body().addLayout(row)
        self._file_label = muted("هنوز فایلی انتخاب نشده. فایل روزانه را از پورتال ایساکو دانلود کنید.")
        toolbar.add(self._file_label)
        layout.addWidget(toolbar)

        # نوار پیشرفت
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # حالت نامعین
        self.progress.hide()
        layout.addWidget(self.progress)

        self.status = muted("")
        layout.addWidget(self.status)

        # جدول
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        self._isaco_path: str | None = None

    # -- انتخاب فایل ---------------------------------------------------

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل لیست قیمت ایساکو", "",
            "فایل اکسل (*.xlsx *.xls)",
        )
        if path:
            self._isaco_path = path
            self._file_label.setText(f"فایل انتخاب‌شده: {path}")
            self.compare_btn.setEnabled(True)

    # -- مقایسه --------------------------------------------------------

    def _compare(self) -> None:
        if not self._isaco_path:
            return
        self._set_busy(True)
        worker = CompareWorker(self.db, self.store, self._isaco_path)
        self._run_worker(worker, self._on_compared)

    def _on_compared(self, plan: SyncPlan) -> None:
        self._plan = plan
        self._fill_table(plan)
        self._set_busy(False)
        s = plan.summary()
        self.status.setText(
            f"مقایسه انجام شد: {self._fa(s['changes'])} تغییر، "
            f"{self._fa(s['needs_review'])} نیازمند بررسی، "
            f"{self._fa(s['no_isaco_price'])} بدون قیمت ایساکو."
        )
        self.apply_btn.setEnabled(s["changes"] > 0)

    def _fill_table(self, plan: SyncPlan) -> None:
        rows = [i for i in plan.items if i.price_changes or i.needs_review]
        self.table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            review = item.needs_review
            cells = [
                item.sku,
                item.name,
                self._money(item.current_price),
                self._money(item.new_price),
                self._pct(item),
                "بررسی شود" if review else "آماده",
            ]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if c in (2, 3, 4):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if review:
                    cell.setBackground(QBrush(QColor("#fff8e1")))
                self.table.setItem(r, c, cell)

    # -- اعمال ---------------------------------------------------------

    def _apply(self) -> None:
        if not self._plan:
            return
        confirm = QMessageBox.question(
            self, "اعمال روی سایت",
            "قیمت‌های جدید روی سایت اعمال شوند؟ (قابل بازگشت است)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        worker = ApplyWorker(self.db, self.store, self._plan)
        self._run_worker(worker, self._on_applied)

    def _on_applied(self, result) -> None:
        self._set_busy(False)
        QMessageBox.information(
            self, "انجام شد",
            f"{self._fa(result.applied_count)} محصول به‌روز شد."
            + (f"\n{self._fa(len(result.outcome.failed))} خطا." if result.outcome.failed else ""),
        )
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

    # -- زیرساخت نخ ----------------------------------------------------

    def _run_worker(self, worker: QObject, on_done) -> None:
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status.setText)
        worker.done.connect(on_done)
        worker.failed.connect(self._on_failed)
        for sig in (worker.done, worker.failed):
            sig.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        # نگه‌داشتن ارجاع تا garbage collect نشود
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(self, "خطا", message)
        self.status.setText(f"خطا: {message}")

    def _set_busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.pick_btn.setEnabled(not busy)
        self.compare_btn.setEnabled(not busy and self._isaco_path is not None)
        if busy:
            self.apply_btn.setEnabled(False)

    # -- کمکی نمایش ----------------------------------------------------

    @staticmethod
    def _fa(n) -> str:
        return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    def _money(self, value) -> str:
        if value is None:
            return "—"
        return self._fa(f"{value:,}") + " ت"

    def _pct(self, item) -> str:
        if item.price_result and item.price_result.change_percent is not None:
            return self._fa(f"{item.price_result.change_percent:+.0f}") + "٪"
        return "—"
