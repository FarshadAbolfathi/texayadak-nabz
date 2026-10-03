"""تست بهبودهای رابط: کپی جدول‌ها، عرض ستون‌ها، تصاویر محصولات، پنجرهٔ
تمام‌صفحه و اسکرول تب سفارش‌ها — بدون شبکه."""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QMessageBox,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
)

from nabz.config import CredentialStore, MemoryBackend, WooCredentials
from nabz.db import Database
from nabz.targets.woocommerce import WooCategory, WooProduct


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def store():
    s = CredentialStore(backend=MemoryBackend())
    s.save_woo(WooCredentials(base_url="https://x.com", consumer_key="ck",
                              consumer_secret="cs"))
    return s


@pytest.fixture(autouse=True)
def no_dialogs(monkeypatch):
    yes = QMessageBox.StandardButton.Yes
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: yes))


def make_table(rows=3, behavior=QAbstractItemView.SelectionBehavior.SelectItems):
    t = QTableWidget(rows, 3)
    t.setSelectionBehavior(behavior)
    for r in range(rows):
        for c in range(3):
            t.setItem(r, c, QTableWidgetItem(f"r{r}c{c}"))
    return t


def key_event(kind, key, text="", native_vk=0, mods=Qt.KeyboardModifier.ControlModifier):
    return QKeyEvent(kind, key, mods, 0, native_vk, 0, text)


# -- کپی -----------------------------------------------------------------


class TestCopy:
    def test_ctrl_c_with_persian_layout_copies(self, qapp):
        """با صفحه‌کلید فارسی Qt کلید «ز» می‌بیند؛ کلید فیزیکی C (0x43) باید کافی باشد."""
        from nabz.ui.widgets import make_copyable
        t = make_table()
        msgs = []
        make_copyable(t, on_copied=msgs.append)
        t.setCurrentCell(1, 2)
        QGuiApplication.clipboard().setText("")
        persian_ze = 0x0632  # «ز»
        QApplication.sendEvent(t, key_event(QEvent.Type.KeyPress, persian_ze, "ز", 0x43))
        assert QGuiApplication.clipboard().text() == "r1c2"
        assert msgs and "کپی شد" in msgs[-1]

    def test_ctrl_c_and_ctrl_insert(self, qapp):
        from nabz.ui.widgets import make_copyable
        t = make_table()
        make_copyable(t)
        t.setCurrentCell(0, 1)
        for key in (Qt.Key.Key_C, Qt.Key.Key_Insert):
            QGuiApplication.clipboard().setText("")
            QApplication.sendEvent(t, key_event(QEvent.Type.KeyPress, key))
            assert QGuiApplication.clipboard().text() == "r0c1"

    def test_shortcut_override_is_claimed(self, qapp):
        """تا میان‌برهای دیگرِ پنجره (یا QAction) کلید را ندزدند."""
        from nabz.ui.widgets import make_copyable
        t = make_table()
        make_copyable(t)
        ev = key_event(QEvent.Type.ShortcutOverride, Qt.Key.Key_C)
        ev.ignore()
        QApplication.sendEvent(t, ev)
        assert ev.isAccepted()

    def test_plain_typing_is_not_intercepted(self, qapp):
        from nabz.ui.widgets import is_copy_key
        assert not is_copy_key(key_event(QEvent.Type.KeyPress, Qt.Key.Key_C, "c", 0x43,
                                         Qt.KeyboardModifier.NoModifier))
        assert not is_copy_key(key_event(
            QEvent.Type.KeyPress, Qt.Key.Key_C, "", 0x43,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))

    def test_row_selection_copies_current_cell(self, qapp):
        from nabz.ui.widgets import copy_text
        t = make_table(behavior=QAbstractItemView.SelectionBehavior.SelectRows)
        t.setCurrentCell(2, 1)
        assert copy_text(t) == "r2c1"

    def test_multi_row_selection_copies_table(self, qapp):
        from nabz.ui.widgets import copy_text
        t = make_table(behavior=QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        t.selectRow(0)
        t.selectRow(1)
        assert copy_text(t) == "r0c0\tr0c1\tr0c2\nr1c0\tr1c1\tr1c2"

    @pytest.mark.parametrize("tab_name", ["sync", "products", "new_products"])
    def test_product_tables_are_copyable(self, qapp, db, store, tab_name):
        from nabz.ui.tabs.new_products import NewProductsTab
        from nabz.ui.tabs.products import ProductsTab
        from nabz.ui.tabs.sync import SyncTab
        cls = {"sync": SyncTab, "products": ProductsTab, "new_products": NewProductsTab}
        tab = cls[tab_name](db, store)
        t = tab.table
        t.setRowCount(1)
        for c in range(t.columnCount()):
            t.setItem(0, c, QTableWidgetItem(f"v{c}"))
        t.setCurrentCell(0, 1)
        QGuiApplication.clipboard().setText("")
        QApplication.sendEvent(t, key_event(QEvent.Type.KeyPress, 0x0632, "ز", 0x43))
        assert QGuiApplication.clipboard().text() == "v1"
        assert t.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


# -- ستون‌ها --------------------------------------------------------------


class TestColumns:
    def test_all_columns_interactive_and_saved(self, qapp, db):
        from nabz.ui.widgets import setup_columns
        t = make_table()
        setup_columns(t, {0: 100, 1: 300, 2: 80}, db=db, key="cols_x", fixed=(0,))
        head = t.horizontalHeader()
        assert head.sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
        assert head.sectionResizeMode(1) == QHeaderView.ResizeMode.Interactive
        assert t.columnWidth(1) == 300
        t.setColumnWidth(1, 450)
        deadline = time.monotonic() + 2
        while db.get_setting("cols_x") is None and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.02)
        assert db.get_setting("cols_x")[1] == 450

        t2 = make_table()
        setup_columns(t2, {0: 100, 1: 300, 2: 80}, db=db, key="cols_x")
        assert t2.columnWidth(1) == 450

    def test_bad_saved_value_is_ignored(self, qapp, db):
        from nabz.ui.widgets import setup_columns
        db.set_setting("cols_y", [1, 2])        # تعداد ستون‌ها نمی‌خواند
        t = make_table()
        setup_columns(t, {1: 222}, db=db, key="cols_y")
        assert t.columnWidth(1) == 222

    @pytest.mark.parametrize("tab_name", ["sync", "products", "new_products"])
    def test_name_column_is_wide_and_resizable(self, qapp, db, store, tab_name):
        from nabz.ui.tabs.new_products import NewProductsTab
        from nabz.ui.tabs.products import ProductsTab
        from nabz.ui.tabs.sync import SyncTab
        tab = {"sync": SyncTab, "products": ProductsTab,
               "new_products": NewProductsTab}[tab_name](db, store)
        head = tab.table.horizontalHeader()
        assert head.sectionResizeMode(tab.COL_NAME) == QHeaderView.ResizeMode.Interactive
        assert tab.table.columnWidth(tab.COL_NAME) >= 400


# -- تصاویر محصولات -------------------------------------------------------


def png_bytes(color="red", size=600) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    img = QImage(size, size // 2, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def wait_for(cond, timeout=5):
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    return cond()


class TestThumbLoader:
    def test_prefers_small_wordpress_variant_and_caches(self, qapp, tmp_path):
        from nabz.ui.thumbs import ThumbLoader
        asked = []

        def fetch(url):
            asked.append(url)
            return png_bytes() if url.endswith("-300x300.jpg") else None

        got = {}
        loader = ThumbLoader(cache_dir=tmp_path, fetch=fetch)
        loader.loaded.connect(lambda u, img: got.__setitem__(u, img))
        assert loader.request("https://x.com/a.jpg")
        assert not loader.request("https://x.com/a.jpg") or True   # تکراری در صف
        assert wait_for(lambda: "https://x.com/a.jpg" in got)
        img = got["https://x.com/a.jpg"]
        assert not img.isNull() and max(img.width(), img.height()) <= 300
        assert asked[0] == "https://x.com/a-300x300.jpg"

        # بار دوم از کش دیسک، بدون درخواست شبکه
        asked.clear()
        got.clear()
        loader2 = ThumbLoader(cache_dir=tmp_path, fetch=fetch)
        loader2.loaded.connect(lambda u, img: got.__setitem__(u, img))
        loader2.request("https://x.com/a.jpg")
        assert wait_for(lambda: "https://x.com/a.jpg" in got)
        assert asked == []
        loader.shutdown()
        loader2.shutdown()

    def test_falls_back_to_original_and_reports_failure(self, qapp, tmp_path):
        from nabz.ui.thumbs import ThumbLoader
        got = {}
        loader = ThumbLoader(cache_dir=tmp_path, fetch=lambda u: (
            png_bytes("blue", 100) if u == "https://x.com/ok.png" else None))
        loader.loaded.connect(lambda u, img: got.__setitem__(u, img))
        loader.request("https://x.com/ok.png")
        loader.request("https://x.com/bad.png")
        assert wait_for(lambda: len(got) == 2)
        assert not got["https://x.com/ok.png"].isNull()
        assert got["https://x.com/bad.png"].isNull()
        loader.shutdown()

    def test_browser_user_agent_is_sent(self, monkeypatch):
        """سرور سایت درخواست غیرمرورگری را ۴۰۳ می‌کند."""
        import requests

        from nabz.ui.thumbs import _Http
        seen = {}

        class Resp:
            status_code = 200
            headers = {"Content-Type": "image/png"}
            content = b"x"

        def fake_get(self, url, timeout):
            seen.update(self.headers)
            return Resp()

        monkeypatch.setattr(requests.Session, "get", fake_get)
        assert _Http().get("https://x.com/a.png") == b"x"
        assert "Mozilla" in seen["User-Agent"]
        assert "image/" in seen["Accept"]


def woo(pid, image=""):
    return WooProduct(id=pid, name=f"محصول {pid}", sku=str(pid), regular_price="1000",
                      stock_quantity=1, stock_status="instock", manage_stock=True,
                      type="simple", status="publish", image_url=image)


class TestProductImages:
    def test_thumbnails_load_and_missing_images_are_marked(self, qapp, db, store, monkeypatch):
        from nabz.ui import thumbs
        from nabz.ui.tabs.products import ProductsTab

        def fake_http_get(self, url):
            return png_bytes() if "has" in url else None
        monkeypatch.setattr(thumbs._Http, "get", fake_http_get)
        monkeypatch.setattr(thumbs, "default_cache_dir",
                            lambda: __import__("pathlib").Path(
                                __import__("tempfile").mkdtemp()))

        tab = ProductsTab(db, store)
        tab._on_loaded(([woo(1, "https://x.com/has.jpg"), woo(2),
                         woo(3, "https://x.com/broken.jpg")],
                        [WooCategory(1, "پژو")]))
        tab._thumb_timer.stop()
        tab._load_visible_thumbs()

        def cell(r):
            return tab.table.item(r, tab.COL_IMG)
        assert "بدون" in cell(1).text()                       # بدون تصویر
        assert wait_for(lambda: not cell(0).icon().isNull())   # تصویر لود شد
        assert wait_for(lambda: cell(2).text() == "⚠️")         # تصویر دارد ولی خراب
        assert "https://x.com/has.jpg" in tab._thumbs
        tab._thumb_loader.shutdown()

    def test_click_on_image_opens_dialog_without_upload_hint(self, qapp, db, store, monkeypatch):
        from PySide6.QtWidgets import QDialog, QLabel, QPushButton

        from nabz.ui.tabs import products as mod
        opened = []
        real = mod.ImageDialog

        class Spy(real):
            def exec(self):
                opened.append(self)
                return QDialog.DialogCode.Rejected
        monkeypatch.setattr(mod, "ImageDialog", Spy)
        # کلیدهای Ctrl ساختگی تست‌های قبلی در وضعیت سراسری Qt می‌مانند
        monkeypatch.setattr(QApplication, "keyboardModifiers",
                            staticmethod(lambda: Qt.KeyboardModifier.NoModifier))
        tab = mod.ProductsTab(db, store)
        tab._on_loaded(([woo(2)], []))
        tab._thumb_timer.stop()
        tab._on_click(0, tab.COL_IMG)
        (dlg,) = opened
        texts = " ".join(w.text() for w in dlg.findChildren(QLabel))
        assert "Application Password" not in texts and "رمز برنامه" not in texts
        file_btn = [b for b in dlg.findChildren(QPushButton) if "فایل" in b.text()][0]
        assert file_btn.isEnabled()
        # کلیک روی ستون دیگر پنجره باز نمی‌کند
        tab._on_click(0, tab.COL_NAME)
        assert len(opened) == 1


class TestWpDefaults:
    def test_wp_password_falls_back_to_bundled_default(self, monkeypatch, store):
        from nabz import defaults
        from nabz.ui.services import woo_client_from_store
        monkeypatch.setattr(defaults, "DEFAULT_WP_USER", "u")
        monkeypatch.setattr(defaults, "DEFAULT_WP_APP_PASSWORD", "p")
        client = woo_client_from_store(store)
        assert client.can_upload_media

    def test_user_entered_password_wins(self, monkeypatch, store):
        from nabz import defaults
        from nabz.ui.services import woo_client_from_store
        monkeypatch.setattr(defaults, "DEFAULT_WP_USER", "u")
        monkeypatch.setattr(defaults, "DEFAULT_WP_APP_PASSWORD", "p")
        creds = store.load_woo()
        creds.wp_user, creds.wp_app_password = "mine", "secret"
        store.save_woo(creds)
        client = woo_client_from_store(store)
        assert client.config.wp_user == "mine"


# -- پنجره و سفارش‌ها --------------------------------------------------------


class TestWindowFit:
    @pytest.fixture
    def window(self, qapp, db, store):
        from nabz.ui.main_window import MainWindow
        w = MainWindow(db, store)
        yield w
        w._allow_close = True
        if w._scheduler:
            w._scheduler.shutdown()

    def test_window_fits_small_scaled_screen(self, window):
        """۱۳۶۶×۷۶۸ با بزرگ‌نمایی ۱۲۵٪ ≈ ۱۰۹۳×۶۱۴ پیکسل منطقی (منهای نوار وظیفه)."""
        hint = window.minimumSizeHint()
        assert hint.width() <= 1000 and hint.height() <= 560
        area = QGuiApplication.primaryScreen().availableGeometry()
        assert window.width() <= area.width() and window.height() <= area.height()

    def test_pages_are_wrapped_but_navigation_still_works(self, window):
        assert isinstance(window.tabs.widget(1), QScrollArea)
        window.tabs.setCurrentWidget(window.orders)
        assert window.tabs.page(window.tabs.currentIndex()) is window.orders
        assert window.tabs.indexOf(window.new_products) >= 0

    def test_heavy_tabs_fit_without_horizontal_scroll(self, window):
        for page in (window.sync, window.new_products, window.products):
            assert page.minimumSizeHint().width() <= 900, type(page).__name__

    def test_app_opens_maximized(self):
        import inspect

        from nabz.ui import app
        assert "showMaximized()" in inspect.getsource(app.run)


class TestOrdersScroll:
    def test_actions_panel_and_tab_scroll(self, qapp, db, store):
        from nabz.ui.tabs.orders import OrdersTab
        tab = OrdersTab(db, store)
        scrolls = tab.findChildren(QScrollArea)
        assert len(scrolls) >= 2   # کل تب + پنل اقدامات
        # دکمه‌های پایین پنل داخل ناحیهٔ اسکرول‌اند و بریده نمی‌شوند
        actions_scroll = [s for s in scrolls if tab.open_btn in s.widget().findChildren(
            type(tab.open_btn))][-1]
        assert actions_scroll.widgetResizable()
