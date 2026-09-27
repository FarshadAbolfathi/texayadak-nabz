"""پنجرهٔ ورود به برنامه با رمز + بازیابی رمز فراموش‌شده.

بار اول رمز ساخته می‌شود؛ دفعات بعد پرسیده می‌شود. اگر رمز فراموش شد،
با کمک پشتیبان (کد چالش–پاسخ) قابل بازیابی است تا برنامه قفل نماند.
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
from ..recovery import make_challenge, verify_response
from .tray import app_icon


class LoginDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._is_setup = not db.has_app_password()
        self.setWindowTitle("تکسایدک نبض — ورود")
        self.setWindowIcon(app_icon())
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(400)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(14)

        title = QLabel("تکسایدک نبض")
        title.setObjectName("H1")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel(
            "اولین ورود: یک رمز برای برنامه انتخاب کنید."
            if self._is_setup else "رمز ورود به برنامه را وارد کنید."
        )
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
        self.button.setMinimumHeight(44)
        self.button.clicked.connect(self._submit)
        layout.addWidget(self.button)

        if not self._is_setup:
            forgot = QPushButton("فراموشی رمز؟")
            forgot.setFlat(True)
            forgot.setStyleSheet("border: none; color: #1f6feb; background: transparent;")
            forgot.setCursor(Qt.CursorShape.PointingHandCursor)
            forgot.clicked.connect(self._forgot)
            layout.addWidget(forgot)

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

    def _forgot(self) -> None:
        dialog = RecoveryDialog(self.db, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(
                self, "انجام شد",
                "رمز جدید ثبت شد. حالا با رمز جدید وارد شوید.",
            )
            self.password.clear()
            self.password.setFocus()


class RecoveryDialog(QDialog):
    """بازیابی رمز با کد چالش–پاسخ از طریق پشتیبان."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._challenge = make_challenge()
        self.setWindowTitle("بازیابی رمز")
        self.setWindowIcon(app_icon())
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(430)
        self._build()

    def _build(self) -> None:
        from .tabs.support import DEVELOPER_PHONE

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(12)

        title = QLabel("بازیابی رمز فراموش‌شده")
        title.setObjectName("H1")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        steps = QLabel(
            "۱) «کد چالش» زیر را برای پشتیبانی بفرستید:\n"
            f"      {DEVELOPER_PHONE}  (واتساپ)\n"
            "۲) «کد پاسخ» را که پشتیبان می‌دهد وارد کنید.\n"
            "۳) رمز جدید تعریف کنید."
        )
        steps.setObjectName("Muted")
        steps.setWordWrap(True)
        layout.addWidget(steps)

        challenge_label = QLabel(self._challenge)
        challenge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        challenge_label.setStyleSheet(
            "font-size: 30px; font-weight: bold; letter-spacing: 8px; "
            "color: #f5820b; background: #fff8e1; border-radius: 10px; padding: 12px;"
        )
        challenge_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(challenge_label)

        self.response = QLineEdit()
        self.response.setPlaceholderText("کد پاسخ از پشتیبان")
        layout.addWidget(self.response)

        self.new_pass = QLineEdit()
        self.new_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pass.setPlaceholderText("رمز جدید")
        layout.addWidget(self.new_pass)

        self.new_pass2 = QLineEdit()
        self.new_pass2.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pass2.setPlaceholderText("تکرار رمز جدید")
        layout.addWidget(self.new_pass2)

        btn = QPushButton("تأیید و تعریف رمز جدید")
        btn.setObjectName("Primary")
        btn.setMinimumHeight(44)
        btn.clicked.connect(self._submit)
        layout.addWidget(btn)

    def _submit(self) -> None:
        if not verify_response(self._challenge, self.response.text()):
            QMessageBox.warning(
                self, "خطا",
                "کد پاسخ نادرست است. مطمئن شوید کد چالش را درست به پشتیبان "
                "داده‌اید و کد پاسخ را دقیق وارد کرده‌اید.",
            )
            return
        pwd = self.new_pass.text()
        if len(pwd) < 4:
            QMessageBox.warning(self, "خطا", "رمز جدید باید حداقل ۴ کاراکتر باشد.")
            return
        if pwd != self.new_pass2.text():
            QMessageBox.warning(self, "خطا", "دو رمز یکسان نیستند.")
            return
        self.db.set_app_password(pwd)
        self.accept()
