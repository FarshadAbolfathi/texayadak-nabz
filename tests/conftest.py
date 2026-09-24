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
