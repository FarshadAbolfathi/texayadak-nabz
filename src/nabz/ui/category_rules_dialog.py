"""تنظیمات دسته‌بندی خودکار: قواعد «کلمه → دسته» و گزینه‌ها."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..categorize import CategoryRule, rules_from_settings
from ..db import Database
from ..targets.woocommerce import WooCategory
from .category_dialog import CategoryDialog
from .services import categorizer_from_db


class CategoryRulesDialog(QDialog):
    def __init__(self, db: Database, categories: list[WooCategory], *,
                 create_category: Callable[[str, int], WooCategory] | None = None,
                 parent=None):
        super().__init__(parent)
        self.db = db
        self.categories = list(categories)
        self._create = create_category
        self.setWindowTitle("تنظیمات دسته‌بندی خودکار")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(760, 600)
        self._rules: list[CategoryRule] = rules_from_settings(
            db.get_setting("category_rules", [])
        )

        layout = QVBoxLayout(self)
        intro = QLabel(
            "برنامه به‌طور خودکار نام دسته‌های سایت را با نام محصول (و ستون «مصرف "
            "خودرو» لیست ایساکو) مقایسه می‌کند؛ مثلاً «سپر عقب ۴۰۵» خودش در دستهٔ "
            "«پژو ۴۰۵» می‌نشیند. برای مواردی که نام دسته در نام محصول نیست "
            "(نام مستعار مثل «آردی» یا دسته‌های نوع قطعه مثل «لنت → لوازم ترمز») "
            "یک قاعده اضافه کنید."
        )
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        layout.addWidget(intro)

        self.auto_match = QCheckBox("تطبیق خودکار با نام دسته‌های سایت")
        self.auto_match.setChecked(bool(db.get_setting("category_auto_match", True)))
        layout.addWidget(self.auto_match)
        self.parents = QCheckBox("دسته‌های والد هم اضافه شوند (مثلاً پژو ۴۰۵ ← پژو)")
        self.parents.setChecked(bool(db.get_setting("category_include_parents", True)))
        layout.addWidget(self.parents)

        default_row = QHBoxLayout()
        default_row.addWidget(QLabel("اگر دسته‌ای پیدا نشد:"))
        self.default = QComboBox()
        self.default.addItem("بدون دسته (دستی تعیین می‌کنم)", 0)
        checker = categorizer_from_db(db, self.categories)
        for cat in sorted(self.categories, key=lambda c: checker.path(c.id)):
            self.default.addItem(checker.path(cat.id), cat.id)
        idx = self.default.findData(int(db.get_setting("category_default", 0) or 0))
        self.default.setCurrentIndex(max(idx, 0))
        default_row.addWidget(self.default, 1)
        layout.addLayout(default_row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["کلمه/عبارت در نام محصول", "دسته‌ها"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 230)
        self.table.cellDoubleClicked.connect(self._edit_row)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        add = QPushButton("➕  قاعدهٔ جدید")
        add.setObjectName("Accent")
        add.clicked.connect(self._add)
        remove = QPushButton("🗑  حذف قاعده")
        remove.clicked.connect(self._remove)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        test_row = QHBoxLayout()
        self.test_input = QLineEdit()
        self.test_input.setPlaceholderText("آزمایش: یک نام محصول بنویسید، مثلاً «سپر عقب ۴۰۵»")
        self.test_input.textChanged.connect(self._test)
        test_row.addWidget(self.test_input, 1)
        layout.addLayout(test_row)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        layout.addWidget(self.test_result)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        box.button(QDialogButtonBox.StandardButton.Save).setText("ذخیره")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("انصراف")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        for w in (self.auto_match, self.parents):
            w.toggled.connect(lambda *_: self._test(self.test_input.text()))
        self.default.currentIndexChanged.connect(
            lambda *_: self._test(self.test_input.text()))
        self._refresh()

    def _names(self, ids) -> str:
        by_id = {c.id: c.name for c in self.categories}
        return "، ".join(by_id.get(i, f"#{i}") for i in ids)

    def _refresh(self) -> None:
        self.table.setRowCount(len(self._rules))
        for r, rule in enumerate(self._rules):
            k = QTableWidgetItem(rule.keyword)
            k.setFlags(k.flags() & ~Qt.ItemFlag.ItemIsEditable)
            v = QTableWidgetItem(self._names(rule.category_ids))
            v.setFlags(v.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 0, k)
            self.table.setItem(r, 1, v)
        self._test(self.test_input.text())

    def _pick(self, keyword: str, selected=()) -> list[int] | None:
        dlg = CategoryDialog(self.categories, selected,
                             title=f"دسته‌ها برای «{keyword}»",
                             create_category=self._create, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        self.categories.extend(dlg.created)
        return dlg.selected_ids()

    def _add(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        keyword, ok = QInputDialog.getText(
            self, "قاعدهٔ جدید", "کلمه یا عبارتی که در نام محصول می‌آید:")
        keyword = keyword.strip()
        if not ok or not keyword:
            return
        ids = self._pick(keyword)
        if not ids:
            return
        self._rules.append(CategoryRule(keyword, tuple(ids)))
        self._refresh()

    def _edit_row(self, row: int, _col: int) -> None:
        rule = self._rules[row]
        ids = self._pick(rule.keyword, rule.category_ids)
        if ids is None:
            return
        if not ids:
            del self._rules[row]
        else:
            self._rules[row] = CategoryRule(rule.keyword, tuple(ids))
        self._refresh()

    def _remove(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        for r in rows:
            del self._rules[r]
        self._refresh()

    def _current_categorizer(self):
        from ..categorize import Categorizer
        return Categorizer(
            self.categories, self._rules,
            include_parents=self.parents.isChecked(),
            default_category=self.default.currentData() or None,
            auto_match=self.auto_match.isChecked(),
        )

    def _test(self, text: str) -> None:
        if not text.strip():
            self.test_result.setText("")
            return
        s = self._current_categorizer().suggest(text)
        if s.category_ids:
            self.test_result.setText(
                f"➜ {self._names(s.category_ids)}   ({s.reason})")
        else:
            self.test_result.setText("➜ دسته‌ای پیدا نشد")

    def _save(self) -> None:
        self.db.set_setting("category_rules", [r.to_dict() for r in self._rules])
        self.db.set_setting("category_auto_match", self.auto_match.isChecked())
        self.db.set_setting("category_include_parents", self.parents.isChecked())
        self.db.set_setting("category_default", int(self.default.currentData() or 0))
        QMessageBox.information(self, "ذخیره شد", "تنظیمات دسته‌بندی ذخیره شد.")
        self.accept()
