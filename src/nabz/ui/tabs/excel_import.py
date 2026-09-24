"""تب ایمپورت اکسل — به‌روزرسانی موجودی (و اختیاراً قیمت) از فایل حسابداری.

کاربر فایل را انتخاب می‌کند، تعیین می‌کند کدام ستون «کد» و کدام «موجودی»
است، و برنامه موجودی سایت را از روی همان فایل به‌روز می‌کند. این مسیر
همان موتور سینک و رول‌بک را استفاده می‌کند، پس کاملاً قابل بازگشت است.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config import CredentialStore
from ...db import Database
from ...engine import build_plan
from ...runner import apply_plan
from ...sources.accounting_excel import ColumnMapping, read_headers, read_rows
from ...sources.haseb_dbf import HasebItem
from ..services import (
    price_rules_from_db,
    stock_rules_from_db,
    woo_client_from_store,
)
from ..widgets import Card, muted


class ImportWorker(QObject):
    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, db, store, path, mapping, update_price):
        super().__init__()
        self.db, self.store = db, store
        self.path, self.mapping, self.update_price = path, mapping, update_price

    def run(self) -> None:
        try:
            self.progress.emit("در حال خواندن فایل ...")
            rows = read_rows(self.path, self.mapping)
            haseb = {
                r.code: HasebItem(
                    code=r.code, raw_code=r.raw_code, name="",
                    quantity=r.quantity if r.quantity is not None else Decimal(0),
                    warehouse_id=0, warehouse_name="",
                )
                for r in rows
            }

            self.progress.emit("در حال خواندن محصولات سایت ...")
            woo = woo_client_from_store(self.store)
            if woo is None:
                self.failed.emit("اطلاعات اتصال ووکامرس کامل نیست.")
                return
            products = woo.fetch_products()

            self.progress.emit("در حال اعمال موجودی ...")
            plan = build_plan(
                products=products, isaco={}, haseb=haseb,
                price_rules=price_rules_from_db(self.db),
                stock_rules=stock_rules_from_db(self.db),
                update_price=False,
            )
            result = apply_plan(
                plan, woo, self.db, mode="excel", include_price=False
            )
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class ExcelImportTab(QWidget):
    def __init__(self, db: Database, store: CredentialStore, parent=None):
        super().__init__(parent)
        self.db = db
        self.store = store
        self._path: str | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QLabel("ایمپورت موجودی از اکسل حسابداری")
        header.setObjectName("H1")
        layout.addWidget(header)

        card = Card("انتخاب فایل و نگاشت ستون‌ها")
        pick = QPushButton("📂  انتخاب فایل اکسل / CSV")
        pick.clicked.connect(self._pick)
        card.add(pick)
        self._file_label = muted("هنوز فایلی انتخاب نشده.")
        card.add(self._file_label)

        form = QFormLayout()
        form.setSpacing(12)
        self.col_code = QComboBox()
        self.col_qty = QComboBox()
        form.addRow("ستون کد کالا:", self.col_code)
        form.addRow("ستون موجودی:", self.col_qty)
        card.body().addLayout(form)
        layout.addWidget(card)

        self.apply_btn = QPushButton("✅  به‌روزرسانی موجودی سایت")
        self.apply_btn.setObjectName("Success")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        layout.addWidget(self.apply_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = muted("")
        layout.addWidget(self.status)

        card.add(muted(
            "اولویت اصلی: به‌روزرسانی موجودی. سقف موجودی از تب تنظیمات اعمال "
            "می‌شود. این کار مثل سینک ایساکو قابل بازگشت است."
        ))
        layout.addStretch(1)

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل حسابداری", "",
            "اکسل و CSV (*.xlsx *.xls *.csv)",
        )
        if not path:
            return
        self._path = path
        self._file_label.setText(f"فایل: {path}")
        try:
            headers = read_headers(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطا", f"خواندن فایل ناموفق: {exc}")
            return
        self.col_code.clear()
        self.col_qty.clear()
        for i, name in enumerate(headers):
            label = f"{i + 1}: {name}"
            self.col_code.addItem(label, i)
            self.col_qty.addItem(label, i)
        # حدس اولیه بر اساس نام ستون
        for i, name in enumerate(headers):
            if "کد" in name:
                self.col_code.setCurrentIndex(i)
            if "موجود" in name or "تعداد" in name:
                self.col_qty.setCurrentIndex(i)
        self.apply_btn.setEnabled(True)

    def _apply(self) -> None:
        if not self._path:
            return
        mapping = ColumnMapping(
            code=self.col_code.currentData(),
            quantity=self.col_qty.currentData(),
        )
        self._set_busy(True)
        worker = ImportWorker(self.db, self.store, self._path, mapping, False)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status.setText)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_done(self, result) -> None:
        self._set_busy(False)
        QMessageBox.information(
            self, "انجام شد",
            f"موجودی {self._fa(result.applied_count)} محصول به‌روز شد.",
        )

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(self, "خطا", message)

    def _set_busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.apply_btn.setEnabled(not busy and self._path is not None)

    @staticmethod
    def _fa(n) -> str:
        return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
