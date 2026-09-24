"""تست خوانندهٔ فایل لیست قیمت ایساکو.

تست‌های نشان‌دار با ``realdata`` فقط وقتی اجرا می‌شوند که فایل واقعی
``res.xlsx`` کنار پروژه باشد. بقیه با فایل ساختگی کار می‌کنند تا
روی هر ماشینی قابل اجرا باشند.
"""

from pathlib import Path

import pytest
from openpyxl import Workbook

from nabz.sources.isaco_excel import (
    EXPECTED_HEADERS,
    IsacoFileError,
    build_prefix_index,
    load,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_FILE = PROJECT_ROOT / "res.xlsx"

# سه ردیف واقعی از فایل ایساکو
SAMPLE_ROWS = [
    ["0050102697", "استارت كامل موتورچهارزغاله", "پژو پارس", "عدد", 1,
     56_000_000, 61_600_000, 50_000_000],
    ["0050102699", "استارت كامل موتورچهارزغاله", "پژو پارس", "عدد", 1,
     62_720_000, 68_992_000, 56_000_000],
    ["0921900699", "سنسور ميل سوپاپ", "پژو پارس", "عدد", 1,
     11_760_000, 12_936_000, 10_500_000],
]


def _make_file(path: Path, headers=EXPECTED_HEADERS, rows=SAMPLE_ROWS) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "لیست قیمت"
    sheet.append(list(headers))
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


class TestLoad:
    def test_reads_rows_and_normalizes_codes(self, tmp_path):
        items = load(_make_file(tmp_path / "p.xlsx"), strict=False)
        assert set(items) == {"0050102697", "0050102699", "0921900699"}

    def test_maps_columns_to_the_right_prices(self, tmp_path):
        items = load(_make_file(tmp_path / "p.xlsx"), strict=False)
        starter = items["0050102699"]
        assert starter.retail == 62_720_000      # قیمت مصرف کننده
        assert starter.vat == 68_992_000         # با ارزش افزوده
        assert starter.wholesale == 56_000_000   # في فروش
        assert starter.car == "پژو پارس"
        assert starter.unit == "عدد"

    def test_raw_code_drops_leading_zeros(self, tmp_path):
        """همان فرمی که کد در حاسب ذخیره شده."""
        items = load(_make_file(tmp_path / "p.xlsx"), strict=False)
        assert items["0050102699"].raw_code == "50102699"


class TestStructureGuard:
    def test_rejects_changed_headers(self, tmp_path):
        bad = list(EXPECTED_HEADERS)
        bad[6] = "قیمت با مالیات"   # ایساکو نام ستون را عوض کرده
        path = _make_file(tmp_path / "bad.xlsx", headers=bad)
        with pytest.raises(IsacoFileError, match="ساختار فایل ایساکو"):
            load(path, strict=False)

    def test_rejects_empty_file(self, tmp_path):
        path = _make_file(tmp_path / "empty.xlsx", rows=[])
        with pytest.raises(IsacoFileError):
            load(path)   # strict روشن ⇒ ردیف کم

    def test_strict_rejects_suspiciously_small_download(self, tmp_path):
        """دانلود ناقص نباید قیمت‌های سایت را خراب کند."""
        path = _make_file(tmp_path / "short.xlsx")
        with pytest.raises(IsacoFileError, match="ناقص"):
            load(path, strict=True)

    def test_skips_rows_without_a_code(self, tmp_path):
        rows = SAMPLE_ROWS + [[None, "بدون کد", "", "", 0, 0, 0, 0]]
        items = load(_make_file(tmp_path / "p.xlsx", rows=rows), strict=False)
        assert len(items) == 3


class TestPrefixIndex:
    def test_groups_variants_of_the_same_part(self, tmp_path):
        items = load(_make_file(tmp_path / "p.xlsx"), strict=False)
        index = build_prefix_index(items)
        family = index["00501026"]
        assert [i.code for i in family] == ["0050102697", "0050102699"]


@pytest.fixture(scope="module")
def items():
    """فایل واقعی ایساکو؛ یک بار برای کل ماژول خوانده می‌شود."""
    if not REAL_FILE.exists():
        pytest.skip("res.xlsx موجود نیست")
    return load(REAL_FILE)


@pytest.mark.realdata
@pytest.mark.skipif(not REAL_FILE.exists(), reason="res.xlsx موجود نیست")
class TestAgainstRealFile:
    """اعتبارسنجی با فایل واقعی دانلودشده از پورتال ایساکو."""

    def test_row_count_is_in_the_expected_range(self, items):
        assert 40_000 < len(items) < 60_000

    def test_every_code_is_exactly_ten_digits(self, items):
        assert all(len(c) == 10 and c.isdigit() for c in items)

    def test_no_row_is_missing_a_price(self, items):
        assert all(i.vat > 0 and i.retail > 0 and i.wholesale > 0
                   for i in items.values())

    def test_vat_is_exactly_ten_percent_above_retail(self, items):
        """قاعده‌ای که روی هر ۴۶٬۸۵۲ ردیف بررسی شد."""
        mismatched = [
            i.code for i in items.values()
            if round(i.retail * 1.1) != i.vat
        ]
        assert not mismatched, f"{len(mismatched)} ردیف قاعده را نقض می‌کنند"

    def test_known_real_product_is_present_and_correct(self, items):
        """قیمت‌هایی که با صفحهٔ وب ایساکو دستی مقایسه شدند."""
        starter = items["0050102699"]
        assert starter.wholesale == 56_000_000
        assert starter.retail == 62_720_000
        assert starter.vat == 68_992_000

    def test_site_skus_resolve_after_normalization(self, items):
        """SKU های واقعی سایت باید بعد از پد شدن پیدا شوند."""
        from nabz.skucode import normalize

        site_skus = ["921900699", "921900599", "50102699", "1080203199", "890139301"]
        for sku in site_skus:
            assert normalize(sku) in items, f"{sku} در لیست ایساکو پیدا نشد"

    def test_unmatched_sku_still_has_a_family_to_suggest(self, items):
        """کدهایی که ایساکو دیگر ندارد، باید نسخهٔ جایگزین داشته باشند.

        ۲۷۰۵۰۰۱۰۹ روی سایت هست ولی ایساکو حذفش کرده. صفحهٔ «تطبیق
        دستی» باید بتواند ۰۲۷۰۵۰۰۱۰۷ و ۰۲۷۰۵۰۰۱۱۴ را پیشنهاد دهد.
        """
        from nabz.skucode import normalize, prefix

        orphan = normalize("270500109")
        assert orphan not in items, "این کد قرار بود در ایساکو نباشد"

        family = build_prefix_index(items).get(prefix(orphan), [])
        assert len(family) >= 2, "هیچ جایگزینی برای پیشنهاد پیدا نشد"
        assert all(c.code != orphan for c in family)
