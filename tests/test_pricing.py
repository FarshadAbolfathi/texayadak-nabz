"""تست قواعد قیمت‌گذاری.

قیمت‌های استفاده‌شده از ردیف‌های واقعی فایل ایساکو گرفته شده‌اند.
"""

from decimal import Decimal

import pytest

from nabz.pricing import (
    GuardReason,
    PriceBase,
    PriceRules,
    compute,
    round_to_step,
)

# استارت کامل موتور EF7 — کد 0050102699 (با تأیید از صفحهٔ وب ایساکو)
STARTER = dict(
    isaco_wholesale=56_000_000,   # في فروش
    isaco_retail=62_720_000,      # قیمت مصرف کننده
    isaco_vat=68_992_000,         # با احتساب ارزش افزوده
)


class TestRoundToStep:
    @pytest.mark.parametrize(
        "value, step, expected",
        [
            (Decimal("7934080"), 1_000, 7_934_000),
            (Decimal("7934080"), 5_000, 7_935_000),
            (Decimal("7934080"), 10_000, 7_930_000),
            (Decimal("7934080"), 0, 7_934_080),    # بدون رند
            (Decimal("1500"), 1_000, 2_000),       # نصف به بالا
            (Decimal("499"), 1_000, 0),
        ],
    )
    def test_rounds_to_nearest_multiple(self, value, step, expected):
        assert round_to_step(value, step) == expected


class TestCompute:
    def test_full_chain_with_fifteen_percent(self):
        """۶۸,۹۹۲,۰۰۰ ریال ÷ ۱۰ × ۱.۱۵ = ۷,۹۳۴,۰۸۰ ⇒ رند ⇒ ۷,۹۳۴,۰۰۰"""
        rules = PriceRules(markup_percent=Decimal("15"), round_to=1_000)
        result = compute(**STARTER, rules=rules)
        assert result.price == 7_934_000
        assert result.base_rial == 68_992_000
        assert result.before_round == Decimal("7934080")
        assert not result.needs_review

    def test_zero_markup_is_just_unit_conversion(self):
        rules = PriceRules(markup_percent=Decimal("0"), round_to=0)
        assert compute(**STARTER, rules=rules).price == 6_899_200

    def test_negative_markup_discounts(self):
        rules = PriceRules(markup_percent=Decimal("-10"), round_to=0)
        assert compute(**STARTER, rules=rules).price == 6_209_280

    @pytest.mark.parametrize(
        "base, expected_rial",
        [
            (PriceBase.VAT, 68_992_000),
            (PriceBase.RETAIL, 62_720_000),
            (PriceBase.WHOLESALE, 56_000_000),
        ],
    )
    def test_base_column_selection(self, base, expected_rial):
        rules = PriceRules(base=base, round_to=0)
        result = compute(**STARTER, rules=rules)
        assert result.base_rial == expected_rial
        assert result.price == expected_rial // 10

    def test_rial_divisor_one_keeps_rial(self):
        """اگر روزی سایت به ریال تغییر کرد."""
        rules = PriceRules(rial_divisor=1, round_to=0)
        assert compute(**STARTER, rules=rules).price == 68_992_000

    def test_fractional_markup(self):
        rules = PriceRules(markup_percent=Decimal("12.5"), round_to=0)
        assert compute(**STARTER, rules=rules).price == 7_761_600


class TestGuards:
    def test_missing_source_price_is_flagged(self):
        rules = PriceRules()
        result = compute(
            isaco_retail=0, isaco_vat=0, isaco_wholesale=0, rules=rules
        )
        assert result.guard is GuardReason.NO_SOURCE_PRICE
        assert result.price == 0
        assert result.needs_review

    def test_big_jump_is_flagged_not_applied_silently(self):
        """محافظی که جلوی فاجعهٔ قیمت ۱۰ برابری را می‌گیرد."""
        rules = PriceRules(max_change_percent=Decimal("50"))
        result = compute(**STARTER, rules=rules, current_site_price=500_000)
        assert result.guard is GuardReason.TOO_BIG_CHANGE
        assert result.needs_review
        assert result.price == 6_899_000  # قیمت حساب شده، ولی علامت‌دار

    def test_small_change_passes(self):
        rules = PriceRules(max_change_percent=Decimal("50"))
        result = compute(**STARTER, rules=rules, current_site_price=6_800_000)
        assert result.guard is GuardReason.NONE
        assert not result.needs_review

    def test_guard_disabled_when_zero(self):
        rules = PriceRules(max_change_percent=Decimal("0"))
        result = compute(**STARTER, rules=rules, current_site_price=1)
        assert result.guard is GuardReason.NONE

    def test_change_percent_is_reported(self):
        rules = PriceRules(max_change_percent=Decimal("0"), round_to=0)
        result = compute(**STARTER, rules=rules, current_site_price=6_899_200)
        assert result.change_percent == Decimal("0")

    def test_below_min_price_is_flagged(self):
        rules = PriceRules(min_price=10_000_000)
        assert compute(**STARTER, rules=rules).guard is GuardReason.BELOW_MIN

    def test_above_max_price_is_flagged(self):
        rules = PriceRules(max_price=1_000_000)
        assert compute(**STARTER, rules=rules).guard is GuardReason.ABOVE_MAX


class TestRulesValidation:
    def test_rejects_zero_divisor(self):
        with pytest.raises(ValueError, match="rial_divisor"):
            PriceRules(rial_divisor=0)

    def test_rejects_negative_round_step(self):
        with pytest.raises(ValueError, match="round_to"):
            PriceRules(round_to=-1)

    def test_rejects_inverted_price_bounds(self):
        with pytest.raises(ValueError, match="min_price"):
            PriceRules(min_price=5_000, max_price=1_000)
