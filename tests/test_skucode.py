"""تست نرمال‌سازی کد کالا.

نمونه‌های این فایل از دادهٔ واقعی سه سیستم گرفته شده‌اند، نه ساختگی.
"""

import pytest

from nabz import skucode


class TestNormalize:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            # --- SKU های واقعی سایت تکسایدک (۹ رقمی، صفر افتاده) ---
            ("921900699", "0921900699"),
            ("270500109", "0270500109"),
            ("890139301", "0890139301"),
            # --- SKU های ۸ رقمی سایت ---
            ("50102699", "0050102699"),
            ("27050018", "0027050018"),
            # --- کدهای واقعی حاسب (فیلد عددی) ---
            ("171301121", "0171301121"),
            ("961500299", "0961500299"),
            # --- کدهایی که از اول ۱۰ رقمی‌اند ---
            ("1080203199", "1080203199"),
            ("0050102699", "0050102699"),
            ("2070201627", "2070201627"),
        ],
    )
    def test_pads_to_ten_digits(self, raw, expected):
        assert skucode.normalize(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("۰۵۰۱۰۲۶۹۹", "0050102699"),   # ارقام فارسی
            ("٠٥٠١٠٢٦٩٩", "0050102699"),   # ارقام عربی
            ("۱۲۳۴۵۶۷", "1234567"),         # عدد ۷ رقمی ⇒ پد نمی‌شود
        ],
    )
    def test_converts_non_ascii_digits(self, raw, expected):
        assert skucode.normalize(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [" 921900699 ", "921-900-699", "921 900 699", "921900699‌", "SKU921900699"],
    )
    def test_strips_junk(self, raw):
        assert skucode.normalize(raw) == "0921900699"

    @pytest.mark.parametrize(
        "raw",
        ["612311206560", "981020116000", "901897209553"],  # کدهای ۱۲ رقمی غیرایساکویی
    )
    def test_leaves_long_codes_alone(self, raw):
        assert skucode.normalize(raw) == raw

    @pytest.mark.parametrize("raw", [None, "", "   ", "ايساکو", "---"])
    def test_returns_empty_for_unusable(self, raw):
        assert skucode.normalize(raw) == ""

    def test_is_idempotent(self):
        once = skucode.normalize("921900699")
        assert skucode.normalize(once) == once

    def test_accepts_non_string_input(self):
        assert skucode.normalize(921900699) == "0921900699"


class TestIsIsacoCode:
    @pytest.mark.parametrize("raw", ["921900699", "0050102699", "50102699"])
    def test_accepts_isaco_shaped_codes(self, raw):
        assert skucode.is_isaco_code(raw)

    @pytest.mark.parametrize("raw", ["612311206560", "100350", "", "12"])
    def test_rejects_others(self, raw):
        assert not skucode.is_isaco_code(raw)


class TestPrefix:
    def test_returns_first_eight_digits(self):
        assert skucode.prefix("0921900804") == "09219008"

    def test_empty_for_non_isaco_code(self):
        assert skucode.prefix("612311206560") == ""

    def test_same_family_matches_real_isaco_variants(self):
        # مورد واقعی: سایت 921900804 دارد، ایساکو 0921900811 — همان قطعه
        assert skucode.same_family("921900804", "0921900811")

    def test_same_family_rejects_different_parts(self):
        assert not skucode.same_family("0921900804", "0920906605")

    def test_same_family_false_when_either_is_not_isaco(self):
        assert not skucode.same_family("612311206560", "612311206561")
