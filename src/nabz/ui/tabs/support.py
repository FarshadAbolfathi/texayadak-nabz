"""تب پشتیبانی — اطلاعات تماس سازندهٔ برنامه."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

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
            "نرم‌افزار حسابداری حاسب، و فروشگاه اینترنتی تکسایدک.\n\n"
            "نسخهٔ ۱.۰"
        ))
        layout.addWidget(about)
        layout.addStretch(1)
