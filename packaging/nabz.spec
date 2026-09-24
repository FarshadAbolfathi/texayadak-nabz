# -*- mode: python ; coding: utf-8 -*-
"""فایل PyInstaller برای ساخت فایل اجرایی ویندوز.

ساخت (روی ویندوز):
    pip install pyinstaller
    pyinstaller packaging/nabz.spec

خروجی در dist/TexayadakNabz/TexayadakNabz.exe خواهد بود.
"""

import os

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
    ["run_app.py"],
    pathex=["src"],
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
    icon="icon.ico" if os.path.exists("packaging/icon.ico") else None,
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
