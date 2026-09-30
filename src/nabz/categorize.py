"""پیشنهاد خودکار دسته‌بندی برای محصولات.

مسئله: محصول جدیدی مثل «سپر عقب ۴۰۵» باید خودش در دستهٔ «پژو ۴۰۵» سایت
بنشیند. راه‌حل سه لایه دارد که به ترتیب اولویت با هم جمع می‌شوند:

1. **قواعد دستی کارفرما** — «هر محصولی که در نامش X بود → دستهٔ Y».
   برای نام‌های مستعار (مثلاً «آردی» → پیکان) یا دسته‌های نوع قطعه
   (مثلاً «لنت» → لوازم ترمز). همیشه اعمال می‌شوند.
2. **تطبیق خودکار با نام دسته‌های خودِ سایت** — هیچ تنظیمی نمی‌خواهد:
   نام هر دسته به کلمه‌های «متمایزکننده» شکسته می‌شود (برای «پژو ۴۰۵»
   فقط «405»، چون «پژو» نام برند است و به تنهایی چیزی را مشخص نمی‌کند).
   اگر همهٔ کلمه‌های متمایزکنندهٔ یک دسته در نام محصول یا ستون «مصرف
   خودرو» لیست ایساکو پیدا شود، آن دسته پیشنهاد می‌شود.
3. **دستهٔ پیش‌فرض** — اگر هیچ‌چیز پیدا نشد (اختیاری).

در پایان، دستهٔ کلی‌تر که یک دستهٔ دقیق‌تر هم پیدا شده حذف می‌شود
(«پراید» کنار «پراید ۱۳۱» اضافه است) و در صورت تمایل، والدهای دستهٔ
انتخاب‌شده هم اضافه می‌شوند (پژو ۴۰۵ → پژو).

کارفرما همیشه پیش از ارسال پیشنهاد را می‌بیند و می‌تواند عوضش کند.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .skucode import to_ascii_digits
from .targets.woocommerce import WooCategory

#: نام برندها و کلمه‌های عمومی که به تنهایی دسته را مشخص نمی‌کنند.
GENERIC_WORDS = frozenset({
    "پژو", "سایپا", "ایران", "خودرو", "ایرانخودرو", "رنو", "کیا", "هیوندای",
    "هیوندا", "تویوتا", "نیسان", "مزدا", "چری", "ام", "وی", "امویام", "جک",
    "لیفان", "دانگ", "فنگ", "دانگفنگ", "بسترن", "هایما", "برلیانس", "پارس‌خودرو",
    "پارسخودرو", "زامیاد", "بهمن", "مدیران", "کرمان", "موتور",
    "peugeot", "saipa", "renault", "kia", "hyundai", "toyota", "nissan",
})

#: کلمه‌های پرکاربرد بی‌معنا در نام دسته که کلاً نادیده گرفته می‌شوند.
STOP_WORDS = frozenset({
    "و", "یا", "با", "به", "از", "برای", "مدل", "سری", "قطعات", "قطعه",
    "لوازم", "یدکی", "جانبی", "انواع", "کلیه", "همه", "تمام", "محصولات",
    "خودروهای", "خودروی", "دسته", "بندی", "دسته‌بندی", "سایر", "متفرقه",
})

_TOKEN = re.compile(r"[0-9]+|[a-z]+|[؀-ۿ]+")


def normalize_text(text: object) -> str:
    """متن فارسی را برای مقایسه یکدست می‌کند.

    >>> normalize_text("سپر عقب ۴۰۵ GLX‌ي")
    'سپر عقب 405 glx ی'
    """
    value = to_ascii_digits(str(text or ""))
    value = (
        value.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
        .replace("ة", "ه").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        .replace("‌", " ").replace("‏", " ").replace("ـ", "")
    )
    value = value.lower()
    return " ".join(_TOKEN.findall(value))


def tokens(text: object) -> list[str]:
    """کلمه‌ها و عددها را جدا می‌کند؛ «405GLX» → «405» و «glx».

    >>> tokens("پژو ۴۰۵GLX - پارس")
    ['پژو', '405', 'glx', 'پارس']
    """
    return normalize_text(text).split()


def distinctive_tokens(name: str) -> frozenset[str]:
    """کلمه‌هایی از نام دسته که واقعاً آن را مشخص می‌کنند.

    >>> sorted(distinctive_tokens("پژو ۴۰۵"))
    ['405']
    >>> sorted(distinctive_tokens("لوازم پراید ۱۳۱"))
    ['131', 'پراید']
    >>> sorted(distinctive_tokens("پژو"))
    ['پژو']
    """
    words = [t for t in tokens(name) if t not in STOP_WORDS]
    specific = frozenset(t for t in words if t not in GENERIC_WORDS)
    # دسته‌ای که فقط نام برند است (مثلاً «پژو») با خود برند شناخته می‌شود
    return specific or frozenset(words)


@dataclass(frozen=True, slots=True)
class CategoryRule:
    """قاعدهٔ دستی: اگر ``keyword`` در متن بود، این دسته‌ها اضافه شوند."""

    keyword: str
    category_ids: tuple[int, ...]

    @classmethod
    def from_dict(cls, data: dict) -> "CategoryRule":
        return cls(
            keyword=str(data.get("keyword", "")),
            category_ids=tuple(int(c) for c in data.get("category_ids", [])),
        )

    def to_dict(self) -> dict:
        return {"keyword": self.keyword, "category_ids": list(self.category_ids)}

    def matches(self, text_tokens: list[str]) -> bool:
        """عبارت کلیدی به‌صورت دنبالهٔ کامل کلمه‌ها جستجو می‌شود.

        >>> CategoryRule("لنت ترمز", (1,)).matches(tokens("لنت ترمز جلو 206"))
        True
        >>> CategoryRule("405", (1,)).matches(tokens("واشر 4050"))
        False
        """
        needle = tokens(self.keyword)
        if not needle:
            return False
        n = len(needle)
        return any(text_tokens[i:i + n] == needle
                   for i in range(len(text_tokens) - n + 1))


@dataclass(slots=True)
class Suggestion:
    """نتیجهٔ پیشنهاد دسته برای یک محصول."""

    category_ids: list[int] = field(default_factory=list)
    #: توضیح کوتاه برای نمایش: چرا این دسته‌ها انتخاب شدند
    reason: str = ""


class Categorizer:
    """دسته‌های سایت را یک‌بار تحلیل می‌کند و برای هر محصول پیشنهاد می‌دهد.

    >>> cats = [WooCategory(1, "پژو"), WooCategory(2, "پژو ۴۰۵", parent=1),
    ...         WooCategory(3, "پراید"), WooCategory(4, "پژو ۲۰۶", parent=1)]
    >>> c = Categorizer(cats)
    >>> c.suggest("سپر عقب ۴۰۵").category_ids
    [2, 1]
    >>> c.suggest("چراغ جلو", car="پراید - پژو 206").category_ids
    [3, 4, 1]
    >>> c.suggest("پیچ").category_ids
    []
    """

    def __init__(
        self,
        categories: Iterable[WooCategory],
        rules: Iterable[CategoryRule] = (),
        *,
        include_parents: bool = True,
        default_category: int | None = None,
        auto_match: bool = True,
    ) -> None:
        self.categories = {c.id: c for c in categories}
        self.rules = [r for r in rules if r.keyword.strip() and r.category_ids]
        self.include_parents = include_parents
        self.default_category = default_category or None
        self.auto_match = auto_match
        self._signatures = {
            cid: distinctive_tokens(c.name) for cid, c in self.categories.items()
        }
        self._signatures = {k: v for k, v in self._signatures.items() if v}

    def ancestors(self, cid: int) -> list[int]:
        result: list[int] = []
        seen = {cid}
        current = self.categories.get(cid)
        while current is not None and current.parent and current.parent not in seen:
            result.append(current.parent)
            seen.add(current.parent)
            current = self.categories.get(current.parent)
        return result

    def path(self, cid: int) -> str:
        """مسیر کامل دسته: «پژو › پژو ۴۰۵»."""
        chain = [cid, *self.ancestors(cid)][::-1]
        return " › ".join(self.categories[c].name for c in chain if c in self.categories)

    def names(self, ids: Iterable[int]) -> str:
        return "، ".join(
            self.categories[c].name for c in ids if c in self.categories
        )

    def suggest(self, name: str, car: str = "") -> Suggestion:
        text_tokens = tokens(f"{name} {car}")
        token_set = set(text_tokens)
        reasons: list[str] = []

        # ۱) قواعد دستی
        chosen: list[int] = []
        for rule in self.rules:
            if rule.matches(text_tokens):
                for cid in rule.category_ids:
                    if cid in self.categories and cid not in chosen:
                        chosen.append(cid)
                reasons.append(f"قاعدهٔ «{rule.keyword}»")

        # ۲) تطبیق با نام دسته‌ها
        if self.auto_match:
            matched = [
                cid for cid, sig in self._signatures.items() if sig <= token_set
            ]
            # حذف دستهٔ کلی‌تر وقتی دقیق‌ترش هم پیدا شده
            pruned = []
            for cid in matched:
                sig = self._signatures[cid]
                more_specific = any(
                    other != cid and (
                        sig < self._signatures[other]
                        or cid in self.ancestors(other)
                    )
                    for other in matched
                )
                if not more_specific:
                    pruned.append(cid)
            pruned.sort(key=lambda c: (-len(self._signatures[c]), c))
            for cid in pruned:
                if cid not in chosen:
                    chosen.append(cid)
            if pruned:
                reasons.append("تطبیق با نام دسته")

        # ۳) پیش‌فرض
        if not chosen and self.default_category in self.categories:
            chosen.append(self.default_category)
            reasons.append("دستهٔ پیش‌فرض")

        if self.include_parents:
            for cid in list(chosen):
                for parent in self.ancestors(cid):
                    if parent not in chosen:
                        chosen.append(parent)

        return Suggestion(category_ids=chosen, reason="، ".join(reasons))


def rules_from_settings(raw: object) -> list[CategoryRule]:
    if not isinstance(raw, list):
        return []
    rules = []
    for item in raw:
        if isinstance(item, dict):
            try:
                rules.append(CategoryRule.from_dict(item))
            except (TypeError, ValueError):
                continue
    return rules
