"""دانلود خودکار لیست قیمت ایساکو با یک مرورگر واقعی (QtWebEngine).

سرور گزارش ایساکو (b2brep) به viewer جاوااسکریپتی نیاز دارد و با HTTP خالص
قابل تقلید نیست. این ماژول مثل یک انسان عمل می‌کند: یک مرورگر Chromium
داخلی باز می‌کند، لاگین می‌کند، به صفحهٔ لیست قیمت می‌رود، دکمهٔ دانلود
اکسل را می‌زند، و فایل دانلودشده را می‌گیرد.

چون یک مرورگر واقعی است، کوکی‌ها بین b2b و b2brep درست به اشتراک گذاشته
می‌شوند و مشکل «Pkg not found» پیش نمی‌آید.

سلکتورها در بالای فایل تعریف شده‌اند تا اگر ایساکو صفحه را عوض کرد، به‌راحتی
به‌روز شوند.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

_log = logging.getLogger("nabz.isaco_browser")

BASE_URL = "https://b2b.isaco.ir"
LOGIN_URL = f"{BASE_URL}/"
PRICELIST_URL = f"{BASE_URL}/PriceList"

# --- سلکتورهای صفحه (در صورت تغییر سایت ایساکو اینجا را عوض کنید) ---
SEL_SCUS = "#Scus"
SEL_USERNAME = "#UserName"
SEL_PASSWORD = "#Password"
SEL_LOGIN_SUBMIT = 'form input[type="submit"]'
# دکمهٔ گزارش اکسل در صفحهٔ لیست قیمت
SEL_EXCEL_BUTTON = "button.k-button-icontext .k-i-excel"

#: بیشترین زمان انتظار برای هر مرحله (میلی‌ثانیه)
STEP_TIMEOUT_MS = 40_000


class IsacoBrowserError(RuntimeError):
    """اتوماسیون مرورگر ایساکو شکست خورد."""


def _js_fill_login(scus: str, username: str, password: str) -> str:
    """جاوااسکریپت پر کردن فرم لاگین و کلیک ورود.

    مقادیر با JSON امن‌سازی می‌شوند و رویداد input برای React ارسال می‌شود.
    """
    import json

    return f"""
    (function() {{
        function setVal(sel, val) {{
            var el = document.querySelector(sel);
            if (!el) return false;
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }}
        var ok = setVal({json.dumps(SEL_SCUS)}, {json.dumps(scus)})
              && setVal({json.dumps(SEL_USERNAME)}, {json.dumps(username)})
              && setVal({json.dumps(SEL_PASSWORD)}, {json.dumps(password)});
        if (!ok) return 'fields-not-found';
        var btn = document.querySelector({json.dumps(SEL_LOGIN_SUBMIT)});
        if (!btn) return 'submit-not-found';
        btn.click();
        return 'ok';
    }})();
    """


def _js_click_excel() -> str:
    """جاوااسکریپت کلیک روی دکمهٔ دانلود اکسل لیست قیمت."""
    import json

    return f"""
    (function() {{
        var icon = document.querySelector({json.dumps(SEL_EXCEL_BUTTON)});
        var btn = icon ? icon.closest('button') : null;
        if (!btn) {{
            // جستجوی جایگزین بر اساس متن
            var buttons = Array.prototype.slice.call(document.querySelectorAll('button'));
            btn = buttons.find(function(b) {{ return b.textContent.indexOf('excel') > -1
                || b.textContent.indexOf('اکسل') > -1; }});
        }}
        if (!btn) return 'excel-button-not-found';
        if (btn.disabled || btn.className.indexOf('btn-disabled') > -1) return 'excel-button-disabled';
        btn.click();
        return 'ok';
    }})();
    """


class IsacoDownloader:
    """با QtWebEngine لیست قیمت ایساکو را دانلود می‌کند.

    باید در نخ اصلی Qt و در حضور یک QApplication اجرا شود.
    """

    def __init__(self, scus: str, username: str, password: str,
                 on_progress: Callable[[str], None] | None = None):
        self.scus = scus
        self.username = username
        self.password = password
        self._progress = on_progress or (lambda m: None)
        self._result_path: str | None = None
        self._error: str | None = None
        self._done = False

    def _emit(self, message: str) -> None:
        _log.info(message)
        self._progress(message)

    def download(self, dest: str, timeout_s: int = 180) -> str:
        """کل فرایند را اجرا می‌کند و مسیر فایل دانلودشده را برمی‌گرداند."""
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView

        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        loop = QEventLoop()
        view = QWebEngineView()
        profile = view.page().profile()

        # مدیریت دانلود: فایل را در مقصد ذخیره کن
        def on_download(item):
            try:
                item.setDownloadDirectory(str(dest_path.parent))
                item.setDownloadFileName(dest_path.name)
            except Exception:  # نسخه‌های قدیمی‌تر API
                item.setPath(str(dest_path))
            item.accept()

            def finished():
                self._result_path = str(dest_path)
                self._done = True
                loop.quit()

            item.isFinishedChanged.connect(
                lambda: finished() if item.isFinished() else None
            )
            # بعضی نسخه‌ها سیگنال دیگری دارند
            try:
                item.stateChanged.connect(
                    lambda s: finished() if int(s) == 2 else None
                )
            except Exception:
                pass

        profile.downloadRequested.connect(on_download)

        # زمان‌بندی مراحل
        state = {"phase": "login"}

        def fail(msg: str) -> None:
            self._error = msg
            self._done = True
            loop.quit()

        def on_load_finished(ok: bool) -> None:
            if not ok:
                return  # بعضی بارگذاری‌های میانی ممکن است ok=False باشند
            url = view.url().toString()
            _log.info("صفحه بارگذاری شد: %s (phase=%s)", url, state["phase"])

            if state["phase"] == "login" and url.rstrip("/") == BASE_URL:
                self._emit("در حال ورود به ایساکو ...")
                state["phase"] = "logging_in"
                view.page().runJavaScript(
                    _js_fill_login(self.scus, self.username, self.password),
                    handle_login_result,
                )

        def handle_login_result(result) -> None:
            if result != "ok":
                fail(f"پر کردن فرم لاگین ناموفق: {result}")
                return
            self._emit("ورود انجام شد، در حال رفتن به لیست قیمت ...")
            state["phase"] = "pricelist"
            # کمی صبر تا لاگین کامل شود، سپس به لیست قیمت برو
            QTimer.singleShot(4000, lambda: view.setUrl(QUrl(PRICELIST_URL)))
            QTimer.singleShot(9000, try_click_excel)

        def try_click_excel() -> None:
            self._emit("در حال کلیک روی دکمهٔ دانلود اکسل ...")
            view.page().runJavaScript(_js_click_excel(), handle_excel_result)

        def handle_excel_result(result) -> None:
            if result == "ok":
                self._emit("دانلود آغاز شد ...")
                return  # منتظر رویداد دانلود می‌مانیم
            if result == "excel-button-disabled":
                # شاید هنوز صفحه آماده نیست؛ یک بار دیگر امتحان کن
                QTimer.singleShot(5000, try_click_excel)
                return
            fail(f"دکمهٔ دانلود اکسل: {result}")

        view.loadFinished.connect(on_load_finished)
        view.setUrl(QUrl(LOGIN_URL))

        # محافظ زمان کلی
        QTimer.singleShot(timeout_s * 1000, lambda: fail("زمان دانلود به پایان رسید"))

        loop.exec()
        view.deleteLater()

        if self._error:
            raise IsacoBrowserError(self._error)
        if not self._result_path or not Path(self._result_path).is_file():
            raise IsacoBrowserError("فایل دانلود نشد")
        return self._result_path
