"""پنجرهٔ اصلی با تب‌ها."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import CredentialStore
from ..db import Database
from ..scheduler import ScheduleConfig, SyncScheduler
from .assets import logo_pixmap
from .tabs.dashboard import DashboardTab
from .tabs.help import HelpTab
from .tabs.settings import SettingsTab
from .tabs.support import SupportTab
from .tray import app_icon


class PageTabs(QTabWidget):
    """تب‌هایی که هر صفحه را در یک ناحیهٔ اسکرول «فقط در صورت نیاز» می‌پیچند.

    اگر صفحه‌نمایش کارفرما باریک باشد (مثلاً لپ‌تاپ ۱۳۶۶ پیکسلی با بزرگ‌نمایی
    ۱۲۵٪ ویندوز)، به‌جای اینکه حداقل عرض تب‌ها پنجره را از لبهٔ صفحه بیرون
    بزند، داخل همان تب اسکرول ظاهر می‌شود. ``setCurrentWidget``/``indexOf``
    همچنان با خودِ صفحه (نه پوشش) کار می‌کنند.
    """

    def addTab(self, page, *args):  # noqa: N802 - امضای Qt
        scroll = QScrollArea()
        scroll.setObjectName("PageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        return super().addTab(scroll, *args)

    def page(self, index: int):
        wrapper = self.widget(index)
        return wrapper.widget() if isinstance(wrapper, QScrollArea) else wrapper

    def indexOf(self, page):  # noqa: N802
        for i in range(self.count()):
            if self.page(i) is page or self.widget(i) is page:
                return i
        return -1

    def setCurrentWidget(self, page):  # noqa: N802
        index = self.indexOf(page)
        if index >= 0:
            self.setCurrentIndex(index)


class AutoSyncWorker(QObject):
    """اجرای سینک خودکار روی نخ جدا (برای tray و زمان‌بند).

    توجه: این worker فقط بخشِ شبکه‌ای/دیتابیسی (خواندن محصولات، مقایسه،
    اعمال) را روی نخ جدا انجام می‌دهد. دانلود مرورگری ایساکو باید پیش از
    آن، روی نخ اصلی Qt انجام شده باشد (به :func:`try_auto_download_isaco`
    و ``MainWindow._run_scheduled_sync`` نگاه کنید) چون ``QWebEngineView``
    فقط در نخ رابط کاربری قابل استفاده است.
    """

    done = Signal(object)

    def __init__(self, db: Database, store: CredentialStore, mode: str = "auto",
                 update_price: bool | None = None, update_stock: bool | None = None):
        super().__init__()
        self.db = db
        self.store = store
        self.mode = mode
        self.update_price = update_price
        self.update_stock = update_stock

    def run(self) -> None:
        from ..jobs import AutoSyncResult, run_auto_sync
        try:
            result = run_auto_sync(
                self.db, self.store, mode=self.mode,
                update_price=self.update_price, update_stock=self.update_stock,
            )
        except Exception as exc:  # noqa: BLE001 - نخ نباید بی‌صدا بمیرد
            result = AutoSyncResult(False, str(exc))
        self.done.emit(result)


class MainWindow(QMainWindow):
    #: از نخ زمان‌بند (APScheduler) امن است چون با QueuedConnection وصل
    #: می‌شود؛ صدور آن همیشه اجرای واقعی را به نخ اصلی Qt موکول می‌کند.
    #: آرگومان: ``ScheduleEntry`` همان ساعت (یا None برای تنظیمات پیش‌فرض).
    auto_sync_requested = Signal(object)

    def __init__(self, db: Database, store: CredentialStore):
        super().__init__()
        self.db = db
        self.store = store
        self.setWindowTitle("تکسایدک نبض")
        self.setWindowIcon(app_icon())
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._fit_to_screen()
        self._scheduler: SyncScheduler | None = None
        self._sync_thread = self._sync_worker = None
        self._allow_close = False
        self._build()
        self._setup_tray()
        fixed_times = self._migrate_schedule_times()
        self._setup_scheduler()
        if fixed_times:
            from PySide6.QtCore import QTimer
            self.schedule._load()      # تب پیش از اصلاح ساخته شده بود
            QTimer.singleShot(1500, lambda: self._announce_schedule_fix(fixed_times))

    def _fit_to_screen(self) -> None:
        """اندازهٔ حالت «غیرتمام‌صفحه» داخل محدودهٔ قابل‌استفادهٔ صفحه؛ خود
        پنجره در :func:`app.run` تمام‌صفحه (Maximized) باز می‌شود."""
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 800)
            return
        area = screen.availableGeometry()
        width = min(1280, int(area.width() * 0.92))
        height = min(800, int(area.height() * 0.9))
        self.resize(width, height)
        self.move(area.x() + (area.width() - width) // 2,
                  area.y() + (area.height() - height) // 2)

    def _build(self) -> None:
        self.tabs = PageTabs()
        self.tabs.setDocumentMode(True)

        self.dashboard = DashboardTab(self.db)
        self.settings = SettingsTab(self.db, self.store)

        # تب‌های اصلی (با شکلک برای خوانایی بهتر)
        self.tabs.addTab(self.dashboard, "🏠  داشبورد")
        self._add_lazy_sync_tab()
        self._add_lazy_new_products_tab()
        self._add_lazy_products_tab()
        self._add_lazy_orders_tab()
        self._add_lazy_excel_tab()
        self._add_lazy_schedule_tab()
        self._add_lazy_reports_tab()
        self.tabs.addTab(self.settings, "⚙️  تنظیمات")
        self.tabs.addTab(HelpTab(), "❓  راهنما")
        self.tabs.addTab(SupportTab(), "📞  پشتیبانی")
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.new_products.refresh_banner()

        # هدر برند بالای پنجره
        root = QWidget()
        root.setObjectName("Root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_header())
        root_layout.addWidget(self.tabs, 1)

        self.setCentralWidget(root)
        self.statusBar().showMessage("آماده")

        # اتصال دکمه‌های داشبورد
        self.dashboard.sync_requested.connect(self._go_to_sync)
        self.dashboard.rollback_requested.connect(self._rollback)
        self.dashboard.new_products_requested.connect(
            lambda: self.tabs.setCurrentWidget(self.new_products))
        self.dashboard.orders_requested.connect(self._go_to_orders)
        self.settings.settings_changed.connect(self._on_settings_changed)

        # QueuedConnection عمداً: صدور این سیگنال از هر نخی (از جمله نخ
        # APScheduler) فقط یک رویداد در صف نخ اصلی می‌گذارد و بلافاصله
        # برمی‌گردد — نه اجرای مستقیم و مسدودکننده. این هم اجرای امنِ
        # QWebEngineView را تضمین می‌کند و هم جلوی هنگ کردن راه‌اندازی
        # برنامه هنگام «جبران اجرای ازدست‌رفته» را می‌گیرد.
        self.auto_sync_requested.connect(
            self._run_scheduled_sync, Qt.ConnectionType.QueuedConnection
        )

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 8, 20, 8)

        logo = QLabel()
        pix = logo_pixmap(height=40)
        if not pix.isNull():
            logo.setPixmap(pix)
        else:
            name = QLabel("تکسایدک نبض")
            name.setObjectName("BrandName")
            layout.addWidget(name)
        layout.addWidget(logo)
        layout.addStretch(1)

        sub = QLabel("مدیریت فروشگاه: قیمت، موجودی، محصولات و سفارش‌ها")
        sub.setObjectName("Muted")
        layout.addWidget(sub)
        return header

    # -- تب‌هایی که هنگام نیاز ساخته می‌شوند (تا وارد کردن سنگین به تأخیر بیفتد) --

    def _add_lazy_sync_tab(self) -> None:
        from .tabs.sync import SyncTab
        self.sync = SyncTab(self.db, self.store)
        self.sync.finished_apply.connect(self.dashboard.refresh)
        self.sync.new_products_found.connect(self._on_new_products_found)
        self.tabs.addTab(self.sync, "🔄  سینک ایساکو")

    NEW_PRODUCTS_TITLE = "🆕  محصولات جدید حاسب"

    def _add_lazy_new_products_tab(self) -> None:
        from .tabs.new_products import NewProductsTab
        self.new_products = NewProductsTab(self.db, self.store)
        self.new_products.badge_changed.connect(self._set_new_products_badge)
        self.tabs.addTab(self.new_products, self.NEW_PRODUCTS_TITLE)

    def _add_lazy_orders_tab(self) -> None:
        from .tabs.orders import OrdersTab
        self.orders = OrdersTab(self.db, self.store)
        self.tabs.addTab(self.orders, "🧾  سفارش‌ها")

    def _add_lazy_excel_tab(self) -> None:
        from .tabs.excel_import import ExcelImportTab
        self.tabs.addTab(ExcelImportTab(self.db, self.store), "📥  ایمپورت اکسل")

    def _add_lazy_products_tab(self) -> None:
        from .tabs.products import ProductsTab
        self.products = ProductsTab(self.db, self.store)
        self.products.changed.connect(self.dashboard.refresh)
        self.tabs.addTab(self.products, "🛒  محصولات سایت")

    def _add_lazy_schedule_tab(self) -> None:
        from .tabs.schedule import ScheduleTab
        self.schedule = ScheduleTab(self.db)
        self.schedule.schedule_changed.connect(self._apply_schedule)
        self.schedule.run_now_requested.connect(self._run_schedule_test)
        self.tabs.addTab(self.schedule, "⏰  زمان‌بندی")

    def _add_lazy_reports_tab(self) -> None:
        from .tabs.reports import ReportsTab
        self.reports = ReportsTab(self.db)
        self.tabs.addTab(self.reports, "📊  گزارش‌ها")

    # -- اقدامات --------------------------------------------------------

    def _go_to_sync(self) -> None:
        self.tabs.setCurrentWidget(self.sync)

    def _go_to_orders(self) -> None:
        self.tabs.setCurrentWidget(self.orders)
        if not self.orders._orders:
            self.orders.load()

    def _rollback(self) -> None:
        run_id = self.db.last_applied_run()
        if run_id is None:
            QMessageBox.information(self, "بازگردانی", "اجرایی برای بازگرداندن نیست.")
            return
        confirm = QMessageBox.question(
            self, "بازگرداندن",
            "آیا مطمئن هستید که می‌خواهید آخرین به‌روزرسانی را به حالت قبل برگردانید؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.sync.do_rollback(run_id)
        self.dashboard.refresh()

    def _on_settings_changed(self) -> None:
        self.statusBar().showMessage("تنظیمات ذخیره شد", 3000)

    # -- اعلان محصولات جدید حاسب ------------------------------------------

    def _set_new_products_badge(self, count: int) -> None:
        self.dashboard.refresh()
        index = self.tabs.indexOf(self.new_products)
        if index < 0:
            return
        title = self.NEW_PRODUCTS_TITLE
        if count:
            title += f"  ({str(count).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))})"
        self.tabs.setTabText(index, title)
        self.tabs.tabBar().setTabTextColor(
            index, QColor("#e65100") if count else QColor())

    def _on_new_products_found(self, count: int) -> None:
        """پس از سینک کامل: کالای جدیدی در حاسب هست که روی سایت نیست."""
        self.new_products.refresh_banner()
        fa_count = str(count).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
        message = (f"{fa_count} کالای جدید در حاسب موجود است که روی سایت نیست. "
                   "برای بررسی و ارسال به سایت به تب «محصولات جدید حاسب» بروید.")
        if self.tray:
            self.tray.showMessage("محصول جدید در حاسب", message, app_icon(), 8000)
        if self.isVisible():
            # غیرمودال: اگر سینک شبانه بود و کسی پشت سیستم نیست، چیزی قفل نمی‌شود
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("محصول جدید در حاسب")
            box.setText(message + "\n\nهمین حالا باز شود؟")
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

            def answered(button) -> None:
                if box.standardButton(button) == QMessageBox.StandardButton.Yes:
                    self.tabs.setCurrentWidget(self.new_products)
                    self.new_products.compare()

            box.buttonClicked.connect(answered)
            box.open()

    # -- System Tray ---------------------------------------------------

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("تکسایدک نبض")

        menu = QMenu()
        open_action = menu.addAction("باز کردن برنامه")
        open_action.triggered.connect(self._restore_from_tray)
        sync_action = menu.addAction("سینک فوری")
        # lambda عمداً: QAction.triggered آرگومان bool می‌فرستد که با
        # پارامتر mode تداخل می‌کند
        sync_action.triggered.connect(lambda: self.run_auto_sync_async(mode="manual"))
        menu.addSeparator()
        quit_action = menu.addAction("خروج کامل")
        quit_action.triggered.connect(self._quit_app)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def _quit_app(self) -> None:
        self._allow_close = True
        if self._scheduler:
            self._scheduler.shutdown()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    def closeEvent(self, event) -> None:
        """بستن پنجره به‌جای خروج، برنامه را در tray کوچک می‌کند."""
        if self._allow_close or self.tray is None:
            if self._scheduler:
                self._scheduler.shutdown()
            event.accept()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "تکسایدک نبض",
            "برنامه در پس‌زمینه فعال است. برای اجرای خودکار باز بماند.",
            app_icon(),
            3000,
        )

    # -- زمان‌بند -------------------------------------------------------

    #: هر چند میلی‌ثانیه زمان‌بند بررسی شود
    SCHEDULE_TICK_MS = 20_000

    SCHEDULE_FIX_KEY = "schedule_rtl_fix_v1"

    def _migrate_schedule_times(self) -> list[tuple[str, str]]:
        """یک‌بار: ساعت‌هایی که با اشکال نمایشی کادر ساعت جابه‌جا ذخیره شده‌اند.

        :returns: فهرست ``(قبل، بعد)`` برای ساعت‌هایی که اصلاح شدند.
        """
        from ..scheduler import fix_rtl_swapped_entries

        if self.db.get_setting(self.SCHEDULE_FIX_KEY, False):
            return []
        self.db.set_setting(self.SCHEDULE_FIX_KEY, True)
        has_saved = (self.db.get_setting("schedule_entries", None) is not None
                     or self.db.get_setting("schedule_time", None) is not None)
        if not has_saved:
            return []
        config = ScheduleConfig.from_settings(self.db.get_setting)
        fixed, changed = fix_rtl_swapped_entries(config.entries)
        if not changed:
            return []
        pairs = [(old.hhmm, new.hhmm) for old, new in zip(config.entries, fixed)
                 if old.hhmm != new.hhmm]
        fixed_cfg = ScheduleConfig(enabled=config.enabled, entries=fixed)
        self.db.set_setting("schedule_entries", [e.to_dict() for e in fixed_cfg.entries])
        if fixed_cfg.entries:
            self.db.set_setting("schedule_time", fixed_cfg.entries[0].hhmm)
        # نوبت‌های ثبت‌شدهٔ امروز با ساعت‌های غلط، مانع اجرای درست نشوند
        self.db.set_setting("schedule_last_slot", None)
        text = "، ".join(f"{a} → {b}" for a, b in pairs)
        self.db.log("warn", f"زمان‌بندی: ساعت‌های جابه‌جا ذخیره‌شده اصلاح شد: {text}")
        import logging
        logging.getLogger("nabz.schedule").warning("اصلاح ساعت‌های جابه‌جا: %s", text)
        return pairs

    def _announce_schedule_fix(self, pairs: list[tuple[str, str]]) -> None:
        from .. import jalali

        lines = "\n".join(
            f"   {jalali.fa_digits(a)}  ←  حالا درست: {jalali.fa_digits(b)}" for a, b in pairs)
        QMessageBox.information(
            self, "اصلاح ساعت‌های زمان‌بندی",
            "در نسخه‌های قبل، کادر ساعت در تب «زمان‌بندی» ساعت و دقیقه را جابه‌جا "
            "نشان می‌داد؛ مثلاً «۰۸:۰۰» دیده می‌شد ولی ۸ دقیقه بعد از نیمه‌شب "
            "ذخیره می‌شد. برای همین اجراها همه نزدیک نیمه‌شب انجام می‌شدند.\n\n"
            "ساعت‌ها خودکار به همان چیزی که دیده بودید اصلاح شد:\n"
            f"{lines}\n\n"
            "لطفاً یک بار تب «زمان‌بندی» را ببینید و اگر لازم بود تغییر دهید.")

    def _setup_scheduler(self) -> None:
        import logging

        from PySide6.QtCore import QTimer

        from ..sync_gate import gate

        sched_log = logging.getLogger("nabz.schedule")
        self._scheduler = SyncScheduler(
            job=self._scheduled_job,
            last_run_getter=self._last_successful_run_time,
            slot_getter=lambda: self.db.get_setting("schedule_last_slot", None),
            slot_setter=lambda slot: self.db.set_setting("schedule_last_slot", slot),
            is_busy=lambda: gate.busy,
            log=lambda msg: (sched_log.info(msg), self.db.log("info", f"زمان‌بندی: {msg}")),
        )
        # تایمر روی نخ اصلی؛ بعد از خواب/خاموشی سیستم هم در اولین تیک جبران می‌شود
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(self.SCHEDULE_TICK_MS)
        self._schedule_timer.timeout.connect(self._schedule_tick)
        self._schedule_timer.start()
        self._apply_schedule()

    def _schedule_tick(self) -> None:
        if self._scheduler is not None:
            try:
                self._scheduler.tick()
            except Exception:  # noqa: BLE001 - تایمر نباید بمیرد
                import logging
                logging.getLogger("nabz.schedule").exception("خطا در تیک زمان‌بند")

    def _apply_schedule(self) -> None:
        if self._scheduler is None:
            return
        config = ScheduleConfig.from_settings(self.db.get_setting)
        self._scheduler.apply_config(config)
        if config.enabled and config.active_entries:
            times = "، ".join(e.hhmm for e in config.active_entries)
            fa_times = times.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
            self.statusBar().showMessage(f"زمان‌بندی فعال: هر روز ساعت {fa_times}", 5000)

    def _last_successful_run_time(self) -> _dt.datetime | None:
        """پایان آخرین سینک خودکارِ موفق (اعمال تکی، ساخت محصول و … حساب نیست)."""
        for run in self.db.recent_runs(limit=50):
            if (run.get("mode") == "auto" and run["status"] == "done"
                    and run.get("finished_at")):
                return _dt.datetime.fromtimestamp(run["finished_at"])
        return None

    def _scheduled_job(self, entry=None) -> None:
        """توسط زمان‌بند صدا زده می‌شود.

        هرگز مستقیم کار سنگین نمی‌کند؛ فقط سیگنال را صادر می‌کند تا با
        QueuedConnection (از هر نخی که باشد) روی نخ اصلی Qt و بیرون از
        تیک تایمر اجرا شود — جایی که QWebEngineView مجاز است.
        """
        self.auto_sync_requested.emit(entry)

    def _run_scheduled_sync(self, entry=None) -> None:
        """روی نخ اصلی اجرا می‌شود: دانلود خودکار ایساکو + سینک کامل."""
        if entry is None:
            self.run_auto_sync_async(mode="auto")
        else:
            self.run_auto_sync_async(
                mode="auto", update_price=entry.price, update_stock=entry.stock)

    def _run_schedule_test(self) -> None:
        """دکمهٔ «تست همین حالا» در تب زمان‌بندی — همان مسیر واقعیِ سینکِ
        خودکار را اجرا می‌کند تا کاربر مطمئن شود زمان‌بندی درست کار می‌کند."""
        self.statusBar().showMessage("در حال اجرای آزمایشیِ سینک خودکار ...")
        self._run_scheduled_sync()

    def run_auto_sync_async(self, mode: str = "manual", *,
                            update_price: bool | None = None,
                            update_stock: bool | None = None) -> None:
        """سینک فوری (از منوی tray یا آزمایش زمان‌بندی).

        ابتدا دانلود خودکار ایساکو را روی همینْ نخ اصلی انجام می‌دهد
        (الزامی برای QWebEngineView)، سپس بخش شبکه‌ای/اعمال را به نخ جدا
        می‌سپارد تا رابط کاربری در طول آن (کوتاه) قفل نشود.
        """
        from ..jobs import try_auto_download_isaco
        from ..sync_gate import gate

        # قفل از همین ابتدا (پیش از دانلود): دانلود حلقهٔ رویداد تودرتو دارد و
        # بدون قفل، درخواست‌های دیگر وسط آن دانلود/سینک دوم را شروع می‌کردند.
        owner = f"سینک {'خودکار' if mode == 'auto' else 'دستی'}"
        if not gate.try_acquire(owner):
            self.statusBar().showMessage(
                f"«{gate.owner}» در حال اجراست؛ این درخواست اجرا نشد.", 6000)
            return
        try:
            if update_price is None:
                update_price = bool(self.db.get_setting("schedule_price", True))
            if update_price:
                # دانلود لیست قیمت فقط وقتی لازم است که قیمت هم سینک شود
                self.statusBar().showMessage("در حال دانلود لیست قیمت ایساکو ...")
                try_auto_download_isaco(
                    self.db, self.store, on_progress=self.statusBar().showMessage
                )

            worker = AutoSyncWorker(self.db, self.store, mode=mode,
                                    update_price=update_price, update_stock=update_stock)
            from .workers import start_worker
            self._sync_worker = worker
            self._sync_thread = start_worker(
                self, worker, on_done=self._on_auto_sync_done,
                on_progress=self.statusBar().showMessage,
                on_finished=lambda: self._clear_sync_thread(owner))
        except Exception:
            gate.release(owner)
            raise

    def _clear_sync_thread(self, owner: str | None = None) -> None:
        from ..sync_gate import gate

        self._sync_thread = self._sync_worker = None
        gate.release(owner)

    def _on_auto_sync_done(self, result) -> None:
        self.dashboard.refresh()
        if hasattr(self, "reports"):
            self.reports.refresh()
        self.statusBar().showMessage(
            result.message if result.ok else f"خطا: {result.message}", 8000
        )
        if self.tray:
            self.tray.showMessage(
                "سینک", result.message if result.ok else f"خطا: {result.message}",
                app_icon(), 4000,
            )
        if getattr(result, "newly_missing", 0):
            self._on_new_products_found(result.newly_missing)
        else:
            self.new_products.refresh_banner()


def default_db_path() -> Path:
    """مسیر فایل دیتابیس در پوشهٔ دادهٔ کاربر."""
    base = Path.home() / ".texayadak-nabz"
    return base / "nabz.db"
