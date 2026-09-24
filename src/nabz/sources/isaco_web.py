"""لاگین و دانلود خودکار از پورتال B2B ایساکو.

این ماژول همان کاری را می‌کند که مرورگر هنگام کار با پورتال انجام می‌دهد:
لاگین با یوزر/رمز، گرفتن توکن JWT، و سپس فراخوانی endpoint های محافظت‌شده
با رمزنگاری hybrid (:mod:`nabz.sources.isaco_crypto`).

جریان کامل (از روی باندل جاوااسکریپت سایت استخراج و مستند شده):

    GET  /                         →  کوکی نشست (connect.sid)
    POST /api/Sec/Login/v2         →  {Scus, UserName, Password, ...}  →  Token
    POST /api/War/Reports/RepPriceListExcel  →  لینک/محتوای فایل اکسل

نکته دربارهٔ captcha: پارامترهای ``Sec/Login/v2`` فقط
``Scus, UserName, Password, ClientVersion, Lng`` است و فیلد captcha ندارد،
پس لاگین معمولی نیازی به کد تصویری ندارد. endpoint جدا ``Sec/GetCapcha``
فقط برای مسیرهای خاص است.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests

from .isaco_crypto import (
    ISACO_SERVER_PUBLIC_KEY,
    IsacoCryptoError,
    decrypt_response,
    encrypt_request,
)

#: کلید خصوصی کلاینت (از باندل سایت) برای رمزگشایی پاسخ‌ها.
#: در باندل عمومی است؛ اینجا نگه نمی‌داریم و هنگام ساخت کلاینت داده می‌شود
#: تا اگر ایساکو عوضش کرد، فقط یک مقدار به‌روزرسانی شود.

BASE_URL = "https://b2b.isaco.ir"
API_ROOT = "/api"

LOGIN_PATH = "Sec/Login/v2"
PRICE_LIST_EXCEL_PATH = "War/Reports/RepPriceListExcel"
PRICE_SEARCH_PATH = "War/Reports/GetPrcLstWgds"
VERSION_PATH = "/version.txt"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)


def digits_only_version(version: str) -> str:
    """نسخهٔ کلاینت را به فرم موردنیاز سرور می‌برد: فقط ارقام.

    سرور نسخه را عددی می‌سنجد، پس ``"3.2.7"`` باید ``"327"`` فرستاده شود
    (با تست زنده روی سرور واقعی تأیید شد؛ فرم نقطه‌دار رد می‌شود).

    >>> digits_only_version("3.2.7")
    '327'
    >>> digits_only_version("3.2.7\\n")
    '327'
    """
    return "".join(ch for ch in version if ch.isdigit())


def fetch_client_version(base_url: str = BASE_URL, timeout: int = 30) -> str:
    """نسخهٔ فعلی کلاینت را از ``/version.txt`` می‌گیرد (فرم عددی)."""
    response = requests.get(
        f"{base_url.rstrip('/')}{VERSION_PATH}",
        params={"nocache": "1"},
        timeout=timeout,
    )
    response.raise_for_status()
    return digits_only_version(response.text)


class IsacoLoginError(RuntimeError):
    """لاگین به پورتال ایساکو شکست خورد."""


class IsacoApiError(RuntimeError):
    """فراخوانی یک endpoint ایساکو شکست خورد."""


@dataclass(slots=True)
class IsacoCredentials:
    """اطلاعات ورود پورتال ایساکو."""

    scus: str          # کد نمایندگی/فروشگاه
    username: str       # نام کاربری
    password: str       # کلمه عبور
    client_version: str = ""
    lang: str = "fa"

    def login_payload(self) -> dict[str, str]:
        # سرور نسخه را عددی می‌سنجد؛ اگر نقطه‌دار داده شده، ارقامش را می‌گیریم.
        version = self.client_version
        if version and any(ch == "." for ch in version):
            version = "".join(ch for ch in version if ch.isdigit())
        return {
            "Scus": self.scus,
            "UserName": self.username,
            "Password": self.password,
            "ClientVersion": version,
            "Lng": self.lang,
        }


@dataclass(slots=True)
class IsacoSession:
    """نتیجهٔ یک لاگین موفق."""

    token: str
    expires_at: float | None = None   # زمان انقضا بر حسب epoch (از JWT)
    raw: dict = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        # کمی حاشیهٔ اطمینان تا وسط یک درخواست منقضی نشویم
        return time.time() >= self.expires_at - 60

    @property
    def full_name(self) -> str:
        return str(self.raw.get("FullName", ""))

    @property
    def scus(self) -> str:
        return str(self.raw.get("Scus", ""))


def _decode_jwt_exp(token: str) -> float | None:
    """زمان انقضای توکن را از payload آن می‌خواند (بدون اعتبارسنجی امضا)."""
    import base64
    import json

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        return float(exp) if exp is not None else None
    except (ValueError, IndexError, KeyError, json.JSONDecodeError):
        return None


class IsacoClient:
    """کلاینت پورتال B2B ایساکو.

    :param client_private_key: کلید خصوصی کلاینت (از باندل سایت) برای
        رمزگشایی پاسخ‌ها.
    :param server_public_key: کلید عمومی سرور برای رمز کردن درخواست‌ها.
    """

    def __init__(
        self,
        client_private_key: str,
        *,
        server_public_key: str = ISACO_SERVER_PUBLIC_KEY,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
        timeout: int = 60,
    ) -> None:
        self.client_private_key = client_private_key
        self.server_public_key = server_public_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", DEFAULT_UA)
        self.auth: IsacoSession | None = None

    # -- زیرساخت -------------------------------------------------------

    def _api_url(self, path: str) -> str:
        return f"{self.base_url}{API_ROOT}/{path.lstrip('/')}"

    def _headers(self, *, authorized: bool) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "Accept": "application/json, text/plain, */*",
            # اینترسپتور axios سایت این هدر را روی هر درخواست می‌گذارد؛
            # بدون آن سرور با «مجاز نیستید» (۴۰۱) پاسخ می‌دهد.
            "sec": "site",
        }
        if authorized:
            if self.auth is None:
                raise IsacoApiError("ابتدا باید لاگین کنید")
            headers["Authorization"] = self.auth.token
        return headers

    def _post_encrypted(
        self, path: str, payload: dict | list, *, authorized: bool
    ) -> dict | list:
        """بدنه را رمز می‌کند، می‌فرستد، و پاسخ را رمزگشایی می‌کند."""
        body = encrypt_request(payload, self.server_public_key)
        response = self._session.post(
            self._api_url(path),
            json=body.as_dict(),
            headers=self._headers(authorized=authorized),
            timeout=self.timeout,
        )
        if not response.ok:
            raise IsacoApiError(f"{path} → {response.status_code}: {response.text[:200]}")

        return self._parse_body(response.json(), path)

    def _parse_body(self, data: Any, path: str) -> dict | list:
        """پاسخ را رمزگشایی یا از حالت رشته‌ای خارج می‌کند.

        ایساکو سه شکل پاسخ می‌دهد:
        - ``{data, key}``  →  رمزشده، با کلید خصوصی باز می‌شود.
        - ``{data: "<json string>"}``  →  رمزنشده (لاگین و خطاها)، فقط
          باید رشتهٔ JSON داخلش را parse کرد.
        - JSON معمولی.
        """
        if isinstance(data, dict) and "data" in data:
            if "key" in data:
                try:
                    return decrypt_response(data, self.client_private_key)
                except IsacoCryptoError as exc:
                    raise IsacoApiError(
                        f"رمزگشایی پاسخ {path} شکست خورد: {exc}"
                    ) from exc
            inner = data["data"]
            if isinstance(inner, str):
                import json as _json

                try:
                    return _json.loads(inner)
                except _json.JSONDecodeError:
                    return {"data": inner}
        return data

    # -- لاگین ---------------------------------------------------------

    def login(self, credentials: IsacoCredentials) -> IsacoSession:
        """با یوزر/رمز لاگین می‌کند و توکن را نگه می‌دارد.

        اول یک ``GET /`` می‌زند تا کوکی نشست (connect.sid) ساخته شود،
        سپس بدنهٔ رمزشدهٔ لاگین را می‌فرستد.
        """
        # کوکی نشست
        self._session.get(f"{self.base_url}/", timeout=self.timeout)

        payload = credentials.login_payload()
        if not payload["ClientVersion"]:
            try:
                payload["ClientVersion"] = fetch_client_version(
                    self.base_url, self.timeout
                )
            except requests.RequestException:
                pass  # اگر نشد، با مقدار خالی تلاش می‌کنیم تا خطای روشن بگیریم

        result = self._post_encrypted(LOGIN_PATH, payload, authorized=False)

        token = self._extract_token(result)
        if not token:
            raise IsacoLoginError(
                "لاگین ناموفق بود؛ توکن دریافت نشد. "
                "یوزر/رمز یا کد نمایندگی را بررسی کنید."
            )

        # فیلدهای مفید (نام، Scus، منوها) داخل result["Data"] هستند.
        data = result.get("Data") if isinstance(result, dict) else None
        self.auth = IsacoSession(
            token=token,
            expires_at=_decode_jwt_exp(token),
            raw=data if isinstance(data, dict) else {},
        )
        return self.auth

    @staticmethod
    def _extract_token(result: dict | list) -> str | None:
        """توکن را از پاسخ لاگین بیرون می‌کشد.

        ساختار پاسخ ایساکو معمولاً ``{Success, Data:{Token}}`` است، ولی
        چند شکل محتمل دیگر را هم پوشش می‌دهیم تا شکننده نباشد.
        """
        if not isinstance(result, dict):
            return None
        if result.get("Success") is False:
            return None
        data = result.get("Data")
        if isinstance(data, dict):
            for key in ("Token", "token", "AccessToken", "Jwt"):
                if data.get(key):
                    return str(data[key])
        for key in ("Token", "token"):
            if result.get(key):
                return str(result[key])
        return None

    def ensure_logged_in(self, credentials: IsacoCredentials) -> IsacoSession:
        """اگر لاگین نیستیم یا توکن منقضی شده، دوباره لاگین می‌کند."""
        if self.auth is None or self.auth.is_expired:
            return self.login(credentials)
        return self.auth

    # -- دانلود لیست قیمت ---------------------------------------------

    def request_price_list(self, params: dict | None = None) -> dict | list:
        """endpoint گزارش اکسل لیست قیمت را صدا می‌زند.

        پاسخ معمولاً شامل مسیر یا شناسهٔ فایل تولیدشده است؛ ساختار دقیقش
        هنگام تست زنده روی سیستم کارفرما نهایی می‌شود و اینجا خام برمی‌گردد.
        """
        return self._post_encrypted(
            PRICE_LIST_EXCEL_PATH, params or {}, authorized=True
        )

    def search_by_code(self, code8: str) -> dict | list:
        """جستجوی کد اختصاصی ۸ رقمی؛ برای صفحهٔ «تطبیق دستی».

        نتایج چند کد ۱۰ رقمی هم‌خانواده را با قیمت و مارک برمی‌گرداند.
        """
        return self._post_encrypted(
            PRICE_SEARCH_PATH, {"WgdsGds": code8}, authorized=True
        )

    def download_file(self, url_or_path: str, dest: str) -> str:
        """فایل تولیدشده را دانلود و ذخیره می‌کند."""
        url = url_or_path
        if url.startswith("/"):
            url = f"{self.base_url}{url}"
        elif not url.startswith("http"):
            url = f"{self.base_url}/{url}"

        headers: dict[str, Any] = {}
        if self.auth is not None:
            headers["Authorization"] = self.auth.token

        with self._session.get(
            url, headers=headers, stream=True, timeout=self.timeout
        ) as response:
            if not response.ok:
                raise IsacoApiError(
                    f"دانلود فایل ناموفق: {response.status_code}"
                )
            with open(dest, "wb") as handle:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        handle.write(chunk)
        return dest
