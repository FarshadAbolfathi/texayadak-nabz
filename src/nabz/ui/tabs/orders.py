"""تب سفارش‌ها — مشاهدهٔ کامل سفارش‌های ووکامرس، تغییر وضعیت و صدور فاکتور.

- فهرست سفارش‌ها با فیلتر وضعیت (با تعداد هرکدام)، جستجو و صفحه‌بندی
- جزئیات کامل: مشتری، نشانی، اقلام، هزینه‌ها، یادداشت‌ها — با تاریخ شمسی
- تغییر وضعیت (ایمیل‌های خودِ ووکامرس مثل همیشه ارسال می‌شوند)
- افزودن یادداشت خصوصی یا یادداشت برای مشتری
- فاکتور فروش: پیش‌نمایش و چاپ، یا ذخیرهٔ PDF
"""

from __future__ import annotations

import html

from PySide6.QtCore import QMarginsF, QSizeF, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPageLayout, QPageSize, QTextDocument, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ... import jalali
from ...config import CredentialStore
from ...db import Database
from ...invoice import (
    ORDER_STATUS_COLOR,
    ORDER_STATUS_FA,
    ShopInfo,
    address_text,
    customer_name,
    format_amount,
    render_invoice_html,
    status_name,
)
from ..services import woo_client_from_store
from ..widgets import Card, fa, make_copyable, muted
from ..workers import run_async

PER_PAGE = 50


def _client(store: CredentialStore):
    woo = woo_client_from_store(store)
    if woo is None:
        raise RuntimeError("اطلاعات اتصال ووکامرس در تنظیمات کامل نیست.")
    return woo


def _fetch_page(store, status, search, page):
    woo = _client(store)
    orders, total, pages = woo.list_orders(
        status=status, search=search, page=page, per_page=PER_PAGE)
    try:
        totals = woo.order_status_totals()
    except Exception:  # noqa: BLE001 - شمارش وضعیت‌ها اختیاری است
        totals = []
    return orders, total, pages, totals


def _fetch_detail(store, order_id):
    woo = _client(store)
    order = woo.get_order(order_id)
    try:
        notes = woo.order_notes(order_id)
    except Exception:  # noqa: BLE001
        notes = []
    return order, notes


def _update_status(store, order_id, status, note, customer_note):
    woo = _client(store)
    order = woo.update_order(order_id, {"status": status})
    if note:
        woo.add_order_note(order_id, note, customer_note=customer_note)
    return order


def _add_note(store, order_id, note, customer_note):
    return _client(store).add_order_note(order_id, note, customer_note=customer_note)


class OrdersTab(QWidget):
    HEADERS = ["شماره", "تاریخ", "مشتری", "تلفن", "شهر", "اقلام", "مبلغ کل",
               "وضعیت", "پرداخت"]
    (COL_NUM, COL_DATE, COL_CUSTOMER, COL_PHONE, COL_CITY, COL_ITEMS,
     COL_TOTAL, COL_STATUS, COL_PAY) = range(9)

    def __init__(self, db: Database, store: CredentialStore, parent=None):
        super().__init__(parent)
        self.db = db
        self.store = store
        self._orders: list[dict] = []
        self._order: dict | None = None
        self._status_names: dict[str, str] = dict(ORDER_STATUS_FA)
        self._page = 1
        self._pages = 1
        self._build()

    # -- ساخت رابط ----------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        header = QLabel("سفارش‌ها")
        header.setObjectName("H1")
        layout.addWidget(header)

        toolbar = QHBoxLayout()
        self.load_btn = QPushButton("🔄  بارگذاری سفارش‌ها")
        self.load_btn.setObjectName("Primary")
        self.load_btn.clicked.connect(lambda: self.load(page=1))
        toolbar.addWidget(self.load_btn)

        self.status_filter = QComboBox()
        self.status_filter.setMinimumWidth(190)
        self.status_filter.currentIndexChanged.connect(lambda *_: self.load(page=1))
        toolbar.addWidget(self.status_filter)

        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو: شمارهٔ سفارش، نام، تلفن یا ایمیل ... (Enter)")
        self.search.returnPressed.connect(lambda: self.load(page=1))
        toolbar.addWidget(self.search, 1)

        self.prev_btn = QPushButton("› قبلی")
        self.prev_btn.clicked.connect(lambda: self.load(page=self._page - 1))
        self.page_label = QLabel("")
        self.next_btn = QPushButton("بعدی ‹")
        self.next_btn.clicked.connect(lambda: self.load(page=self._page + 1))
        for w in (self.prev_btn, self.page_label, self.next_btn):
            toolbar.addWidget(w)
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        layout.addLayout(toolbar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = muted("برای دیدن سفارش‌های سایت، «بارگذاری سفارش‌ها» را بزنید.")
        layout.addWidget(self.status)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(self.COL_CUSTOMER, QHeaderView.ResizeMode.Stretch)
        for col, w in {self.COL_NUM: 80, self.COL_DATE: 140, self.COL_PHONE: 120,
                       self.COL_CITY: 100, self.COL_ITEMS: 60, self.COL_TOTAL: 140,
                       self.COL_STATUS: 130, self.COL_PAY: 150}.items():
            self.table.setColumnWidth(col, w)
        self.table.itemSelectionChanged.connect(self._on_select)
        make_copyable(self.table, code_columns=(self.COL_NUM, self.COL_PHONE),
                      on_copied=self.status.setText)
        splitter.addWidget(self.table)

        detail = QWidget()
        detail_layout = QHBoxLayout(detail)
        detail_layout.setContentsMargins(0, 8, 0, 0)
        detail_layout.setSpacing(12)

        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.detail.setHtml(self._placeholder())
        detail_layout.addWidget(self.detail, 3)

        actions = Card("اقدامات سفارش")
        self.order_title = QLabel("—")
        self.order_title.setObjectName("CardTitle")
        actions.add(self.order_title)

        actions.add(QLabel("تغییر وضعیت به:"))
        self.new_status = QComboBox()
        actions.add(self.new_status)
        self.status_note = QLineEdit()
        self.status_note.setPlaceholderText("توضیح برای مشتری (اختیاری) — مثلاً کد رهگیری پست")
        actions.add(self.status_note)
        self.save_status_btn = QPushButton("✅  ثبت وضعیت")
        self.save_status_btn.setObjectName("Success")
        self.save_status_btn.clicked.connect(self._save_status)
        actions.add(self.save_status_btn)
        actions.add(muted("ووکامرس مطابق تنظیمات سایت به مشتری ایمیل/پیامک می‌فرستد."))

        actions.add(QLabel("یادداشت:"))
        self.note = QPlainTextEdit()
        self.note.setMaximumHeight(70)
        actions.add(self.note)
        self.note_customer = QCheckBox("برای مشتری هم ارسال شود")
        actions.add(self.note_customer)
        self.add_note_btn = QPushButton("📝  افزودن یادداشت")
        self.add_note_btn.clicked.connect(self._add_note)
        actions.add(self.add_note_btn)

        inv_row = QHBoxLayout()
        self.print_btn = QPushButton("🖨  چاپ فاکتور")
        self.print_btn.setObjectName("Primary")
        self.print_btn.clicked.connect(self._print_invoice)
        self.pdf_btn = QPushButton("📄  PDF")
        self.pdf_btn.clicked.connect(self._save_pdf)
        inv_row.addWidget(self.print_btn, 2)
        inv_row.addWidget(self.pdf_btn, 1)
        actions.body().addLayout(inv_row)
        self.open_btn = QPushButton("🌐  باز کردن در پیشخوان سایت")
        self.open_btn.clicked.connect(self._open_in_admin)
        actions.add(self.open_btn)
        actions.body().addStretch(1)
        actions.setMinimumWidth(300)
        actions.setMaximumWidth(380)
        detail_layout.addWidget(actions, 1)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        self.table.setMinimumHeight(220)
        splitter.setSizes([380, 420])
        layout.addWidget(splitter, 1)
        self._fill_status_filter([])
        self._set_order_actions(False)

    def _placeholder(self) -> str:
        return ("<div dir='rtl' style='color:#888;padding:20px'>"
                "یک سفارش را از جدول انتخاب کنید تا جزئیات آن نمایش داده شود.</div>")

    def _fill_status_filter(self, totals: list[dict]) -> None:
        current = self.status_filter.currentData()
        self.status_filter.blockSignals(True)
        self.status_filter.clear()
        grand = sum(int(t.get("total") or 0) for t in totals)
        self.status_filter.addItem(
            "همهٔ سفارش‌ها" + (f" ({fa(grand)})" if totals else ""), "any")
        if totals:
            for t in totals:
                slug = str(t.get("slug", "")).removeprefix("wc-")
                name = ORDER_STATUS_FA.get(slug) or t.get("name") or slug
                self._status_names[slug] = name
                self.status_filter.addItem(f"{name} ({fa(t.get('total', 0))})", slug)
        else:
            for slug, name in ORDER_STATUS_FA.items():
                if slug not in ("trash", "checkout-draft"):
                    self.status_filter.addItem(name, slug)
        idx = self.status_filter.findData(current)
        self.status_filter.setCurrentIndex(max(idx, 0))
        self.status_filter.blockSignals(False)

        self.new_status.clear()
        for slug, name in self._status_names.items():
            if slug not in ("trash", "checkout-draft"):
                self.new_status.addItem(name, slug)

    # -- بارگذاری فهرست --------------------------------------------------

    def load(self, page: int = 1) -> None:
        page = max(1, page)
        self._busy(True, "در حال خواندن سفارش‌ها ...")
        run_async(
            self, _fetch_page, self.store, self.status_filter.currentData(),
            self.search.text().strip(), page,
            on_done=lambda result: self._on_loaded(result, page),
            on_failed=self._on_failed,
        )

    def _on_loaded(self, result, page: int) -> None:
        orders, total, pages, totals = result
        self._busy(False)
        if totals:
            self._fill_status_filter(totals)
        self._orders = orders
        self._page, self._pages = page, max(pages, 1)
        self.page_label.setText(f"صفحهٔ {fa(page)} از {fa(self._pages)}")
        self.prev_btn.setEnabled(page > 1)
        self.next_btn.setEnabled(page < self._pages)
        self._fill()
        self.status.setText(f"{fa(total)} سفارش — نمایش {fa(len(orders))} مورد.")

    def _fill(self) -> None:
        self.table.setRowCount(len(self._orders))
        for r, o in enumerate(self._orders):
            billing = o.get("billing") or {}
            shipping = o.get("shipping") or {}
            items = sum(int(i.get("quantity") or 0) for i in o.get("line_items") or [])
            slug = o.get("status", "")
            cells = {
                self.COL_NUM: fa(o.get("number") or o.get("id")),
                self.COL_DATE: jalali.format_iso(o.get("date_created")),
                self.COL_CUSTOMER: customer_name(o),
                self.COL_PHONE: fa(billing.get("phone", "")),
                self.COL_CITY: shipping.get("city") or billing.get("city") or "",
                self.COL_ITEMS: fa(items),
                self.COL_TOTAL: format_amount(o.get("total"), o.get("currency", "IRT")),
                self.COL_STATUS: status_name(slug, self._status_names),
                self.COL_PAY: o.get("payment_method_title", ""),
            }
            for c, text in cells.items():
                item = QTableWidgetItem(str(text))
                if c != self.COL_CUSTOMER:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == self.COL_NUM:
                    item.setData(Qt.ItemDataRole.UserRole, int(o["id"]))
                if c == self.COL_STATUS:
                    color = ORDER_STATUS_COLOR.get(slug, "#455a64")
                    item.setForeground(QBrush(QColor("white")))
                    item.setBackground(QBrush(QColor(color)))
                self.table.setItem(r, c, item)

    # -- جزئیات ------------------------------------------------------------

    def _selected_id(self) -> int | None:
        rows = {i.row() for i in self.table.selectedItems()}
        if not rows:
            return None
        item = self.table.item(rows.pop(), self.COL_NUM)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _on_select(self) -> None:
        order_id = self._selected_id()
        if order_id is None:
            return
        summary = next((o for o in self._orders if int(o["id"]) == order_id), None)
        if summary:
            self._show_order(summary, [])
        run_async(self, _fetch_detail, self.store, order_id,
                  on_done=lambda res: self._on_detail(order_id, res),
                  on_failed=lambda msg: self.status.setText(f"جزئیات خوانده نشد: {msg}"))

    def _on_detail(self, order_id: int, result) -> None:
        if self._selected_id() != order_id:
            return  # کاربر در این فاصله سفارش دیگری انتخاب کرده
        order, notes = result
        self._show_order(order, notes)

    def _show_order(self, order: dict, notes: list[dict]) -> None:
        self._order = order
        number = fa(order.get("number") or order.get("id"))
        self.order_title.setText(f"سفارش #{number}")
        idx = self.new_status.findData(order.get("status"))
        if idx >= 0:
            self.new_status.setCurrentIndex(idx)
        self._set_order_actions(True)
        self.detail.setHtml(self._detail_html(order, notes))

    def _detail_html(self, o: dict, notes: list[dict]) -> str:
        esc = lambda v: html.escape(str(v or ""))  # noqa: E731
        cur = o.get("currency", "IRT")
        billing = o.get("billing") or {}
        shipping = o.get("shipping") or {}
        rows = "".join(
            "<tr>"
            f"<td>{esc(i.get('name'))}</td>"
            f"<td align='center' style='font-family:Consolas'>{esc(i.get('sku'))}</td>"
            f"<td align='center'>{fa(i.get('quantity'))}</td>"
            f"<td align='center'>{format_amount(i.get('total'), cur)}</td>"
            "</tr>"
            for i in o.get("line_items") or []
        )
        shipping_title = "، ".join(
            s.get("method_title", "") for s in o.get("shipping_lines") or [])
        notes_html = "".join(
            f"<p style='margin:4px 0;padding:4px;background:"
            f"{'#e3f2fd' if n.get('customer_note') else '#f5f5f5'}'>"
            f"<small>{jalali.format_iso(n.get('date_created'))}"
            f"{' — برای مشتری' if n.get('customer_note') else ''}</small><br>"
            f"{n.get('note', '')}</p>"
            for n in notes
        )
        status = status_name(o.get("status", ""), self._status_names)
        return f"""<div dir="rtl">
<h3>سفارش #{fa(esc(o.get('number') or o.get('id')))} — {esc(status)}</h3>
<p>تاریخ ثبت: <b>{jalali.format_iso(o.get('date_created'))}</b>
 &nbsp;|&nbsp; پرداخت: {esc(o.get('payment_method_title')) or '—'}
 {(' &nbsp;|&nbsp; تاریخ پرداخت: ' + jalali.format_iso(o.get('date_paid'))) if o.get('date_paid') else ''}
 {(' &nbsp;|&nbsp; کد تراکنش: ' + fa(esc(o.get('transaction_id')))) if o.get('transaction_id') else ''}</p>
<p><b>مشتری:</b> {esc(customer_name(o))} &nbsp;|&nbsp; {fa(esc(billing.get('phone')))}
 {(' &nbsp;|&nbsp; ' + esc(billing.get('email'))) if billing.get('email') else ''}</p>
<p><b>نشانی صورت‌حساب:</b> {fa(esc(address_text(billing))) or '—'}</p>
<p><b>ارسال</b> {('(' + esc(shipping_title) + ')') if shipping_title else ''}:
 {fa(esc(address_text(shipping))) or 'همان نشانی صورت‌حساب'}</p>
<table width="100%" border="1" cellspacing="0" cellpadding="4" style="border-collapse:collapse;border-color:#ccc">
<tr style="background:#eceff1"><th>کالا</th><th>کد</th><th>تعداد</th><th>مبلغ</th></tr>
{rows}
</table>
<p>ارسال: {format_amount(o.get('shipping_total'), cur)} &nbsp;|&nbsp;
تخفیف: {format_amount(o.get('discount_total'), cur)} &nbsp;|&nbsp;
<b>جمع کل: {format_amount(o.get('total'), cur)}</b></p>
{('<p><b>یادداشت مشتری:</b> ' + esc(o.get('customer_note')) + '</p>') if o.get('customer_note') else ''}
{('<h4>یادداشت‌ها</h4>' + notes_html) if notes_html else ''}
</div>"""

    def _set_order_actions(self, on: bool) -> None:
        for w in (self.new_status, self.status_note, self.save_status_btn, self.note,
                  self.note_customer, self.add_note_btn, self.print_btn, self.pdf_btn,
                  self.open_btn):
            w.setEnabled(on)

    # -- اقدامات -------------------------------------------------------------

    def _save_status(self) -> None:
        if not self._order:
            return
        slug = self.new_status.currentData()
        if slug == self._order.get("status") and not self.status_note.text().strip():
            QMessageBox.information(self, "بدون تغییر", "وضعیت سفارش همین است.")
            return
        number = fa(self._order.get("number") or self._order.get("id"))
        answer = QMessageBox.question(
            self, "تغییر وضعیت",
            f"وضعیت سفارش #{number} به «{self.new_status.currentText()}» تغییر کند؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        order_id = int(self._order["id"])
        note = self.status_note.text().strip()
        self._busy(True, "در حال ثبت وضعیت ...")

        def done(order) -> None:
            self._busy(False)
            self.status_note.clear()
            self.db.log("info", f"وضعیت سفارش {order_id} → {slug}")
            self.status.setText(f"وضعیت سفارش #{number} ثبت شد.")
            self._replace_order(order)

        run_async(self, _update_status, self.store, order_id, slug, note, bool(note),
                  on_done=done, on_failed=self._on_failed)

    def _add_note(self) -> None:
        if not self._order:
            return
        text = self.note.toPlainText().strip()
        if not text:
            return
        order_id = int(self._order["id"])
        self._busy(True, "در حال افزودن یادداشت ...")

        def done(_note) -> None:
            self._busy(False)
            self.note.clear()
            self.status.setText("یادداشت ثبت شد.")
            self._on_select()

        run_async(self, _add_note, self.store, order_id, text,
                  self.note_customer.isChecked(), on_done=done, on_failed=self._on_failed)

    def _replace_order(self, order: dict) -> None:
        for i, o in enumerate(self._orders):
            if int(o["id"]) == int(order["id"]):
                self._orders[i] = order
        row = next((r for r in range(self.table.rowCount())
                    if self.table.item(r, self.COL_NUM).data(Qt.ItemDataRole.UserRole)
                    == int(order["id"])), None)
        self._fill()
        if row is not None:
            self.table.setCurrentCell(row, self.COL_NUM)

    # -- فاکتور ---------------------------------------------------------------

    def _invoice_document(self) -> QTextDocument:
        shop = ShopInfo.from_settings(self.db.get_setting)
        doc = QTextDocument()
        option = QTextOption()
        option.setTextDirection(Qt.LayoutDirection.RightToLeft)
        doc.setDefaultTextOption(option)
        doc.setHtml(render_invoice_html(self._order, shop, status_names=self._status_names,
                                        reverse_columns=True))
        return doc

    @staticmethod
    def _a4_printer(printer) -> None:
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)

    def _print_invoice(self) -> None:
        if not self._order:
            return
        from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        self._a4_printer(printer)
        doc = self._invoice_document()
        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle("پیش‌نمایش فاکتور")
        preview.resize(900, 1000)
        preview.paintRequested.connect(lambda p: (
            doc.setPageSize(QSizeF(p.pageRect(QPrinter.Unit.Point).size())), doc.print_(p)))
        preview.exec()

    def _save_pdf(self) -> None:
        if not self._order:
            return
        number = self._order.get("number") or self._order.get("id")
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ فاکتور PDF", f"فاکتور-{number}.pdf", "PDF (*.pdf)")
        if not path:
            return
        from PySide6.QtPrintSupport import QPrinter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        self._a4_printer(printer)
        doc = self._invoice_document()
        doc.setPageSize(QSizeF(printer.pageRect(QPrinter.Unit.Point).size()))
        doc.print_(printer)
        self.status.setText(f"فاکتور در {path} ذخیره شد.")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_in_admin(self) -> None:
        if not self._order:
            return
        creds = self.store.load_woo()
        if not creds.base_url:
            return
        url = (f"{creds.base_url.rstrip('/')}/wp-admin/post.php?post="
               f"{int(self._order['id'])}&action=edit")
        QDesktopServices.openUrl(QUrl(url))

    # -- کمکی ---------------------------------------------------------------

    def _busy(self, busy: bool, text: str = "") -> None:
        self.progress.setVisible(busy)
        self.load_btn.setEnabled(not busy)
        if text:
            self.status.setText(text)

    def _on_failed(self, message: str) -> None:
        self._busy(False)
        self.status.setText(f"خطا: {message}")
        QMessageBox.critical(self, "خطا", message)
