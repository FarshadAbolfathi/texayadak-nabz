"""پنجرهٔ ورود به برنامه با رمز.

بار اول که برنامه اجرا می‌شود رمزی تعریف نشده، پس از کاربر می‌خواهد یک
رمز بسازد. دفعات بعد رمز را می‌پرسد. این جلوی این را می‌گیرد که هر کسی
پشت سیستم کارفرما به قیمت و موجودی سایت دست بزند.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..db import Database


class LoginDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._is_setup = not db.has_app_password()
        self.setWindowTitle("تکسایدک نبض — ورود")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(380)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title = QLabel("تکسایدک نبض")
        title.setObjectName("H1")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        if self._is_setup:
            hint = QLabel("اولین ورود: یک رمز برای برنامه انتخاب کنید.")
        else:
            hint = QLabel("رمز ورود به برنامه را وارد کنید.")
        hint.setObjectName("Muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("رمز عبور")
        self.password.returnPressed.connect(self._submit)
        layout.addWidget(self.password)

        if self._is_setup:
            self.confirm = QLineEdit()
            self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm.setPlaceholderText("تکرار رمز عبور")
            self.confirm.returnPressed.connect(self._submit)
            layout.addWidget(self.confirm)

        self.button = QPushButton("ساخت رمز و ورود" if self._is_setup else "ورود")
        self.button.setObjectName("Primary")
        self.button.clicked.connect(self._submit)
        layout.addWidget(self.button)

    def _submit(self) -> None:
        pwd = self.password.text()
        if self._is_setup:
            if len(pwd) < 4:
                QMessageBox.warning(self, "خطا", "رمز باید حداقل ۴ کاراکتر باشد.")
                return
            if pwd != self.confirm.text():
                QMessageBox.warning(self, "خطا", "دو رمز یکسان نیستند.")
                return
            self.db.set_app_password(pwd)
            self.accept()
        else:
            if self.db.verify_app_password(pwd):
                self.accept()
            else:
                QMessageBox.warning(self, "خطا", "رمز اشتباه است.")
                self.password.clear()
                self.password.setFocus()
