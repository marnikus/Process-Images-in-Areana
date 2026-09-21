"""Job count is display-only — nothing routes by the number (2026-09-21).

Owner instruction: remove the job-*queueing* concept (I-28 load balancing) and
keep only the counter as a number. The three routing sites that used to pick the
tab with the fewest completed jobs now take the first free/ready tab in pool
order (join order = the `#n` worker number, I-55); the counter itself stays,
keeps counting, keeps persisting and keeps being shown.

`jobs_completed` must therefore appear only in counting/restore/display paths.

RED at `764d267`: the picks below returned the *lowest-count* tab, not the first
one, and `_pick_lowest_count` / `_best_ready_id` existed by name.
"""

import pathlib

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import cooldown_service as svc
from app.services import multi_page_dispatcher as mpd

pytestmark = pytest.mark.unit

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def make_info(tab_id: str, jobs: int = 0) -> PageInfo:
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                    url="https://arena.ai", status=PageStatus.STEADY,
                    is_connected=True, jobs_completed=jobs)


def pool_of(*specs) -> PagePool:
    """Pool in the given order; `specs` are (tab_id, jobs_completed) pairs."""
    pool = PagePool()
    for tab_id, jobs in specs:
        pool.add_page(make_info(tab_id, jobs))
    return pool


# ---- the pool's own pick ---------------------------------------------------


@pytest.mark.asyncio
async def test_free_page_is_the_first_in_pool_order_not_the_lowest_count():
    pool = pool_of(("a", 9), ("b", 1), ("c", 4))
    got = await pool.get_free_page()
    assert got is not None and got.tab_id == "a", "the count never reorders the pool"


@pytest.mark.asyncio
async def test_acquire_takes_the_first_free_and_marks_it_busy():
    pool = pool_of(("a", 4), ("b", 1))
    got = await pool.acquire_free_page("j1")
    assert got is not None and got.tab_id == "a"
    assert pool.get_page("a").status == PageStatus.BUSY
    assert pool.get_page("b").status == PageStatus.STEADY


@pytest.mark.asyncio
async def test_a_busy_front_tab_hands_over_to_the_next_one_in_order():
    pool = pool_of(("a", 1), ("b", 9), ("c", 0))
    pool.mark_busy("a", "other")
    got = await pool.get_free_page()
    assert got is not None and got.tab_id == "b", "order only: c has the fewest jobs"


# ---- the run's tab resolution (the URL-list link) --------------------------


def test_resolve_primary_tab_uses_pool_order_not_the_count():
    pool = pool_of(("a", 5), ("b", 2))
    assert svc.resolve_primary_tab(pool, "ghost") == "a"
    pool.get_page("a").jobs_completed = 0        # the numbers change…
    pool.get_page("b").jobs_completed = 42       # …and the answer must not
    assert svc.resolve_primary_tab(pool, "ghost") == "a"


def test_resolve_allowed_uses_pool_order_within_the_checked_set():
    pool = pool_of(("a", 1), ("b", 7), ("c", 3))
    assert svc.resolve_primary_tab(pool, "ghost", allowed={"b", "c"}) == "b"


# ---- the parallel dispatcher's acquire -------------------------------------


def test_acquire_free_in_takes_the_first_allowed_in_pool_order():
    pool = pool_of(("a", 4), ("b", 1), ("checked", 9))
    got = mpd._acquire_free_in(pool, {"a", "b"}, "job1")
    assert got is not None and got.tab_id == "a"
    assert got.status == PageStatus.BUSY and got.current_job_id == "job1"


# ---- the counter itself stays ---------------------------------------------


def test_the_counter_still_counts_and_still_reaches_the_snapshot():
    pool = pool_of(("a", 0))
    assert svc.register_job_done(pool, "a") == 1
    assert svc.register_job_done(pool, "a") == 2
    assert pool.get_page("a").jobs_completed == 2
    snap = pool.status_snapshot()
    assert snap["pages"][0]["jobs_completed"] == 2
    assert snap["pages"][0]["last_job_at"], "the counting timestamp stays too"
    assert svc.register_job_done(pool, "nope") == -1
    assert svc.register_job_done(None, "a") == -1


# ---- static guard: the routing helpers never read the number ---------------


def _body_of(source: str, name: str) -> str:
    """Source of one top-level function, from `def name` to the next top-level def."""
    start = source.index(f"def {name}(")
    rest = source[start + 1:]
    nxt = rest.find("\ndef ")
    return rest[:nxt if nxt > 0 else len(rest)]


def test_no_routing_helper_reads_the_job_counter():
    page_pool = (APP / "browser" / "page_pool.py").read_text(encoding="utf-8")
    cooldown = (APP / "services" / "cooldown_service.py").read_text(encoding="utf-8")
    dispatch = (APP / "services" / "multi_page_dispatcher.py").read_text(encoding="utf-8")

    assert "_pick_lowest_count" not in page_pool, "the count-based picker is gone"
    assert "_best_ready_id" not in cooldown, "the count-based ready picker is gone"
    assert "jobs_completed" not in page_pool, "the pool never reads the counter"
    for name in ("_first_ready_id", "_resolve_allowed_tab"):
        assert "jobs_completed" not in _body_of(cooldown, name), f"{name} routes by order alone"
    assert "jobs_completed" not in _body_of(dispatch, "_acquire_free_in")


def test_the_rule_is_named_for_what_it_does():
    """A reader greps for the pick and reads the rule, not a comment about it."""
    page_pool = (APP / "browser" / "page_pool.py").read_text(encoding="utf-8")
    cooldown = (APP / "services" / "cooldown_service.py").read_text(encoding="utf-8")
    assert "def _pick_free(" in page_pool
    assert "def _first_ready_id(" in cooldown
    assert "pool order" in _body_of(page_pool, "_pick_free")
    assert "pool order" in _body_of(cooldown, "_first_ready_id")
