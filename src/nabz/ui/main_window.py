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
    """اجرای سینک خودکار روی نخ جدا (برای tray و زمان‌بند)."""

    done = Signal(object)

    def __init__(self, db: Database, store: CredentialStore):
        super().__init__()
        self.db = db
        self.store = store

    def run(self) -> None:
        from ..jobs import run_auto_sync
        result = run_auto_sync(self.db, self.store)
        self.done.emit(result)


class MainWindow(QMainWindow):
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
        sync_action.triggered.connect(self.run_auto_sync_async)
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
        """توسط زمان‌بند صدا زده می‌شود (روی نخ APScheduler)."""
        from ..jobs import run_auto_sync
        result = run_auto_sync(self.db, self.store)
        if self.tray and result.ok:
            self.tray.showMessage("سینک خودکار", result.message, app_icon(), 4000)

    def run_auto_sync_async(self) -> None:
        """سینک فوری از منوی tray، روی نخ جدا."""
        worker = AutoSyncWorker(self.db, self.store)
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
        if self.tray:
            self.tray.showMessage(
                "سینک", result.message if result.ok else f"خطا: {result.message}",
                app_icon(), 4000,
            )


def default_db_path() -> Path:
    """مسیر فایل دیتابیس در پوشهٔ دادهٔ کاربر."""
    base = Path.home() / ".texayadak-nabz"
    return base / "nabz.db"
