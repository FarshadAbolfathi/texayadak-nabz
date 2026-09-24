"""تست منطق زمان‌بندی — مخصوصاً جبران اجرای از دست رفته."""

import datetime as dt

import pytest

from nabz.scheduler import (
    ScheduleConfig,
    SyncScheduler,
    next_run_at,
    should_catch_up,
)


class TestNextRunAt:
    def test_later_today(self):
        now = dt.datetime(2026, 1, 1, 2, 0)
        assert next_run_at(now, 3, 0) == dt.datetime(2026, 1, 1, 3, 0)

    def test_tomorrow_when_passed(self):
        now = dt.datetime(2026, 1, 1, 10, 0)
        assert next_run_at(now, 3, 0) == dt.datetime(2026, 1, 2, 3, 0)

    def test_exactly_now_goes_tomorrow(self):
        now = dt.datetime(2026, 1, 1, 3, 0)
        assert next_run_at(now, 3, 0) == dt.datetime(2026, 1, 2, 3, 0)


class TestShouldCatchUp:
    def test_missed_run_needs_catchup(self):
        now = dt.datetime(2026, 1, 2, 10, 0)   # سیستم صبح روشن شد
        last = dt.datetime(2026, 1, 1, 3, 0)   # آخرین اجرا دیروز
        assert should_catch_up(now, 3, 0, last)

    def test_already_ran_today(self):
        now = dt.datetime(2026, 1, 2, 10, 0)
        last = dt.datetime(2026, 1, 2, 3, 5)   # امروز اجرا شده
        assert not should_catch_up(now, 3, 0, last)

    def test_before_scheduled_time(self):
        now = dt.datetime(2026, 1, 2, 1, 0)    # هنوز ۳ صبح نشده
        last = dt.datetime(2026, 1, 1, 3, 0)
        assert not should_catch_up(now, 3, 0, last)

    def test_never_ran_and_time_passed(self):
        now = dt.datetime(2026, 1, 2, 10, 0)
        assert should_catch_up(now, 3, 0, None)

    def test_never_ran_before_time(self):
        now = dt.datetime(2026, 1, 2, 1, 0)
        assert not should_catch_up(now, 3, 0, None)


class TestScheduleConfig:
    def test_from_hhmm(self):
        cfg = ScheduleConfig.from_hhmm(True, "03:30")
        assert cfg.enabled and cfg.hour == 3 and cfg.minute == 30


class TestSyncScheduler:
    def test_catch_up_runs_job(self):
        calls = []
        last = dt.datetime(2026, 1, 1, 3, 0)
        sched = SyncScheduler(
            job=lambda: calls.append(1),
            last_run_getter=lambda: last,
        )
        sched._config = ScheduleConfig(enabled=True, hour=3, minute=0)
        ran = sched.catch_up_if_needed(now=dt.datetime(2026, 1, 2, 10, 0))
        assert ran
        assert calls == [1]

    def test_no_catchup_when_disabled(self):
        calls = []
        sched = SyncScheduler(
            job=lambda: calls.append(1),
            last_run_getter=lambda: None,
        )
        sched._config = ScheduleConfig(enabled=False, hour=3, minute=0)
        assert not sched.catch_up_if_needed(now=dt.datetime(2026, 1, 2, 10, 0))
        assert calls == []

    def test_no_catchup_when_already_ran(self):
        calls = []
        sched = SyncScheduler(
            job=lambda: calls.append(1),
            last_run_getter=lambda: dt.datetime(2026, 1, 2, 3, 1),
        )
        sched._config = ScheduleConfig(enabled=True, hour=3, minute=0)
        assert not sched.catch_up_if_needed(now=dt.datetime(2026, 1, 2, 10, 0))

    def test_job_error_does_not_propagate(self):
        def boom():
            raise RuntimeError("خطا")
        sched = SyncScheduler(job=boom, last_run_getter=lambda: None)
        sched._config = ScheduleConfig(enabled=True, hour=3, minute=0)
        # نباید استثنا پرتاب شود
        sched.catch_up_if_needed(now=dt.datetime(2026, 1, 2, 10, 0))

    def test_real_scheduler_start_and_stop(self):
        """اطمینان از اینکه APScheduler واقعی راه می‌افتد و می‌ایستد."""
        sched = SyncScheduler(job=lambda: None, last_run_getter=lambda: None)
        sched.apply_config(ScheduleConfig(enabled=True, hour=3, minute=0))
        assert sched.is_running
        sched.shutdown()
        assert not sched.is_running

    def test_disabled_config_does_not_run(self):
        sched = SyncScheduler(job=lambda: None, last_run_getter=lambda: None)
        sched.apply_config(ScheduleConfig(enabled=False))
        # نباید job فعالی داشته باشد
        assert not sched.is_running or len(sched._scheduler.get_jobs()) == 0
        sched.shutdown()
