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

    def test_enabled_config_is_running(self):
        sched = SyncScheduler(job=lambda: None, last_run_getter=lambda: None)
        sched.apply_config(ScheduleConfig(enabled=True, hour=23, minute=59))
        assert sched.is_running
        sched.shutdown()

    def test_disabled_config_does_not_run(self):
        calls = []
        sched = SyncScheduler(job=lambda: calls.append(1), last_run_getter=lambda: None)
        sched.apply_config(ScheduleConfig(enabled=False))
        assert not sched.is_running
        assert sched.tick(dt.datetime(2026, 1, 2, 10, 0)) is None
        assert calls == []


class TestMultipleEntries:
    def test_entries_sorted_and_deduplicated(self):
        from nabz.scheduler import ScheduleEntry
        cfg = ScheduleConfig(enabled=True, entries=[
            ScheduleEntry(14, 0), ScheduleEntry(3, 0), ScheduleEntry(14, 0, price=False),
        ])
        assert [e.hhmm for e in cfg.entries] == ["03:00", "14:00"]

    def test_from_settings_migrates_single_time(self):
        store = {"schedule_enabled": True, "schedule_time": "04:30",
                 "schedule_price": False}
        cfg = ScheduleConfig.from_settings(lambda k, d=None: store.get(k, d))
        assert cfg.enabled
        (entry,) = cfg.entries
        assert entry.hhmm == "04:30" and not entry.price and entry.stock

    def test_from_settings_reads_entries(self):
        store = {"schedule_entries": [{"time": "09:00", "stock": False},
                                      {"time": "21:15"}]}
        cfg = ScheduleConfig.from_settings(lambda k, d=None: store.get(k, d))
        assert [e.hhmm for e in cfg.entries] == ["09:00", "21:15"]
        assert cfg.entries[0].price and not cfg.entries[0].stock

    def test_empty_list_stays_empty(self):
        store = {"schedule_entries": [], "schedule_time": "03:00"}
        cfg = ScheduleConfig.from_settings(lambda k, d=None: store.get(k, d))
        assert cfg.entries == ()

    def test_catch_up_passes_latest_missed_entry(self):
        from nabz.scheduler import ScheduleEntry
        got = []
        sched = SyncScheduler(job=lambda entry: got.append(entry),
                              last_run_getter=lambda: dt.datetime(2026, 1, 2, 3, 5))
        sched._config = ScheduleConfig(enabled=True, entries=[
            ScheduleEntry(3, 0), ScheduleEntry(12, 0, price=False),
            ScheduleEntry(18, 0),
        ])
        assert sched.catch_up_if_needed(now=dt.datetime(2026, 1, 2, 13, 0))
        assert got[0].hhmm == "12:00" and not got[0].price

    def test_disabled_entry_is_ignored(self):
        from nabz.scheduler import ScheduleEntry, due_entry
        entries = [ScheduleEntry(3, 0), ScheduleEntry(12, 0, enabled=False)]
        now = dt.datetime(2026, 1, 2, 13, 0)
        assert due_entry(now, entries, dt.datetime(2026, 1, 2, 3, 5)) is None

    def test_each_entry_has_unique_key(self):
        from nabz.scheduler import ScheduleEntry
        assert ScheduleEntry(1, 0).key != ScheduleEntry(9, 30).key


def entries_every_2h():
    from nabz.scheduler import ScheduleEntry
    return [ScheduleEntry(h, 0) for h in range(0, 24, 2)]


def make(calls, store=None, busy=lambda: False, last=lambda: None):
    store = store if store is not None else {}
    sched = SyncScheduler(
        job=lambda entry: calls.append(entry.hhmm),
        last_run_getter=last,
        slot_getter=lambda: store.get("slot"),
        slot_setter=lambda v: store.__setitem__("slot", v),
        is_busy=busy,
    )
    sched._config = ScheduleConfig(enabled=True, entries=entries_every_2h())
    return sched, store


class TestSlotScheduler:
    """بازسازی مشکل کارفرما: زمان‌بندی هر ۲ ساعت، بعضی اجرا نمی‌شد و نیمه‌شب
    ده‌ها اجرای پشت‌سرهم ثبت شد."""

    def test_full_day_runs_every_slot_exactly_once(self):
        calls = []
        sched, _ = make(calls)
        t = dt.datetime(2026, 1, 2, 0, 0, 0)
        while t < dt.datetime(2026, 1, 3, 0, 0, 0):
            sched.tick(t)                   # هر ۲۰ ثانیه، مثل تایمر پنجره
            t += dt.timedelta(seconds=20)
        assert calls == [f"{h:02d}:00" for h in range(0, 24, 2)]

    def test_no_storm_when_ticked_repeatedly(self):
        calls = []
        sched, _ = make(calls)
        for sec in range(0, 1800, 5):       # نیم ساعت تیک پشت‌سرهم بعد از نیمه‌شب
            sched.tick(dt.datetime(2026, 1, 2, 0, 0) + dt.timedelta(seconds=sec))
        assert calls == ["00:00"]

    def test_slot_survives_restart(self):
        calls = []
        sched, store = make(calls)
        sched.tick(dt.datetime(2026, 1, 2, 8, 0, 30))
        again, _ = make(calls, store)        # برنامه دوباره باز شد
        again.tick(dt.datetime(2026, 1, 2, 8, 5))
        assert calls == ["08:00"]

    def test_busy_slot_waits_then_runs_once(self):
        calls = []
        state = {"busy": True}
        sched, _ = make(calls, busy=lambda: state["busy"])
        for m in range(0, 10):
            sched.tick(dt.datetime(2026, 1, 2, 10, m))
        assert calls == []                  # منتظر ماند، از دست نرفت
        state["busy"] = False
        sched.tick(dt.datetime(2026, 1, 2, 10, 11))
        sched.tick(dt.datetime(2026, 1, 2, 10, 12))
        assert calls == ["10:00"]

    def test_after_sleep_only_latest_missed_slot_runs(self):
        calls = []
        sched, store = make(calls)
        store["slot"] = "2026-01-02 06:00"
        sched.tick(dt.datetime(2026, 1, 2, 13, 30))   # سیستم ۶ تا ۱۳:۳۰ خواب بود
        sched.tick(dt.datetime(2026, 1, 2, 13, 31))
        assert calls == ["12:00"]

    def test_next_day_runs_again(self):
        calls = []
        sched, _ = make(calls)
        sched.tick(dt.datetime(2026, 1, 2, 22, 1))
        sched.tick(dt.datetime(2026, 1, 3, 0, 0, 10))
        assert calls == ["22:00", "00:00"]

    def test_auto_run_after_slot_time_satisfies_slot(self):
        calls = []
        sched, store = make(calls, last=lambda: dt.datetime(2026, 1, 2, 8, 3))
        sched.tick(dt.datetime(2026, 1, 2, 8, 10))
        assert calls == [] and store["slot"] == "2026-01-02 08:00"

    def test_failing_job_is_not_retried_in_a_loop(self):
        calls = []

        def boom(entry):
            calls.append(entry.hhmm)
            raise RuntimeError("شبکه")

        store = {}
        sched = SyncScheduler(job=boom, last_run_getter=lambda: None,
                              slot_getter=lambda: store.get("slot"),
                              slot_setter=lambda v: store.__setitem__("slot", v))
        sched._config = ScheduleConfig(enabled=True, entries=entries_every_2h())
        for sec in range(0, 600, 20):
            sched.tick(dt.datetime(2026, 1, 2, 4, 0) + dt.timedelta(seconds=sec))
        assert calls == ["04:00"]

    def test_disabled_entry_is_skipped(self):
        from nabz.scheduler import ScheduleEntry
        calls = []
        sched, _ = make(calls)
        sched._config = ScheduleConfig(enabled=True, entries=[
            ScheduleEntry(8, 0), ScheduleEntry(10, 0, enabled=False)])
        sched.tick(dt.datetime(2026, 1, 2, 10, 30))
        assert calls == ["08:00"]
