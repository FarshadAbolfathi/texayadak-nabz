"""اجرای کارهای شبکه‌ای در پس‌زمینه بدون قفل شدن رابط کاربری.

⚠️ نکتهٔ حیاتی PySide6: اگر سیگنالِ شیئی که روی نخ دیگری است به یک
``lambda`` یا تابع داخلی (نه متدِ یک QObject) وصل شود، آن تابع روی **همان
نخ پس‌زمینه** اجرا می‌شود. دست زدن به ویجت از نخ پس‌زمینه برنامه را بی‌صدا
و بدون هیچ لاگی کرش می‌کند. برای همین نتیجه همیشه از راه یک «رله» که روی
نخ اصلی زندگی می‌کند و با ``QueuedConnection`` به متدِ خودش وصل است تحویل
داده می‌شود؛ هر نوع callback (lambda، تابع داخلی، متد) امن است.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

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


class MainThreadRelay(QObject):
    """callbackها را روی نخی که رله در آن ساخته شده (نخ اصلی) اجرا می‌کند."""

    def __init__(self, on_done=None, on_failed=None, on_progress=None):
        super().__init__()
        self._on_done = on_done
        self._on_failed = on_failed
        self._on_progress = on_progress

    def attach(self, worker: QObject) -> None:
        queued = Qt.ConnectionType.QueuedConnection
        if hasattr(worker, "done"):
            worker.done.connect(self.deliver_done, queued)
        if hasattr(worker, "failed"):
            worker.failed.connect(self.deliver_failed, queued)
        if hasattr(worker, "progress"):
            worker.progress.connect(self.deliver_progress, queued)

    @Slot(object)
    def deliver_done(self, result) -> None:
        self._call(self._on_done, result)

    @Slot()
    def deliver_signal(self) -> None:
        """برای سیگنال‌های بی‌آرگومان (مثل QThread.finished)."""
        self._call(self._on_done, None)

    @Slot(str)
    def deliver_failed(self, message: str) -> None:
        self._call(self._on_failed, message)

    @Slot(str)
    def deliver_progress(self, message: str) -> None:
        self._call(self._on_progress, message)

    @staticmethod
    def _call(callback, value) -> None:
        if callback is None:
            return
        try:
            callback(value)
        except RuntimeError as exc:
            # ویجتِ مقصد در این فاصله بسته شده («already deleted»)
            _log.warning("نتیجهٔ کار پس‌زمینه تحویل نشد: %s", exc)
        except Exception:  # noqa: BLE001 - خطای رابط نباید برنامه را ببندد
            _log.exception("خطا در پردازش نتیجهٔ کار پس‌زمینه")


def start_worker(
    owner: QObject,
    worker: QObject,
    *,
    on_done: Callable[[Any], None] | None = None,
    on_failed: Callable[[str], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    on_finished: Callable[[], None] | None = None,
) -> QThread:
    """``worker.run`` را روی یک QThread اجرا و callbackها را امن روی نخ اصلی
    تحویل می‌دهد. نخ، worker و رله تا پایان کامل نخ روی ``owner`` نگه داشته
    می‌شوند تا هیچ‌کدام زودتر از موعد پاک نشوند (پاک شدن QThread در حال
    اجرا هم برنامه را کرش می‌دهد).
    """
    relay = MainThreadRelay(on_done, on_failed, on_progress)
    relay.attach(worker)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    for name in ("done", "failed"):
        if hasattr(worker, name):
            getattr(worker, name).connect(thread.quit)

    jobs: list = owner.__dict__.setdefault("_async_jobs", [])
    entry: tuple = ()

    def cleanup(_=None) -> None:
        # روی نخ اصلی اجرا می‌شود؛ صبر تا نخ واقعاً تمام شود، بعد رها کردن
        # ارجاع‌ها (رها کردن QThreadِ در حال اجرا = کرش)
        thread.wait(5000)
        try:
            jobs.remove(entry)
        except ValueError:
            pass
        if on_finished:
            try:
                on_finished()
            except Exception:  # noqa: BLE001
                _log.exception("خطا پس از پایان کار پس‌زمینه")

    # QThread.finished از خودِ نخ پس‌زمینه صادر می‌شود → با رله به نخ اصلی
    finished = MainThreadRelay(on_done=cleanup)
    thread.finished.connect(finished.deliver_signal, Qt.ConnectionType.QueuedConnection)
    entry = (thread, worker, relay, finished)
    jobs.append(entry)
    thread.start()
    return thread


def run_async(
    owner: QObject,
    func: Callable[..., Any],
    *args,
    on_done: Callable[[Any], None] | None = None,
    on_failed: Callable[[str], None] | None = None,
    **kwargs,
) -> FuncWorker:
    """``func`` را در پس‌زمینه اجرا می‌کند و نتیجه را روی نخ اصلی برمی‌گرداند."""
    worker = FuncWorker(func, *args, **kwargs)
    start_worker(owner, worker, on_done=on_done, on_failed=on_failed)
    return worker
