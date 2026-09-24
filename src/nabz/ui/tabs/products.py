"""تب محصولات سایت — مشاهده، ویرایش دستی قیمت/موجودی، و خروجی اکسل."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
from ..services import woo_client_from_store
from ..widgets import Card, muted


class FetchWorker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, store):
        super().__init__()
        self.store = store

    def run(self) -> None:
        try:
            woo = woo_client_from_store(self.store)
            if woo is None:
                self.failed.emit("اطلاعات اتصال ووکامرس کامل نیست.")
                return
            self.done.emit(woo.fetch_products())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class ProductsTab(QWidget):
    HEADERS = ["شناسه", "کد (SKU)", "نام", "قیمت (تومان)", "موجودی"]

    def __init__(self, db: Database, store: CredentialStore, parent=None):
        super().__init__(parent)
        self.db = db
        self.store = store
        self._products = []
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QLabel("محصولات سایت")
        header.setObjectName("H1")
        layout.addWidget(header)

        toolbar = QHBoxLayout()
        self.load_btn = QPushButton("🔄  بارگذاری محصولات")
        self.load_btn.setObjectName("Primary")
        self.load_btn.clicked.connect(self._load)
        toolbar.addWidget(self.load_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو با نام یا کد ...")
        self.search.textChanged.connect(self._filter)
        toolbar.addWidget(self.search, 1)

        self.export_btn = QPushButton("📤  خروجی اکسل")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        toolbar.addWidget(self.export_btn)

        self.save_btn = QPushButton("💾  ذخیرهٔ تغییرات")
        self.save_btn.setObjectName("Success")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save)
        toolbar.addWidget(self.save_btn)
        layout.addLayout(toolbar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = muted("برای شروع، روی «بارگذاری محصولات» بزنید.")
        layout.addWidget(self.status)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table, 1)

    def _load(self) -> None:
        self.progress.show()
        self.load_btn.setEnabled(False)
        worker = FetchWorker(self.store)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_loaded)
        worker.failed.connect(self._on_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_loaded(self, products) -> None:
        self.progress.hide()
        self.load_btn.setEnabled(True)
        self._products = products
        self._fill(products)
        self.status.setText(f"{self._fa(len(products))} محصول بارگذاری شد.")
        self.export_btn.setEnabled(True)
        self.save_btn.setEnabled(True)

    def _fill(self, products) -> None:
        self.table.setRowCount(len(products))
        for r, p in enumerate(products):
            id_item = QTableWidgetItem(self._fa(p.id))
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            id_item.setData(Qt.ItemDataRole.UserRole, p.id)
            sku_item = QTableWidgetItem(p.sku)
            sku_item.setFlags(sku_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item = QTableWidgetItem(p.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            price_item = QTableWidgetItem(p.regular_price or "")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stock_item = QTableWidgetItem(
                "" if p.stock_quantity is None else str(p.stock_quantity)
            )
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            for c, item in enumerate(
                [id_item, sku_item, name_item, price_item, stock_item]
            ):
                self.table.setItem(r, c, item)

    def _filter(self, text: str) -> None:
        text = text.strip()
        for r in range(self.table.rowCount()):
            sku = self.table.item(r, 1).text()
            name = self.table.item(r, 2).text()
            self.table.setRowHidden(r, bool(text) and text not in sku and text not in name)

    def _save(self) -> None:
        """قیمت و موجودی ویرایش‌شده را با محصولات اصلی مقایسه و ارسال می‌کند."""
        by_id = {p.id: p for p in self._products}
        updates = []
        for r in range(self.table.rowCount()):
            pid = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            original = by_id.get(pid)
            if not original:
                continue
            new_price = self.table.item(r, 3).text().strip()
            new_stock = self.table.item(r, 4).text().strip()
            payload = {"id": pid}
            if new_price and new_price != (original.regular_price or ""):
                payload["regular_price"] = new_price
            if new_stock and new_stock != (
                "" if original.stock_quantity is None else str(original.stock_quantity)
            ):
                payload["manage_stock"] = True
                payload["stock_quantity"] = int(new_stock)
            if len(payload) > 1:
                updates.append(payload)

        if not updates:
            QMessageBox.information(self, "تغییری نیست", "هیچ تغییری برای ذخیره نیست.")
            return
        confirm = QMessageBox.question(
            self, "ذخیره",
            f"{self._fa(len(updates))} محصول تغییر کرده. روی سایت اعمال شود؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        woo = woo_client_from_store(self.store)
        if woo is None:
            QMessageBox.warning(self, "خطا", "اطلاعات اتصال کامل نیست.")
            return
        try:
            outcome = woo.batch_update(updates)
            self.db.log("info", f"ویرایش دستی: {len(outcome.updated)} محصول.")
            QMessageBox.information(
                self, "ذخیره شد",
                f"{self._fa(len(outcome.updated))} محصول به‌روز شد.",
            )
            self._load()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطا", str(exc))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ خروجی اکسل", "محصولات.xlsx", "اکسل (*.xlsx)"
        )
        if not path:
            return
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "محصولات"
            ws.append(["شناسه", "کد", "نام", "قیمت", "موجودی", "وضعیت"])
            for p in self._products:
                ws.append([p.id, p.sku, p.name, p.regular_price,
                           p.stock_quantity, p.stock_status])
            wb.save(path)
            QMessageBox.information(self, "ذخیره شد", f"خروجی در {path} ذخیره شد.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطا", str(exc))

    def _on_failed(self, message: str) -> None:
        self.progress.hide()
        self.load_btn.setEnabled(True)
        QMessageBox.critical(self, "خطا", message)

    @staticmethod
    def _fa(n) -> str:
        return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
