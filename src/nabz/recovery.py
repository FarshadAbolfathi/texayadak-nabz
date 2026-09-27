"""بازیابی رمز فراموش‌شدهٔ برنامه، با کمک پشتیبان (چالش–پاسخ).

کارفرمای غیرفنی ممکن است رمز ورود به برنامه را فراموش کند. برای اینکه
هیچ‌وقت قفل نشود، این سازوکار را داریم:

    ۱) کارفرما «فراموشی رمز» را می‌زند و یک «کد چالش» می‌بیند.
    ۲) کد چالش را برای پشتیبان (سازنده) می‌فرستد.
    ۳) پشتیبان با ابزار ``scripts/reset_code.py`` کد پاسخ را می‌سازد.
    ۴) کارفرما کد پاسخ را وارد می‌کند و رمز جدید تعریف می‌کند.

کد پاسخ = HMAC-SHA256 روی کد چالش با یک کلید پنهان که فقط سازنده دارد.
پس تنها سازنده می‌تواند کد پاسخ درست را بسازد.

نکتهٔ امنیتی: کلید داخل برنامهٔ توزیع‌شده است و در تئوری قابل استخراج
است. هدف این محافظ، جلوگیری از دسترسی اتفاقی کارکنان است، نه دفاع در
برابر مهاجم متخصصی که خودِ فایل اجرایی را مهندسی معکوس کند. برای این
کاربرد کاملاً کافی است.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# کلید پنهان بازیابی — فقط سازنده. اگر لو رفت، اینجا عوضش کنید.
# (این مقدار در ابزار سازنده هم باید همین باشد.)
RECOVERY_SECRET = b"texayadak-nabz::recovery::v1::9f3a7c21e8b4"

# طول کد چالش (کاراکترهای بدون‌ابهام برای خواندن تلفنی)
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بدون I,O,0,1
_CHALLENGE_LEN = 6
_RESPONSE_LEN = 8


def make_challenge() -> str:
    """یک کد چالش تصادفی می‌سازد (هر بار متفاوت)."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CHALLENGE_LEN))


def response_for(challenge: str) -> str:
    """کد پاسخِ متناظر با یک چالش را می‌سازد (فقط با کلید پنهان).

    >>> a = response_for("ABCDEF")
    >>> a == response_for("abcdef")   # حساس به بزرگی/کوچکی نیست
    True
    >>> len(a) == 8
    True
    """
    normalized = challenge.strip().upper().encode("ascii", "ignore")
    digest = hmac.new(RECOVERY_SECRET, normalized, hashlib.sha256).hexdigest()
    # تبدیل به کاراکترهای خوانا از همان الفبا
    out = []
    for i in range(_RESPONSE_LEN):
        byte = int(digest[i * 2 : i * 2 + 2], 16)
        out.append(_ALPHABET[byte % len(_ALPHABET)])
    return "".join(out)


def verify_response(challenge: str, response: str) -> bool:
    """آیا کد پاسخ برای این چالش درست است؟"""
    expected = response_for(challenge)
    given = response.strip().upper().replace("-", "").replace(" ", "")
    return hmac.compare_digest(expected, given)
