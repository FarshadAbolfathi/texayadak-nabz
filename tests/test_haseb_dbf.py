"""تست خوانندهٔ دیتابیس حاسب.

فایل‌های آزمایشی با همان ساختار واقعی ساخته می‌شوند (dBase III،
انکودینگ CP1256، فیلد عددی راست‌چین) تا نیازی به دیتابیس کارفرما نباشد.
"""

from decimal import Decimal

import pytest

from nabz.sources.haseb_dbf import (
    DbfError,
    DbfReader,
    load_products,
    load_warehouses,
)
from .conftest import write_dbf

# ردیف‌های واقعی cal.DBF کارفرما
ROWS = [
    {"COD": "171301121", "NAME": "کاسه نمد چپ هوزينگ پلوس 405ويژن ايساکو",
     "COD_ANB": "1", "NAME_ANB": "انبار کالاهاي ايساکو",
     "MOJ": "0.00000", "GH_FO": "0.0000"},
    {"COD": "270900125", "NAME": "بلبرينگ پلوس ژاپن405 ايساکو",
     "COD_ANB": "1", "NAME_ANB": "انبار کالاهاي ايساکو",
     "MOJ": "4.00000", "GH_FO": "0.0000"},
    {"COD": "1080203199", "NAME": "شيلنگ بخاري کنفدار تک سوز405ايساکو",
     "COD_ANB": "1", "NAME_ANB": "انبار کالاهاي ايساکو",
     "MOJ": "12.00000", "GH_FO": "0.0000"},
    {"COD": "612311206560", "NAME": "دسته برف پاکن 206HB جهانپارت",
     "COD_ANB": "5", "NAME_ANB": "انبار کالاهاي جهان پارت",
     "MOJ": "3.00000", "GH_FO": "0.0000"},
]


class TestDbfReader:
    def test_reads_header_metadata(self, make_cal):
        with DbfReader(make_cal(ROWS)) as reader:
            assert reader.record_count == 4
            assert "COD" in reader.field_names()
            assert "MOJ" in reader.field_names()

    def test_reads_persian_text_correctly(self, make_cal):
        """انکودینگ CP1256 — با دادهٔ واقعی تأیید شده."""
        with DbfReader(make_cal(ROWS)) as reader:
            names = [r["NAME"] for r in reader.rows(fields=["NAME"])]
        assert "بلبرينگ پلوس ژاپن405 ايساکو" in names

    def test_can_read_only_selected_columns(self, make_cal):
        with DbfReader(make_cal(ROWS)) as reader:
            row = next(reader.rows(fields=["COD", "MOJ"]))
        assert set(row) == {"COD", "MOJ"}

    def test_unknown_column_raises_a_clear_error(self, make_cal):
        with DbfReader(make_cal(ROWS)) as reader:
            with pytest.raises(DbfError, match="MOJODI"):
                list(reader.rows(fields=["MOJODI"]))

    def test_deleted_records_are_skipped_by_default(self, make_cal):
        path = make_cal(ROWS, deleted={1})
        with DbfReader(path) as reader:
            codes = [r["COD"] for r in reader.rows(fields=["COD"])]
        assert "270900125" not in codes
        assert len(codes) == 3

    def test_deleted_records_can_be_included(self, make_cal):
        path = make_cal(ROWS, deleted={1})
        with DbfReader(path) as reader:
            rows = list(reader.rows(fields=["COD"], include_deleted=True))
        assert len(rows) == 4
        assert sum(r["_deleted"] == "1" for r in rows) == 1

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(DbfError, match="پیدا نشد"):
            DbfReader(tmp_path / "nope.DBF").open()

    def test_truncated_header_raises(self, tmp_path):
        broken = tmp_path / "broken.DBF"
        broken.write_bytes(b"\x03\x00\x00")
        with pytest.raises(DbfError, match="ناقص"):
            DbfReader(broken).open()


class TestNeverTouchesTheOriginal:
    """قول اصلی ما به کارفرما: دیتابیس حسابداری دست‌نخورده می‌ماند."""

    def test_source_file_is_unchanged_after_reading(self, make_cal):
        path = make_cal(ROWS)
        before = path.read_bytes()
        with DbfReader(path) as reader:
            list(reader.rows())
        assert path.read_bytes() == before

    def test_temp_copy_is_removed_after_close(self, make_cal):
        reader = DbfReader(make_cal(ROWS))
        reader.open()
        temp = reader._temp
        assert temp is not None and temp.exists()
        reader.close()
        assert not temp.exists()

    def test_reading_without_copy_also_leaves_file_intact(self, make_cal):
        path = make_cal(ROWS)
        before = path.read_bytes()
        with DbfReader(path, use_copy=False) as reader:
            list(reader.rows())
        assert path.read_bytes() == before


class TestLoadProducts:
    def test_codes_are_normalized_to_ten_digits(self, make_cal):
        items = load_products(make_cal(ROWS))
        assert "0171301121" in items
        assert "0270900125" in items
        assert "1080203199" in items

    def test_keeps_the_raw_code_for_reporting(self, make_cal):
        items = load_products(make_cal(ROWS))
        assert items["0171301121"].raw_code == "171301121"

    def test_quantity_is_decimal(self, make_cal):
        items = load_products(make_cal(ROWS))
        assert items["0270900125"].quantity == Decimal("4.00000")

    def test_non_isaco_codes_are_kept_unpadded(self, make_cal):
        items = load_products(make_cal(ROWS))
        assert "612311206560" in items

    def test_warehouse_filter_keeps_only_requested_ones(self, make_cal):
        items = load_products(make_cal(ROWS), warehouses={1})
        assert len(items) == 3
        assert "612311206560" not in items

    def test_same_code_in_two_warehouses_is_summed(self, make_cal):
        """از دید سایت یک SKU وجود دارد، پس موجودی‌ها جمع می‌شوند."""
        rows = ROWS + [{
            "COD": "270900125", "NAME": "بلبرينگ پلوس ژاپن405",
            "COD_ANB": "16", "NAME_ANB": "انبار بدنه ايساکو",
            "MOJ": "6.00000", "GH_FO": "0.0000",
        }]
        items = load_products(make_cal(rows))
        assert items["0270900125"].quantity == Decimal("10.00000")

    def test_rows_without_a_code_are_skipped(self, make_cal):
        rows = ROWS + [{"COD": "", "NAME": "بدون کد", "COD_ANB": "1",
                        "NAME_ANB": "x", "MOJ": "5.00000", "GH_FO": "0"}]
        assert len(load_products(make_cal(rows))) == 4


class TestLoadWarehouses:
    def test_reads_id_to_name_map(self, tmp_path):
        path = write_dbf(
            tmp_path / "anb.DBF",
            [("COD", "N", 10, 0), ("NAME", "C", 50, 0)],
            [
                {"COD": "1", "NAME": "انبار کالاهاي موتوري ايساکو"},
                {"COD": "5", "NAME": "انبار کالاهاي جهان پارت"},
                {"COD": "17", "NAME": "انبار پيچ و خار"},
            ],
        )
        warehouses = load_warehouses(path)
        assert warehouses[1] == "انبار کالاهاي موتوري ايساکو"
        assert warehouses[17] == "انبار پيچ و خار"
