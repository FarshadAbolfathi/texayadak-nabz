"""تب محصولات سایت — مدیریت کامل محصولات ووکامرس.

همهٔ ستون‌ها (جز شناسه) قابل ویرایش‌اند: تصویر شاخص، کد، نام، قیمت،
قیمت ویژه، موجودی، وضعیت موجودی، وضعیت انتشار و دسته‌بندی‌ها. تغییرات
اول فقط در جدول علامت می‌خورند (رنگی) و با «ذخیرهٔ تغییرات» یک‌جا روی
سایت اعمال می‌شوند. تغییر قیمت/موجودی مثل سینک در «گزارش‌ها» ثبت
می‌شود و با «بازگرداندن» قابل برگشت است.

ویرایش گروهی (دسته، قیمت درصدی، وضعیت‌ها)، افزودن محصول دستی، انتقال
به زباله‌دان و خروجی اکسل هم اینجاست.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import jalali
from ...config import CredentialStore
from ...db import Database, Snapshot
from ...skucode import digits_only, normalize
from ...targets.woocommerce import WooProduct
from ..category_dialog import CategoryDialog
from ..services import woo_client_from_store
from ..widgets import fa, make_copyable, money, muted
from ..workers import run_async

STOCK_STATUS = [("instock", "موجود"), ("outofstock", "ناموجود"),
                ("onbackorder", "پیش‌سفارش")]
PUBLISH_STATUS = [("publish", "منتشرشده"), ("draft", "پیش‌نویس"),
                  ("pending", "در انتظار بررسی"), ("private", "خصوصی")]

_CHANGED = QColor("#e3f2fd")


def _clean_price(text: str) -> str:
    """«۱٬۲۵۰٬۰۰۰» → «1250000»؛ نقطهٔ اعشار (اولی) حفظ می‌شود.

    >>> _clean_price("۱٬۲۵۰٬۰۰۰ تومان"), _clean_price("99.50")
    ('1250000', '99.50')
    """
    import re

    from ...skucode import to_ascii_digits
    value = re.sub(r"[^0-9.]", "", to_ascii_digits(str(text)).replace("٫", "."))
    head, dot, tail = value.partition(".")
    return head + (dot + tail.replace(".", "") if tail else "")
THUMB = 48


# -- کارهای پس‌زمینه --------------------------------------------------------


def _fetch(store: CredentialStore):
    woo = woo_client_from_store(store)
    if woo is None:
        raise RuntimeError("اطلاعات اتصال ووکامرس کامل نیست.")
    return woo.fetch_products(), woo.fetch_categories()


def _save(store: CredentialStore, updates: list[dict], uploads: dict[int, tuple]):
    """اول تصاویر محلی را آپلود، بعد همهٔ تغییرات را یک‌جا ارسال می‌کند."""
    woo = woo_client_from_store(store)
    if woo is None:
        raise RuntimeError("اطلاعات اتصال ووکامرس کامل نیست.")
    errors: dict[int, str] = {}
    by_id = {u["id"]: u for u in updates}
    for pid, (path, title, gallery) in uploads.items():
        try:
            media_id, _ = woo.upload_media(path, title=title)
            by_id[pid]["images"] = [{"id": media_id}, *({"id": g} for g in gallery)]
        except Exception as exc:  # noqa: BLE001
            errors[pid] = f"آپلود تصویر: {exc}"
            by_id[pid].pop("images", None)
    ready = [u for u in updates if len(u) > 1]
    outcome = woo.batch_update(ready)
    outcome.failed.update(errors)
    return outcome


def _create_one(store: CredentialStore, payload: dict):
    woo = woo_client_from_store(store)
    if woo is None:
        raise RuntimeError("اطلاعات اتصال ووکامرس کامل نیست.")
    created, failed = woo.batch_create([payload])
    if failed:
        raise RuntimeError(next(iter(failed.values())))
    return created[0]


def _trash(store: CredentialStore, ids: list[int]):
    woo = woo_client_from_store(store)
    if woo is None:
        raise RuntimeError("اطلاعات اتصال ووکامرس کامل نیست.")
    return woo.batch_delete(ids)


# -- delegate ها --------------------------------------------------------------


class ComboDelegate(QStyledItemDelegate):
    """ویرایش ستون با فهرست کشویی؛ مقدار واقعی در UserRole نگه داشته می‌شود."""

    def __init__(self, options: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.options = options

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        for value, label in self.options:
            combo.addItem(label, value)
        return combo

    def setEditorData(self, editor, index):
        i = editor.findData(index.data(Qt.ItemDataRole.UserRole))
        editor.setCurrentIndex(max(i, 0))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentData(), Qt.ItemDataRole.UserRole)
        model.setData(index, editor.currentText(), Qt.ItemDataRole.DisplayRole)


class MoneyDelegate(QStyledItemDelegate):
    """قیمت خام (۱۲۵۰۰۰۰) را با جداکنندهٔ هزارگان نشان می‌دهد."""

    def displayText(self, value, locale):
        text = str(value or "").strip()
        if text and text.replace(".", "", 1).isdigit():
            return money(text, unit="")
        return text


# -- پنجرهٔ تصویر ---------------------------------------------------------------


class ImageDialog(QDialog):
    """انتخاب تصویر شاخص: فایل از کامپیوتر، آدرس اینترنتی، یا حذف."""

    def __init__(self, current: QPixmap | None, can_upload: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تصویر شاخص")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.result_action: tuple[str, str] | None = None
        layout = QVBoxLayout(self)
        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumSize(260, 260)
        if current is not None and not current.isNull():
            preview.setPixmap(current.scaled(
                260, 260, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            preview.setText("بدون تصویر")
        layout.addWidget(preview)

        file_btn = QPushButton("📁  انتخاب فایل از کامپیوتر")
        file_btn.setObjectName("Primary")
        file_btn.clicked.connect(self._pick_file)
        layout.addWidget(file_btn)
        if not can_upload:
            layout.addWidget(muted(
                "برای آپلود فایل، در «تنظیمات» نام کاربری و «رمز برنامه» "
                "(Application Password) وردپرس را وارد کنید. تا آن موقع می‌توانید "
                "از آدرس اینترنتی تصویر استفاده کنید."))
            file_btn.setEnabled(False)
        url_btn = QPushButton("🔗  آدرس اینترنتی تصویر")
        url_btn.clicked.connect(self._pick_url)
        layout.addWidget(url_btn)
        remove_btn = QPushButton("🗑  حذف تصویر شاخص")
        remove_btn.setObjectName("Danger")
        remove_btn.clicked.connect(lambda: self._done(("remove", "")))
        layout.addWidget(remove_btn)
        cancel = QPushButton("انصراف")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def _done(self, action: tuple[str, str]) -> None:
        self.result_action = action
        self.accept()

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب تصویر", "", "تصویر (*.jpg *.jpeg *.png *.webp *.gif)")
        if path:
            self._done(("file", path))

    def _pick_url(self) -> None:
        url, ok = QInputDialog.getText(self, "آدرس تصویر", "آدرس کامل تصویر (https://...):")
        url = url.strip()
        if ok and url.startswith(("http://", "https://")):
            self._done(("url", url))


# -- پنجرهٔ افزودن محصول -------------------------------------------------------


class NewProductDialog(QDialog):
    def __init__(self, categories, create_category, parent=None):
        super().__init__(parent)
        self.setWindowTitle("افزودن محصول جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(460, 320)
        self._categories = categories
        self._create_category = create_category
        self.category_ids: list[int] = []
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.sku = QLineEdit()
        self.price = QLineEdit()
        self.price.setPlaceholderText("تومان")
        self.stock = QSpinBox()
        self.stock.setRange(0, 1_000_000)
        self.status = QComboBox()
        for value, label in PUBLISH_STATUS[:2]:
            self.status.addItem(label, value)
        self.cat_btn = QPushButton("انتخاب دسته ...")
        self.cat_btn.clicked.connect(self._pick)
        form.addRow("نام محصول:", self.name)
        form.addRow("کد کالا (SKU):", self.sku)
        form.addRow("قیمت:", self.price)
        form.addRow("موجودی:", self.stock)
        form.addRow("وضعیت:", self.status)
        form.addRow("دسته‌بندی:", self.cat_btn)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("ساخت روی سایت")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("انصراف")
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def _pick(self) -> None:
        dlg = CategoryDialog(self._categories, self.category_ids,
                             create_category=self._create_category, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._categories.extend(dlg.created)
            self.category_ids = dlg.selected_ids()
            names = [c.name for c in self._categories if c.id in self.category_ids]
            self.cat_btn.setText("، ".join(names) or "انتخاب دسته ...")

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "ناقص", "نام محصول را وارد کنید.")
            return
        self.accept()

    def payload(self) -> dict:
        stock = self.stock.value()
        data = {
            "name": self.name.text().strip(),
            "type": "simple",
            "status": self.status.currentData(),
            "manage_stock": True,
            "stock_quantity": stock,
            "stock_status": "instock" if stock > 0 else "outofstock",
        }
        sku = self.sku.text().strip()
        if sku:
            data["sku"] = normalize(sku) or sku
        price = digits_only(self.price.text())
        if price:
            data["regular_price"] = price
        if self.category_ids:
            data["categories"] = [{"id": c} for c in self.category_ids]
        return data


# -- خودِ تب -------------------------------------------------------------------


class ProductsTab(QWidget):
    #: پس از ذخیرهٔ تغییرات (برای به‌روز شدن داشبورد)
    changed = Signal()

    HEADERS = ["تصویر", "شناسه", "کد (SKU)", "نام محصول", "قیمت (تومان)",
               "قیمت ویژه", "موجودی", "وضعیت موجودی", "وضعیت انتشار", "دسته‌بندی‌ها"]
    (COL_IMG, COL_ID, COL_SKU, COL_NAME, COL_PRICE, COL_SALE, COL_STOCK,
     COL_STOCK_STATUS, COL_STATUS, COL_CATS) = range(10)

    def __init__(self, db: Database, store: CredentialStore, parent=None):
        super().__init__(parent)
        self.db = db
        self.store = store
        self._products: list[WooProduct] = []
        self._by_id: dict[int, WooProduct] = {}
        self._categories = []
        self._cat_names: dict[int, str] = {}
        # تغییرات دسته/تصویر که در جدول متن ساده نیستند
        self._cat_changes: dict[int, list[int]] = {}
        self._img_changes: dict[int, tuple[str, str]] = {}
        self._thumbs: dict[str, QPixmap] = {}
        self._pending_thumbs: set[str] = set()
        self._filling = False
        self._net = None
        self._build()

    # -- ساخت رابط ----------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

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

        self.cat_filter = QComboBox()
        self.cat_filter.addItem("همهٔ دسته‌ها", None)
        self.cat_filter.currentIndexChanged.connect(lambda *_: self._filter())
        toolbar.addWidget(self.cat_filter)

        self.stock_filter = QComboBox()
        self.stock_filter.addItem("همهٔ وضعیت‌ها", None)
        for value, label in STOCK_STATUS:
            self.stock_filter.addItem(label, value)
        self.stock_filter.addItem("بدون تصویر", "__noimg")
        self.stock_filter.addItem("بدون دسته", "__nocat")
        self.stock_filter.addItem("فقط تغییرکرده‌ها", "__changed")
        self.stock_filter.currentIndexChanged.connect(lambda *_: self._filter())
        toolbar.addWidget(self.stock_filter)
        layout.addLayout(toolbar)

        actions = QHBoxLayout()
        self.add_btn = QPushButton("➕  محصول جدید")
        self.add_btn.clicked.connect(self._add_product)
        self.bulk_btn = QPushButton("🧰  ویرایش گروهی انتخاب‌شده‌ها")
        self.bulk_btn.clicked.connect(self._bulk_menu)
        self.trash_btn = QPushButton("🗑  انتقال به زباله‌دان")
        self.trash_btn.setObjectName("Danger")
        self.trash_btn.clicked.connect(self._trash_selected)
        self.export_btn = QPushButton("📤  خروجی اکسل")
        self.export_btn.clicked.connect(self._export)
        self.discard_btn = QPushButton("↩️  لغو تغییرات")
        self.discard_btn.clicked.connect(self._discard)
        self.save_btn = QPushButton("💾  ذخیرهٔ تغییرات")
        self.save_btn.setObjectName("Success")
        self.save_btn.clicked.connect(self._save)
        for b in (self.add_btn, self.bulk_btn, self.trash_btn, self.export_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.discard_btn)
        actions.addWidget(self.save_btn)
        layout.addLayout(actions)
        for b in (self.add_btn, self.bulk_btn, self.trash_btn, self.export_btn,
                  self.discard_btn, self.save_btn):
            b.setEnabled(False)

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
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(THUMB + 8)
        self.table.setIconSize(QSize(THUMB, THUMB))
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        widths = {self.COL_IMG: THUMB + 16, self.COL_ID: 70, self.COL_SKU: 150,
                  self.COL_PRICE: 120, self.COL_SALE: 110, self.COL_STOCK: 70,
                  self.COL_STOCK_STATUS: 110, self.COL_STATUS: 115, self.COL_CATS: 220}
        for col, w in widths.items():
            self.table.setColumnWidth(col, w)
        self.table.setItemDelegateForColumn(
            self.COL_STOCK_STATUS, ComboDelegate(STOCK_STATUS, self.table))
        self.table.setItemDelegateForColumn(
            self.COL_STATUS, ComboDelegate(PUBLISH_STATUS, self.table))
        self.table.setItemDelegateForColumn(self.COL_PRICE, MoneyDelegate(self.table))
        self.table.setItemDelegateForColumn(self.COL_SALE, MoneyDelegate(self.table))
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.verticalScrollBar().valueChanged.connect(
            lambda *_: self._thumb_timer.start())
        make_copyable(self.table, code_columns=(self.COL_SKU,),
                      on_copied=self.status.setText)
        layout.addWidget(self.table, 1)
        layout.addWidget(muted(
            "برای ویرایش هر خانه دابل‌کلیک کنید (یا شروع به تایپ کنید). روی "
            "«تصویر» یا «دسته‌بندی‌ها» دابل‌کلیک کنید تا پنجرهٔ انتخاب باز شود. "
            "خانه‌های تغییرکرده آبی می‌شوند و تا «ذخیرهٔ تغییرات» روی سایت نمی‌روند."
        ))

        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(150)
        self._thumb_timer.timeout.connect(self._load_visible_thumbs)

    # -- بارگذاری -----------------------------------------------------

    def _load(self) -> None:
        if self._has_changes():
            answer = QMessageBox.question(
                self, "تغییرات ذخیره‌نشده",
                "تغییرات ذخیره‌نشده از بین می‌روند. ادامه می‌دهید؟",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._busy(True, "در حال خواندن محصولات و دسته‌های سایت ...")
        run_async(self, _fetch, self.store,
                  on_done=self._on_loaded, on_failed=self._on_failed)

    def _on_loaded(self, result) -> None:
        products, categories = result
        self._busy(False)
        self._products = list(products)
        self._by_id = {p.id: p for p in self._products}
        self._set_categories(categories)
        self._cat_changes.clear()
        self._img_changes.clear()
        self._fill()
        self.status.setText(f"{fa(len(self._products))} محصول بارگذاری شد.")
        for b in (self.add_btn, self.bulk_btn, self.trash_btn, self.export_btn):
            b.setEnabled(True)
        self._update_save_state()

    def _set_categories(self, categories) -> None:
        self._categories = list(categories)
        self._cat_names = {c.id: c.name for c in self._categories}
        current = self.cat_filter.currentData()
        self.cat_filter.blockSignals(True)
        self.cat_filter.clear()
        self.cat_filter.addItem("همهٔ دسته‌ها", None)
        for c in sorted(self._categories, key=lambda c: c.name):
            self.cat_filter.addItem(f"{c.name} ({fa(c.count)})", c.id)
        idx = self.cat_filter.findData(current)
        self.cat_filter.setCurrentIndex(max(idx, 0))
        self.cat_filter.blockSignals(False)

    def _fill(self) -> None:
        self._filling = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._products))
        code_font = QFont("Consolas")
        code_font.setStyleHint(QFont.StyleHint.Monospace)
        for r, p in enumerate(self._products):
            img = QTableWidgetItem()
            img.setFlags(img.flags() & ~Qt.ItemFlag.ItemIsEditable)
            img.setData(Qt.ItemDataRole.UserRole, p.image_url)
            img.setToolTip("دابل‌کلیک برای تغییر تصویر شاخص")
            if not p.image_url:
                img.setText("＋")
                img.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, self.COL_IMG, img)

            pid = QTableWidgetItem(fa(p.id))
            pid.setFlags(pid.flags() & ~Qt.ItemFlag.ItemIsEditable)
            pid.setData(Qt.ItemDataRole.UserRole, p.id)
            pid.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, self.COL_ID, pid)

            sku = QTableWidgetItem(p.sku)
            sku.setFont(code_font)
            sku.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, self.COL_SKU, sku)
            self.table.setItem(r, self.COL_NAME, QTableWidgetItem(p.name))

            for col, value in ((self.COL_PRICE, p.regular_price),
                               (self.COL_SALE, p.sale_price)):
                cell = QTableWidgetItem(value or "")
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, col, cell)

            stock = QTableWidgetItem(
                "" if p.stock_quantity is None else str(p.stock_quantity))
            stock.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if not p.manage_stock:
                stock.setToolTip("مدیریت موجودی برای این محصول خاموش است؛ "
                                 "با وارد کردن عدد روشن می‌شود.")
            self.table.setItem(r, self.COL_STOCK, stock)

            for col, value, options in (
                (self.COL_STOCK_STATUS, p.stock_status, STOCK_STATUS),
                (self.COL_STATUS, p.status, PUBLISH_STATUS),
            ):
                labels = dict(options)
                cell = QTableWidgetItem(labels.get(value, value))
                cell.setData(Qt.ItemDataRole.UserRole, value)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, col, cell)

            cats = QTableWidgetItem(p.category_names)
            cats.setFlags(cats.flags() & ~Qt.ItemFlag.ItemIsEditable)
            cats.setToolTip("دابل‌کلیک برای تغییر دسته‌ها")
            self.table.setItem(r, self.COL_CATS, cats)
        self._filling = False
        self._filter()
        self._thumb_timer.start()

    # -- تصاویر کوچک ------------------------------------------------------

    def _network(self):
        if self._net is None:
            from PySide6.QtNetwork import QNetworkAccessManager
            self._net = QNetworkAccessManager(self)
            self._net.finished.connect(self._on_thumb_reply)
        return self._net

    def _load_visible_thumbs(self) -> None:
        if not self._products:
            return
        top = self.table.rowAt(0)
        bottom = self.table.rowAt(self.table.viewport().height() - 1)
        top = max(top, 0)
        bottom = self.table.rowCount() - 1 if bottom < 0 else bottom
        from PySide6.QtNetwork import QNetworkRequest
        for r in range(top, min(bottom + 3, self.table.rowCount())):
            item = self.table.item(r, self.COL_IMG)
            url = item.data(Qt.ItemDataRole.UserRole) if item else ""
            if not url or url in self._pending_thumbs:
                continue
            if url in self._thumbs:
                item.setIcon(QIcon(self._thumbs[url]))
                continue
            if url.startswith("file:"):
                pix = QPixmap(QUrl(url).toLocalFile())
                self._store_thumb(url, pix)
                continue
            self._pending_thumbs.add(url)
            request = QNetworkRequest(QUrl(url))
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
            self._network().get(request)

    def _on_thumb_reply(self, reply) -> None:
        url = reply.request().url().toString()
        self._pending_thumbs.discard(url)
        pix = QPixmap()
        if not reply.error():
            pix.loadFromData(reply.readAll())
        reply.deleteLater()
        self._store_thumb(url, pix)

    def _store_thumb(self, url: str, pix: QPixmap) -> None:
        if pix.isNull():
            return
        pix = pix.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        self._thumbs[url] = pix
        for r in range(self.table.rowCount()):
            item = self.table.item(r, self.COL_IMG)
            if item and item.data(Qt.ItemDataRole.UserRole) == url:
                item.setIcon(QIcon(pix))
                item.setText("")

    # -- ویرایش -------------------------------------------------------

    def _pid(self, row: int) -> int:
        return int(self.table.item(row, self.COL_ID).data(Qt.ItemDataRole.UserRole))

    def _original_value(self, p: WooProduct, col: int) -> str:
        return {
            self.COL_SKU: p.sku,
            self.COL_NAME: p.name,
            self.COL_PRICE: p.regular_price or "",
            self.COL_SALE: p.sale_price or "",
            self.COL_STOCK: "" if p.stock_quantity is None else str(p.stock_quantity),
            self.COL_STOCK_STATUS: p.stock_status,
            self.COL_STATUS: p.status,
        }.get(col, "")

    def _current_value(self, row: int, col: int) -> str:
        item = self.table.item(row, col)
        if item is None:
            return ""
        if col in (self.COL_STOCK_STATUS, self.COL_STATUS):
            return str(item.data(Qt.ItemDataRole.UserRole) or "")
        return item.text().strip()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        r, c = item.row(), item.column()
        if c in (self.COL_PRICE, self.COL_SALE, self.COL_STOCK):
            # فقط رقم (ارقام فارسی هم پذیرفته می‌شوند)؛ قیمت می‌تواند اعشار داشته باشد
            clean = (digits_only(item.text()) if c == self.COL_STOCK
                     else _clean_price(item.text()))
            if clean != item.text():
                self._filling = True
                item.setText(clean)
                self._filling = False
        self._refresh_row_marks(r)
        self._update_save_state()

    def _refresh_row_marks(self, r: int) -> None:
        p = self._by_id.get(self._pid(r))
        if p is None:
            return
        self._filling = True
        for c in (self.COL_SKU, self.COL_NAME, self.COL_PRICE, self.COL_SALE,
                  self.COL_STOCK, self.COL_STOCK_STATUS, self.COL_STATUS):
            item = self.table.item(r, c)
            changed = self._current_value(r, c) != self._original_value(p, c)
            item.setBackground(QBrush(_CHANGED) if changed else QBrush())
        cats = self.table.item(r, self.COL_CATS)
        cats.setBackground(QBrush(_CHANGED) if p.id in self._cat_changes else QBrush())
        img = self.table.item(r, self.COL_IMG)
        img.setBackground(QBrush(_CHANGED) if p.id in self._img_changes else QBrush())
        self._filling = False

    def _on_double_click(self, row: int, col: int) -> None:
        if col == self.COL_CATS:
            self._edit_categories([row])
        elif col == self.COL_IMG:
            self._edit_image(row)

    def _create_category(self, name: str, parent: int):
        woo = woo_client_from_store(self.store)
        if woo is None:
            raise RuntimeError("اطلاعات اتصال ووکامرس کامل نیست.")
        return woo.create_category(name, parent)

    def _row_categories(self, row: int) -> list[int]:
        pid = self._pid(row)
        if pid in self._cat_changes:
            return self._cat_changes[pid]
        return self._by_id[pid].category_ids

    def _set_row_categories(self, row: int, ids: list[int]) -> None:
        p = self._by_id[self._pid(row)]
        if sorted(ids) == sorted(p.category_ids):
            self._cat_changes.pop(p.id, None)
        else:
            self._cat_changes[p.id] = list(ids)
        self._filling = True
        self.table.item(row, self.COL_CATS).setText(
            "، ".join(self._cat_names.get(c, f"#{c}") for c in ids))
        self._filling = False
        self._refresh_row_marks(row)

    def _edit_categories(self, rows: list[int], mode: str = "set") -> None:
        if not rows:
            return
        first = self._row_categories(rows[0]) if mode == "set" else []
        title = {
            "set": "دسته‌بندی‌ها" if len(rows) == 1
                   else f"تعیین دسته برای {fa(len(rows))} محصول (جایگزینی)",
            "add": f"افزودن دسته به {fa(len(rows))} محصول",
            "remove": f"حذف دسته از {fa(len(rows))} محصول",
        }[mode]
        dlg = CategoryDialog(self._categories, first, title=title,
                             create_category=self._create_category, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.created:
            self._set_categories(self._categories + dlg.created)
        chosen = dlg.selected_ids()
        for r in rows:
            current = self._row_categories(r)
            if mode == "add":
                ids = current + [c for c in chosen if c not in current]
            elif mode == "remove":
                ids = [c for c in current if c not in chosen]
            else:
                ids = chosen
            self._set_row_categories(r, ids)
        self._update_save_state()

    def _edit_image(self, row: int) -> None:
        item = self.table.item(row, self.COL_IMG)
        url = item.data(Qt.ItemDataRole.UserRole)
        woo = woo_client_from_store(self.store)
        dlg = ImageDialog(self._thumbs.get(url), bool(woo and woo.can_upload_media), self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_action:
            return
        action, value = dlg.result_action
        pid = self._pid(row)
        self._img_changes[pid] = (action, value)
        self._filling = True
        item.setIcon(QIcon())
        if action == "remove":
            item.setData(Qt.ItemDataRole.UserRole, "")
            item.setText("✖")
        else:
            shown = QUrl.fromLocalFile(value).toString() if action == "file" else value
            item.setData(Qt.ItemDataRole.UserRole, shown)
            item.setText("…")
        self._filling = False
        self._refresh_row_marks(row)
        self._thumb_timer.start()
        self._update_save_state()

    # -- ویرایش گروهی --------------------------------------------------------

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedItems()
                       if not self.table.isRowHidden(i.row())})

    def _bulk_menu(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(
                self, "انتخاب", "ابتدا ردیف‌ها را انتخاب کنید (با Ctrl یا Shift).")
            return
        menu = QMenu(self)
        menu.addAction("🏷  افزودن دسته", lambda: self._edit_categories(rows, "add"))
        menu.addAction("🏷  حذف دسته", lambda: self._edit_categories(rows, "remove"))
        menu.addAction("🏷  تعیین دسته (جایگزینی)", lambda: self._edit_categories(rows, "set"))
        menu.addSeparator()
        menu.addAction("💰  تغییر درصدی قیمت", lambda: self._bulk_price(rows))
        menu.addAction("📦  تعیین موجودی", lambda: self._bulk_stock(rows))
        sub = menu.addMenu("وضعیت موجودی")
        for value, label in STOCK_STATUS:
            sub.addAction(label, lambda v=value, lb=label:
                          self._bulk_set(rows, self.COL_STOCK_STATUS, v, lb))
        sub = menu.addMenu("وضعیت انتشار")
        for value, label in PUBLISH_STATUS:
            sub.addAction(label, lambda v=value, lb=label:
                          self._bulk_set(rows, self.COL_STATUS, v, lb))
        menu.exec(self.bulk_btn.mapToGlobal(self.bulk_btn.rect().bottomLeft()))

    def _bulk_set(self, rows, col, value, label) -> None:
        for r in rows:
            item = self.table.item(r, col)
            self._filling = True
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setText(label)
            self._filling = False
            self._refresh_row_marks(r)
        self._update_save_state()

    def _bulk_price(self, rows) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("تغییر درصدی قیمت")
        dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        form = QFormLayout(dlg)
        percent = QDoubleSpinBox()
        percent.setRange(-90, 500)
        percent.setSuffix(" ٪")
        percent.setValue(10)
        step = QComboBox()
        for v, label in ((0, "بدون رند"), (1000, "هزار تومان"), (10000, "ده هزار تومان")):
            step.addItem(label, v)
        step.setCurrentIndex(1)
        form.addRow("درصد تغییر (منفی = کاهش):", percent)
        form.addRow("رند به:", step)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        from ...pricing import round_to_step
        factor = (Decimal(100) + Decimal(str(percent.value()))) / Decimal(100)
        changed = 0
        for r in rows:
            item = self.table.item(r, self.COL_PRICE)
            try:
                current = Decimal(item.text())
            except ArithmeticError:
                continue
            item.setText(str(round_to_step(current * factor,
                                           int(step.currentData()))))
            changed += 1
        self.status.setText(f"قیمت {fa(changed)} محصول تغییر کرد (هنوز ذخیره نشده).")

    def _bulk_stock(self, rows) -> None:
        value, ok = QInputDialog.getInt(self, "تعیین موجودی", "موجودی:", 0, 0, 1_000_000)
        if not ok:
            return
        for r in rows:
            self.table.item(r, self.COL_STOCK).setText(str(value))
            label = "موجود" if value > 0 else "ناموجود"
            self._bulk_set([r], self.COL_STOCK_STATUS,
                           "instock" if value > 0 else "outofstock", label)

    # -- فیلتر ------------------------------------------------------------

    def _filter(self, *_args) -> None:
        text = self.search.text().strip()
        cat = self.cat_filter.currentData()
        extra = self.stock_filter.currentData()
        for r in range(self.table.rowCount()):
            sku = self.table.item(r, self.COL_SKU).text()
            name = self.table.item(r, self.COL_NAME).text()
            visible = not text or text in sku or text in name or text == fa(sku)
            if visible and cat is not None:
                visible = cat in self._row_categories(r)
            if visible and extra:
                pid = self._pid(r)
                if extra == "__noimg":
                    visible = not self.table.item(r, self.COL_IMG).data(
                        Qt.ItemDataRole.UserRole)
                elif extra == "__nocat":
                    visible = not self._row_categories(r)
                elif extra == "__changed":
                    visible = bool(self._row_payload(r)) or pid in self._img_changes
                else:
                    visible = self._current_value(r, self.COL_STOCK_STATUS) == extra
            self.table.setRowHidden(r, not visible)
        self._thumb_timer.start()

    # -- ذخیره ------------------------------------------------------------

    def _row_payload(self, r: int) -> dict:
        """تغییرات یک ردیف به شکل ووکامرس (بدون تصویر)."""
        p = self._by_id.get(self._pid(r))
        if p is None:
            return {}
        payload: dict = {}
        cur = lambda c: self._current_value(r, c)  # noqa: E731
        if cur(self.COL_SKU) != p.sku:
            payload["sku"] = cur(self.COL_SKU)
        if cur(self.COL_NAME) != p.name and cur(self.COL_NAME):
            payload["name"] = cur(self.COL_NAME)
        if cur(self.COL_PRICE) != (p.regular_price or ""):
            payload["regular_price"] = cur(self.COL_PRICE)
        if cur(self.COL_SALE) != (p.sale_price or ""):
            payload["sale_price"] = cur(self.COL_SALE)
        old_stock = "" if p.stock_quantity is None else str(p.stock_quantity)
        if cur(self.COL_STOCK) != old_stock:
            if cur(self.COL_STOCK) == "":
                payload["manage_stock"] = False
            else:
                payload["manage_stock"] = True
                payload["stock_quantity"] = int(cur(self.COL_STOCK))
        if cur(self.COL_STOCK_STATUS) != p.stock_status:
            payload["stock_status"] = cur(self.COL_STOCK_STATUS)
        if cur(self.COL_STATUS) != p.status:
            payload["status"] = cur(self.COL_STATUS)
        if p.id in self._cat_changes:
            payload["categories"] = [{"id": c} for c in self._cat_changes[p.id]]
        return payload

    def _has_changes(self) -> bool:
        if self._img_changes or self._cat_changes:
            return True
        return any(self._row_payload(r) for r in range(self.table.rowCount()))

    def _update_save_state(self) -> None:
        count = sum(
            1 for r in range(self.table.rowCount())
            if self._row_payload(r) or self._pid(r) in self._img_changes
        )
        self.save_btn.setEnabled(count > 0)
        self.discard_btn.setEnabled(count > 0)
        self.save_btn.setText(
            f"💾  ذخیرهٔ تغییرات ({fa(count)})" if count else "💾  ذخیرهٔ تغییرات")

    def _discard(self) -> None:
        self._cat_changes.clear()
        self._img_changes.clear()
        self._fill()
        self._update_save_state()

    def _save(self) -> None:
        updates: list[dict] = []
        uploads: dict[int, tuple] = {}
        snapshots: list[Snapshot] = []
        problems: list[str] = []
        for r in range(self.table.rowCount()):
            pid = self._pid(r)
            p = self._by_id[pid]
            payload = self._row_payload(r)
            regular = payload.get("regular_price", p.regular_price)
            sale = payload.get("sale_price", p.sale_price)
            if sale and regular and Decimal(sale) >= Decimal(regular):
                problems.append(f"• {p.name}: قیمت ویژه باید کمتر از قیمت اصلی باشد.")
                continue
            image = self._img_changes.get(pid)
            gallery = self._gallery_ids(p)
            if image:
                action, value = image
                if action == "remove":
                    payload["images"] = [{"id": g} for g in gallery]
                elif action == "url":
                    payload["images"] = [{"src": value}, *({"id": g} for g in gallery)]
                else:
                    uploads[pid] = (value, payload.get("name", p.name), gallery)
            if not payload and pid not in uploads:
                continue
            updates.append({"id": pid, **payload})
            if "regular_price" in payload or "stock_quantity" in payload:
                new_stock = payload.get("stock_quantity")
                snapshots.append(Snapshot(
                    product_id=pid, sku=normalize(p.sku),
                    old_price=p.regular_price or None,
                    new_price=payload.get("regular_price"),
                    old_stock=p.stock_quantity,
                    new_stock=new_stock,
                    old_status=p.stock_status,
                    new_status=payload.get("stock_status", p.stock_status),
                ))
        if problems:
            QMessageBox.warning(self, "خطا در مقادیر", "\n".join(problems[:15]))
            return
        if not updates:
            QMessageBox.information(self, "تغییری نیست", "هیچ تغییری برای ذخیره نیست.")
            return
        answer = QMessageBox.question(
            self, "ذخیره",
            f"تغییرات {fa(len(updates))} محصول روی سایت اعمال شود؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._pending_snapshots = snapshots
        self._busy(True, "در حال ذخیره روی سایت ...")
        run_async(self, _save, self.store, updates, uploads,
                  on_done=self._on_saved, on_failed=self._on_failed)

    @staticmethod
    def _gallery_ids(p: WooProduct) -> list[int]:
        return list(p.gallery_ids)

    def _on_saved(self, outcome) -> None:
        self._busy(False)
        applied = set(outcome.updated)
        snaps = self._pending_snapshots
        if snaps:
            run_id = self.db.start_run("edit")
            for s in snaps:
                s.applied = s.product_id in applied
            self.db.record_snapshots(run_id, snaps)
            self.db.finish_run(run_id, "done",
                               {"applied": len(applied), "failed": len(outcome.failed)})
        self.db.log("info", f"ویرایش محصولات: {len(applied)} موفق، "
                            f"{len(outcome.failed)} خطا.")
        text = f"{fa(len(applied))} محصول به‌روز شد."
        if outcome.failed:
            names = {p.id: p.name for p in self._products}
            text += "\n\nخطاها:\n" + "\n".join(
                f"• {names.get(pid, pid)}: {msg}"
                for pid, msg in list(outcome.failed.items())[:15])
            QMessageBox.warning(self, "نتیجه", text)
        else:
            QMessageBox.information(self, "ذخیره شد", text)
        self.changed.emit()
        self._cat_changes.clear()
        self._img_changes.clear()
        self._load()

    # -- افزودن / حذف ---------------------------------------------------------

    def _add_product(self) -> None:
        dlg = NewProductDialog(self._categories, self._create_category, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dlg.payload()
        self._busy(True, "در حال ساخت محصول ...")

        def done(pid) -> None:
            self._busy(False)
            self.db.log("info", f"محصول «{payload['name']}» (شناسهٔ {pid}) دستی ساخته شد.")
            QMessageBox.information(self, "ساخته شد", f"محصول با شناسهٔ {fa(pid)} ساخته شد.")
            self._load()

        run_async(self, _create_one, self.store, payload,
                  on_done=done, on_failed=self._on_failed)

    def _trash_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "انتخاب", "ابتدا ردیف‌ها را انتخاب کنید.")
            return
        names = [self.table.item(r, self.COL_NAME).text() for r in rows]
        answer = QMessageBox.warning(
            self, "انتقال به زباله‌دان",
            f"{fa(len(rows))} محصول به زباله‌دان سایت منتقل شود؟\n\n"
            + "\n".join(f"• {n}" for n in names[:10])
            + ("\n…" if len(names) > 10 else "")
            + "\n\n(از پیشخوان وردپرس قابل بازگرداندن است)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        ids = [self._pid(r) for r in rows]
        self._busy(True, "در حال حذف ...")

        def done(outcome) -> None:
            self._busy(False)
            self.db.log("warn", f"{len(outcome.updated)} محصول به زباله‌دان منتقل شد: "
                                + "، ".join(names[:20]))
            QMessageBox.information(
                self, "انجام شد", f"{fa(len(outcome.updated))} محصول حذف شد.")
            self._load()

        run_async(self, _trash, self.store, ids, on_done=done, on_failed=self._on_failed)

    # -- خروجی --------------------------------------------------------------

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ خروجی اکسل", f"محصولات-{jalali.today()}.xlsx", "اکسل (*.xlsx)")
        if not path:
            return
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "محصولات"
            ws.sheet_view.rightToLeft = True
            ws.append(["شناسه", "کد", "نام", "قیمت", "قیمت ویژه", "موجودی",
                       "وضعیت موجودی", "وضعیت انتشار", "دسته‌بندی‌ها", "تصویر"])
            stock_fa, pub_fa = dict(STOCK_STATUS), dict(PUBLISH_STATUS)
            for p in self._products:
                ws.append([p.id, p.sku, p.name, p.regular_price, p.sale_price,
                           p.stock_quantity, stock_fa.get(p.stock_status, p.stock_status),
                           pub_fa.get(p.status, p.status), p.category_names, p.image_url])
            ws.append([])
            ws.append([f"تاریخ خروجی: {jalali.now_str()}"])
            wb.save(path)
            QMessageBox.information(self, "ذخیره شد", f"خروجی در {path} ذخیره شد.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطا", str(exc))

    # -- کمکی ----------------------------------------------------------------

    def _busy(self, busy: bool, text: str = "") -> None:
        self.progress.setVisible(busy)
        self.load_btn.setEnabled(not busy)
        self.save_btn.setEnabled(not busy and self._has_changes())
        if text:
            self.status.setText(text)

    def _on_failed(self, message: str) -> None:
        self._busy(False)
        self.status.setText(f"خطا: {message}")
        QMessageBox.critical(self, "خطا", message)

