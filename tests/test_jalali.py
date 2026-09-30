"""تست تبدیل تاریخ شمسی."""

import datetime as dt

import pytest

from nabz import jalali


@pytest.mark.parametrize("greg, jal", [
    ((2024, 3, 20), (1403, 1, 1)),     # نوروز ۱۴۰۳
    ((2025, 3, 20), (1403, 12, 30)),   # ۱۴۰۳ کبیسه است
    ((2025, 3, 21), (1404, 1, 1)),
    ((2026, 9, 30), (1405, 7, 8)),
    ((2000, 1, 1), (1378, 10, 11)),
])
def test_known_dates(greg, jal):
    assert jalali.gregorian_to_jalali(*greg) == jal
    assert jalali.jalali_to_gregorian(*jal) == greg


def test_roundtrip_many_days():
    start = dt.date(1990, 1, 1)
    for i in range(0, 20000, 3):
        d = start + dt.timedelta(days=i)
        j = jalali.gregorian_to_jalali(d.year, d.month, d.day)
        assert jalali.jalali_to_gregorian(*j) == (d.year, d.month, d.day)


def test_format_ts_and_iso():
    ts = dt.datetime(2026, 9, 30, 8, 5).timestamp()
    assert jalali.format_ts(ts) == "۱۴۰۵/۰۷/۰۸  ۰۸:۰۵"
    assert jalali.format_ts(None) == "—"
    assert jalali.format_iso("2026-09-30T08:05:00") == "۱۴۰۵/۰۷/۰۸  ۰۸:۰۵"
    assert jalali.format_iso("bad") == "—"


def test_today_is_file_safe():
    assert "/" not in jalali.today()
