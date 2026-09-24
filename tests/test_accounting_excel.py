"""تست خواندن اکسل/CSV حسابداری با نگاشت ستون."""

from decimal import Decimal

import pytest
from openpyxl import Workbook

from nabz.sources.accounting_excel import (
    ColumnMapping,
    read_headers,
    read_rows,
)


def make_xlsx(path, rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


SAMPLE = [
    ["کد کالا", "نام", "موجودی", "قیمت"],
    ["50102699", "استارت", "5", "56000000"],
    ["921900699", "سنسور", "0", "11760000"],
]


class TestHeaders:
    def test_reads_header_row(self, tmp_path):
        path = make_xlsx(tmp_path / "a.xlsx", SAMPLE)
        assert read_headers(path) == ["کد کالا", "نام", "موجودی", "قیمت"]


class TestReadRows:
    def test_maps_columns(self, tmp_path):
        path = make_xlsx(tmp_path / "a.xlsx", SAMPLE)
        rows = read_rows(path, ColumnMapping(code=0, quantity=2, price=3))
        assert len(rows) == 2
        assert rows[0].code == "0050102699"       # نرمال‌شده
        assert rows[0].quantity == Decimal("5")
        assert rows[0].price == Decimal("56000000")

    def test_quantity_only(self, tmp_path):
        path = make_xlsx(tmp_path / "a.xlsx", SAMPLE)
        rows = read_rows(path, ColumnMapping(code=0, quantity=2))
        assert rows[0].price is None
        assert rows[0].quantity == Decimal("5")

    def test_skips_rows_without_code(self, tmp_path):
        data = SAMPLE + [["", "بی‌کد", "3", "1000"]]
        path = make_xlsx(tmp_path / "a.xlsx", data)
        rows = read_rows(path, ColumnMapping(code=0, quantity=2))
        assert len(rows) == 2

    def test_persian_digits_in_quantity(self, tmp_path):
        data = [["کد", "موجودی"], ["50102699", "۵"]]
        path = make_xlsx(tmp_path / "a.xlsx", data)
        rows = read_rows(path, ColumnMapping(code=0, quantity=1))
        assert rows[0].quantity == Decimal("5")

    def test_comma_separated_numbers(self, tmp_path):
        data = [["کد", "قیمت"], ["50102699", "56,000,000"]]
        path = make_xlsx(tmp_path / "a.xlsx", data)
        rows = read_rows(path, ColumnMapping(code=0, price=1))
        assert rows[0].price == Decimal("56000000")


class TestCsv:
    def test_reads_csv(self, tmp_path):
        path = tmp_path / "a.csv"
        path.write_text("کد,موجودی\n50102699,5\n921900699,0\n", encoding="utf-8-sig")
        rows = read_rows(path, ColumnMapping(code=0, quantity=1))
        assert len(rows) == 2
        assert rows[1].code == "0921900699"
        assert rows[1].quantity == Decimal("0")
