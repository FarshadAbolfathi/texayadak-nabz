"""آیکون System Tray و ساخت آیکون برنامه به‌صورت برنامه‌نویسی.

چون فایل آیکون جدا نداریم، یک آیکون ساده (دایرهٔ آبی با حرف «ن») می‌سازیم
تا برنامه هم در tray و هم روی نوار وظیفه آیکون داشته باشد.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap

from .theme import COLORS


def app_icon() -> QIcon:
    """آیکون برنامه: دایرهٔ آبی با حرف «ن»."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor(COLORS["primary"])))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(2, 2, 60, 60))

    painter.setPen(QColor("white"))
    font = QFont()
    font.setPointSize(30)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "ن")
    painter.end()

    return QIcon(pixmap)
