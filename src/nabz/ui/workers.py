"""اجرای کارهای شبکه‌ای در پس‌زمینه بدون قفل شدن رابط کاربری."""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

_log = logging.getLogger("nabz.ui")


class FuncWorker(QObject):
    """یک تابع دلخواه را روی نخ جدا اجرا می‌کند."""

    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, func: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            self.done.emit(self._func(*self._args, **self._kwargs))
        except Exception as exc:  # noqa: BLE001
            _log.exception("خطا در کار پس‌زمینه")
            self.failed.emit(str(exc) or exc.__class__.__name__)


def run_async(
    owner: QObject,
    func: Callable[..., Any],
    *args,
    on_done: Callable[[Any], None] | None = None,
    on_failed: Callable[[str], None] | None = None,
    **kwargs,
) -> FuncWorker:
    """``func`` را در پس‌زمینه اجرا می‌کند و نتیجه را روی نخ اصلی برمی‌گرداند.

    مرجع نخ و worker روی ``owner`` نگه داشته می‌شود تا تا پایان کار
    توسط garbage collector پاک نشوند.
    """
    worker = FuncWorker(func, *args, **kwargs)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    if on_done:
        worker.done.connect(on_done)
    if on_failed:
        worker.failed.connect(on_failed)
    worker.done.connect(thread.quit)
    worker.failed.connect(thread.quit)

    jobs: list = owner.__dict__.setdefault("_async_jobs", [])
    jobs.append((thread, worker))

    def cleanup() -> None:
        try:
            jobs.remove((thread, worker))
        except ValueError:
            pass
        thread.deleteLater()

    thread.finished.connect(cleanup)
    thread.start()
    return worker
