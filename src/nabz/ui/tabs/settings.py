"""تب تنظیمات — قواعد قیمت، موجودی، اعتبارنامه‌ها و مسیر منابع."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...config import (
    CredentialStore,
    IsacoCredentialsConfig,
    WooCredentials,
)
from ...db import Database
from ..widgets import Card, field, inline_field, muted, scrollable


class SettingsTab(QWidget):
    settings_changed = Signal()

    def __init__(self, db: Database, store: CredentialStore, parent=None):
        super().__init__(parent)
        self.db = db
        self.store = store
        self._build()
        self._load()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        # --- قواعد قیمت ---
        price_card = Card("قواعد قیمت‌گذاری")

        self.markup = QDoubleSpinBox()
        self.markup.setRange(-90, 900)
        self.markup.setSuffix("  ٪")
        self.markup.setDecimals(1)
        price_card.add(field("درصد سود روی قیمت ایساکو", self.markup))

        self.base = QComboBox()
        self.base.addItem("قیمت با ارزش افزوده", "vat")
        self.base.addItem("قیمت مصرف‌کننده (خرده)", "retail")
        self.base.addItem("قیمت عمده (فی فروش)", "wholesale")
        price_card.add(field("مبنای قیمت", self.base))

        self.round_to = QComboBox()
        for label, val in [("بدون رند", 0), ("۱٬۰۰۰ تومان", 1000),
                           ("۵٬۰۰۰ تومان", 5000), ("۱۰٬۰۰۰ تومان", 10000)]:
            self.round_to.addItem(label, val)
        self.round_to.setCurrentIndex(1)
        price_card.add(field("رند کردن قیمت به", self.round_to))

        self.max_change = QSpinBox()
        self.max_change.setRange(0, 1000)
        self.max_change.setSuffix("  ٪")
        price_card.add(field("سقف تغییر مجاز خودکار", self.max_change))

        price_card.add(muted(
            "«سقف تغییر»: اگر قیمتی بیش از این درصد تغییر کند، خودکار اعمال "
            "نمی‌شود و برای بررسی دستی زرد علامت می‌خورد. ۰ یعنی بدون محدودیت."
        ))
        layout.addWidget(price_card)

        # --- قواعد موجودی ---
        stock_card = Card("قواعد موجودی")
        self.max_stock = QSpinBox()
        self.max_stock.setRange(0, 100000)
        stock_card.add(field("سقف موجودی روی سایت", self.max_stock))
        self.reserve = QSpinBox()
        self.reserve.setRange(0, 1000)
        stock_card.add(field("موجودی رزرو (نمایش نده)", self.reserve))
        stock_card.add(muted(
            "سقف موجودی: حتی اگر انبار بیشتر داشته باشد، روی سایت بیشتر از این "
            "عدد نمایش داده نمی‌شود. ۰ یعنی بدون سقف."
        ))
        layout.addWidget(stock_card)

        # --- اعتبارنامه‌ها ---
        cred_card = Card("اتصال‌ها")
        self.woo_url = QLineEdit()
        self.woo_url.setPlaceholderText("https://texayadak.com")
        cred_card.add(field("آدرس سایت", self.woo_url))
        self.woo_key = QLineEdit()
        self.woo_key.setPlaceholderText("ck_...")
        cred_card.add(field("کلید ووکامرس (Consumer Key)", self.woo_key))
        self.woo_secret = QLineEdit()
        self.woo_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.woo_secret.setPlaceholderText("cs_...")
        cred_card.add(field("رمز ووکامرس (Consumer Secret)", self.woo_secret))

        row = QHBoxLayout()
        row.setSpacing(12)
        self.isaco_scus = QLineEdit()
        self.isaco_user = QLineEdit()
        row.addWidget(field("کد نمایندگی ایساکو", self.isaco_scus), 1)
        row.addWidget(field("نام کاربری ایساکو", self.isaco_user), 1)
        cred_card.body().addLayout(row)
        self.isaco_pass = QLineEdit()
        self.isaco_pass.setEchoMode(QLineEdit.EchoMode.Password)
        cred_card.add(field("رمز ایساکو", self.isaco_pass))

        self._secure_note = muted("")
        cred_card.add(self._secure_note)
        layout.addWidget(cred_card)

        # --- مسیر منابع ---
        paths_card = Card("مسیر فایل‌های داده (برای سینک خودکار)")
        self.haseb_path = self._path_row(paths_card, "فایل cal.DBF حاسب",
                                         "فایل DBF (*.DBF *.dbf)")
        self.isaco_path = self._path_row(paths_card, "فایل اکسل ایساکو (اختیاری)",
                                         "اکسل (*.xlsx *.xls)")
        paths_card.add(muted(
            "مسیر cal.DBF معمولاً در پوشهٔ نصب حاسب (DBF2) است. اگر سینک خودکار "
            "فعال باشد، از این مسیرها می‌خواند."
        ))
        layout.addWidget(paths_card)

        save = QPushButton("💾  ذخیرهٔ تنظیمات")
        save.setObjectName("Primary")
        save.setMinimumHeight(46)
        save.clicked.connect(self._save)
        layout.addWidget(save)
        layout.addStretch(1)

        outer.addWidget(scrollable(content))

    def _path_row(self, card: Card, label: str, filter_: str) -> QLineEdit:
        line = QLineEdit()
        line.setReadOnly(True)
        line.setPlaceholderText("انتخاب نشده")
        browse = QPushButton("انتخاب ...")
        browse.setMaximumWidth(120)

        def pick():
            path, _ = QFileDialog.getOpenFileName(self, label, "", filter_)
            if path:
                line.setText(path)

        browse.clicked.connect(pick)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(line, 1)
        row.addWidget(browse)
        wrapper = QWidget()
        wrapper.setLayout(row)
        card.add(field(label, wrapper))
        return line

    def _load(self) -> None:
        self.markup.setValue(float(self.db.get_setting("markup_percent", 0)))
        self._set_combo(self.base, self.db.get_setting("price_base", "vat"))
        self._set_combo(self.round_to, self.db.get_setting("round_to", 1000))
        self.max_change.setValue(int(self.db.get_setting("max_change_percent", 50)))
        self.max_stock.setValue(int(self.db.get_setting("max_on_site", 2)))
        self.reserve.setValue(int(self.db.get_setting("reserve", 0)))

        woo = self.store.load_woo()
        self.woo_url.setText(woo.base_url)
        self.woo_key.setText(woo.consumer_key)
        self.woo_secret.setText(woo.consumer_secret)

        isaco = self.store.load_isaco()
        self.isaco_scus.setText(isaco.scus)
        self.isaco_user.setText(isaco.username)
        self.isaco_pass.setText(isaco.password)

        self.haseb_path.setText(self.db.get_setting("haseb_cal_path", ""))
        self.isaco_path.setText(self.db.get_setting("isaco_excel_path", ""))

        if self.store.is_secure:
            self._secure_note.setText(
                "🔒 رمزها به‌صورت رمزنگاری‌شده در سیستم ویندوز ذخیره می‌شوند."
            )
        else:
            self._secure_note.setText(
                "⚠️ ذخیرهٔ امن سیستم در دسترس نیست؛ رمزها با احتیاط نگهداری می‌شوند."
            )

    @staticmethod
    def _set_combo(combo: QComboBox, value) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _save(self) -> None:
        self.db.set_setting("markup_percent", self.markup.value())
        self.db.set_setting("price_base", self.base.currentData())
        self.db.set_setting("round_to", self.round_to.currentData())
        self.db.set_setting("max_change_percent", self.max_change.value())
        self.db.set_setting("max_on_site", self.max_stock.value())
        self.db.set_setting("reserve", self.reserve.value())
        self.db.set_setting("haseb_cal_path", self.haseb_path.text().strip())
        self.db.set_setting("isaco_excel_path", self.isaco_path.text().strip())

        self.store.save_woo(WooCredentials(
            base_url=self.woo_url.text().strip(),
            consumer_key=self.woo_key.text().strip(),
            consumer_secret=self.woo_secret.text().strip(),
        ))
        self.store.save_isaco(IsacoCredentialsConfig(
            scus=self.isaco_scus.text().strip(),
            username=self.isaco_user.text().strip(),
            password=self.isaco_pass.text().strip(),
        ))
        self.settings_changed.emit()
        QMessageBox.information(self, "ذخیره شد", "تنظیمات با موفقیت ذخیره شد.")
