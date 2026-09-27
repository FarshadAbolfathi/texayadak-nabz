"""اطلاعات نسخه و build برنامه.

مقادیر پیش‌فرض برای اجرای محلی است. هنگام ساخت با GitHub Actions، این فایل
با شمارهٔ build واقعی، کامیت و تاریخ بازنویسی می‌شود تا کاربر بتواند نسخهٔ
نصب‌شده را با صفحهٔ Releases مطابقت دهد.
"""

from __future__ import annotations

APP_VERSION = "1.0"
BUILD_NUMBER = "محلی"   # روی CI با github.run_number جایگزین می‌شود
COMMIT = ""             # هفت رقم اول کامیت
BUILD_DATE = ""         # تاریخ ساخت


def _to_fa(text: str) -> str:
    return str(text).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def version_line() -> str:
    """یک خط نمایشی نسخه برای بخش «دربارهٔ برنامه»."""
    parts = [f"نسخهٔ {_to_fa(APP_VERSION)}"]
    if BUILD_NUMBER and BUILD_NUMBER != "محلی":
        parts.append(f"build {_to_fa(BUILD_NUMBER)}")
    elif BUILD_NUMBER:
        parts.append(BUILD_NUMBER)
    if COMMIT:
        parts.append(f"({COMMIT})")
    line = "  —  ".join(parts[:2])
    if len(parts) > 2:
        line += "  " + parts[2]
    if BUILD_DATE:
        line += f"\nتاریخ ساخت: {_to_fa(BUILD_DATE)}"
    return line
