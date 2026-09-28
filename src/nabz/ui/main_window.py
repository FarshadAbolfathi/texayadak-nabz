"""پنجرهٔ اصلی با تب‌ها."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
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


class AutoSyncWorker(QObject):
    """اجرای سینک خودکار روی نخ جدا (برای tray و زمان‌بند).

    توجه: این worker فقط بخشِ شبکه‌ای/دیتابیسی (خواندن محصولات، مقایسه،
    اعمال) را روی نخ جدا انجام می‌دهد. دانلود مرورگری ایساکو باید پیش از
    آن، روی نخ اصلی Qt انجام شده باشد (به :func:`try_auto_download_isaco`
    و ``MainWindow._run_scheduled_sync`` نگاه کنید) چون ``QWebEngineView``
    فقط در نخ رابط کاربری قابل استفاده است.
    """

    done = Signal(object)

    def __init__(self, db: Database, store: CredentialStore, mode: str = "auto"):
        super().__init__()
        self.db = db
        self.store = store
        self.mode = mode

    def run(self) -> None:
        from ..jobs import run_auto_sync
        result = run_auto_sync(self.db, self.store, mode=self.mode)
        self.done.emit(result)


class MainWindow(QMainWindow):
    #: از نخ زمان‌بند (APScheduler) امن است چون با QueuedConnection وصل
    #: می‌شود؛ صدور آن همیشه اجرای واقعی را به نخ اصلی Qt موکول می‌کند.
    auto_sync_requested = Signal()

    def __init__(self, db: Database, store: CredentialStore):
        super().__init__()
        self.db = db
        self.store = store
        self.setWindowTitle("تکسایدک نبض")
        self.setWindowIcon(app_icon())
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1100, 720)
        self._scheduler: SyncScheduler | None = None
        self._allow_close = False
        self._build()
        self._setup_tray()
        self._setup_scheduler()

    def _build(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.dashboard = DashboardTab(self.db)
        self.settings = SettingsTab(self.db, self.store)

        # تب‌های اصلی (با شکلک برای خوانایی بهتر)
        self.tabs.addTab(self.dashboard, "🏠  داشبورد")
        self._add_lazy_sync_tab()
        self._add_lazy_excel_tab()
        self._add_lazy_products_tab()
        self.tabs.addTab(self.settings, "⚙️  تنظیمات")
        self._add_lazy_schedule_tab()
        self._add_lazy_reports_tab()
        self.tabs.addTab(HelpTab(), "❓  راهنما")
        self.tabs.addTab(SupportTab(), "📞  پشتیبانی")

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

        sub = QLabel("همگام‌سازی قیمت و موجودی")
        sub.setObjectName("Muted")
        layout.addWidget(sub)
        return header

    # -- تب‌هایی که هنگام نیاز ساخته می‌شوند (تا وارد کردن سنگین به تأخیر بیفتد) --

    def _add_lazy_sync_tab(self) -> None:
        from .tabs.sync import SyncTab
        self.sync = SyncTab(self.db, self.store)
        self.sync.finished_apply.connect(self.dashboard.refresh)
        self.tabs.addTab(self.sync, "🔄  سینک ایساکو")

    def _add_lazy_excel_tab(self) -> None:
        from .tabs.excel_import import ExcelImportTab
        self.tabs.addTab(ExcelImportTab(self.db, self.store), "📥  ایمپورت اکسل")

    def _add_lazy_products_tab(self) -> None:
        from .tabs.products import ProductsTab
        self.tabs.addTab(ProductsTab(self.db, self.store), "🛒  محصولات سایت")

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
        self.showNormal()
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

    def _setup_scheduler(self) -> None:
        self._scheduler = SyncScheduler(
            job=self._scheduled_job,
            last_run_getter=self._last_successful_run_time,
        )
        self._apply_schedule()

    def _apply_schedule(self) -> None:
        if self._scheduler is None:
            return
        config = ScheduleConfig.from_hhmm(
            bool(self.db.get_setting("schedule_enabled", False)),
            self.db.get_setting("schedule_time", "03:00"),
        )
        self._scheduler.apply_config(config)
        if config.enabled:
            self.statusBar().showMessage(
                f"زمان‌بندی فعال: هر روز ساعت {config.hour:02d}:{config.minute:02d}",
                5000,
            )

    def _last_successful_run_time(self) -> _dt.datetime | None:
        for run in self.db.recent_runs(limit=20):
            if run["status"] == "done" and run.get("finished_at"):
                return _dt.datetime.fromtimestamp(run["finished_at"])
        return None

    def _scheduled_job(self) -> None:
        """توسط زمان‌بند صدا زده می‌شود — ممکن است روی نخ APScheduler باشد.

        هرگز مستقیم کار سنگین نمی‌کند؛ فقط سیگنال را صادر می‌کند تا با
        QueuedConnection به نخ اصلی Qt منتقل شود (جایی که QWebEngineView
        برای دانلود خودکار ایساکو مجاز است).
        """
        self.auto_sync_requested.emit()

    def _run_scheduled_sync(self) -> None:
        """روی نخ اصلی اجرا می‌شود: دانلود خودکار ایساکو + سینک کامل."""
        self.run_auto_sync_async(mode="auto")

    def _run_schedule_test(self) -> None:
        """دکمهٔ «تست همین حالا» در تب زمان‌بندی — همان مسیر واقعیِ سینکِ
        خودکار را اجرا می‌کند تا کاربر مطمئن شود زمان‌بندی درست کار می‌کند."""
        self.statusBar().showMessage("در حال اجرای آزمایشیِ سینک خودکار ...")
        self._run_scheduled_sync()

    def run_auto_sync_async(self, mode: str = "manual") -> None:
        """سینک فوری (از منوی tray یا آزمایش زمان‌بندی).

        ابتدا دانلود خودکار ایساکو را روی همینْ نخ اصلی انجام می‌دهد
        (الزامی برای QWebEngineView)، سپس بخش شبکه‌ای/اعمال را به نخ جدا
        می‌سپارد تا رابط کاربری در طول آن (کوتاه) قفل نشود.
        """
        from ..jobs import try_auto_download_isaco

        self.statusBar().showMessage("در حال دانلود لیست قیمت ایساکو ...")
        try_auto_download_isaco(
            self.db, self.store, on_progress=self.statusBar().showMessage
        )

        worker = AutoSyncWorker(self.db, self.store, mode=mode)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_auto_sync_done)
        worker.done.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._sync_thread, self._sync_worker = thread, worker
        thread.start()

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


def default_db_path() -> Path:
    """مسیر فایل دیتابیس در پوشهٔ دادهٔ کاربر."""
    base = Path.home() / ".texayadak-nabz"
    return base / "nabz.db"
