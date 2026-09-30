"""کلاینت REST ووکامرس سایت تکسایدک.

فقط بخش‌هایی از WooCommerce REST API v3 که لازم داریم: خواندن، ساخت،
ویرایش و حذف محصولات، دسته‌بندی‌ها، سفارش‌ها (مشاهده، تغییر وضعیت و
یادداشت) و آپلود تصویر شاخص در کتابخانهٔ رسانهٔ وردپرس.

نکتهٔ کلیدی سرعت: به‌جای ``PUT`` جدا برای هر محصول، از endpoint
``products/batch`` استفاده می‌کنیم که تا ۱۰۰ محصول را در یک درخواست
به‌روز می‌کند. برای ۳۰۰ محصول یعنی ۳ درخواست به‌جای ۳۰۰ تا.
"""

from __future__ import annotations

import logging
import mimetypes
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterator

import requests

_log = logging.getLogger("nabz.woo")

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
    sale_price: str = ""
    #: دسته‌بندی‌ها: ``((شناسه، نام), ...)``
    categories: tuple[tuple[int, str], ...] = ()
    #: تصویر شاخص (اولین تصویر محصول)
    image_url: str = ""
    image_id: int = 0
    #: بقیهٔ تصاویر گالری (تا هنگام عوض کردن تصویر شاخص حذف نشوند)
    gallery_ids: tuple[int, ...] = ()

    @property
    def category_ids(self) -> list[int]:
        return [cid for cid, _ in self.categories]

    @property
    def category_names(self) -> str:
        return "، ".join(name for _, name in self.categories)

    @property
    def price_toman(self) -> int | None:
        if not self.regular_price:
            return None
        try:
            return int(Decimal(self.regular_price))
        except (ArithmeticError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class WooCategory:
    """یک دسته‌بندی محصول در ووکامرس."""

    id: int
    name: str
    parent: int = 0
    slug: str = ""
    count: int = 0


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
    #: نام کاربری و «رمز برنامه» (Application Password) وردپرس؛ فقط برای
    #: آپلود تصویر از روی کامپیوتر لازم است، چون کلیدهای ووکامرس به
    #: کتابخانهٔ رسانهٔ وردپرس دسترسی ندارند.
    wp_user: str = ""
    wp_app_password: str = ""

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
        if path.startswith("/wp-json/"):
            return f"{self.config.base_url}{path}"
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
            _log.debug("%s %s (تلاش %d)", method, path, attempt)
            try:
                response = self._session.request(method, self._url(path), **kwargs)
            except requests.RequestException as exc:
                last_error = exc
                _log.warning("خطای شبکه در %s %s: %s", method, path, exc)
            else:
                if response.status_code < 500:
                    if not response.ok:
                        _log.error(
                            "%s %s → %s | %s", method, path,
                            response.status_code, response.text[:300],
                        )
                        raise WooError(
                            f"{method} {path} → {response.status_code}: "
                            f"{response.text[:300]}"
                        )
                    return response
                last_error = WooError(
                    f"{method} {path} → {response.status_code}"
                )
                _log.warning("پاسخ ۵xx در %s %s: %s", method, path,
                             response.status_code)

            if attempt < self.config.retries:
                time.sleep(delay)
                delay *= 2

        raise WooError(f"{method} {path} پس از {self.config.retries} تلاش ناموفق ماند: {last_error}")

    # -- خواندن محصولات ------------------------------------------------

    _PRODUCT_FIELDS = (
        "id,name,sku,regular_price,sale_price,stock_quantity,stock_status,"
        "manage_stock,type,status,categories,images"
    )

    @staticmethod
    def _to_product(raw: dict) -> WooProduct:
        images = raw.get("images") or []
        first = images[0] if images and isinstance(images[0], dict) else {}
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
            sale_price=str(raw.get("sale_price") or ""),
            categories=tuple(
                (int(c["id"]), str(c.get("name", "")))
                for c in (raw.get("categories") or [])
                if isinstance(c, dict) and "id" in c
            ),
            image_url=str(first.get("src") or ""),
            image_id=int(first.get("id") or 0),
            gallery_ids=tuple(
                int(img["id"]) for img in images[1:]
                if isinstance(img, dict) and img.get("id")
            ),
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
            returned: set[int] = set()
            errors: dict[int, str] = {}
            for p in body.get("update", []):
                if "id" not in p:
                    continue
                if p.get("error"):
                    errors[int(p["id"])] = _error_message(p["error"])
                else:
                    returned.add(int(p["id"]))
            for item in chunk:
                pid = int(item["id"])
                if pid in returned:
                    outcome.updated.append(pid)
                else:
                    outcome.failed[pid] = errors.get(pid, "در پاسخ ووکامرس برنگشت")
        return outcome

    def batch_create(self, products: list[dict]) -> tuple[dict[int, int], dict[int, str]]:
        """چند محصول جدید می‌سازد.

        :returns: ``(ساخته‌شده‌ها، خطاها)``؛ کلید هر دو «اندیسِ آیتم در
            ورودی» است. ساخته‌شده‌ها به شناسهٔ محصول جدید نگاشت می‌شوند.
        """
        created: dict[int, int] = {}
        failed: dict[int, str] = {}
        for start in range(0, len(products), BATCH_LIMIT):
            chunk = products[start : start + BATCH_LIMIT]
            body = self._request(
                "POST", "products/batch", json={"create": chunk}
            ).json()
            results = body.get("create", [])
            for offset in range(len(chunk)):
                index = start + offset
                item = results[offset] if offset < len(results) else None
                if not item:
                    failed[index] = "در پاسخ ووکامرس برنگشت"
                elif item.get("error") or not item.get("id"):
                    failed[index] = _error_message(item.get("error"))
                else:
                    created[index] = int(item["id"])
        return created, failed

    def batch_delete(self, ids: list[int], *, force: bool = False) -> BatchOutcome:
        """محصولات را حذف می‌کند (پیش‌فرض: انتقال به زباله‌دان، قابل برگشت)."""
        outcome = BatchOutcome()
        for start in range(0, len(ids), BATCH_LIMIT):
            chunk = ids[start : start + BATCH_LIMIT]
            if force:
                body = self._request(
                    "POST", "products/batch", json={"delete": chunk}
                ).json()
                ok = {int(p["id"]) for p in body.get("delete", [])
                      if "id" in p and not p.get("error")}
            else:
                # حذف batch همیشه دائمی است؛ برای زباله‌دان وضعیت را عوض می‌کنیم
                ok = set(self.batch_update(
                    [{"id": pid, "status": "trash"} for pid in chunk]
                ).updated)
            for pid in chunk:
                if pid in ok:
                    outcome.updated.append(pid)
                else:
                    outcome.failed[pid] = "حذف نشد"
        return outcome

    def fetch_variation_skus(self, product_id: int) -> list[str]:
        """SKU همهٔ متغیرهای یک محصول متغیر."""
        skus: list[str] = []
        page = 1
        while True:
            response = self._request(
                "GET", f"products/{product_id}/variations",
                params={"per_page": PAGE_SIZE, "page": page, "_fields": "id,sku"},
            )
            batch = response.json()
            skus.extend((v.get("sku") or "").strip() for v in batch)
            total_pages = int(response.headers.get("X-WP-TotalPages", page))
            if not batch or page >= total_pages:
                return [s for s in skus if s]
            page += 1

    # -- دسته‌بندی‌ها --------------------------------------------------

    def fetch_categories(self) -> list[WooCategory]:
        """همهٔ دسته‌بندی‌های محصول."""
        result: list[WooCategory] = []
        page = 1
        while True:
            response = self._request(
                "GET", "products/categories",
                params={"per_page": PAGE_SIZE, "page": page,
                        "_fields": "id,name,parent,slug,count"},
            )
            batch = response.json()
            for raw in batch:
                result.append(WooCategory(
                    id=int(raw["id"]),
                    name=_unescape(raw.get("name", "")),
                    parent=int(raw.get("parent") or 0),
                    slug=raw.get("slug", ""),
                    count=int(raw.get("count") or 0),
                ))
            total_pages = int(response.headers.get("X-WP-TotalPages", page))
            if not batch or page >= total_pages:
                return result
            page += 1

    def create_category(self, name: str, parent: int = 0) -> WooCategory:
        raw = self._request(
            "POST", "products/categories", json={"name": name, "parent": parent}
        ).json()
        return WooCategory(id=int(raw["id"]), name=_unescape(raw.get("name", name)),
                           parent=int(raw.get("parent") or 0),
                           slug=raw.get("slug", ""))

    # -- تصویر ---------------------------------------------------------

    @property
    def can_upload_media(self) -> bool:
        return bool(self.config.wp_user and self.config.wp_app_password)

    def upload_media(self, path: str, *, title: str = "") -> tuple[int, str]:
        """یک فایل تصویر را در کتابخانهٔ رسانهٔ وردپرس آپلود می‌کند.

        :returns: ``(شناسهٔ رسانه، آدرس تصویر)``
        """
        if not self.can_upload_media:
            raise WooError(
                "برای آپلود تصویر از کامپیوتر، نام کاربری و «رمز برنامه» "
                "وردپرس را در تنظیمات وارد کنید."
            )
        import os
        from urllib.parse import quote

        filename = os.path.basename(path)
        mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
        with open(path, "rb") as handle:
            data = handle.read()
        url = f"{self.config.base_url}/wp-json/wp/v2/media"
        headers = {
            "Content-Type": mime,
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        }
        try:
            response = requests.post(
                url, data=data, headers={**self._BROWSER_HEADERS, **headers},
                auth=(self.config.wp_user, self.config.wp_app_password),
                timeout=max(self.config.timeout, 120),
            )
        except requests.RequestException as exc:
            raise WooError(f"آپلود تصویر ناموفق: {exc}") from exc
        if not response.ok:
            raise WooError(
                f"آپلود تصویر ناموفق ({response.status_code}): {response.text[:300]}"
            )
        body = response.json()
        media_id = int(body["id"])
        if title:
            try:
                requests.post(
                    f"{url}/{media_id}", json={"title": title, "alt_text": title},
                    headers=self._BROWSER_HEADERS,
                    auth=(self.config.wp_user, self.config.wp_app_password),
                    timeout=self.config.timeout,
                )
            except requests.RequestException:
                pass  # عنوان تصویر حیاتی نیست
        return media_id, str(body.get("source_url", ""))

    # -- سفارش‌ها ------------------------------------------------------

    def fetch_orders(
        self, status: str | None = None, per_page: int = 50, page: int = 1
    ) -> list[dict]:
        return self.list_orders(status=status, per_page=per_page, page=page)[0]

    def list_orders(
        self,
        *,
        status: str | None = None,
        search: str = "",
        page: int = 1,
        per_page: int = 50,
        after: str | None = None,
        before: str | None = None,
    ) -> tuple[list[dict], int, int]:
        """یک صفحه از سفارش‌ها، جدیدترین اول.

        :returns: ``(سفارش‌ها، تعداد کل، تعداد صفحات)``
        """
        params: dict[str, Any] = {
            "per_page": per_page, "page": page, "orderby": "date", "order": "desc",
        }
        if status and status != "any":
            params["status"] = status
        if search:
            params["search"] = search
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        response = self._request("GET", "orders", params=params)
        total = int(response.headers.get("X-WP-Total", 0) or 0)
        pages = int(response.headers.get("X-WP-TotalPages", 1) or 1)
        return response.json(), total, pages

    def get_order(self, order_id: int) -> dict:
        return self._request("GET", f"orders/{order_id}").json()

    def update_order(self, order_id: int, data: dict) -> dict:
        return self._request("PUT", f"orders/{order_id}", json=data).json()

    def order_notes(self, order_id: int) -> list[dict]:
        return self._request("GET", f"orders/{order_id}/notes").json()

    def add_order_note(self, order_id: int, note: str, *,
                       customer_note: bool = False) -> dict:
        return self._request(
            "POST", f"orders/{order_id}/notes",
            json={"note": note, "customer_note": customer_note},
        ).json()

    def order_status_totals(self) -> list[dict]:
        """وضعیت‌های سفارش (شامل وضعیت‌های سفارشیِ افزونه‌ها) با تعداد هرکدام.

        :returns: ``[{"slug": "processing", "name": "در حال انجام", "total": 3}, ...]``
        """
        return self._request("GET", "reports/orders/totals").json()

    def get_store_currency(self) -> str:
        """واحد پول فروشگاه؛ برای تکسایدک باید ``IRT`` (تومان) باشد."""
        response = self._request("GET", "settings/general")
        for setting in response.json():
            if setting.get("id") == "woocommerce_currency":
                return str(setting.get("value", ""))
        return ""


def _error_message(error: Any) -> str:
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "خطای نامشخص")
    return str(error or "خطای نامشخص")


def _unescape(text: str) -> str:
    """ووکامرس نام دسته‌ها را HTML-escape می‌کند (مثلاً ``&amp;``)."""
    import html
    return html.unescape(str(text))
