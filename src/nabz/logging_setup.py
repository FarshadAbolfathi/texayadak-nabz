"""پیکربندی لاگ برنامه برای دیباگ راحت‌تر.

همهٔ رویدادها و خطاها در یک فایل لاگ نوشته می‌شوند که کارفرما می‌تواند
برای پشتیبانی بفرستد. لاگ چرخشی است (فایل بزرگ نمی‌شود) و خطاهای
پیش‌بینی‌نشده هم خودکار ثبت می‌شوند.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR_NAME = ".texayadak-nabz"
LOG_FILE_NAME = "nabz.log"

_configured = False


def log_dir() -> Path:
    path = Path.home() / LOG_DIR_NAME / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file() -> Path:
    return log_dir() / LOG_FILE_NAME


class _JalaliFormatter(logging.Formatter):
    """زمان هر خط لاگ به تاریخ شمسی (با ارقام انگلیسی برای جستجوی راحت)."""

    def formatTime(self, record, datefmt=None):  # noqa: N802 - امضای logging
        import datetime as _dt

        from .jalali import format_datetime

        return format_datetime(
            _dt.datetime.fromtimestamp(record.created),
            persian_digits=False, seconds=True,
        )


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """لاگ را یک‌بار پیکربندی می‌کند و logger ریشه را برمی‌گرداند."""
    global _configured
    logger = logging.getLogger("nabz")
    if _configured:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    fmt = _JalaliFormatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    # فایل چرخشی: تا ۱ مگابایت، ۵ فایل پشتیبان
    file_handler = RotatingFileHandler(
        log_file(), maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    # کنسول هم (برای اجرای توسعه)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    # ثبت خطاهای پیش‌بینی‌نشده
    def _excepthook(exc_type, exc_value, exc_tb):
        logger.critical("خطای پیش‌بینی‌نشده", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    import threading

    def _thread_excepthook(args):
        logger.critical("خطای پیش‌بینی‌نشده در نخ %s", getattr(args.thread, "name", "?"),
                        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = _thread_excepthook

    _enable_crash_log(logger)
    _install_qt_message_handler(logger)

    _configured = True
    logger.info("=== شروع برنامه ===")
    return logger


CRASH_FILE_NAME = "crash.log"
_crash_file = None   # باید تا پایان برنامه باز بماند


def _enable_crash_log(logger: logging.Logger) -> None:
    """کرش‌های بومی (Qt/C++) هیچ لاگ پایتونی نمی‌گذارند؛ faulthandler در همان
    لحظه ردِ اجرای همهٔ نخ‌ها را در crash.log می‌نویسد."""
    global _crash_file
    import faulthandler

    try:
        _crash_file = open(log_dir() / CRASH_FILE_NAME, "a", encoding="utf-8")  # noqa: SIM115
        import datetime as _dt
        _crash_file.write(f"\n=== اجرا {_dt.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
        _crash_file.flush()
        faulthandler.enable(file=_crash_file, all_threads=True)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("ثبت کرش فعال نشد: %s", exc)


def _install_qt_message_handler(logger: logging.Logger) -> None:
    """هشدار و خطاهای داخلی Qt را هم وارد فایل لاگ می‌کند."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }
    qt_log = logging.getLogger("nabz.qt")

    def handler(mode, context, message) -> None:
        level = levels.get(mode, logging.WARNING)
        if getattr(context, "category", "") == "js" and level < logging.CRITICAL:
            # پیام‌های کنسول جاوااسکریپتِ خود سایت ایساکو (هشدار moment،
            # CORS چت‌بات و …) ربطی به برنامه ندارند و لاگ را پر می‌کردند
            return
        if level >= logging.WARNING:
            qt_log.log(level, "%s", message)
        if mode == QtMsgType.QtFatalMsg:
            for h in logger.handlers:
                h.flush()

    qInstallMessageHandler(handler)


def get_logger(name: str = "nabz") -> logging.Logger:
    """logger ماژول را می‌دهد (زیرمجموعهٔ لاگ اصلی)."""
    if name == "nabz":
        return logging.getLogger("nabz")
    return logging.getLogger(f"nabz.{name}")


def read_recent_log(max_bytes: int = 200_000) -> str:
    """آخرین بخش فایل لاگ را برمی‌گرداند (برای نمایش در برنامه)."""
    path = log_file()
    if not path.is_file():
        return "فایل لاگ هنوز ساخته نشده است."
    try:
        data = path.read_bytes()
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        return data.decode("utf-8", "replace")
    except OSError as exc:
        return f"خطا در خواندن فایل لاگ: {exc}"
