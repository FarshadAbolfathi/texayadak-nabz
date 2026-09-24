"""تم و استایل مشترک برنامه — ساده، تمیز، راست‌به‌چپ.

هدف: ظاهری که کارفرمای غیرفنی راحت باشد. رنگ‌های آرام، دکمه‌های بزرگ و
واضح، فونت خوانا، و همه‌چیز راست‌چین برای فارسی.
"""

from __future__ import annotations

# پالت رنگ — آبی آرام برند + خنثی‌های ملایم
COLORS = {
    "primary": "#1f6feb",       # آبی اصلی (دکمه‌های مهم)
    "primary_dark": "#1a5fd0",
    "success": "#1a7f37",       # سبز (تأیید، موفق)
    "danger": "#cf222e",        # قرمز (خطر، رول‌بک)
    "warning": "#bf8700",       # زرد (بازبینی)
    "bg": "#f6f8fa",            # پس‌زمینهٔ کلی
    "panel": "#ffffff",         # کارت‌ها و پنل‌ها
    "border": "#d0d7de",
    "text": "#1f2328",
    "text_muted": "#656d76",
    "row_alt": "#f6f8fa",
    "selection": "#ddf4ff",
}

FONT_FAMILY = "Vazirmatn, Tahoma, 'Segoe UI', sans-serif"


def stylesheet() -> str:
    """استایل‌شیت سراسری برنامه."""
    c = COLORS
    return f"""
    * {{
        font-family: {FONT_FAMILY};
        font-size: 14px;
        color: {c['text']};
    }}
    QMainWindow, QDialog, QWidget#Root {{
        background: {c['bg']};
    }}

    /* --- تب‌ها --- */
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: 8px;
        background: {c['panel']};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {c['text_muted']};
        padding: 10px 20px;
        margin-left: 2px;
        border: 1px solid transparent;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        font-size: 14px;
    }}
    QTabBar::tab:selected {{
        background: {c['panel']};
        color: {c['primary']};
        border: 1px solid {c['border']};
        border-bottom-color: {c['panel']};
        font-weight: bold;
    }}
    QTabBar::tab:hover:!selected {{
        color: {c['text']};
    }}

    /* --- کارت‌ها --- */
    QFrame#Card {{
        background: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 10px;
    }}
    QLabel#CardTitle {{
        font-size: 16px;
        font-weight: bold;
        color: {c['text']};
    }}
    QLabel#StatNumber {{
        font-size: 30px;
        font-weight: bold;
        color: {c['primary']};
    }}
    QLabel#StatLabel {{
        font-size: 13px;
        color: {c['text_muted']};
    }}
    QLabel#Muted {{ color: {c['text_muted']}; }}
    QLabel#H1 {{ font-size: 20px; font-weight: bold; }}

    /* --- دکمه‌ها --- */
    QPushButton {{
        background: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 9px 18px;
        font-size: 14px;
    }}
    QPushButton:hover {{ background: {c['row_alt']}; }}
    QPushButton:disabled {{ color: {c['text_muted']}; background: {c['bg']}; }}

    QPushButton#Primary {{
        background: {c['primary']};
        color: white;
        border: none;
        font-weight: bold;
    }}
    QPushButton#Primary:hover {{ background: {c['primary_dark']}; }}
    QPushButton#Primary:disabled {{ background: #9db8e0; }}

    QPushButton#Success {{ background: {c['success']}; color: white; border: none; font-weight: bold; }}
    QPushButton#Danger  {{ background: {c['danger']};  color: white; border: none; font-weight: bold; }}

    /* --- ورودی‌ها --- */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit {{
        background: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 8px 10px;
        min-height: 20px;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border: 1px solid {c['primary']};
    }}

    /* --- جدول --- */
    QTableWidget, QTableView {{
        background: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        gridline-color: {c['border']};
        selection-background-color: {c['selection']};
        selection-color: {c['text']};
        alternate-background-color: {c['row_alt']};
    }}
    QHeaderView::section {{
        background: {c['bg']};
        color: {c['text_muted']};
        padding: 8px;
        border: none;
        border-bottom: 1px solid {c['border']};
        font-weight: bold;
    }}
    QTableWidget::item {{ padding: 6px; }}

    /* --- نوار وضعیت --- */
    QStatusBar {{ background: {c['panel']}; color: {c['text_muted']}; }}

    QProgressBar {{
        border: 1px solid {c['border']};
        border-radius: 8px;
        text-align: center;
        background: {c['panel']};
        height: 22px;
    }}
    QProgressBar::chunk {{
        background: {c['primary']};
        border-radius: 7px;
    }}
    """
