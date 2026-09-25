# -*- mode: python ; coding: utf-8 -*-
"""فایل PyInstaller برای ساخت فایل اجرایی ویندوز.

ساخت (روی ویندوز):
    pip install pyinstaller
    pyinstaller packaging/nabz.spec

خروجی در dist/TexayadakNabz/TexayadakNabz.exe خواهد بود.
"""

import os

# PyInstaller مسیرهای نسبی در spec را نسبت به پوشهٔ خود spec می‌سنجد.
# با SPECPATH (پوشهٔ این فایل = packaging) مسیر مطلق ریشهٔ مخزن را می‌سازیم
# تا صرف‌نظر از پوشهٔ اجرا، فایل ورودی درست پیدا شود.
ROOT = os.path.dirname(SPECPATH)
ENTRY_SCRIPT = os.path.join(ROOT, "run_app.py")
SRC_PATH = os.path.join(ROOT, "src")
ICON_PATH = os.path.join(SPECPATH, "icon.ico")

block_cipher = None

# ماژول‌هایی که PyInstaller ممکن است خودکار پیدا نکند
hidden = [
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.macOS",
    "apscheduler.schedulers.background",
    "apscheduler.triggers.cron",
    "Crypto.Cipher.AES",
    "Crypto.Cipher.PKCS1_OAEP",
    "Crypto.PublicKey.RSA",
    "openpyxl",
]

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[SRC_PATH],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PySide6.QtWebEngineCore"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TexayadakNabz",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # بدون پنجرهٔ کنسول
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TexayadakNabz",
)
