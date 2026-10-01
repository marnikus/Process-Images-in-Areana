"""URL List inline edits and batch cooldown reset — real PagePool + real slots."""

import json
import time
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.persistence import cooldown_store
from app.services.job_count import restore_page_stats
from app.services.worker_stats import worker_stats_key
from app.services.tab_reset import clear_time
from app.ui.panels.page_pool import PagePoolMixin

pytestmark = pytest.mark.unit


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class Host(PagePoolMixin):
    """The actual pool-panel slots with counted publish/persistence seams."""

    def __init__(self, pool):
        self._page_pool = pool
        self._batch_future = None
        self.page_pool_updated = Emitter()
        self.logs = []
        self.persist_calls = 0
        self.persist_result = True
        self._log = lambda message, level="info": self.logs.append((level, message))
        self._persist_cooldowns = self._persist

    def _persist(self):
        self.persist_calls += 1
        return self.persist_result


def add_page(pool, tab_id, *, status=PageStatus.STEADY, seconds=0, pending=0,
             jobs=7, image=None, error=None):
    page = PageInfo(tab_id=tab_id, ws_url=f"ws://{tab_id}", title=f"Worker {tab_id}",
                    url=f"https://arena.ai/{tab_id}", is_connected=True,
                    jobs_completed=jobs, pending_penalty=pending)
    pool.add_page(page)
    page.status = status
    page.cooldown_until = time.time() + seconds if seconds else 0
    page.cooldown_total = seconds
    page.current_image = image
    page.current_job_id = f"job-{tab_id}" if image else None
    page.error = error
    return page


def reply_json(raw):
    return json.loads(raw)


def test_global_reset_is_noop_for_zero_rows_and_disabled_state():
    pool = PagePool()
    host = Host(pool)
    result = reply_json(host.reset_all_cooldowns())
    assert result["ok"] is True and result["reset"] == 0
    assert result["persisted"] is True
    assert host.persist_calls == 0
    assert host.page_pool_updated.calls == []


def test_global_reset_one_row_clears_timer_and_recalculates_readiness():
    pool = PagePool()
    page = add_page(pool, "one", status=PageStatus.COOLDOWN, seconds=120, jobs=11,
                    error="leave unrelated error alone")
    host = Host(pool)

    result = reply_json(host.reset_all_cooldowns())

    assert result == {"ok": True, "reset": 1, "reset_tab_ids": ["one"],
                      "failed_tab_ids": [], "deferred_tab_ids": [], "persisted": True}
    assert page.remaining_seconds() == 0 and page.cooldown_total == 0
    assert page.status == PageStatus.STEADY
    assert page.jobs_completed == 11 and page.error == "leave unrelated error alone"
    assert pool.status_snapshot()["free"] == 1
    assert pool.status_snapshot()["cooling"] == 0
    assert host.persist_calls == 1 and len(host.page_pool_updated.calls) == 1


def test_global_reset_many_rows_clears_idle_debt_but_preserves_live_job_debt():
    pool = PagePool()
    timer = add_page(pool, "timer", status=PageStatus.COOLDOWN, seconds=300, jobs=3,
                     error="keep")
    pending = add_page(pool, "pending", pending=45, jobs=5)
    live = add_page(pool, "live", status=PageStatus.BUSY, seconds=20, pending=90,
                    jobs=9, image="running.png", error="keep live error")
    untouched = add_page(pool, "untouched", status=PageStatus.ERROR, jobs=10,
                         error="untouched error")
    host = Host(pool)
    host._batch_future = SimpleNamespace(done=lambda: False)

    result = reply_json(host.reset_all_cooldowns())

    assert result["ok"] is True and result["reset"] == 3
    assert result["reset_tab_ids"] == ["timer", "pending", "live"]
    assert result["failed_tab_ids"] == [] and result["deferred_tab_ids"] == ["live"]
    assert timer.remaining_seconds() == 0 and timer.error == "keep" and timer.jobs_completed == 3
    assert pending.pending_penalty == 0 and pending.jobs_completed == 5
    assert live.remaining_seconds() == 0 and live.pending_penalty == 90
    assert live.status == PageStatus.BUSY and live.current_image == "running.png"
    assert live.current_job_id == "job-live" and live.error == "keep live error"
    assert live.jobs_completed == 9
    assert untouched.status == PageStatus.ERROR and untouched.error == "untouched error"
    assert untouched.jobs_completed == 10
    snap = pool.status_snapshot()
    assert snap["cooling"] == 0 and snap["busy"] == 1
    assert host.persist_calls == 1 and len(host.page_pool_updated.calls) == 1


def test_live_reset_clears_stale_timer_fields_but_preserves_pending_debt():
    pool = PagePool()
    page = add_page(pool, "live", status=PageStatus.BUSY, pending=60, image="run.png")
    page.cooldown_until = time.time() - 10
    page.cooldown_total = 90
    page.cooldown_reason = "expired timer"
    host = Host(pool)
    host._batch_future = SimpleNamespace(done=lambda: False)

    result = reply_json(host.reset_all_cooldowns())

    assert result["reset_tab_ids"] == ["live"] and result["deferred_tab_ids"] == ["live"]
    assert page.cooldown_until == 0 and page.cooldown_total == 0 and page.cooldown_reason == ""
    assert page.pending_penalty == 60 and page.current_image == "run.png"


def test_live_pending_only_is_deferred_without_rewriting_or_persisting():
    pool = PagePool()
    page = add_page(pool, "live", status=PageStatus.BUSY, pending=60, image="run.png")
    host = Host(pool)
    host._batch_future = SimpleNamespace(done=lambda: False)

    result = reply_json(host.reset_all_cooldowns())

    assert result["reset"] == 0 and result["deferred_tab_ids"] == ["live"]
    assert page.pending_penalty == 60 and page.status == PageStatus.BUSY
    assert host.persist_calls == 0 and host.page_pool_updated.calls == []


def test_global_apply_failure_keeps_other_resets_and_names_the_failed_worker():
    pool = PagePool()
    broken = add_page(pool, "broken", status=PageStatus.COOLDOWN, seconds=40)
    good = add_page(pool, "good", status=PageStatus.COOLDOWN, seconds=50)
    broken.clear_timer = lambda: (_ for _ in ()).throw(RuntimeError("cannot clear"))
    host = Host(pool)

    result = reply_json(host.reset_all_cooldowns())

    assert result["reset"] == 1 and result["reset_tab_ids"] == ["good"]
    assert result["failed_tab_ids"] == ["broken"]
    assert broken.remaining_seconds() > 0 and good.remaining_seconds() == 0
    assert host.persist_calls == 1 and len(host.page_pool_updated.calls) == 1


def test_global_persistence_failure_keeps_resets_and_reports_every_affected_worker():
    pool = PagePool()
    pages = [add_page(pool, tab, status=PageStatus.COOLDOWN, seconds=60)
             for tab in ("a", "b")]
    host = Host(pool)
    host.persist_result = False

    result = reply_json(host.reset_all_cooldowns())

    assert result["reset"] == 2 and result["reset_tab_ids"] == ["a", "b"]
    assert result["persisted"] is False
    assert all(page.remaining_seconds() == 0 for page in pages), "no rollback on write failure"
    assert host.persist_calls == 1 and len(host.page_pool_updated.calls) == 1


def test_row_reset_uses_same_cooldown_policy_and_keeps_other_rows_and_job_count():
    pool = PagePool()
    target = add_page(pool, "target", status=PageStatus.COOLDOWN, seconds=70, jobs=12)
    other = add_page(pool, "other", status=PageStatus.COOLDOWN, seconds=90, jobs=4)
    host = Host(pool)

    result = clear_time(host, "target")

    assert result["ok"] is True and result["busy"] is False
    assert target.remaining_seconds() == 0 and target.jobs_completed == 12
    assert other.remaining_seconds() > 0 and other.jobs_completed == 4


def test_live_row_reset_keeps_stacked_penalty_and_does_not_touch_the_job():
    pool = PagePool()
    page = add_page(pool, "live", status=PageStatus.BUSY, seconds=30, pending=80,
                    jobs=6, image="busy.png")
    host = Host(pool)
    host._batch_future = SimpleNamespace(done=lambda: False)

    result = clear_time(host, "live")

    assert result["busy"] is True
    assert page.remaining_seconds() == 0 and page.pending_penalty == 80
    assert page.jobs_completed == 6 and page.current_image == "busy.png"
    assert page.current_job_id == "job-live" and page.status == PageStatus.BUSY


def test_job_count_slot_sets_only_the_display_counter_and_noops_unchanged():
    pool = PagePool()
    page = add_page(pool, "worker", status=PageStatus.BUSY, jobs=7, image="running.png")
    host = Host(pool)
    host.state = SimpleNamespace(urls=["unchanged"], images=["image.png"])

    changed = reply_json(host.set_page_job_count("worker", "0003"))
    assert changed == {"ok": True, "changed": True, "count": "3", "persisted": True}
    assert page.jobs_completed == 3 and page.status == PageStatus.BUSY
    assert page.current_image == "running.png" and page.current_job_id == "job-worker"
    assert host.state.urls == ["unchanged"] and host.state.images == ["image.png"]
    assert host.persist_calls == 1 and len(host.page_pool_updated.calls) == 1
    assert len(host.logs) == 1

    same = reply_json(host.set_page_job_count("worker", "3"))
    assert same == {"ok": True, "changed": False, "count": "3", "persisted": True}
    assert host.persist_calls == 1 and len(host.page_pool_updated.calls) == 1
    assert len(host.logs) == 1


def test_job_count_slot_rejects_invalid_unknown_and_negative_values():
    pool = PagePool()
    page = add_page(pool, "worker", jobs=7)
    host = Host(pool)

    for value in ("", " ", "-1", "+1", "1.5", "1e3", "2 jobs"):
        result = reply_json(host.set_page_job_count("worker", value))
        assert result["ok"] is False, value
        assert page.jobs_completed == 7
    assert reply_json(host.set_page_job_count("ghost", "2"))["error"] == "unknown tab"
    assert host.persist_calls == 0 and host.page_pool_updated.calls == [] and host.logs == []


def test_inline_slots_report_missing_pool_without_side_effects():
    host = Host(None)

    reset = reply_json(host.reset_all_cooldowns())
    count = reply_json(host.set_page_job_count("worker", "3"))

    assert reset == {"ok": False, "error": "pool not initialized"}
    assert count == {"ok": False, "error": "pool not initialized"}
    assert host.persist_calls == 0 and host.page_pool_updated.calls == []


def test_global_reset_reports_pool_lock_failure_without_publishing():
    class BrokenPool:
        @property
        def _lock(self):
            raise RuntimeError("pool lock unavailable")

    host = Host(BrokenPool())

    result = reply_json(host.reset_all_cooldowns())

    assert result == {"ok": False, "error": "pool lock unavailable"}
    assert host.persist_calls == 0 and host.page_pool_updated.calls == []


def test_worker_count_persistence_failure_keeps_live_override_and_warns():
    pool = PagePool()
    page = add_page(pool, "worker", jobs=2)
    host = Host(pool)
    host.persist_result = False

    result = reply_json(host.set_page_job_count("worker", "8"))

    assert result == {"ok": True, "changed": True, "count": "8", "persisted": False}
    assert page.jobs_completed == 8
    assert host.logs == [("warn", "⚠ Jobs completed for aka_0001 set to 8; value is live but could not be persisted")]


def test_worker_count_override_round_trips_a_decrease_and_preserves_legacy_url_fallback(tmp_path):
    path = tmp_path / "cooldowns.json"
    pool = PagePool()
    page = add_page(pool, "same-id", jobs=9)
    cooldown_store.save_pool_snapshot(path, pool)
    page.jobs_completed = 2
    cooldown_store.save_pool_snapshot(path, pool)

    stats = cooldown_store.load_stats(path)
    url_key = cooldown_store.normalize_url(page.url)
    assert stats[url_key]["jobs_completed"] == 9, "legacy URL maxima stay as fallback"
    assert stats[worker_stats_key("same-id")]["jobs_completed"] == 2

    restored = PagePool()
    same = add_page(restored, "same-id", jobs=9)
    assert restore_page_stats(restored, "same-id", url_key, stats) == 2
    other = add_page(restored, "other-id", jobs=0)
    assert restore_page_stats(restored, "other-id", url_key, stats) == 9
    assert same.jobs_completed == 2 and other.jobs_completed == 9
