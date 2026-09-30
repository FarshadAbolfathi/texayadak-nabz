"""تست پیشنهاد خودکار دسته‌بندی."""

from nabz.categorize import Categorizer, CategoryRule, distinctive_tokens, tokens
from nabz.targets.woocommerce import WooCategory

CATS = [
    WooCategory(1, "پژو"),
    WooCategory(2, "پژو ۴۰۵", parent=1),
    WooCategory(3, "پژو ۲۰۶", parent=1),
    WooCategory(4, "پژو پارس", parent=1),
    WooCategory(10, "سایپا"),
    WooCategory(11, "پراید", parent=10),
    WooCategory(12, "پراید ۱۳۱", parent=10),
    WooCategory(20, "لوازم ترمز"),
    WooCategory(30, "سمند"),
]


def test_tokens_split_letters_and_digits():
    assert tokens("۴۰۵GLX") == ["405", "glx"]
    assert tokens("سپر‌عقب") == ["سپر", "عقب"]  # نیم‌فاصله


def test_brand_word_is_not_distinctive():
    assert distinctive_tokens("پژو ۴۰۵") == {"405"}
    assert distinctive_tokens("پژو") == {"پژو"}


def test_bumper_405_goes_to_peugeot_405_and_parent():
    c = Categorizer(CATS)
    assert c.suggest("سپر عقب ۴۰۵").category_ids == [2, 1]


def test_number_must_be_whole_token():
    c = Categorizer(CATS)
    assert 2 not in c.suggest("واشر 4050").category_ids


def test_more_specific_category_wins():
    c = Categorizer(CATS, include_parents=False)
    assert c.suggest("چراغ پراید ۱۳۱").category_ids == [12]


def test_car_column_from_isaco_is_used():
    c = Categorizer(CATS, include_parents=False)
    ids = c.suggest("دیسک ترمز", car="پژو 405 - سمند").category_ids
    # خودرو از ستون مصرف خودرو، نوع قطعه از نام دستهٔ «لوازم ترمز»
    assert set(ids) == {2, 20, 30}


def test_manual_rule_adds_category():
    rules = [CategoryRule("لنت", (20,)), CategoryRule("آردی", (4,))]
    c = Categorizer(CATS, rules, include_parents=False)
    assert c.suggest("لنت جلو ۲۰۶").category_ids == [20, 3]


def test_default_category_when_nothing_matches():
    c = Categorizer(CATS, default_category=20)
    assert c.suggest("پیچ").category_ids == [20]
    assert Categorizer(CATS).suggest("پیچ").category_ids == []


def test_auto_match_can_be_disabled():
    c = Categorizer(CATS, auto_match=False)
    assert c.suggest("سپر ۴۰۵").category_ids == []


def test_arabic_letters_are_normalized():
    c = Categorizer([WooCategory(5, "کیسه هوا")], include_parents=False)
    assert c.suggest("كيسه هوا راننده").category_ids == [5]


def test_path_and_cycle_safety():
    cats = [WooCategory(1, "الف", parent=2), WooCategory(2, "ب", parent=1)]
    c = Categorizer(cats)
    assert c.ancestors(1) == [2]  # در حلقه گیر نمی‌کند
    assert Categorizer(CATS).path(2) == "پژو › پژو ۴۰۵"
