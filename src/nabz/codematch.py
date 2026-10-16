"""پیشنهاد تطبیق کد محصولات سایت با لیست ایساکو.

ایساکو گاهی دو رقم آخر کد کالا را حذف می‌کند (مثلاً «1230200599» در لیست به
شکل «12302005» می‌آید که پس از نرمال‌سازی «0012302005» می‌شود). آن‌وقت کد
محصول سایت در لیست پیدا نمی‌شود و قیمتش سینک نمی‌شود.

این ماژول فقط **پیشنهاد** می‌دهد؛ هیچ تطبیقی خودکار ذخیره نمی‌شود، چون مثلاً
«12302005» در لیست واقعی ایساکو سه کالای متفاوت (…05، …98، …99) را
می‌پوشاند و حدس اشتباه یعنی قیمت اشتباه روی سایت. کارفرما با دیدن نام دو
طرف تأیید می‌کند و تطبیق در جدول ``code_map`` ذخیره می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass

from .skucode import CODE_LEN, normalize
from .sources.isaco_excel import IsacoItem

#: طول پیشوند «هم‌خانواده» (همان قطعه، نسخه/تأمین‌کنندهٔ دیگر)
FAMILY_LEN = 8


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    item: IsacoItem
    reason: str          # «short» = کد کوتاه‌شده، «family» = هم‌خانواده

    @property
    def label(self) -> str:
        return {"short": "کد کوتاه‌شده در ایساکو",
                "family": "هم‌خانواده (۸ رقم اول یکسان)"}[self.reason]


def short_code_key(site_sku: str) -> str:
    """کلید ایساکو اگر دو رقم آخر کد حذف شده باشد.

    >>> short_code_key("1230200599")
    '0012302005'
    >>> short_code_key("12345")
    ''
    """
    code = normalize(site_sku)
    if len(code) != CODE_LEN:
        return ""
    return normalize(code[:-2])


def build_family_index(isaco: dict[str, IsacoItem]) -> dict[str, list[IsacoItem]]:
    index: dict[str, list[IsacoItem]] = {}
    for item in isaco.values():
        if len(item.code) == CODE_LEN:
            index.setdefault(item.code[:FAMILY_LEN], []).append(item)
    for family in index.values():
        family.sort(key=lambda i: i.code)
    return index


def suggest(
    site_sku: str,
    isaco: dict[str, IsacoItem],
    family_index: dict[str, list[IsacoItem]] | None = None,
    *,
    limit: int = 8,
) -> list[MatchCandidate]:
    """پیشنهادهای تطبیق برای کدی که دقیقاً در لیست ایساکو نیست.

    >>> from nabz.sources.isaco_excel import IsacoItem as I
    >>> lst = {c: I(c, c, "", "عدد", 1, 1, 1, 1) for c in ("0012302005", "1230200505")}
    >>> [(c.item.code, c.reason) for c in suggest("1230200599", lst)]
    [('0012302005', 'short'), ('1230200505', 'family')]
    """
    code = normalize(site_sku)
    if not code or code in isaco:
        return []
    result: list[MatchCandidate] = []
    seen: set[str] = set()
    key = short_code_key(code)
    if key and key in isaco:
        result.append(MatchCandidate(isaco[key], "short"))
        seen.add(key)
    if len(code) == CODE_LEN:
        index = family_index if family_index is not None else build_family_index(isaco)
        for item in index.get(code[:FAMILY_LEN], []):
            if item.code not in seen and item.code != code:
                result.append(MatchCandidate(item, "family"))
                seen.add(item.code)
    return result[:limit]


def resolve(
    site_sku: str,
    isaco: dict[str, IsacoItem],
    code_map: dict[str, str],
) -> tuple[IsacoItem | None, str]:
    """کالای ایساکوی یک محصول سایت: اول کد دقیق، بعد تطبیق تأییدشده.

    :returns: ``(کالا، کد ایساکوی استفاده‌شده اگر از تطبیق آمده وگرنه "")``
    """
    code = normalize(site_sku)
    if code in isaco:
        return isaco[code], ""
    mapped = code_map.get(code) or code_map.get(site_sku)
    if mapped:
        target = normalize(mapped)
        if target in isaco:
            return isaco[target], target
    return None, ""
