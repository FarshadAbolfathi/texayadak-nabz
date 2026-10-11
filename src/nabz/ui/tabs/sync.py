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
from pathlib import Path

_log = logging.getLogger("nabz.sync")

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QButtonGroup,
    QLineEdit,
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
from ...engine import MatchStatus, SyncPlan, build_plan
from ...runner import apply_plan, rollback_run
from ...sources.haseb_dbf import load_products as load_haseb
from ...sources.isaco_excel import load as load_isaco
from ..services import (
    price_rules_from_db,
    stock_rules_from_db,
    woo_client_from_store,
)
from ..widgets import Card, make_copyable, muted, setup_columns


#: دسته‌بندی ردیف‌های جدول سینک برای فیلتر و رنگ
ROW_KINDS: list[tuple[str, str]] = [
    ("all", "همه"),
    ("change", "تغییر دارد"),
    ("review", "بررسی شود"),
    ("same", "بدون تغییر"),
    ("no_isaco", "در ایساکو نیست"),
    ("other", "سایر"),
]

_KIND_BG = {"change": "#e3f2fd", "review": "#fff8e1", "other": "#f5f5f5"}


def row_kind(item, inc_price: bool = True) -> str:
    """یک محصول سایت پس از مقایسه در کدام دسته است؟

    - change: قیمت یا موجودی باید عوض شود
    - review: تغییر بزرگ است و محافظ فعال شده (دستی تأیید شود)
    - same: با ایساکو/حاسب یکی است؛ کاری لازم نیست
    - no_isaco: کد در لیست ایساکو نیست (قیمتش سینک نمی‌شود)
    - other: کد ندارد یا قیمت سایت خالی است
    """
    if item.needs_review:
        return "review"
    if item.changes:
        return "change"
    if item.match is MatchStatus.NO_SKU:
        return "other"
    if item.current_price is None and item.new_price:
        return "other"           # قیمت سایت خالی است؛ خودکار پر نمی‌شود
    if inc_price and item.match is MatchStatus.NO_ISACO_PRICE:
        return "no_isaco"
    return "same"


def row_status_text(item, kind: str, inc_stock: bool = True) -> str:
    if kind == "review":
        return "⚠️ بررسی شود (تغییر قیمت زیاد)"
    if kind == "change":
        parts = [p for p, on in (("قیمت", item.price_changes),
                                 ("موجودی", item.stock_changes)) if on]
        return "🔄 تغییر " + " و ".join(parts)
    if kind == "other":
        if item.match is MatchStatus.NO_SKU:
            return "کد (SKU) ندارد"
        return "قیمت سایت خالی است"
    if kind == "no_isaco":
        return "در لیست ایساکو نیست"
    text = "✓ بدون تغییر"
    if inc_stock and item.match is MatchStatus.NO_HASEB_STOCK:
        text += " (در حاسب نیست)"
    return text


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
            fresh = 0
            if haseb:
                from ...jobs import record_missing_products
                try:
                    _, fresh = record_missing_products(self.db, haseb, products, woo)
                except Exception:  # noqa: BLE001 - فقط اطلاع‌رسانی است
                    _log.warning("بررسی محصولات جدید حاسب نشد", exc_info=True)
            self.done.emit((plan, bool(isaco), bool(haseb), fresh))
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


class TableApplyWorker(QObject):
    """به‌روزرسانی‌های ساخته‌شده از جدول را اعمال و برای رول‌بک ثبت می‌کند."""

    progress = Signal(str)
    done = Signal(object)      # (تعداد موفق، تعداد خطا)
    failed = Signal(str)

    def __init__(self, db, store, updates, snapshots, mode="manual"):
        super().__init__()
        self.db, self.store = db, store
        self.updates, self.snapshots, self.mode = updates, snapshots, mode

    def run(self) -> None:
        try:
            self.progress.emit("در حال اعمال روی سایت ...")
            woo = woo_client_from_store(self.store)
            if woo is None:
                self.failed.emit("اطلاعات اتصال ووکامرس کامل نیست.")
                return
            run_id = self.db.start_run(self.mode)
            outcome = woo.batch_update(self.updates)
            applied = set(outcome.updated)
            for snap in self.snapshots:
                snap.applied = snap.product_id in applied
            self.db.record_snapshots(run_id, self.snapshots)
            self.db.finish_run(
                run_id, "done",
                {"applied": len(applied), "failed": len(outcome.failed)},
            )
            self.db.log(
                "info",
                f"اعمال {self.mode}: {len(applied)} محصول، {len(outcome.failed)} خطا.",
                run_id=run_id,
            )
            self.done.emit((len(applied), len(outcome.failed)))
        except Exception as exc:  # noqa: BLE001
            _log.exception("خطا در اعمال سینک")
            self.failed.emit(str(exc))


class SyncTab(QWidget):
    finished_apply = Signal()
    #: تعداد کالاهای تازه‌کشف‌شدهٔ حاسب که روی سایت نیستند
    new_products_found = Signal(int)

    HEADERS = ["کد (SKU)", "نام محصول", "قیمت فعلی", "قیمت جدید",
               "موجودی فعلی", "موجودی جدید", "وضعیت", "اعمال"]
    # ستون‌های قابل‌ویرایش: قیمت جدید و موجودی جدید
    COL_SKU, COL_NAME, COL_CUR_PRICE, COL_NEW_PRICE = 0, 1, 2, 3
    COL_CUR_STOCK, COL_NEW_STOCK, COL_STATUS, COL_APPLY = 4, 5, 6, 7

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
        # وضعیت لیست ایساکو: تازه است؟ امروز ایساکو چند قلم را عوض کرده؟
        self.isaco_info = QLabel("")
        self.isaco_info.setWordWrap(True)
        self.isaco_info.hide()
        layout.addWidget(self.isaco_info)

        # فیلتر وضعیت: بعد از مقایسه همهٔ محصولات سایت در جدول هستند
        filter_row = QHBoxLayout()
        self.kind_group = QButtonGroup(self)
        self.kind_buttons: dict[str, QRadioButton] = {}
        for key, label in ROW_KINDS:
            btn = QRadioButton(label)
            btn.setProperty("kind", key)
            self.kind_group.addButton(btn)
            self.kind_buttons[key] = btn
            filter_row.addWidget(btn)
        self.kind_buttons["all"].setChecked(True)
        self.kind_group.buttonToggled.connect(
            lambda _b, on: on and self._apply_filter())
        filter_row.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو با نام یا کد ...")
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(lambda *_: self._apply_filter())
        filter_row.addWidget(self.search)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(False)
        # فقط با دابل‌کلیک قابل ویرایش (تا اتفاقی تغییر نکند)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        # انتخاب خانه‌ای (نه ردیفی) تا بتوان فقط کد را انتخاب و کپی کرد
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.verticalHeader().setVisible(False)
        # عرض همهٔ ستون‌ها با کشیدن لبهٔ سرستون قابل تغییر است و ذخیره می‌شود؛
        # ستون کد آن‌قدر پهن که کد ۱۰ یا ۱۲ رقمی کامل دیده شود.
        setup_columns(self.table, {
            self.COL_SKU: 140, self.COL_NAME: 380, self.COL_CUR_PRICE: 130,
            self.COL_NEW_PRICE: 130, self.COL_CUR_STOCK: 110, self.COL_NEW_STOCK: 110,
            self.COL_STATUS: 230, self.COL_APPLY: 90,
        }, db=self.db, key="cols_sync_v2", stretch_last=False)
        # قیمت جدید هم مثل قیمت فعلی با جداکنندهٔ هزارگان (مقدار خام عدد می‌ماند)
        from .products import MoneyDelegate
        self.table.setItemDelegateForColumn(self.COL_NEW_PRICE, MoneyDelegate(self.table))
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.itemChanged.connect(self._on_item_edited)
        make_copyable(self.table, code_columns=(self.COL_SKU,),
                      on_copied=self.status.setText)
        layout.addWidget(self.table, 1)
        hint = muted(
            "برای ویرایش «قیمت جدید» یا «موجودی جدید» روی خانه دابل‌کلیک کنید. "
            "دابل‌کلیک روی کد آن را کپی می‌کند؛ Ctrl+C یا راست‌کلیک هم برای کپی "
            "کار می‌کند. دکمهٔ «اعمال» فقط همان محصول را روی سایت می‌گذارد."
        )
        layout.addWidget(hint)

        self._manual_path: str | None = None
        self._row_items: list = []  # نگاشت شمارهٔ ردیف → SyncItem
        self._row_kinds: list[str] = []
        self._edited_rows: set[int] = set()
        self._filling = False

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل لیست قیمت ایساکو", "", "فایل اکسل (*.xlsx *.xls)"
        )
        if path:
            self._manual_path = path
            self.status.setText(f"فایل دستی انتخاب شد: {path}")

    def _fetch(self) -> None:
        if not self._set_busy(True, "دریافت و مقایسه"):
            return
        self._downloaded_now = False
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
        from ...jobs import try_auto_download_isaco

        self.status.setText("در حال دانلود خودکار لیست قیمت از ایساکو ...")
        path = try_auto_download_isaco(
            self.db, self.store, on_progress=self.status.setText
        )
        self._downloaded_now = bool(path)
        if not path:
            self.status.setText(
                "دانلود خودکار نشد؛ از فایل تنظیم‌شده استفاده می‌شود (در صورت وجود)."
            )

    def _show_isaco_info(self, plan) -> None:
        from ...jobs import isaco_freshness

        if self._manual_path:
            text, stale = f"لیست ایساکو: فایل دستی ({Path(self._manual_path).name}).", False
        else:
            site = {i.sku for i in plan.items if i.sku}
            pending = {i.sku for i in plan.items if i.price_changes}
            text, stale = isaco_freshness(
                self.db, site, pending,
                downloaded_now=getattr(self, "_downloaded_now", False))
        color = "#c62828" if stale else "#2e7d32"
        self.isaco_info.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.isaco_info.setText(text)
        self.isaco_info.show()

    def _on_compared(self, result) -> None:
        plan, inc_price, inc_stock, fresh = result
        if inc_price:
            try:
                self._show_isaco_info(plan)
            except Exception:  # noqa: BLE001 - فقط اطلاع‌رسانی است
                _log.warning("نمایش وضعیت لیست ایساکو نشد", exc_info=True)
        self._plan = plan
        self._inc_price, self._inc_stock = inc_price, inc_stock
        self._fill_table(plan)
        self._set_busy(False)
        counts = self._kind_counts()
        total = len(self._row_items)
        self.status.setText(
            f"مقایسه انجام شد — {self._fa(total)} محصول سایت بررسی شد: "
            f"{self._fa(counts['change'])} تغییر، "
            f"{self._fa(counts['review'])} نیازمند بررسی، "
            f"{self._fa(counts['same'])} بدون تغییر، "
            f"{self._fa(counts['no_isaco'])} در ایساکو نیست، "
            f"{self._fa(counts['other'])} سایر."
        )
        # اگر تغییری هست همان‌ها، وگرنه کل فهرست (تا معلوم باشد مقایسه انجام شده)
        default = "change" if counts["change"] + counts["review"] else "all"
        self.kind_buttons[default].setChecked(True)
        self._apply_filter()
        self.apply_btn.setEnabled(counts["change"] + counts["review"] > 0)
        if fresh:
            self.new_products_found.emit(fresh)

    def _fill_table(self, plan: SyncPlan) -> None:
        """همهٔ محصولات سایت؛ ردیف‌های تغییر/بررسی اول، بعد بقیه."""
        order = {"review": 0, "change": 1, "other": 2, "no_isaco": 3, "same": 4}
        inc_price = getattr(self, "_inc_price", True)
        inc_stock = getattr(self, "_inc_stock", True)
        pairs = [(row_kind(i, inc_price), i) for i in plan.items]
        pairs.sort(key=lambda p: (order[p[0]], p[1].name))
        self._row_items = [i for _, i in pairs]
        self._row_kinds = [k for k, _ in pairs]
        self._edited_rows = set()

        self._filling = True
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(pairs))
        code_font = self._code_font()
        for r, (kind, item) in enumerate(pairs):
            new_price_raw = "" if item.new_price is None else str(item.new_price)
            new_stock_raw = "" if item.new_stock is None else str(item.new_stock)
            cells = {
                self.COL_SKU: item.sku,
                self.COL_NAME: item.name,
                self.COL_CUR_PRICE: self._money(item.current_price),
                self.COL_NEW_PRICE: new_price_raw,
                self.COL_CUR_STOCK: self._num(item.current_stock),
                self.COL_NEW_STOCK: new_stock_raw,
                self.COL_STATUS: row_status_text(item, kind, inc_stock),
            }
            bg = QBrush(QColor(_KIND_BG[kind])) if kind in _KIND_BG else None
            for c, text in cells.items():
                cell = QTableWidgetItem(text)
                if c != self.COL_NAME:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == self.COL_SKU:
                    cell.setFont(code_font)
                    cell.setToolTip(f"{text}\nدابل‌کلیک: کپی کد")
                if c == self.COL_NAME:
                    cell.setToolTip(text)
                if bg is not None:
                    cell.setBackground(bg)
                if c == self.COL_STATUS:
                    if kind == "same":
                        cell.setForeground(QBrush(QColor("#2e7d32")))
                    elif kind == "no_isaco":
                        cell.setForeground(QBrush(QColor("#757575")))
                # فقط قیمت/موجودی جدید قابل ویرایش‌اند
                if c not in (self.COL_NEW_PRICE, self.COL_NEW_STOCK):
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, cell)

            # دکمهٔ اعمال تکی فقط برای ردیف‌هایی که کاری دارند
            self.table.removeCellWidget(r, self.COL_APPLY)
            if kind in ("change", "review"):
                self._add_apply_button(r)
        self.table.setUpdatesEnabled(True)
        self._filling = False
        self._update_kind_counts()

    def _add_apply_button(self, r: int) -> None:
        btn = QPushButton("اعمال")
        btn.setObjectName("Primary")
        btn.setStyleSheet("padding: 2px 10px; min-height: 0px; font-size: 12px;")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _=False, row=r: self._apply_single(row))
        self.table.setCellWidget(r, self.COL_APPLY, btn)

    def _kind_counts(self) -> dict[str, int]:
        counts = {key: 0 for key, _ in ROW_KINDS}
        for kind in self._row_kinds:
            counts[kind] += 1
        counts["all"] = len(self._row_kinds)
        return counts

    def _update_kind_counts(self) -> None:
        counts = self._kind_counts()
        for key, label in ROW_KINDS:
            self.kind_buttons[key].setText(f"{label} ({self._fa(counts[key])})")

    def current_kind(self) -> str:
        btn = self.kind_group.checkedButton()
        return btn.property("kind") if btn else "all"

    def _apply_filter(self) -> None:
        kind = self.current_kind()
        text = self.search.text().strip()
        for r, item in enumerate(self._row_items):
            k = self._row_kinds[r]
            if kind == "all":
                ok = True
            elif kind == "change":
                ok = k in ("change", "review") or r in self._edited_rows
            else:
                ok = k == kind
            if ok and text:
                ok = text in item.sku or text in item.name
            self.table.setRowHidden(r, not ok)

    def _on_item_edited(self, cell: QTableWidgetItem) -> None:
        """ویرایش دستی «قیمت جدید»/«موجودی جدید» هر ردیف (حتی بدون تغییر)."""
        if self._filling or cell.column() not in (self.COL_NEW_PRICE, self.COL_NEW_STOCK):
            return
        r = cell.row()
        if r >= len(self._row_items) or r in self._edited_rows:
            return
        self._edited_rows.add(r)
        self._filling = True
        status = self.table.item(r, self.COL_STATUS)
        if status is not None:
            status.setText("✏️ ویرایش دستی")
            status.setForeground(QBrush(QColor("#1565c0")))
        self._filling = False
        if self.table.cellWidget(r, self.COL_APPLY) is None:
            self._add_apply_button(r)
        self.apply_btn.setEnabled(True)

    def rows_to_apply(self) -> list[int]:
        """ردیف‌هایی که «اعمال روی سایت» می‌فرستد (فیلتر جدول اثری ندارد)."""
        return [r for r, k in enumerate(self._row_kinds)
                if k in ("change", "review") or r in self._edited_rows]

    @staticmethod
    def _code_font() -> QFont:
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        return font

    def _on_double_click(self, row: int, col: int) -> None:
        if col != self.COL_SKU:
            return
        item = self.table.item(row, col)
        if item and item.text():
            QGuiApplication.clipboard().setText(item.text())
            self.status.setText(f"کد {item.text()} کپی شد.")

    def _collect_rows(self, row_indices: list[int]):
        """از ردیف‌های جدول، به‌روزرسانی ووکامرس و snapshot رول‌بک می‌سازد.

        مقادیر «قیمت جدید» و «موجودی جدید» از خودِ جدول خوانده می‌شوند تا
        ویرایش‌های دستی کاربر لحاظ شوند.
        """
        from ...db import Snapshot

        updates, snapshots = [], []
        for r in row_indices:
            if r >= len(self._row_items):
                continue
            item = self._row_items[r]
            # ردیف‌های نیازمند بررسی فقط با تأیید صریح کاربر اعمال شوند
            new_price = self.table.item(r, self.COL_NEW_PRICE).text().strip()
            new_stock = self.table.item(r, self.COL_NEW_STOCK).text().strip()
            old_price = "" if item.current_price is None else str(item.current_price)
            old_stock = item.current_stock

            payload = {"id": item.product_id}
            snap = Snapshot(product_id=item.product_id, sku=item.sku,
                            old_price=old_price or None, old_stock=old_stock,
                            old_status="instock" if old_stock else "outofstock")

            if new_price and new_price != old_price:
                payload["regular_price"] = new_price
                snap.new_price = new_price

            old_stock_s = "" if old_stock is None else str(old_stock)
            if new_stock != old_stock_s and new_stock != "":
                try:
                    q = int(float(new_stock))
                    payload["manage_stock"] = True
                    payload["stock_quantity"] = q
                    payload["stock_status"] = "instock" if q > 0 else "outofstock"
                    snap.new_stock = q
                    snap.new_status = payload["stock_status"]
                except ValueError:
                    pass

            if len(payload) > 1:
                updates.append(payload)
                snapshots.append(snap)
        return updates, snapshots

    def _apply(self) -> None:
        confirm = QMessageBox.question(
            self, "اعمال روی سایت",
            "همهٔ تغییرات روی سایت اعمال شوند؟ (قابل بازگشت است)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._apply_rows(self.rows_to_apply(), mode="manual")

    def _apply_single(self, row: int) -> None:
        updates, snapshots = self._collect_rows([row])
        if not updates:
            QMessageBox.information(self, "تغییری نیست",
                                    "این محصول تغییری برای اعمال ندارد.")
            return
        self._apply_rows([row], mode="row", silent=True)

    def _apply_rows(self, row_indices: list[int], mode="manual",
                    silent: bool = False) -> None:
        updates, snapshots = self._collect_rows(row_indices)
        if not updates:
            QMessageBox.information(self, "تغییری نیست", "تغییری برای اعمال نیست.")
            return
        if not self._set_busy(True, "اعمال تغییرات سینک"):
            return
        worker = TableApplyWorker(self.db, self.store, updates, snapshots, mode)
        self._run_worker(worker, self._on_applied)

    def _on_applied(self, result) -> None:
        applied, failed = result
        self._set_busy(False)
        msg = f"{self._fa(applied)} محصول به‌روز شد."
        if failed:
            msg += f"\n{self._fa(failed)} خطا."
        QMessageBox.information(self, "انجام شد", msg)
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
        from ..workers import start_worker
        self._worker = worker
        self._thread = start_worker(self, worker, on_done=on_done,
                                    on_failed=self._on_failed,
                                    on_progress=self.status.setText)

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(self, "خطا", message)
        self.status.setText(f"خطا: {message}")

    def _set_busy(self, busy: bool, owner: str = "") -> bool:
        """شروع/پایان کار؛ با قفل سراسری سینک (هم‌زمان با سینک خودکار نه).

        :returns: ``False`` اگر کار دیگری در حال اجراست و نباید شروع کرد.
        """
        from ...sync_gate import gate

        if busy:
            if not gate.try_acquire(owner or "تب سینک"):
                QMessageBox.information(
                    self, "صبر کنید",
                    f"«{gate.owner}» در حال اجراست. بعد از پایان آن دوباره امتحان کنید.")
                return False
            self._gate_owner = owner or "تب سینک"
        else:
            gate.release(getattr(self, "_gate_owner", None))
            self._gate_owner = None
        self.progress.setVisible(busy)
        self.fetch_btn.setEnabled(not busy)
        self.pick_btn.setEnabled(not busy)
        if busy:
            self.apply_btn.setEnabled(False)
        return True

    @staticmethod
    def _fa(n) -> str:
        return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    def _money(self, value) -> str:
        return "—" if value is None else self._fa(f"{value:,}") + " ت"

    def _num(self, value) -> str:
        return "—" if value is None else self._fa(value)
