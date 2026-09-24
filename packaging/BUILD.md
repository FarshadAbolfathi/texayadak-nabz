# ساخت فایل نصبی ویندوز — تکسایدک نبض

این مراحل باید **روی یک سیستم ویندوز** انجام شوند (PyInstaller برای هر سیستم‌عاملی
خروجی همان سیستم‌عامل را می‌سازد؛ برای exe ویندوزی باید روی ویندوز build کنید).

## پیش‌نیازها

1. Python 3.12 (۶۴ بیتی) از python.org
2. Inno Setup 6 از https://jrsoftware.org/isdl.php

## مرحلهٔ ۱ — محیط و وابستگی‌ها

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e .
pip install pyinstaller
```

## مرحلهٔ ۲ — تست (اختیاری ولی توصیه‌شده)

```bat
pip install pytest pytest-cov
pytest -q
```

## مرحلهٔ ۳ — ساخت فایل اجرایی

```bat
pyinstaller packaging\nabz.spec
```

خروجی: `dist\TexayadakNabz\TexayadakNabz.exe`
می‌توانید همین الان اجرایش کنید و مطمئن شوید کار می‌کند.

## مرحلهٔ ۴ — ساخت فایل نصبی

`packaging\installer.iss` را با **Inno Setup Compiler** باز کنید و `Build > Compile`
را بزنید. خروجی:

```
packaging\Output\TexayadakNabz-Setup-1.0.0.exe
```

این تک‌فایل را به کارفرما بدهید. فقط Next می‌زند و نصب می‌شود.

## نکات

- **آیکون**: یک فایل `packaging\icon.ico` بگذارید تا آیکون اختصاصی داشته باشد
  (وگرنه آیکون پیش‌فرض استفاده می‌شود). برنامه در tray هم یک آیکون ساده می‌سازد.
- **اجرای خودکار هنگام بوت**: در نصب‌کننده گزینه‌اش هست؛ برای سینک خودکار شبانه
  لازم است برنامه در حال اجرا (در tray) باشد.
- **آنتی‌ویروس**: گاهی exeهای PyInstaller را اشتباه علامت می‌زنند. اگر شد، برنامه
  را در whitelist ویندوز دیفندر اضافه کنید یا فایل را sign کنید.
- **دیتابیس برنامه**: در `%USERPROFILE%\.texayadak-nabz\nabz.db` ساخته می‌شود و
  شامل تنظیمات، تاریخچه و snapshotهای رول‌بک است.
