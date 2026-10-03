"""بارگذاری تصویر کوچک محصولات در پس‌زمینه.

چرا با ``requests`` و نه ``QNetworkAccessManager``: سرور سایت درخواست‌هایی
را که شبیه مرورگر نیستند با ۴۰۳ رد می‌کند (همان مشکل REST). اینجا همان
هدرهای مرورگری کلاینت ووکامرس فرستاده می‌شود.

برای سبک ماندن، اول نسخهٔ کوچکِ ساخته‌شده توسط وردپرس (``-300x300`` و
``-150x150``) امتحان می‌شود و اگر نبود خود تصویر اصلی. تصاویر روی دیسک
کش می‌شوند تا دفعهٔ بعد فوری نمایش داده شوند.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage

_log = logging.getLogger("nabz.ui")

#: بیشترین ضلع تصویری که نگه داشته می‌شود (برای پیش‌نمایش پنجرهٔ تصویر هم کافی)
MAX_SIDE = 300

_SIZED = re.compile(r"-\d+x\d+(?=\.[A-Za-z0-9]+$)")
_EXT = re.compile(r"(\.[A-Za-z0-9]+)$")


def candidate_urls(url: str) -> list[str]:
    """نسخه‌های کوچک وردپرسی یک تصویر، به ترتیب اولویت، و در آخر خود تصویر.

    >>> candidate_urls("https://x.com/up/a.jpg")
    ['https://x.com/up/a-300x300.jpg', 'https://x.com/up/a-150x150.jpg', 'https://x.com/up/a.jpg']
    >>> candidate_urls("https://x.com/up/a-600x400.png")
    ['https://x.com/up/a-600x400.png']
    >>> candidate_urls("https://x.com/img?id=5")
    ['https://x.com/img?id=5']
    """
    path = url.split("?", 1)[0]
    if "?" in url or _SIZED.search(path) or not _EXT.search(path):
        return [url]
    return [_EXT.sub(rf"-{size}\1", url) for size in ("300x300", "150x150")] + [url]


def default_cache_dir() -> Path:
    from ..logging_setup import LOG_DIR_NAME
    return Path.home() / LOG_DIR_NAME / "thumbs"


class _Http:
    """یک session جدا برای هر نخ (requests.Session امن چندنخی نیست)."""

    def __init__(self) -> None:
        self._local = threading.local()

    def get(self, url: str) -> bytes | None:
        import requests

        from ..targets.woocommerce import WooClient

        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(WooClient._BROWSER_HEADERS)
            session.headers["Accept"] = "image/avif,image/webp,image/png,image/*,*/*;q=0.8"
            self._local.session = session
        try:
            response = session.get(url, timeout=20)
        except requests.RequestException as exc:
            _log.debug("تصویر %s: %s", url, exc)
            return None
        kind = response.headers.get("Content-Type", "")
        if response.status_code != 200 or (kind and not kind.startswith("image/")):
            return None
        return response.content


class ThumbLoader(QObject):
    """درخواست تصویر می‌گیرد و نتیجه را روی نخ اصلی با سیگنال ``loaded`` می‌دهد.

    ``loaded(url, image)``: اگر بارگذاری نشد، ``image.isNull()`` است.
    """

    loaded = Signal(str, QImage)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        workers: int = 6,
        cache_dir: Path | None = None,
        fetch: Callable[[str], bytes | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="thumb")
        self._cache_dir = cache_dir if cache_dir is not None else default_cache_dir()
        self._fetch = fetch or _Http().get
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._closed = False
        self.destroyed.connect(lambda *_: self.shutdown())

    def request(self, url: str) -> bool:
        """``url`` را در صف می‌گذارد؛ اگر قبلاً در صف بود ``False``."""
        if not url or self._closed:
            return False
        with self._lock:
            if url in self._pending:
                return False
            self._pending.add(url)
        self._pool.submit(self._work, url)
        return True

    def is_pending(self, url: str) -> bool:
        with self._lock:
            return url in self._pending

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- نخ کارگر ---------------------------------------------------------

    def _cache_file(self, url: str) -> Path:
        return self._cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".img")

    def _work(self, url: str) -> None:
        image = QImage()
        try:
            image = self._load(url)
        except Exception:  # noqa: BLE001 - یک تصویر خراب نباید چیزی را خراب کند
            _log.debug("خطا در بارگذاری تصویر %s", url, exc_info=True)
        finally:
            with self._lock:
                self._pending.discard(url)
        if self._closed:
            return
        try:
            self.loaded.emit(url, image)
        except RuntimeError:
            pass  # تب بسته شده است

    def _load(self, url: str) -> QImage:
        cache = self._cache_file(url)
        if cache.is_file():
            image = QImage()
            if image.loadFromData(cache.read_bytes()):
                return image
        for candidate in candidate_urls(url):
            if self._closed:
                break
            data = self._fetch(candidate)
            if not data:
                continue
            image = QImage()
            if not image.loadFromData(data):
                continue
            if max(image.width(), image.height()) > MAX_SIDE:
                image = image.scaled(MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            self._save_cache(cache, image)
            return image
        return QImage()

    def _save_cache(self, path: Path, image: QImage) -> None:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            buffer.close()
            path.write_bytes(bytes(data))
        except OSError:
            pass
