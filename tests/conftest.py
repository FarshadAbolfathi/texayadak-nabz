"""ابزارهای مشترک تست‌ها."""

import struct
from pathlib import Path

import pytest

from nabz.sources.haseb_dbf import ENCODING


def write_dbf(
    path: Path,
    fields: list[tuple[str, str, int, int]],
    rows: list[dict[str, str]],
    *,
    deleted: set[int] = frozenset(),
) -> Path:
    """یک فایل DBF نسخهٔ dBase III می‌سازد.

    با همان ساختاری که حاسب تولید می‌کند، تا خوانندهٔ ما را بدون نیاز
    به دیتابیس واقعی کارفرما بتوانیم تست کنیم.

    :param fields: لیست ``(نام، نوع، طول، اعشار)``
    :param deleted: شماره‌های ردیفی که به‌عنوان حذف‌شده علامت بخورند
    """
    record_length = 1 + sum(f[2] for f in fields)
    header_length = 32 + 32 * len(fields) + 1

    out = bytearray()
    out += struct.pack(
        "<BBBBIHH20x",
        0x03,            # dBase III بدون فایل memo
        126, 1, 1,       # تاریخ آخرین تغییر (YY MM DD)
        len(rows),
        header_length,
        record_length,
    )

    for name, ftype, length, decimals in fields:
        out += name.encode("ascii").ljust(11, b"\x00")
        out += ftype.encode("ascii")
        out += b"\x00" * 4
        out += bytes([length, decimals])
        out += b"\x00" * 14
    out += b"\x0d"

    for index, row in enumerate(rows):
        out += b"*" if index in deleted else b" "
        for name, ftype, length, _ in fields:
            value = str(row.get(name, ""))
            encoded = value.encode(ENCODING, "replace")[:length]
            # حاسب فیلدهای عددی را راست‌چین و متنی را چپ‌چین می‌کند
            out += encoded.rjust(length) if ftype == "N" else encoded.ljust(length)
    out += b"\x1a"   # نشانهٔ پایان فایل

    path.write_bytes(bytes(out))
    return path


#: ساختار سادهٔ جدول کالا با همان نام و نوع ستون‌های واقعی حاسب
CAL_FIELDS = [
    ("COD", "N", 12, 0),
    ("NAME", "C", 100, 0),
    ("COD_ANB", "N", 10, 0),
    ("NAME_ANB", "C", 50, 0),
    ("MOJ", "N", 20, 5),
    ("GH_FO", "N", 20, 4),
]


@pytest.fixture
def make_cal(tmp_path):
    """کارخانهٔ ساخت فایل ``cal.DBF`` آزمایشی."""

    def _make(rows, *, deleted=frozenset(), name="cal.DBF"):
        return write_dbf(tmp_path / name, CAL_FIELDS, rows, deleted=deleted)

    return _make


@pytest.fixture(autouse=True)
def _reset_sync_gate():
    """قفل سراسری سینک بین تست‌ها نشت نکند."""
    from nabz.sync_gate import gate
    gate.reset()
    yield
    gate.reset()


@pytest.fixture(scope="session", autouse=True)
def _qt_orderly_teardown():
    """در پایان نشست، پنجره‌ها/تایمرها قبل از QApplication پاک شوند.

    بدون این، پایتون موقع خروج اشیای Qt را با ترتیب دلخواه پاک می‌کند و روی
    ویندوز (CI) بعد از پاس شدن همهٔ تست‌ها «Fatal Python error: Aborted» می‌دهد.
    """
    yield
    try:
        from PySide6.QtCore import QCoreApplication, QEvent, QTimer
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        for timer in widget.findChildren(QTimer):
            timer.stop()
        tray = getattr(widget, "tray", None)
        if tray is not None:
            tray.hide()
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    import gc
    gc.collect()
