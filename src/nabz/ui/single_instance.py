"""اجرای تک‌نسخه‌ای برنامه.

در لاگ سیستم کارفرما چند «شروع برنامه» در یک ثانیه دیده شد: با چند بار
کلیک روی آیکون، چند نسخه هم‌زمان باز می‌ماند و هر کدام زمان‌بند خودش را
داشت → سینک‌ها و دانلودهای ایساکو چندبرابر و هم‌زمان روی یک دیتابیس.

حالا نسخهٔ اول یک قفل فایل (QLockFile؛ پس از کرش هم با بررسی PID آزاد
می‌شود) و یک کانال محلی (QLocalServer) می‌گیرد. نسخهٔ بعدی فقط به نسخهٔ
اول پیام «نمایش بده» می‌فرستد و خودش بسته می‌شود.
"""

from __future__ import annotations

import getpass
import logging
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_log = logging.getLogger("nabz")


def _default_lock_path() -> Path:
    from ..logging_setup import LOG_DIR_NAME
    folder = Path.home() / LOG_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "app.lock"


def _default_key() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    safe = "".join(ch for ch in user if ch.isalnum()) or "user"
    return f"texayadak-nabz-{safe}"


class SingleInstance(QObject):
    """``acquire()`` → ``True`` یعنی این نسخهٔ اصلی است و باید اجرا شود."""

    #: نسخهٔ دیگری خواست پنجره نمایش داده شود
    activated = Signal()

    def __init__(self, key: str | None = None, lock_path: Path | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.key = key or _default_key()
        self._lock = QLockFile(str(lock_path or _default_lock_path()))
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        if not self._lock.tryLock(200):
            self._notify_running_instance()
            return False
        QLocalServer.removeServer(self.key)       # کانال جامانده از کرش قبلی
        self._server = QLocalServer(self)
        if not self._server.listen(self.key):
            _log.warning("کانال تک‌نسخه‌ای باز نشد: %s", self._server.errorString())
        self._server.newConnection.connect(self._on_connection)
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._lock.isLocked():
            self._lock.unlock()

    def _notify_running_instance(self) -> None:
        socket = QLocalSocket()
        socket.connectToServer(self.key)
        if socket.waitForConnected(1000):
            socket.write(b"show")
            socket.flush()
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            _log.info("برنامه از قبل باز است؛ همان پنجره نمایش داده شد.")
        else:
            _log.info("برنامه از قبل باز است (کانال پاسخ نداد).")

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.waitForReadyRead(500)
            conn.readAll()
            conn.disconnectFromServer()
            conn.deleteLater()
            self.activated.emit()
