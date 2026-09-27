"""کلاینت REST ووکامرس سایت تکسایدک.

فقط بخش‌هایی از WooCommerce REST API v3 که لازم داریم: خواندن محصولات،
به‌روزرسانی دسته‌ای قیمت و موجودی، و خواندن سفارش‌ها.

نکتهٔ کلیدی سرعت: به‌جای ``PUT`` جدا برای هر محصول، از endpoint
``products/batch`` استفاده می‌کنیم که تا ۱۰۰ محصول را در یک درخواست
به‌روز می‌کند. برای ۳۰۰ محصول یعنی ۳ درخواست به‌جای ۳۰۰ تا.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterator

import requests

#: بیشترین تعداد آیتم در هر درخواست batch (محدودیت خود ووکامرس).
BATCH_LIMIT = 100

#: بیشترین تعداد محصول در هر صفحهٔ خواندن.
PAGE_SIZE = 100


class WooError(RuntimeError):
    """خطای ارتباط با ووکامرس."""


@dataclass(frozen=True, slots=True)
class WooProduct:
    """نمای سبک یک محصول سایت (فقط فیلدهای موردنیاز ما)."""

    id: int
    name: str
    sku: str
    regular_price: str
    stock_quantity: int | None
    stock_status: str
    manage_stock: bool
    type: str
    status: str

    @property
    def price_toman(self) -> int | None:
        if not self.regular_price:
            return None
        try:
            return int(Decimal(self.regular_price))
        except (ArithmeticError, ValueError):
            return None


@dataclass(slots=True)
class WooConfig:
    """آدرس و کلیدهای اتصال به ووکامرس."""

    base_url: str
    consumer_key: str
    consumer_secret: str
    timeout: int = 60
    #: تعداد تلاش مجدد در صورت خطای شبکه یا ۵xx.
    retries: int = 3
    #: مکث بین تلاش‌ها (ثانیه)؛ با هر تلاش دو برابر می‌شود.
    backoff: float = 2.0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")


@dataclass(slots=True)
class BatchOutcome:
    """نتیجهٔ یک به‌روزرسانی دسته‌ای."""

    updated: list[int] = field(default_factory=list)
    failed: dict[int, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed

    def merge(self, other: "BatchOutcome") -> None:
        self.updated.extend(other.updated)
        self.failed.update(other.failed)


class WooClient:
    """کلاینت کوچک و متمرکز REST ووکامرس."""

    #: هدرهای شبیه مرورگر واقعی. خیلی از سرورها/فایروال‌ها (ModSecurity،
    #: Cloudflare، LiteSpeed) درخواست با User-Agent «python-requests» را
    #: با ۴۰۳ Forbidden بلاک می‌کنند. با این هدرها مثل مرورگر رفتار می‌کنیم.
    _BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fa,en;q=0.9",
        "Connection": "keep-alive",
    }

    def __init__(self, config: WooConfig, session: requests.Session | None = None):
        self.config = config
        self._session = session or requests.Session()
        self._session.auth = (config.consumer_key, config.consumer_secret)
        self._session.headers.update(self._BROWSER_HEADERS)

    # -- پایه ----------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}/wp-json/wc/v3/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.config.timeout)
        # اگر سرور هدر Authorization را حذف کند (رایج روی بعضی هاست‌ها)،
        # کلیدها را به‌صورت پارامتر query هم می‌فرستیم (روی HTTPS امن است).
        params = kwargs.pop("params", None) or {}
        params.setdefault("consumer_key", self.config.consumer_key)
        params.setdefault("consumer_secret", self.config.consumer_secret)
        kwargs["params"] = params

        last_error: Exception | None = None
        delay = self.config.backoff

        for attempt in range(1, self.config.retries + 1):
            try:
                response = self._session.request(method, self._url(path), **kwargs)
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code < 500:
                    if not response.ok:
                        raise WooError(
                            f"{method} {path} → {response.status_code}: "
                            f"{response.text[:300]}"
                        )
                    return response
                last_error = WooError(
                    f"{method} {path} → {response.status_code}"
                )

            if attempt < self.config.retries:
                time.sleep(delay)
                delay *= 2

        raise WooError(f"{method} {path} پس از {self.config.retries} تلاش ناموفق ماند: {last_error}")

    # -- خواندن محصولات ------------------------------------------------

    _PRODUCT_FIELDS = (
        "id,name,sku,regular_price,stock_quantity,stock_status,"
        "manage_stock,type,status"
    )

    @staticmethod
    def _to_product(raw: dict) -> WooProduct:
        return WooProduct(
            id=int(raw["id"]),
            name=raw.get("name", ""),
            sku=(raw.get("sku") or "").strip(),
            regular_price=str(raw.get("regular_price") or ""),
            stock_quantity=raw.get("stock_quantity"),
            stock_status=raw.get("stock_status", ""),
            manage_stock=bool(raw.get("manage_stock")),
            type=raw.get("type", "simple"),
            status=raw.get("status", ""),
        )

    def iter_products(self, status: str = "any") -> Iterator[WooProduct]:
        """همهٔ محصولات را صفحه‌به‌صفحه می‌خواند."""
        page = 1
        while True:
            response = self._request(
                "GET",
                "products",
                params={
                    "per_page": PAGE_SIZE,
                    "page": page,
                    "status": status,
                    "_fields": self._PRODUCT_FIELDS,
                },
            )
            batch = response.json()
            if not batch:
                break
            for raw in batch:
                yield self._to_product(raw)
            total_pages = int(response.headers.get("X-WP-TotalPages", page))
            if page >= total_pages:
                break
            page += 1

    def fetch_products(self, status: str = "any") -> list[WooProduct]:
        return list(self.iter_products(status=status))

    def count_products(self, status: str = "any") -> int:
        response = self._request(
            "GET",
            "products",
            params={"per_page": 1, "status": status, "_fields": "id"},
        )
        return int(response.headers.get("X-WP-Total", 0))

    # -- به‌روزرسانی دسته‌ای -------------------------------------------

    def batch_update(self, updates: list[dict]) -> BatchOutcome:
        """چند محصول را در دسته‌های ۱۰۰تایی به‌روز می‌کند.

        هر آیتم باید ``id`` داشته باشد و هر فیلد قابل قبول ووکامرس، مثل
        ``regular_price``، ``stock_quantity``، ``manage_stock``،
        ``stock_status``.
        """
        outcome = BatchOutcome()
        for start in range(0, len(updates), BATCH_LIMIT):
            chunk = updates[start : start + BATCH_LIMIT]
            response = self._request(
                "POST", "products/batch", json={"update": chunk}
            )
            body = response.json()
            returned = {int(p["id"]) for p in body.get("update", []) if "id" in p}
            for item in chunk:
                pid = int(item["id"])
                if pid in returned:
                    outcome.updated.append(pid)
                else:
                    outcome.failed[pid] = "در پاسخ ووکامرس برنگشت"
        return outcome

    # -- سفارش‌ها ------------------------------------------------------

    def fetch_orders(
        self, status: str | None = None, per_page: int = 50, page: int = 1
    ) -> list[dict]:
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if status:
            params["status"] = status
        return self._request("GET", "orders", params=params).json()

    def get_store_currency(self) -> str:
        """واحد پول فروشگاه؛ برای تکسایدک باید ``IRT`` (تومان) باشد."""
        response = self._request("GET", "settings/general")
        for setting in response.json():
            if setting.get("id") == "woocommerce_currency":
                return str(setting.get("value", ""))
        return ""
