"""تم و استایل مشترک برنامه — راست‌به‌چپ، مدرن، برند آبی‑نارنجی.

رنگ‌ها از لوگوی برنامه گرفته شده‌اند: آبی «N» و نارنجی «T».
"""

from __future__ import annotations

COLORS = {
    # برند
    "primary": "#1f6feb",        # آبی اصلی
    "primary_dark": "#1559c9",
    "primary_light": "#3b82f6",
    "accent": "#f5820b",         # نارنجی برند (T)
    "accent_dark": "#e06f00",
    # وضعیت
    "success": "#1a7f37",
    "success_dark": "#146c2e",
    "danger": "#cf222e",
    "danger_dark": "#b31b26",
    "warning": "#bf8700",
    "warning_bg": "#fff8e1",
    # خنثی
    "bg": "#eef1f6",             # پس‌زمینهٔ کلی (کمی سردتر)
    "panel": "#ffffff",
    "border": "#dbe1e8",
    "border_strong": "#c7ced7",
    "text": "#1f2328",
    "text_muted": "#5b6470",
    "row_alt": "#f7f9fc",
    "selection": "#e3f0ff",
    "sidebar": "#ffffff",
}

FONT_FAMILY = "Vazirmatn, 'Segoe UI', Tahoma, sans-serif"


def stylesheet() -> str:
    c = COLORS
    return f"""
    * {{
        font-family: {FONT_FAMILY};
        font-size: 14px;
        color: {c['text']};
    }}
    QMainWindow, QDialog {{ background: {c['bg']}; }}
    QWidget#Root {{ background: {c['bg']}; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    /* --- نوار عنوان بالای پنجره (هدر برند) --- */
    QFrame#Header {{
        background: {c['panel']};
        border-bottom: 1px solid {c['border']};
    }}
    QLabel#BrandName {{
        font-size: 18px;
        font-weight: bold;
        color: {c['primary']};
    }}
    QLabel#BrandSub {{ font-size: 12px; color: {c['accent']}; font-weight: bold; }}

    /* --- تب‌ها --- */
    QTabWidget::pane {{
        border: none;
        background: transparent;
        top: 0px;
    }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {c['text_muted']};
        padding: 11px 18px;
        margin: 0 2px;
        border: none;
        border-bottom: 3px solid transparent;
        font-size: 14px;
    }}
    QTabBar::tab:selected {{
        color: {c['primary']};
        border-bottom: 3px solid {c['accent']};
        font-weight: bold;
    }}
    QTabBar::tab:hover:!selected {{
        color: {c['text']};
        border-bottom: 3px solid {c['border_strong']};
    }}

    /* --- کارت‌ها --- */
    QFrame#Card {{
        background: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QLabel#CardTitle {{
        font-size: 15px;
        font-weight: bold;
        color: {c['text']};
        padding-bottom: 2px;
    }}
    QFrame#CardAccent {{
        background: {c['accent']};
        border-radius: 2px;
        max-width: 4px;
        min-width: 4px;
    }}
    QLabel#StatNumber {{ font-size: 32px; font-weight: bold; color: {c['primary']}; }}
    QLabel#StatLabel {{ font-size: 13px; color: {c['text_muted']}; }}
    QLabel#Muted {{ color: {c['text_muted']}; font-size: 13px; }}
    QLabel#H1 {{ font-size: 22px; font-weight: bold; color: {c['text']}; }}
    QLabel#FieldLabel {{ color: {c['text_muted']}; font-size: 13px; font-weight: bold; }}

    /* --- دکمه‌ها --- */
    QPushButton {{
        background: {c['panel']};
        border: 1px solid {c['border_strong']};
        border-radius: 9px;
        padding: 9px 18px;
        font-size: 14px;
    }}
    QPushButton:hover {{ background: {c['row_alt']}; border-color: {c['primary_light']}; }}
    QPushButton:disabled {{ color: #9aa4b0; background: {c['bg']}; border-color: {c['border']}; }}

    QPushButton#Primary {{
        background: {c['primary']};
        color: white; border: none; font-weight: bold;
    }}
    QPushButton#Primary:hover {{ background: {c['primary_dark']}; }}
    QPushButton#Primary:disabled {{ background: #9db8e0; color: #eef; }}

    QPushButton#Accent {{
        background: {c['accent']}; color: white; border: none; font-weight: bold;
    }}
    QPushButton#Accent:hover {{ background: {c['accent_dark']}; }}

    QPushButton#Success {{ background: {c['success']}; color: white; border: none; font-weight: bold; }}
    QPushButton#Success:hover {{ background: {c['success_dark']}; }}
    QPushButton#Success:disabled {{ background: #a7cdb4; color: #eef; }}

    QPushButton#Danger {{ background: {c['danger']}; color: white; border: none; font-weight: bold; }}
    QPushButton#Danger:hover {{ background: {c['danger_dark']}; }}

    /* --- ورودی‌ها --- */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit {{
        background: {c['panel']};
        border: 1px solid {c['border_strong']};
        border-radius: 9px;
        padding: 9px 11px;
        min-height: 20px;
        selection-background-color: {c['selection']};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTimeEdit:focus {{
        border: 2px solid {c['primary']};
        padding: 8px 10px;
    }}
    QLineEdit:read-only {{ background: {c['row_alt']}; color: {c['text_muted']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox QAbstractItemView {{
        background: {c['panel']};
        border: 1px solid {c['border_strong']};
        border-radius: 8px;
        selection-background-color: {c['selection']};
        selection-color: {c['text']};
        padding: 4px;
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button {{
        width: 20px; border: none; background: {c['row_alt']};
    }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 20px; height: 20px;
        border: 1px solid {c['border_strong']};
        border-radius: 5px; background: {c['panel']};
    }}
    QCheckBox::indicator:checked {{
        background: {c['primary']}; border-color: {c['primary']};
        image: none;
    }}

    /* --- جدول --- */
    QTableWidget, QTableView {{
        background: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        gridline-color: {c['row_alt']};
        selection-background-color: {c['selection']};
        selection-color: {c['text']};
        alternate-background-color: {c['row_alt']};
    }}
    QHeaderView::section {{
        background: {c['bg']};
        color: {c['text_muted']};
        padding: 10px 8px;
        border: none;
        border-bottom: 2px solid {c['border']};
        font-weight: bold;
    }}
    QTableWidget::item {{ padding: 7px; }}

    /* --- اسکرول‌بار --- */
    QScrollBar:vertical {{
        background: transparent; width: 12px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border_strong']}; border-radius: 6px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c['text_muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c['border_strong']}; border-radius: 6px; min-width: 30px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* --- سایر --- */
    QStatusBar {{ background: {c['panel']}; color: {c['text_muted']}; border-top: 1px solid {c['border']}; }}
    QProgressBar {{
        border: none; border-radius: 8px; text-align: center;
        background: {c['border']}; height: 8px; color: transparent;
    }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 8px; }}
    """
