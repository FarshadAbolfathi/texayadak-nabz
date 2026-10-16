"""پنجرهٔ تطبیق کد محصولات سایت با کالاهای لیست ایساکو.

برای هر محصول سایت که کدش در ایساکو نیست، پیشنهادها (کد کوتاه‌شده، سپس
هم‌خانواده‌ها) با نام، خودرو و قیمتِ محاسبه‌شده کنار نام محصول سایت نشان
داده می‌شوند. هیچ گزینه‌ای پیش‌فرض انتخاب نیست؛ کارفرما باید با دیدن نام دو
طرف خودش تأیید کند.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..pricing import compute as compute_price
from .widgets import fa, make_copyable, money, muted, setup_columns

_NONE = "— تطبیق نده —"


class CodeMatchDialog(QDialog):
    """``rows``: فهرست ``(SyncItem, [MatchCandidate, ...])``.

    پس از تأیید، ``chosen`` = «کد سایت → کد ایساکو» برای ردیف‌های انتخاب‌شده.
    """

    COLS = ["کد سایت", "نام محصول سایت", "کالای ایساکو (انتخاب کنید)", "قیمت سایت",
            "قیمت با این تطبیق"]
    C_SKU, C_NAME, C_PICK, C_CUR, C_NEW = range(5)

    def __init__(self, rows, price_rules, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تطبیق کد با لیست ایساکو")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1150, 560)
        self._rows = rows
        self._rules = price_rules
        self.chosen: dict[str, str] = {}

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            f"<b>{fa(len(rows))}</b> محصول سایت در لیست ایساکو پیدا نشد ولی کالای "
            "مشابهی در لیست هست."))
        lay.addWidget(muted(
            "برای هر ردیف، اگر کالای ایساکو همان محصول است انتخابش کنید (نام دو طرف را "
            "مقایسه کنید). «کد کوتاه‌شده» یعنی ایساکو دو رقم آخر کد را حذف کرده؛ "
            "«هم‌خانواده» یعنی ۸ رقم اول یکی است ولی ممکن است نسخهٔ دیگری باشد. "
            "تطبیق‌ها ذخیره و از این به بعد در سینک دستی و خودکار استفاده می‌شوند."))

        self.table = QTableWidget(len(rows), len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(40)
        setup_columns(self.table, {self.C_SKU: 120, self.C_NAME: 300, self.C_PICK: 430,
                                   self.C_CUR: 110, self.C_NEW: 130})
        self.table.setColumnWidth(self.C_PICK, 480)
        self._combos: list[QComboBox] = []
        for r, (item, candidates) in enumerate(rows):
            sku = QTableWidgetItem(item.sku)
            sku.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, self.C_SKU, sku)
            name = QTableWidgetItem(item.name)
            name.setToolTip(item.name)
            self.table.setItem(r, self.C_NAME, name)
            cur = QTableWidgetItem(money(item.current_price, unit=""))
            cur.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, self.C_CUR, cur)
            self.table.setItem(r, self.C_NEW, QTableWidgetItem(""))

            combo = QComboBox()
            combo.addItem(_NONE, "")
            for cand in candidates:
                it = cand.item
                car = f" — {it.car}" if it.car else ""
                combo.addItem(f"{it.code}  |  {it.name}{car}  ({cand.label})", it.code)
                combo.setItemData(combo.count() - 1,
                                  f"{it.name}{car}\n{cand.label}", Qt.ItemDataRole.ToolTipRole)
            combo.currentIndexChanged.connect(lambda _i, row=r: self._on_pick(row))
            self.table.setCellWidget(r, self.C_PICK, combo)
            self._combos.append(combo)
        make_copyable(self.table, code_columns=(self.C_SKU,))
        lay.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.pick_short = QPushButton("انتخاب همهٔ «کد کوتاه‌شده»‌ها")
        self.pick_short.setToolTip("فقط ردیف‌هایی که پیشنهاد «کد کوتاه‌شده» دارند؛ "
                                   "باز هم نام‌ها را چک کنید.")
        self.pick_short.clicked.connect(self._select_short)
        clear = QPushButton("پاک کردن انتخاب‌ها")
        clear.clicked.connect(lambda: [c.setCurrentIndex(0) for c in self._combos])
        buttons.addWidget(self.pick_short)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        self.summary = QLabel("")
        buttons.addWidget(self.summary)
        cancel = QPushButton("انصراف")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("ذخیرهٔ تطبیق‌ها")
        self.ok.setObjectName("Success")
        self.ok.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok)
        lay.addLayout(buttons)
        self._update_summary()

    def _candidate(self, row: int, code: str):
        for cand in self._rows[row][1]:
            if cand.item.code == code:
                return cand
        return None

    def _on_pick(self, row: int) -> None:
        code = self._combos[row].currentData()
        cell = self.table.item(row, self.C_NEW)
        cand = self._candidate(row, code) if code else None
        if cand is None:
            cell.setText("")
            cell.setBackground(QBrush())
        else:
            it = cand.item
            price = compute_price(isaco_retail=it.retail, isaco_vat=it.vat,
                                  isaco_wholesale=it.wholesale, rules=self._rules).price
            cell.setText(money(price, unit=""))
            cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setBackground(QBrush(QColor("#e8f5e9")))
        self._update_summary()

    def _select_short(self) -> None:
        for r, (_item, candidates) in enumerate(self._rows):
            for i, cand in enumerate(candidates, start=1):
                if cand.reason == "short":
                    self._combos[r].setCurrentIndex(i)
                    break

    def selections(self) -> dict[str, str]:
        return {item.sku: combo.currentData()
                for (item, _), combo in zip(self._rows, self._combos)
                if combo.currentData()}

    def _update_summary(self) -> None:
        self.summary.setText(f"{fa(len(self.selections()))} تطبیق انتخاب شده")
        self.ok.setEnabled(bool(self.selections()))

    def _accept(self) -> None:
        self.chosen = self.selections()
        self.accept()
