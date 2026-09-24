"""تست زندهٔ لاگین و کشف ساختار پاسخ endpoint دانلود لیست قیمت ایساکو.

اطلاعات ورود از فایل محلی ``isaco_secrets.local.json`` خوانده می‌شود
(در .gitignore است و کامیت نمی‌شود). این اسکریپت فقط برای تأیید یک‌بارهٔ
جریان لاگین/دانلود است؛ منطق واقعی در ``nabz.sources.isaco_web`` است.

اجرا:
    .venv/bin/python scripts/live_isaco_login.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nabz.sources.isaco_web import IsacoClient, IsacoCredentials  # noqa: E402

SECRETS = ROOT / "isaco_secrets.local.json"
BUNDLE_PRIV = "https://b2b.isaco.ir/static/js/19.b703063e.chunk.js"


def fetch_client_private_key() -> str:
    """کلید خصوصی کلاینت را از باندل زندهٔ سایت می‌گیرد (عمومی است)."""
    js = requests.get(BUNDLE_PRIV, timeout=60).text
    match = re.search(r"MIIEvQIBADANBgkqhkiG9w0B[A-Za-z0-9+/=]+", js)
    if not match:
        raise SystemExit("کلید خصوصی در باندل پیدا نشد؛ شاید هش فایل عوض شده.")
    return match.group(0)


def main() -> None:
    if not SECRETS.is_file():
        raise SystemExit(f"فایل رمز پیدا نشد: {SECRETS}")

    secrets = json.loads(SECRETS.read_text(encoding="utf-8"))
    creds = IsacoCredentials(
        scus=secrets["scus"],
        username=secrets["username"],
        password=secrets["password"],
    )

    print("→ گرفتن کلید خصوصی کلاینت از باندل ...")
    private_key = fetch_client_private_key()
    print(f"  کلید گرفته شد ({len(private_key)} کاراکتر)")

    client = IsacoClient(private_key)

    print("→ لاگین به ایساکو ...")
    session = client.login(creds)
    print(f"  ✅ لاگین موفق. توکن: {session.token[:40]}...")
    if session.expires_at:
        import datetime
        exp = datetime.datetime.fromtimestamp(session.expires_at)
        print(f"  انقضا: {exp}")

    print("→ درخواست گزارش اکسل لیست قیمت ...")
    result = client.request_price_list()
    print("  پاسخ خام endpoint دانلود:")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    main()
