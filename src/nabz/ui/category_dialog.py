"""پنجرهٔ انتخاب دسته‌بندی‌های یک یا چند محصول (درختی، با جستجو)."""

from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
)

from ..categorize import normalize_text
from ..targets.woocommerce import WooCategory


class CategoryDialog(QDialog):
    """درخت دسته‌های سایت با تیک.

    :param create_category: ``(نام، والد) → WooCategory``؛ اگر داده شود
        دکمهٔ «دستهٔ جدید» فعال است و دسته مستقیم روی سایت ساخته می‌شود.
    """

    def __init__(
        self,
        categories: Iterable[WooCategory],
        selected: Iterable[int] = (),
        *,
        title: str = "انتخاب دسته‌بندی",
        create_category: Callable[[str, int], WooCategory] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(460, 560)
        self._categories = {c.id: c for c in categories}
        self._create = create_category
        self._items: dict[int, QTreeWidgetItem] = {}
        #: دسته‌هایی که در این پنجره ساخته شدند (تا صدازننده فهرستش را به‌روز کند)
        self.created: list[WooCategory] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))

        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجوی دسته ...")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree, 1)

        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        row = QHBoxLayout()
        if create_category is not None:
            new_btn = QPushButton("➕  دستهٔ جدید")
            new_btn.clicked.connect(self._new_category)
            row.addWidget(new_btn)
        clear_btn = QPushButton("پاک کردن همه")
        clear_btn.clicked.connect(lambda: self.set_selected([]))
        row.addWidget(clear_btn)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("تأیید")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()
        self.set_selected(selected)
        self.tree.itemChanged.connect(lambda *_: self._update_summary())

    def _populate(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items.clear()
        children: dict[int, list[WooCategory]] = {}
        for c in self._categories.values():
            parent = c.parent if c.parent in self._categories else 0
            children.setdefault(parent, []).append(c)

        def add(parent_item, parent_id: int, depth: int = 0) -> None:
            if depth > 20:
                return  # محافظ در برابر حلقه در داده‌های خراب
            for cat in sorted(children.get(parent_id, []), key=lambda c: c.name):
                item = QTreeWidgetItem([cat.name])
                item.setData(0, Qt.ItemDataRole.UserRole, cat.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                if parent_item is None:
                    self.tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                self._items[cat.id] = item
                add(item, cat.id, depth + 1)

        add(None, 0)
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def set_selected(self, ids: Iterable[int]) -> None:
        wanted = set(ids)
        self.tree.blockSignals(True)
        for cid, item in self._items.items():
            item.setCheckState(
                0, Qt.CheckState.Checked if cid in wanted else Qt.CheckState.Unchecked
            )
        self.tree.blockSignals(False)
        self._update_summary()

    def selected_ids(self) -> list[int]:
        result = []
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                result.append(int(item.data(0, Qt.ItemDataRole.UserRole)))
            it += 1
        return result

    def _update_summary(self) -> None:
        names = [self._categories[c].name for c in self.selected_ids()
                 if c in self._categories]
        self.summary.setText(
            "انتخاب‌شده: " + ("، ".join(names) if names else "هیچ")
        )

    def _filter(self, text: str) -> None:
        needle = normalize_text(text)

        def visit(item: QTreeWidgetItem) -> bool:
            own = not needle or needle in normalize_text(item.text(0))
            child_match = False
            for i in range(item.childCount()):
                child_match = visit(item.child(i)) or child_match
            visible = own or child_match
            item.setHidden(not visible)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def _new_category(self) -> None:
        name, ok = QInputDialog.getText(self, "دستهٔ جدید", "نام دسته:")
        name = name.strip()
        if not ok or not name:
            return
        current = self.tree.currentItem()
        parent_id = 0
        if current is not None:
            parent_name = current.text(0)
            answer = QMessageBox.question(
                self, "والد",
                f"دستهٔ «{name}» زیرمجموعهٔ «{parent_name}» باشد؟",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                parent_id = int(current.data(0, Qt.ItemDataRole.UserRole))
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            cat = self._create(name, parent_id)
        except Exception as exc:  # noqa: BLE001
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "خطا", f"ساخت دسته ناموفق بود:\n{exc}")
            return
        QGuiApplication.restoreOverrideCursor()
        selected = self.selected_ids() + [cat.id]
        self._categories[cat.id] = cat
        self._populate()
        self.set_selected(selected)
        self.created.append(cat)
