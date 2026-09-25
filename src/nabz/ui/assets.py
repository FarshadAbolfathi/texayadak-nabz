"""دسترسی به فایل‌های گرافیکی برنامه (لوگو و آیکون).

هم در حالت توسعه (کنار سورس) و هم در حالت بسته‌شده با PyInstaller کار می‌کند.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap


def _assets_dir() -> Path:
    # در حالت PyInstaller، فایل‌ها کنار اجرایی در پوشهٔ _internal قرار می‌گیرند
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "nabz" / "ui" / "assets"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent / "assets"


def asset_path(name: str) -> Path:
    return _assets_dir() / name


def app_icon() -> QIcon:
    """آیکون برنامه (نماد NT)."""
    path = asset_path("icon.png")
    if path.is_file():
        return QIcon(str(path))
    return QIcon()


def logo_pixmap(height: int = 40) -> QPixmap:
    """لوگوی کامل افقی، مقیاس‌شده به ارتفاع دلخواه."""
    from PySide6.QtCore import Qt

    path = asset_path("logo_full.png")
    if not path.is_file():
        return QPixmap()
    pix = QPixmap(str(path))
    return pix.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
