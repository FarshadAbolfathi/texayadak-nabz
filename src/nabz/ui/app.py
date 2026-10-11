"""نقطهٔ ورود برنامهٔ گرافیکی تکسایدک نبض."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from ..config import CredentialStore
from ..db import Database
from .login import LoginDialog
from .main_window import MainWindow, default_db_path
from .theme import stylesheet


def run(db_path: str | Path | None = None) -> int:
    """برنامه را اجرا می‌کند: ورود با رمز، سپس پنجرهٔ اصلی."""
    from ..logging_setup import setup_logging
    logger = setup_logging()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("تکسایدک نبض")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setStyleSheet(stylesheet())
    from .tray import app_icon
    app.setWindowIcon(app_icon())

    from ..build_info import BUILD_NUMBER, COMMIT
    logger.info("نسخه build=%s commit=%s", BUILD_NUMBER, COMMIT)

    # فقط یک نسخه از برنامه: اجرای دوباره، پنجرهٔ باز را جلو می‌آورد
    from .single_instance import SingleInstance
    instance = SingleInstance()
    if not instance.acquire():
        return 0
    shown: list = []          # پنجرهٔ اصلی پس از ورود اینجا قرار می‌گیرد
    instance.activated.connect(
        lambda: shown and shown[0]._restore_from_tray())

    path = Path(db_path) if db_path else default_db_path()
    db = Database(path)
    store = CredentialStore()
    _seed_defaults(db, store)

    # اگر رمز تنظیم شده و کارفرما خواسته هنگام ورود پرسیده شود
    needs_login = db.has_app_password() and db.get_setting("require_password", True)
    if not db.has_app_password():
        needs_login = True  # بار اول برای ساخت رمز

    if needs_login:
        login = LoginDialog(db)
        if login.exec() != QDialog.DialogCode.Accepted:
            db.close()
            instance.release()
            return 0

    window = MainWindow(db, store)
    shown.append(window)
    # همیشه تمام‌صفحه (و داخل محدودهٔ صفحه، بدون بیرون‌زدگی از لبه‌ها)
    window.showMaximized()
    code = app.exec()
    _shutdown_cleanly(window)
    db.close()
    instance.release()
    return code


def _shutdown_cleanly(window) -> None:
    """پنجره، تایمرها و نخ‌ها را تا وقتی QApplication زنده است پاک می‌کند.

    اگر این‌ها به پاک‌سازی پایانی پایتون سپرده شوند، روی ویندوز ممکن است
    بعد از خود QApplication پاک شوند و موقع خروج کرش بدهند.
    """
    from PySide6.QtCore import QCoreApplication, QEvent

    try:
        timer = getattr(window, "_schedule_timer", None)
        if timer is not None:
            timer.stop()
        thread = getattr(window, "_sync_thread", None)
        if thread is not None:
            thread.quit()
            thread.wait(10_000)
        tray = getattr(window, "tray", None)
        if tray is not None:
            tray.hide()
        window.hide()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
    except Exception:  # noqa: BLE001 - خروج نباید گیر کند
        pass


def _seed_defaults(db, store) -> None:
    """بار اول، اعتبارنامه‌های پیش‌فرض تکسایدک را ذخیره می‌کند تا برنامه
    بدون تنظیم دستی کار کند."""
    from pathlib import Path as _Path

    from ..config import IsacoCredentialsConfig, WooCredentials
    from ..defaults import (
        DEFAULT_HASEB_CAL,
        DEFAULT_ISACO_PASSWORD,
        DEFAULT_ISACO_SCUS,
        DEFAULT_ISACO_USERNAME,
        DEFAULT_WOO_KEY,
        DEFAULT_WOO_SECRET,
        DEFAULT_WOO_URL,
    )

    if not store.load_woo().base_url:
        store.save_woo(WooCredentials(
            base_url=DEFAULT_WOO_URL,
            consumer_key=DEFAULT_WOO_KEY,
            consumer_secret=DEFAULT_WOO_SECRET,
        ))
    if not store.load_isaco().scus:
        store.save_isaco(IsacoCredentialsConfig(
            scus=DEFAULT_ISACO_SCUS,
            username=DEFAULT_ISACO_USERNAME,
            password=DEFAULT_ISACO_PASSWORD,
        ))
    if not db.get_setting("haseb_cal_path") and _Path(DEFAULT_HASEB_CAL).is_file():
        db.set_setting("haseb_cal_path", DEFAULT_HASEB_CAL)


def main() -> None:
    import logging
    import os

    code = run()
    # همه‌چیز (دیتابیس، لاگ، پنجره) بسته شده؛ از پاک‌سازی پایانی و بی‌ترتیبِ
    # اشیای Qt توسط پایتون صرف‌نظر می‌کنیم که روی ویندوز می‌تواند هنگام خروج
    # کرش بدهد و crash.log را با خطای گمراه‌کننده پر کند.
    logging.shutdown()
    try:
        sys.stdout and sys.stdout.flush()
        sys.stderr and sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    os._exit(code)


if __name__ == "__main__":
    main()
