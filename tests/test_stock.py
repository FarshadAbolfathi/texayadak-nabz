"""تست قواعد موجودی — مخصوصاً سقف موجودی که خواستهٔ صریح کارفرماست."""

import pytest

from nabz.stock import StockRules, StockStatus, compute

CODE = "0270900125"   # بلبرینگ پلوس ژاپن ۴۰۵ — کالای واقعی حاسب


class TestCap:
    @pytest.mark.parametrize(
        "haseb, expected",
        [
            ("0.00000", 0),
            ("1.00000", 1),
            ("2.00000", 2),
            ("5.00000", 2),      # سقف اعمال می‌شود
            ("300.00000", 2),
            ("2079.00000", 2),   # واقعی: کالای انبار پیچ و خار
        ],
    )
    def test_never_exceeds_cap(self, haseb, expected):
        rules = StockRules(max_on_site=2)
        assert compute(CODE, haseb, rules).quantity == expected

    def test_capped_flag_is_set_only_when_capped(self):
        rules = StockRules(max_on_site=2)
        assert compute(CODE, "5.00000", rules).capped
        assert not compute(CODE, "2.00000", rules).capped
        assert not compute(CODE, "1.00000", rules).capped

    def test_zero_cap_means_no_limit(self):
        rules = StockRules(max_on_site=0)
        assert compute(CODE, "300.00000", rules).quantity == 300

    def test_per_code_override_wins(self):
        rules = StockRules(max_on_site=2, per_code_max={CODE: 10})
        assert compute(CODE, "50.00000", rules).quantity == 10
        assert compute("0050102699", "50.00000", rules).quantity == 2

    def test_source_quantity_is_preserved_for_reporting(self):
        result = compute(CODE, "300.00000", StockRules(max_on_site=2))
        assert result.source_quantity == 300
        assert result.quantity == 2


class TestStatus:
    def test_zero_stock_is_out_of_stock(self):
        result = compute(CODE, "0.00000", StockRules())
        assert result.status is StockStatus.OUT_OF_STOCK
        assert result.quantity == 0

    def test_positive_stock_is_in_stock(self):
        assert compute(CODE, "1.00000", StockRules()).status is StockStatus.IN_STOCK


class TestReserve:
    def test_reserve_keeps_last_units_off_the_site(self):
        """کارفرما نمی‌خواهد آخرین عدد انبارش آنلاین فروخته شود."""
        rules = StockRules(max_on_site=5, reserve=1)
        assert compute(CODE, "1.00000", rules).quantity == 0
        assert compute(CODE, "3.00000", rules).quantity == 2
        assert compute(CODE, "10.00000", rules).quantity == 5

    def test_reserve_makes_item_out_of_stock(self):
        rules = StockRules(reserve=2)
        assert compute(CODE, "2.00000", rules).status is StockStatus.OUT_OF_STOCK


class TestFractional:
    @pytest.mark.parametrize(
        "haseb, expected",
        [
            ("0.20000", 0),    # واقعی: کد 981020116025 در حاسب
            ("1.90000", 1),    # به پایین، تا بیشتر از موجودی نفروشیم
            ("2.50000", 2),
        ],
    )
    def test_rounds_down_never_up(self, haseb, expected):
        assert compute(CODE, haseb, StockRules(max_on_site=0)).quantity == expected


class TestRobustness:
    @pytest.mark.parametrize("value", [None, "", "   ", "abc", "-", "1,5"])
    def test_unparsable_quantity_is_zero_not_crash(self, value):
        result = compute(CODE, value, StockRules())
        assert result.quantity == 0
        assert result.status is StockStatus.OUT_OF_STOCK

    @pytest.mark.parametrize("value, expected", [("۵", 5), ("٧", 7)])
    def test_persian_and_arabic_digits_are_understood(self, value, expected):
        """اگر روزی موجودی با ارقام فارسی آمد، درست خوانده شود."""
        result = compute(CODE, value, StockRules(max_on_site=0))
        assert result.source_quantity == expected

    def test_excluded_codes_are_passed_through_untouched(self):
        rules = StockRules(max_on_site=2, excluded=frozenset({CODE}))
        result = compute(CODE, "300.00000", rules)
        assert result.skipped
        assert result.quantity == 300


class TestRulesValidation:
    def test_rejects_negative_cap(self):
        with pytest.raises(ValueError, match="max_on_site"):
            StockRules(max_on_site=-1)

    def test_rejects_negative_reserve(self):
        with pytest.raises(ValueError, match="reserve"):
            StockRules(reserve=-1)
