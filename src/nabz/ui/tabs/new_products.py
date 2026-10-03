"""تب محصولات جدید حاسب — کالاهای موجود در حاسب که روی سایت نیستند.

جریان:
۱) «مقایسهٔ حاسب با سایت»: کالاهای حاسب که هیچ محصولی با همان کد روی
   سایت ندارند فهرست می‌شوند؛ قیمت (از ایساکو یا حاسب) و دستهٔ پیشنهادی
   هم حساب می‌شود. کارفرما شرط نمایش را انتخاب می‌کند: «موجودی و قیمت»
   (پیش‌فرض)، «فقط موجودی» یا «فقط قیمت» — بدون نیاز به مقایسهٔ دوباره.
۲) کارفرما عنوان، قیمت، موجودی و دسته را بازبینی/ویرایش می‌کند.
۳) با «ارسال به سایت» و تأیید، فقط ردیف‌های تیک‌خورده ساخته می‌شوند.

این تب هرگز خودکار چیزی روی سایت نمی‌سازد و بخشی از سینک زمان‌بندی‌شده
نیست؛ سینک فقط خبر می‌دهد که کالای جدیدی پیدا شده است.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QButtonGroup,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config import CredentialStore
from ...db import Database
from ...new_products import (
    CRITERIA,
    DEFAULT_CRITERIA,
    NewProduct,
    build_candidates,
    find_missing,
    matches_criteria,
    price_for,
    site_skus,
    to_woo_create,
)
from ...skucode import digits_only
from ..category_dialog import CategoryDialog
from ..category_rules_dialog import CategoryRulesDialog
from ..services import (
    categorizer_from_db,
    price_rules_from_db,
    stock_rules_from_db,
    woo_client_from_store,
)
from ..widgets import Card, fa, make_copyable, money, muted, setup_columns
from ..workers import run_async


def _compare(db: Database, store: CredentialStore, all_warehouses: bool) -> dict:
    """در پس‌زمینه: حاسب + سایت + (اختیاری) ایساکو → فهرست محصولات جدید."""
    from ...sources.haseb_dbf import load_products as load_haseb
    from ...sources.isaco_excel import load as load_isaco

    haseb_path = db.get_setting("haseb_cal_path", "")
    if not (haseb_path and Path(haseb_path).is_file()):
        raise RuntimeError("مسیر فایل حاسب (cal.DBF) در تنظیمات تعیین نشده یا پیدا نشد.")
    woo = woo_client_from_store(store)
    if woo is None:
        raise RuntimeError("اطلاعات اتصال ووکامرس در تنظیمات کامل نیست.")

    warehouses = None if all_warehouses else db.get_setting("isaco_warehouses", None)
    haseb = load_haseb(haseb_path, warehouses=set(warehouses) if warehouses else None)

    products = woo.fetch_products()
    extra: list[str] = []
    for p in products:
        if p.type == "variable":
            extra.extend(woo.fetch_variation_skus(p.id))
    categories = woo.fetch_categories()

    isaco = {}
    isaco_path = db.get_setting("isaco_excel_path", "")
    if isaco_path and Path(isaco_path).is_file():
        try:
            isaco = load_isaco(isaco_path)
        except Exception:  # noqa: BLE001 - قیمت ایساکو اختیاری است
            isaco = {}

    ignored = db.get_setting("new_products_ignored", []) or []
    price_rules = price_rules_from_db(db)
    # همهٔ غایب‌ها که «موجودی یا قیمت» دارند؛ فیلتر شرط انتخابی در خود جدول
    # انجام می‌شود تا تغییر شرط بدون خواندن دوبارهٔ سایت اعمال شود.
    missing = [
        m for m in find_missing(haseb, site_skus(products, extra),
                                ignored=ignored, min_quantity=None)
        if m.quantity > 0 or price_for(m, isaco.get(m.code), price_rules)[0]
    ]
    candidates = build_candidates(
        missing,
        isaco=isaco,
        price_rules=price_rules,
        stock_rules=stock_rules_from_db(db),
        categorizer=categorizer_from_db(db, categories),
    )
    criteria = db.get_setting("new_products_criteria", DEFAULT_CRITERIA)
    codes = [c.code for c in candidates if matches_criteria(c, criteria)]
    db.set_setting("new_products_pending", codes)
    seen = set(db.get_setting("new_products_seen", []) or [])
    db.set_setting("new_products_seen", sorted(seen | set(codes)))
    db.set_setting("new_products_unread", False)
    return {
        "candidates": candidates,
        "categories": categories,
        "haseb_count": len(haseb),
        "site_count": len(products),
        "isaco": bool(isaco),
    }


def _create(store: CredentialStore, payloads: list[dict]):
    woo = woo_client_from_store(store)
    if woo is None:
        raise RuntimeError("اطلاعات اتصال ووکامرس کامل نیست.")
    return woo.batch_create(payloads)


class NewProductsTab(QWidget):
    #: وقتی تعداد «خوانده‌نشده‌ها» عوض شد (برای برچسب تب در پنجرهٔ اصلی)
    badge_changed = Signal(int)

    HEADERS = ["✓", "کد (SKU)", "عنوان محصول", "قیمت (تومان)", "منبع قیمت",
               "موجودی حاسب", "موجودی سایت", "دسته‌بندی", "انبار"]
    (COL_CHECK, COL_CODE, COL_NAME, COL_PRICE, COL_SOURCE,
     COL_HASEB, COL_STOCK, COL_CATS, COL_WH) = range(9)

    def __init__(self, db: Database, store: CredentialStore, parent=None):
        super().__init__(parent)
        self.db = db
        self.store = store
        self._candidates: list[NewProduct] = []
        self._compare_info: dict | None = None
        self._categories = []
        self._categorizer = None
        self._filling = False
        self._build()
        self.refresh_banner()

    # -- ساخت رابط ----------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)

        header = QLabel("محصولات جدید حاسب")
        header.setObjectName("H1")
        layout.addWidget(header)

        self.banner = QFrame()
        self.banner.setObjectName("Card")
        self.banner.setStyleSheet(
            "QFrame#Card { background: #fff4e5; border: 1px solid #f5a623; }")
        banner_layout = QHBoxLayout(self.banner)
        self.banner_text = QLabel("")
        self.banner_text.setWordWrap(True)
        banner_layout.addWidget(self.banner_text, 1)
        self.banner.hide()
        layout.addWidget(self.banner)

        toolbar = Card()
        row = QHBoxLayout()
        self.compare_btn = QPushButton("🔍  مقایسهٔ حاسب با سایت")
        self.compare_btn.setObjectName("Primary")
        self.compare_btn.setMinimumHeight(44)
        self.compare_btn.clicked.connect(self.compare)
        row.addWidget(self.compare_btn, 2)

        self.all_wh = QCheckBox("همهٔ انبارهای حاسب")
        self.all_wh.setToolTip(
            "خاموش: فقط انبارهایی که برای سینک تعیین شده‌اند.\n"
            "روشن: کالاهای همهٔ انبارها بررسی می‌شوند.")
        self.all_wh.setChecked(bool(self.db.get_setting("new_products_all_wh", False)))
        self.all_wh.toggled.connect(
            lambda on: self.db.set_setting("new_products_all_wh", on))
        row.addWidget(self.all_wh)

        rules_btn = QPushButton("🏷  تنظیم دسته‌بندی خودکار")
        rules_btn.clicked.connect(self._open_rules)
        row.addWidget(rules_btn, 1)
        toolbar.body().addLayout(row)

        crit_row = QHBoxLayout()
        crit_label = QLabel("شرط نمایش کالاهایی که روی سایت نیستند:")
        crit_label.setObjectName("FieldLabel")
        crit_row.addWidget(crit_label)
        self.criteria_group = QButtonGroup(self)
        self.criteria_buttons: dict[str, QRadioButton] = {}
        saved = self.db.get_setting("new_products_criteria", DEFAULT_CRITERIA)
        if saved not in CRITERIA:
            saved = DEFAULT_CRITERIA
        for key, label in CRITERIA.items():
            btn = QRadioButton(label)
            btn.setProperty("criteria", key)
            btn.setChecked(key == saved)
            self.criteria_group.addButton(btn)
            self.criteria_buttons[key] = btn
            crit_row.addWidget(btn)
        crit_row.addStretch(1)
        self.criteria_group.buttonToggled.connect(self._on_criteria_toggled)
        toolbar.body().addLayout(crit_row)
        toolbar.add(muted(
            "کالاهای حاسب که هیچ محصولی با همان کد روی سایت ندارند، با شرط بالا "
            "نشان داده می‌شوند (پیش‌فرض: هم موجودی و هم قیمت داشته باشند). قیمت از "
            "لیست ایساکو (با همان درصد سود سینک) و اگر نبود از قیمت فروش حاسب حساب "
            "می‌شود؛ دسته هم خودکار پیشنهاد می‌شود. هیچ محصولی بدون تأیید شما روی "
            "سایت ساخته نمی‌شود."
        ))
        layout.addWidget(toolbar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = muted("")
        layout.addWidget(self.status)

        filter_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو با نام یا کد ...")
        self.search.textChanged.connect(lambda *_: self._apply_filters())
        filter_row.addWidget(self.search, 1)
        sel_all = QPushButton("انتخاب همه")
        sel_all.clicked.connect(lambda: self._set_all_checked(True))
        sel_none = QPushButton("هیچ‌کدام")
        sel_none.clicked.connect(lambda: self._set_all_checked(False))
        bulk_cat = QPushButton("🏷  دسته برای انتخاب‌شده‌ها")
        bulk_cat.clicked.connect(self._bulk_categories)
        resuggest = QPushButton("♻️  پیشنهاد مجدد دسته")
        resuggest.clicked.connect(self._resuggest)
        for b in (sel_all, sel_none, bulk_cat, resuggest):
            filter_row.addWidget(b)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed)
        # همهٔ ستون‌ها با کشیدن لبهٔ سرستون قابل تغییر عرض‌اند (دابل‌کلیک روی
        # لبه = اندازهٔ خودکار)؛ عرض‌ها برای دفعهٔ بعد هم ذخیره می‌شوند.
        setup_columns(self.table, {
            self.COL_CHECK: 40, self.COL_CODE: 130, self.COL_NAME: 420,
            self.COL_PRICE: 120, self.COL_SOURCE: 90, self.COL_HASEB: 115,
            self.COL_STOCK: 115, self.COL_CATS: 240, self.COL_WH: 140,
        }, db=self.db, key="cols_new_products", fixed=(self.COL_CHECK,))
        from .products import MoneyDelegate
        self.table.setItemDelegateForColumn(self.COL_PRICE, MoneyDelegate(self.table))
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.itemChanged.connect(self._on_item_changed)
        make_copyable(self.table, code_columns=(self.COL_CODE,),
                      on_copied=self.status.setText)
        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("وضعیت محصول روی سایت:"))
        self.publish = QComboBox()
        self.publish.addItem("منتشر شود", "publish")
        self.publish.addItem("پیش‌نویس", "draft")
        self.publish.setToolTip("پیش‌نویس: محصول ساخته می‌شود ولی تا انتشار دستی "
                                "در سایت دیده نمی‌شود.")
        idx = self.publish.findData(self.db.get_setting("new_products_status", "publish"))
        self.publish.setCurrentIndex(max(idx, 0))
        self.publish.currentIndexChanged.connect(
            lambda *_: self.db.set_setting("new_products_status", self.publish.currentData()))
        bottom.addWidget(self.publish)
        bottom.addStretch(1)

        ignored_btn = QPushButton("👁  نادیده‌گرفته‌ها")
        ignored_btn.clicked.connect(self._manage_ignored)
        bottom.addWidget(ignored_btn)
        self.ignore_btn = QPushButton("🙈  نادیده گرفتن انتخاب‌شده‌ها")
        self.ignore_btn.clicked.connect(self._ignore_selected)
        bottom.addWidget(self.ignore_btn)
        self.send_btn = QPushButton("🚀  ارسال انتخاب‌شده‌ها به سایت")
        self.send_btn.setObjectName("Success")
        self.send_btn.setMinimumHeight(44)
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send)
        layout.addLayout(bottom)
        send_row = QHBoxLayout()
        send_row.addStretch(1)
        send_row.addWidget(self.send_btn)
        layout.addLayout(send_row)
        layout.addWidget(muted(
            "برای ویرایش عنوان، قیمت یا موجودی روی خانه دابل‌کلیک کنید. "
            "دابل‌کلیک روی ستون «دسته‌بندی» پنجرهٔ انتخاب دسته را باز می‌کند."
        ))

    # -- اعلان --------------------------------------------------------

    def unread_count(self) -> int:
        if not self.db.get_setting("new_products_unread", False):
            return 0
        return len(self.db.get_setting("new_products_pending", []) or [])

    def refresh_banner(self) -> None:
        pending = self.db.get_setting("new_products_pending", []) or []
        unread = self.unread_count()
        if unread:
            self.banner_text.setText(
                f"🆕  {fa(unread)} کالا در حاسب موجود است که روی سایت نیست. "
                "برای دیدن فهرست و ارسال به سایت، «مقایسهٔ حاسب با سایت» را بزنید."
            )
            self.banner.show()
        elif pending and not self._candidates:
            self.banner_text.setText(
                f"در آخرین بررسی {fa(len(pending))} کالای حاسب روی سایت نبود.")
            self.banner.show()
        else:
            self.banner.hide()
        self.badge_changed.emit(unread)

    # -- مقایسه -------------------------------------------------------

    def compare(self) -> None:
        self._set_busy(True, "در حال خواندن حاسب، محصولات و دسته‌های سایت ...")
        run_async(self, _compare, self.db, self.store, self.all_wh.isChecked(),
                  on_done=self._on_compared, on_failed=self._on_failed)

    def _on_compared(self, result: dict) -> None:
        self._set_busy(False)
        self._candidates = result["candidates"]
        self._categories = result["categories"]
        self._categorizer = categorizer_from_db(self.db, self._categories)
        self._compare_info = result
        self._fill()
        self._apply_filters()
        self.send_btn.setEnabled(bool(self._candidates))
        self.refresh_banner()

    def criteria(self) -> str:
        btn = self.criteria_group.checkedButton()
        return btn.property("criteria") if btn else DEFAULT_CRITERIA

    def _on_criteria_toggled(self, button, checked: bool) -> None:
        if not checked:
            return
        self.db.set_setting("new_products_criteria", self.criteria())
        if self._candidates:
            self._apply_filters()
            self.db.set_setting("new_products_pending", [
                c.code for c in self._candidates if matches_criteria(c, self.criteria())])
            self.refresh_banner()

    def _update_criteria_counts(self) -> None:
        for key, btn in self.criteria_buttons.items():
            label = CRITERIA[key]
            if self._candidates:
                n = sum(1 for c in self._candidates if matches_criteria(c, key))
                label += f" ({fa(n)})"
            btn.setText(label)

    def _status_text(self) -> str:
        info = self._compare_info
        shown = [c for r, c in enumerate(self._candidates)
                 if not self.table.isRowHidden(r)]
        text = f"{fa(len(shown))} کالای جدید با شرط «{CRITERIA[self.criteria()]}»"
        if info:
            text += (f" (از {fa(info['haseb_count'])} کالای حاسب و "
                     f"{fa(info['site_count'])} محصول سایت)")
        text += "."
        no_price = sum(1 for c in shown if not c.price)
        no_cat = sum(1 for c in shown if not c.category_ids)
        if no_price:
            text += f"  {fa(no_price)} بدون قیمت."
        if no_cat:
            text += f"  {fa(no_cat)} بدون دسته."
        if info and not info["isaco"]:
            text += "  (فایل ایساکو تنظیم نشده؛ قیمت فقط از حاسب.)"
        return text

    def _fill(self) -> None:
        self._filling = True
        self.table.setRowCount(len(self._candidates))
        code_font = QFont("Consolas")
        code_font.setStyleHint(QFont.StyleHint.Monospace)
        for r, cand in enumerate(self._candidates):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked)
            check.setData(Qt.ItemDataRole.UserRole, r)
            self.table.setItem(r, self.COL_CHECK, check)

            code = self._ro(cand.code)
            code.setFont(code_font)
            code.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, self.COL_CODE, code)

            name = QTableWidgetItem(cand.name)
            name.setToolTip(cand.name)
            self.table.setItem(r, self.COL_NAME, name)

            price = QTableWidgetItem("" if cand.price is None else str(cand.price))
            price.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price.setToolTip(money(cand.price))
            self.table.setItem(r, self.COL_PRICE, price)

            source = self._ro(cand.price_source or "—")
            source.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, self.COL_SOURCE, source)

            haseb = self._ro(fa(cand.haseb_quantity))
            haseb.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, self.COL_HASEB, haseb)

            stock = QTableWidgetItem(str(cand.stock))
            stock.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, self.COL_STOCK, stock)

            self.table.setItem(r, self.COL_CATS, self._ro(""))
            self._show_categories(r)
            self.table.setItem(r, self.COL_WH, self._ro(cand.warehouse))
            self._mark_row(r)
        self._filling = False

    @staticmethod
    def _ro(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _show_categories(self, r: int) -> None:
        cand = self._candidates[r]
        item = self.table.item(r, self.COL_CATS)
        names = self._categorizer.names(cand.category_ids) if self._categorizer else ""
        item.setText(names or "— انتخاب کنید —")
        tip = "\n".join(self._categorizer.path(c) for c in cand.category_ids) \
            if self._categorizer else ""
        if cand.category_reason:
            tip += f"\n({cand.category_reason})"
        item.setToolTip((tip.strip() + "\nدابل‌کلیک برای تغییر").strip())

    def _mark_row(self, r: int) -> None:
        """ردیف‌های ناقص (بدون قیمت یا دسته) با رنگ زرد مشخص می‌شوند."""
        cand = self._candidates[r]
        incomplete = not cand.price or not cand.category_ids
        brush = QBrush(QColor("#fff8e1")) if incomplete else QBrush()
        for c in range(self.table.columnCount()):
            item = self.table.item(r, c)
            if item is not None:
                item.setBackground(brush)

    # -- ویرایش -------------------------------------------------------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        r, c = item.row(), item.column()
        if r >= len(self._candidates):
            return
        cand = self._candidates[r]
        if c == self.COL_NAME:
            cand.name = item.text().strip()
            item.setToolTip(cand.name)
        elif c == self.COL_PRICE:
            digits = digits_only(item.text())
            cand.price = int(digits) if digits else None
            if cand.price_source != "دستی":
                cand.price_source = "دستی"
                self.table.item(r, self.COL_SOURCE).setText("دستی")
            item.setToolTip(money(cand.price))
        elif c == self.COL_STOCK:
            digits = digits_only(item.text())
            cand.stock = int(digits) if digits else 0
        self._mark_row(r)

    def _on_double_click(self, row: int, col: int) -> None:
        if col == self.COL_CATS:
            self._edit_categories([row])

    def _create_category(self, name: str, parent: int):
        woo = woo_client_from_store(self.store)
        if woo is None:
            raise RuntimeError("اطلاعات اتصال ووکامرس کامل نیست.")
        return woo.create_category(name, parent)

    def _edit_categories(self, rows: list[int]) -> None:
        if not rows or not self._categories:
            return
        first = self._candidates[rows[0]]
        title = (f"دسته‌بندی «{first.name}»" if len(rows) == 1
                 else f"دسته‌بندی برای {fa(len(rows))} محصول")
        dlg = CategoryDialog(self._categories, first.category_ids, title=title,
                             create_category=self._create_category, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.created:
            self._categories.extend(dlg.created)
            self._categorizer = categorizer_from_db(self.db, self._categories)
        ids = dlg.selected_ids()
        for r in rows:
            self._candidates[r].category_ids = list(ids)
            self._candidates[r].category_reason = "دستی"
            self._show_categories(r)
            self._mark_row(r)

    def _checked_rows(self) -> list[int]:
        return [
            r for r in range(self.table.rowCount())
            if not self.table.isRowHidden(r)
            and self.table.item(r, self.COL_CHECK).checkState() == Qt.CheckState.Checked
        ]

    def _set_all_checked(self, on: bool) -> None:
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for r in range(self.table.rowCount()):
            if not self.table.isRowHidden(r):
                self.table.item(r, self.COL_CHECK).setCheckState(state)

    def _bulk_categories(self) -> None:
        rows = self._checked_rows()
        if not rows:
            QMessageBox.information(self, "انتخاب", "ابتدا ردیف‌هایی را تیک بزنید.")
            return
        self._edit_categories(rows)

    def _resuggest(self) -> None:
        if not self._categories:
            return
        self._categorizer = categorizer_from_db(self.db, self._categories)
        for r in self._checked_rows():
            cand = self._candidates[r]
            s = self._categorizer.suggest(cand.name, cand.car)
            cand.category_ids, cand.category_reason = list(s.category_ids), s.reason
            self._show_categories(r)
            self._mark_row(r)
        self.status.setText("دسته‌های ردیف‌های انتخاب‌شده دوباره پیشنهاد شد.")

    def _open_rules(self) -> None:
        if not self._categories:
            woo = woo_client_from_store(self.store)
            if woo is None:
                QMessageBox.warning(self, "خطا", "اطلاعات اتصال ووکامرس کامل نیست.")
                return
            try:
                self._categories = woo.fetch_categories()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "خطا", f"دسته‌های سایت خوانده نشد:\n{exc}")
                return
        dlg = CategoryRulesDialog(self.db, self._categories,
                                  create_category=self._create_category, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and self._candidates:
            self._categorizer = categorizer_from_db(self.db, self._categories)
            answer = QMessageBox.question(
                self, "اعمال قواعد",
                "دسته‌های ردیف‌های انتخاب‌شده با قواعد جدید دوباره پیشنهاد شوند؟",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._resuggest()

    def _apply_filters(self) -> None:
        """شرط انتخابی (موجودی/قیمت) + متن جستجو؛ ردیف‌های نامرتبط مخفی می‌شوند."""
        text = self.search.text().strip()
        criteria = self.criteria()
        for r, cand in enumerate(self._candidates):
            code = self.table.item(r, self.COL_CODE).text()
            name = self.table.item(r, self.COL_NAME).text()
            hide = not matches_criteria(cand, criteria) or (
                bool(text) and text not in code and text not in name)
            self.table.setRowHidden(r, hide)
        self._update_criteria_counts()
        if self._candidates or self._compare_info:
            self.status.setText(self._status_text())

    # -- نادیده گرفتن ---------------------------------------------------

    def _ignore_selected(self) -> None:
        rows = self._checked_rows()
        if not rows:
            QMessageBox.information(self, "انتخاب", "ابتدا ردیف‌هایی را تیک بزنید.")
            return
        answer = QMessageBox.question(
            self, "نادیده گرفتن",
            f"{fa(len(rows))} کالا دیگر در این فهرست نمایش داده نشوند؟\n"
            "(از «نادیده‌گرفته‌ها» قابل بازگرداندن است)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        ignored = set(self.db.get_setting("new_products_ignored", []) or [])
        ignored.update(self._candidates[r].code for r in rows)
        self.db.set_setting("new_products_ignored", sorted(ignored))
        self._remove_rows(rows)

    def _manage_ignored(self) -> None:
        ignored = list(self.db.get_setting("new_products_ignored", []) or [])
        dlg = QDialog(self)
        dlg.setWindowTitle("کالاهای نادیده‌گرفته")
        dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        dlg.resize(360, 460)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("کدهای انتخاب‌شده دوباره در فهرست نشان داده می‌شوند:"))
        lst = QListWidget()
        for code in ignored:
            item = QListWidgetItem(code)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            lst.addItem(item)
        lay.addWidget(lst, 1)
        restore = QPushButton("بازگرداندن تیک‌خورده‌ها")
        restore.setObjectName("Primary")
        lay.addWidget(restore)

        def do_restore() -> None:
            keep = [lst.item(i).text() for i in range(lst.count())
                    if lst.item(i).checkState() != Qt.CheckState.Checked]
            self.db.set_setting("new_products_ignored", keep)
            dlg.accept()
            if len(keep) != len(ignored):
                self.status.setText("برای دیدن کالاهای بازگردانده، دوباره مقایسه کنید.")

        restore.clicked.connect(do_restore)
        dlg.exec()

    # -- ارسال به سایت --------------------------------------------------

    def _send(self) -> None:
        rows = self._checked_rows()
        if not rows:
            QMessageBox.information(self, "انتخاب", "هیچ ردیفی تیک نخورده است.")
            return
        chosen = [self._candidates[r] for r in rows]
        if any(not c.name for c in chosen):
            QMessageBox.warning(self, "ناقص", "عنوان بعضی ردیف‌ها خالی است.")
            return
        warnings = []
        no_price = sum(1 for c in chosen if not c.price)
        no_cat = sum(1 for c in chosen if not c.category_ids)
        if no_price:
            warnings.append(f"• {fa(no_price)} محصول قیمت ندارد (روی سایت قابل خرید نیست).")
        if no_cat:
            warnings.append(f"• {fa(no_cat)} محصول دسته‌بندی ندارد.")
        status = self.publish.currentData()
        msg = (
            f"{fa(len(chosen))} محصول جدید روی سایت ساخته شود "
            f"({'منتشرشده' if status == 'publish' else 'پیش‌نویس'})؟"
        )
        if warnings:
            msg += "\n\n" + "\n".join(warnings)
        answer = QMessageBox.question(
            self, "ارسال به سایت", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        payloads = [to_woo_create(c, status=status) for c in chosen]
        self._sending = rows
        self._set_busy(True, "در حال ساخت محصولات روی سایت ...")
        run_async(self, _create, self.store, payloads,
                  on_done=self._on_sent, on_failed=self._on_failed)

    def _on_sent(self, result) -> None:
        created, failed = result
        self._set_busy(False)
        rows = self._sending
        run_id = self.db.start_run("create")
        self.db.finish_run(run_id, "done" if not failed else "failed",
                           {"applied": len(created), "failed": len(failed)})
        names = [self._candidates[rows[i]].name for i in created]
        self.db.log(
            "info",
            f"ایجاد محصول جدید از حاسب: {len(created)} موفق، {len(failed)} خطا. "
            + "، ".join(names[:20]),
            run_id=run_id,
        )
        done_rows = [rows[i] for i in created]
        errors = [
            f"• {self._candidates[rows[i]].name}: {msg}" for i, msg in failed.items()
        ]
        # کدهای ساخته‌شده از فهرست «در انتظار» خارج شوند
        made = {self._candidates[r].code for r in done_rows}
        pending = [c for c in (self.db.get_setting("new_products_pending", []) or [])
                   if c not in made]
        self.db.set_setting("new_products_pending", pending)
        self._remove_rows(done_rows)

        text = f"{fa(len(created))} محصول روی سایت ساخته شد."
        if errors:
            text += "\n\nخطاها:\n" + "\n".join(errors[:15])
            QMessageBox.warning(self, "نتیجه", text)
        else:
            QMessageBox.information(self, "انجام شد", text)
        self.status.setText(text.split("\n")[0])

    def _remove_rows(self, rows: list[int]) -> None:
        drop = set(rows)
        self._candidates = [c for i, c in enumerate(self._candidates) if i not in drop]
        self._fill()
        self._apply_filters()
        self.send_btn.setEnabled(bool(self._candidates))
        self.refresh_banner()

    # -- کمکی ---------------------------------------------------------

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.progress.setVisible(busy)
        self.compare_btn.setEnabled(not busy)
        self.send_btn.setEnabled(not busy and bool(self._candidates))
        if text:
            self.status.setText(text)

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self.status.setText(f"خطا: {message}")
        QMessageBox.critical(self, "خطا", message)
