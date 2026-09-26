"""Watcher generation wait — start, restart on a new JOB-ID, ONE timeout (live fix 2026-09-27).

Owner report: "Generation timeout 677s limit 180s" logged twice a second forever;
the generation had finished and a new one had already started. The page probe is
covered by `tests/js/test_watcher_generation_probe.mjs`; this is the decision side.
"""
import time

import pytest

from app.services.watcher import WatcherService
from app.services.watcher_config import WatcherConfig
from app.services.watcher_pkg.generation import Episode, fresh_jobs, page_jobs

pytestmark = pytest.mark.unit


class Page:
    """Fake CDP page: spinner on/off + the JOB-IDs the probe reports."""

    def __init__(self, gen=True, jobs=()):
        self.gen, self.jobs = gen, list(jobs)
        self.overlays, self.hides = [], 0

    async def is_security_dialog_visible(self):
        return False

    async def is_generating(self):
        return self.gen, {"details": [], "jobs": list(self.jobs)}

    async def show_watcher_overlay(self, msg, kind=None, timeout_sec=None):
        self.overlays.append(kind)

    async def hide_watcher_overlay(self):
        self.hides += 1


class Runner:
    def __init__(self):
        self.paused = self.resumed = 0

    def pause_run(self):
        self.paused += 1

    def resume_run(self):
        self.resumed += 1


@pytest.fixture
def env():
    page, runner, logs = Page(jobs=["a1"]), Runner(), []
    svc = WatcherService(config=WatcherConfig(enabled=True, generation_timeout_sec=180),
                         cdp_controller_getter=lambda: page, job_runner_getter=lambda: runner)
    svc.set_logger(lambda msg, level="info": logs.append((level, msg)))
    return svc, page, runner, logs


def lines(logs, word):
    return [m for _level, m in logs if word in m]


def expire(svc):
    svc.state.waiting_since = time.time() - 181


@pytest.mark.asyncio
async def test_after_the_timeout_the_spinner_is_ignored_quietly(env):
    svc, page, runner, logs = env
    await svc.check_once()
    expire(svc)
    for _ in range(5):
        state = await svc.check_once()
    assert len(lines(logs, "Generation timeout")) == 1              # not every tick any more
    assert state["status"] == "watching" and state["waiting_kind"] is None
    assert (runner.paused, runner.resumed, page.hides) == (1, 1, 1)


@pytest.mark.asyncio
async def test_a_new_job_id_restarts_the_clock_without_a_second_pause(env):
    svc, page, runner, logs = env
    await svc.check_once()
    svc.state.waiting_since = time.time() - 170
    page.jobs.append("b2")                                            # the next job's bubble
    state = await svc.check_once()
    assert state["waiting_kind"] == "generation" and state["waiting_duration"] <= 1
    assert state["generation_waits"] == 2 and lines(logs, "new generation [b2]")
    assert runner.paused == 1 and page.overlays == ["generation"]


@pytest.mark.asyncio
async def test_a_new_generation_after_a_timeout_waits_again(env):
    svc, page, runner, logs = env
    await svc.check_once()
    expire(svc)
    await svc.check_once()
    page.jobs = ["c3"]                                                # New Chat + next job
    state = await svc.check_once()
    assert state["status"] == "waiting_generation" and runner.paused == 2
    assert page.overlays == ["generation", "generation"]


@pytest.mark.asyncio
async def test_the_spinner_going_away_rearms_the_watcher(env):
    svc, page, runner, logs = env
    await svc.check_once()
    expire(svc)
    await svc.check_once()
    page.gen = False
    await svc.check_once()
    page.gen = True
    state = await svc.check_once()
    assert state["status"] == "waiting_generation" and state["generation_waits"] == 2


@pytest.mark.asyncio
async def test_the_first_job_id_after_an_empty_page_is_adopted_silently(env):
    svc, page, runner, logs = env
    page.jobs = []
    await svc.check_once()
    page.jobs = ["a1"]
    state = await svc.check_once()
    assert state["generation_waits"] == 1 and not lines(logs, "new generation")


@pytest.mark.parametrize("details,expected", [({"jobs": ["x", "", None, "y"]}, {"x", "y"}),
                                              ({}, set()), (None, set()), ({"jobs": None}, set())])
def test_page_jobs_tolerates_any_probe_answer(details, expected):
    assert page_jobs(details) == frozenset(expected)


def test_fresh_jobs_needs_a_baseline():
    assert fresh_jobs(Episode(), frozenset({"a"})) == frozenset()
    assert fresh_jobs(Episode(jobs=frozenset({"a"})), frozenset({"a", "b"})) == frozenset({"b"})
