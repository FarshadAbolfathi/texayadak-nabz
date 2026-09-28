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
# دکمهٔ گزارش اکسل در صفحهٔ لیست قیمت (دو راه: آیکون اکسل، و مسیر صفحه)
SEL_EXCEL_ICON = ".k-icon.k-i-excel"
SEL_EXCEL_PATH = "#root > div > div.sc-Rmtcm.fnmBum > div > div > div:nth-child(4) button"

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
    """جاوااسکریپت کلیک روی دکمهٔ دانلود اکسل لیست قیمت.

    سه راه برای یافتن دکمه: آیکون اکسل، مسیر صفحه، و جستجوی متنی.
    کلاس ``btn-disabled`` گاهی ظاهری است؛ اگر دکمه پیدا شد، کلیک می‌کنیم.
    """
    import json

    return f"""
    (function() {{
        var btn = null;
        var icon = document.querySelector({json.dumps(SEL_EXCEL_ICON)});
        if (icon) btn = icon.closest('button');
        if (!btn) btn = document.querySelector({json.dumps(SEL_EXCEL_PATH)});
        if (!btn) {{
            var buttons = Array.prototype.slice.call(document.querySelectorAll('button'));
            btn = buttons.find(function(b) {{ return b.textContent.indexOf('excel') > -1
                || b.textContent.indexOf('اکسل') > -1; }});
        }}
        if (!btn) return 'excel-button-not-found';
        // برخی نسخه‌ها disabled ظاهری دارند؛ محدودیت را برمی‌داریم و کلیک می‌کنیم
        btn.disabled = false;
        btn.classList.remove('btn-disabled');
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

    def download(self, dest: str, timeout_s: int = 240) -> str:
        """کل فرایند را اجرا می‌کند و مسیر فایل دانلودشده را برمی‌گرداند.

        مراحل: ورود → صفحهٔ لیست قیمت → کلیک دکمهٔ اکسل → یک پنجرهٔ گزارش
        (b2brep) باز می‌شود که پس از رندر شدن گزارش (چند ده ثانیه برای ۴۶
        هزار ردیف) خودکار فایل را دانلود می‌کند. آن دانلود گرفته و ذخیره
        می‌شود.
        """
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView

        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        loop = QEventLoop()
        # پنجرهٔ گزارش که با کلیک باز می‌شود باید یک view واقعی داشته باشد،
        # وگرنه دانلود اجرا نمی‌شود.
        popup_views: list = []

        downloader = self  # برای دسترسی در closure

        class MainPage(QWebEnginePage):
            def createWindow(self, _window_type):
                downloader._emit("در حال آماده‌سازی گزارش (چند لحظه صبر کنید) ...")
                popup_view = QWebEngineView()
                popup_views.append(popup_view)
                return popup_view.page()

        view = QWebEngineView()
        page = MainPage(view.page().profile(), view)
        view.setPage(page)
        profile = page.profile()

        def on_download(item):
            item.setDownloadDirectory(str(dest_path.parent))
            item.setDownloadFileName(dest_path.name)
            item.accept()
            self._emit("در حال دانلود فایل لیست قیمت ...")

            def finished():
                if item.isFinished():
                    self._result_path = str(dest_path)
                    self._done = True
                    loop.quit()

            item.isFinishedChanged.connect(finished)

        profile.downloadRequested.connect(on_download)

        state = {"phase": "login", "clicked": False}

        def fail(msg: str) -> None:
            if not self._done:
                self._error = msg
                self._done = True
                loop.quit()

        def on_load_finished(ok: bool) -> None:
            url = view.url().toString()
            _log.info("صفحه: %s (phase=%s ok=%s)", url, state["phase"], ok)

            if state["phase"] == "login" and url.rstrip("/") == BASE_URL:
                self._emit("در حال ورود به ایساکو ...")
                state["phase"] = "logging_in"
                page.runJavaScript(
                    _js_fill_login(self.scus, self.username, self.password),
                    handle_login_result,
                )
            elif "PriceList" in url and not state["clicked"]:
                state["clicked"] = True
                self._emit("در حال باز کردن لیست قیمت ...")
                # صبر برای بارگذاری دادهٔ صفحه، سپس کلیک دکمهٔ اکسل
                QTimer.singleShot(8000, try_click_excel)

        def handle_login_result(result) -> None:
            if result != "ok":
                fail(f"ورود ناموفق: {result} (یوزر/رمز/کد نمایندگی را بررسی کنید)")
                return
            self._emit("ورود انجام شد، در حال رفتن به لیست قیمت ...")
            state["phase"] = "pricelist"
            QTimer.singleShot(4000, lambda: view.setUrl(QUrl(PRICELIST_URL)))

        def try_click_excel() -> None:
            self._emit("در حال کلیک روی دکمهٔ دانلود اکسل ...")
            page.runJavaScript(_js_click_excel(), handle_excel_result)

        def handle_excel_result(result) -> None:
            if result == "ok":
                self._emit(
                    "گزارش در حال آماده‌سازی است؛ برای ۴۶ هزار قلم ممکن است "
                    "تا یک دقیقه طول بکشد ..."
                )
                return  # منتظر رویداد دانلود می‌مانیم
            fail(f"دکمهٔ دانلود اکسل پیدا نشد: {result}")

        view.loadFinished.connect(on_load_finished)
        view.setUrl(QUrl(LOGIN_URL))

        QTimer.singleShot(timeout_s * 1000, lambda: fail("زمان دانلود به پایان رسید"))

        loop.exec()
        view.deleteLater()
        for pv in popup_views:
            pv.deleteLater()

        if self._error:
            raise IsacoBrowserError(self._error)
        if not self._result_path or not Path(self._result_path).is_file():
            raise IsacoBrowserError("فایل دانلود نشد")
        return self._result_path
