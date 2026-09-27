"""تب پشتیبانی — اطلاعات تماس سازندهٔ برنامه."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..widgets import Card, muted

# اطلاعات سازنده
DEVELOPER_NAME = "Farshad Abolfathi"
DEVELOPER_PHONE = "09127259609"
WHATSAPP_URL = "https://wa.me/989127259609"


class SupportTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        card = Card("پشتیبانی و ارتباط با سازنده")
        card.add(muted(
            "برای هر گونه سوال، مشکل فنی، یا درخواست تغییر در برنامه، با سازندهٔ "
            "برنامه در تماس باشید. پاسخ‌گویی از طریق واتساپ سریع‌تر است."
        ))

        name = QLabel(f"👤  {DEVELOPER_NAME}")
        name.setStyleSheet("font-size: 16px; font-weight: bold;")
        card.add(name)

        phone = QLabel(f"📞  {DEVELOPER_PHONE}")
        phone.setStyleSheet("font-size: 16px;")
        phone.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.add(phone)

        whatsapp = QPushButton("💬  گفتگو در واتساپ")
        whatsapp.setObjectName("Success")
        whatsapp.setCursor(Qt.CursorShape.PointingHandCursor)
        whatsapp.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(WHATSAPP_URL))
        )
        card.add(whatsapp)

        layout.addWidget(card)

        about = Card("دربارهٔ برنامه")
        about.add(muted(
            "تکسایدک نبض — برنامهٔ همگام‌سازی قیمت و موجودی بین سامانهٔ ایساکو، "
            "نرم‌افزار حسابداری حاسب، و فروشگاه اینترنتی تکسایدک."
        ))
        from ...build_info import version_line
        version = QLabel(version_line())
        version.setStyleSheet("font-weight: bold; color: #1f6feb;")
        version.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        about.add(version)
        about.add(muted(
            "برای اطمینان از داشتن آخرین نسخه، این شمارهٔ build را با شمارهٔ "
            "آخرین نسخه در صفحهٔ دانلود مقایسه کنید."
        ))
        layout.addWidget(about)

        # --- لاگ برای دیباگ ---
        log_card = Card("گزارش فنی (لاگ)")
        log_card.add(muted(
            "اگر مشکلی پیش آمد، این لاگ را برای پشتیبانی بفرستید تا سریع‌تر "
            "علت را پیدا کند."
        ))
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        refresh_btn = QPushButton("🔄  نمایش لاگ")
        refresh_btn.clicked.connect(self._show_log)
        save_btn = QPushButton("💾  ذخیرهٔ فایل لاگ")
        save_btn.setObjectName("Primary")
        save_btn.clicked.connect(self._save_log)
        open_btn = QPushButton("📂  باز کردن پوشهٔ لاگ")
        open_btn.clicked.connect(self._open_log_dir)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(open_btn)
        log_card.body().addLayout(btn_row)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMinimumHeight(220)
        self._log_view.setStyleSheet(
            "font-family: 'Consolas', monospace; font-size: 12px;"
        )
        self._log_view.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        log_card.add(self._log_view)
        layout.addWidget(log_card)

        layout.addStretch(1)

    def _show_log(self) -> None:
        from ...logging_setup import read_recent_log
        self._log_view.setPlainText(read_recent_log())
        self._log_view.verticalScrollBar().setValue(
            self._log_view.verticalScrollBar().maximum()
        )

    def _save_log(self) -> None:
        from ...logging_setup import log_file
        import shutil

        src = log_file()
        if not src.is_file():
            QMessageBox.information(self, "لاگ", "هنوز لاگی ثبت نشده است.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ فایل لاگ", "nabz-log.txt", "فایل متنی (*.txt *.log)"
        )
        if dest:
            try:
                shutil.copyfile(src, dest)
                QMessageBox.information(
                    self, "ذخیره شد",
                    f"فایل لاگ ذخیره شد:\n{dest}\n\nآن را برای پشتیبانی بفرستید.",
                )
            except OSError as exc:
                QMessageBox.critical(self, "خطا", str(exc))

    def _open_log_dir(self) -> None:
        from ...logging_setup import log_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir())))
