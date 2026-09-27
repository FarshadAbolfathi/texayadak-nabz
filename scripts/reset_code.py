"""ابزار سازنده: از روی «کد چالش» کارفرما، «کد پاسخ» را می‌سازد.

وقتی کارفرما رمز برنامه را فراموش کرد و «کد چالش» را برایتان فرستاد،
این را اجرا کنید و کد چالش را وارد کنید تا کد پاسخ را بگیرید و به او بدهید.

اجرا:
    python scripts/reset_code.py            # سپس کد چالش را وارد کنید
    python scripts/reset_code.py ABCDEF     # یا مستقیم به‌عنوان آرگومان
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nabz.recovery import response_for  # noqa: E402


def main() -> None:
    if len(sys.argv) > 1:
        challenge = sys.argv[1]
    else:
        challenge = input("کد چالش کارفرما را وارد کنید: ").strip()

    if not challenge:
        print("کد چالش خالی است.")
        return

    print()
    print(f"  کد چالش : {challenge.upper()}")
    print(f"  کد پاسخ : {response_for(challenge)}")
    print()
    print("این «کد پاسخ» را به کارفرما بدهید تا وارد کند و رمز جدید بسازد.")


if __name__ == "__main__":
    main()
