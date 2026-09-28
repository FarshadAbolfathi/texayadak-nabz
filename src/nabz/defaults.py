"""مقادیر پیش‌فرض اتصال برای فروشگاه تکسایدک.

این فایل عمداً خالی است تا هیچ رمزی در مخزن گیت نباشد. هنگام ساخت با
GitHub Actions، مقادیر واقعی از GitHub Secrets (رمزنگاری‌شده) در این فایل
نوشته می‌شوند و در فایل اجرایی نهایی قرار می‌گیرند تا برنامه بدون تایپ
دستی کار کند.

اگر این مقادیر خالی بمانند (مثلاً اجرای محلی)، برنامه فقط از کاربر
می‌خواهد یک‌بار در تنظیمات آن‌ها را وارد کند.
"""

from __future__ import annotations

# ووکامرس (فروشگاه تکسایدک)
DEFAULT_WOO_URL = ""
DEFAULT_WOO_KEY = ""
DEFAULT_WOO_SECRET = ""

# ایساکو (پورتال B2B)
DEFAULT_ISACO_SCUS = ""
DEFAULT_ISACO_USERNAME = ""
DEFAULT_ISACO_PASSWORD = ""

# مسیر پیش‌فرض فایل کالای حاسب (سال مالی جاری)
DEFAULT_HASEB_CAL = r"D:\rahnama\HasebmDX8.001\DBF2\cal.DBF"
