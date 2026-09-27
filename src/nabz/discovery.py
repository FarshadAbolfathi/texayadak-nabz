"""یافتن خودکار فایل دیتابیس حاسب روی سیستم کارفرما.

کارفرمای غیرفنی نمی‌داند cal.DBF کجاست؛ این ماژول مسیرهای رایج نصب حاسب
را می‌گردد تا خودش پیدایش کند.
"""

from __future__ import annotations

import string
from pathlib import Path

#: نام فایل جدول کالای حاسب
CAL_FILENAME = "cal.DBF"

#: زیرمسیرهای رایج نصب حاسب که ممکن است cal.DBF داخلشان باشد
_KNOWN_SUBPATHS = [
    r"rahnama\HasebmDX8.001\DBF2",
    r"rahnama\HasebmDX8.001\DBF",
    r"rahnamaz\hasebm7.013\DBF2",
    r"rahnamaz\hasebm7.013\DBF",
    r"rahnama\HasebmDX8.001\DBF2",
]


def _candidate_roots() -> list[Path]:
    """درایوهای موجود ویندوز به‌علاوهٔ ریشهٔ سیستم فعلی."""
    roots: list[Path] = []
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:\\")
        if drive.exists():
            roots.append(drive)
    if not roots:  # سیستم غیرویندوزی (توسعه/تست)
        roots.append(Path("/"))
    return roots


def find_haseb_cal(deep_scan: bool = False) -> list[str]:
    """مسیرهای محتمل ``cal.DBF`` را برمی‌گرداند، تازه‌ترین اول.

    ابتدا مسیرهای شناخته‌شده را چک می‌کند (سریع). اگر ``deep_scan`` روشن
    باشد و چیزی پیدا نشد، پوشهٔ rahnama را روی هر درایو تا چند سطح می‌گردد.
    """
    found: list[Path] = []

    # ۱) مسیرهای شناخته‌شده (سریع)
    for root in _candidate_roots():
        for sub in _KNOWN_SUBPATHS:
            candidate = root / sub / CAL_FILENAME
            if candidate.is_file() and candidate not in found:
                found.append(candidate)

    # ۲) جستجوی عمیق‌تر در پوشه‌های rahnama
    if deep_scan and not found:
        for root in _candidate_roots():
            for base_name in ("rahnama", "rahnamaz"):
                base = root / base_name
                if not base.is_dir():
                    continue
                try:
                    for path in base.rglob(CAL_FILENAME):
                        # فقط پوشه‌های داده (DBF2 معمولاً سال جاری است)
                        if path.is_file() and path not in found:
                            found.append(path)
                except (OSError, PermissionError):
                    continue

    # تازه‌ترین (سال مالی جاری) اول
    found.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return [str(p) for p in found]


def best_haseb_cal(deep_scan: bool = True) -> str | None:
    """محتمل‌ترین مسیر cal.DBF را می‌دهد (تازه‌ترین)، یا None."""
    results = find_haseb_cal(deep_scan=deep_scan)
    return results[0] if results else None
