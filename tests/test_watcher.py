import pytest
from app.services.watcher import WatcherConfig, WatcherState, WatcherService

@pytest.mark.unit
def test_watcher_config_defaults():
    cfg = WatcherConfig()
    assert cfg.check_interval_ms == 2000
    assert cfg.captcha_timeout_sec == 300
    assert cfg.generation_timeout_sec == 600
    assert cfg.enabled is False

@pytest.mark.unit
def test_watcher_state_defaults():
    st = WatcherState()
    assert st.status == "idle"
    assert st.checks_count == 0

@pytest.mark.unit
def test_watcher_update_config():
    cfg = WatcherConfig()
    svc = WatcherService(config=cfg)
    svc.update_config(enabled=True, check_interval_ms=1500, captcha_timeout_sec=200, generation_timeout_sec=400)
    assert svc.config.enabled is True
    assert svc.config.check_interval_ms == 1500
    assert svc.config.captcha_timeout_sec == 200
    assert svc.config.generation_timeout_sec == 400
    # cleanup
    svc.stop()

@pytest.mark.unit
def test_watcher_get_config():
    cfg = WatcherConfig(enabled=True, check_interval_ms=1000)
    svc = WatcherService(config=cfg)
    d = svc.get_config()
    assert d["enabled"] is True
    assert d["check_interval_ms"] == 1000

@pytest.mark.unit
def test_watcher_get_state():
    svc = WatcherService()
    st = svc.get_state()
    assert "status" in st
    assert "checks_count" in st


# --- D4.1: check_once lifecycle against a fake CDP (RULE 8) ---

import asyncio
import time


class FakeWatcherCDP:
    def __init__(self, captcha=False, gen=False, gen_details=None,
                 raise_captcha=False, raise_gen=False):
        self.captcha = captcha
        self.gen = gen
        self.gen_details = gen_details if gen_details is not None else {"details": []}
        self.raise_captcha = raise_captcha
        self.raise_gen = raise_gen
        self.overlays = []
        self.hides = 0

    async def is_security_dialog_visible(self):
        if self.raise_captcha:
            raise RuntimeError("dialog probe broken")
        return self.captcha

    async def is_generating(self):
        if self.raise_gen:
            raise RuntimeError("gen probe broken")
        return self.gen, self.gen_details

    async def show_watcher_overlay(self, msg, kind=None, timeout_sec=None):
        self.overlays.append((msg, kind, timeout_sec))

    async def hide_watcher_overlay(self):
        self.hides += 1


class FakeJobRunner:
    def __init__(self):
        self.paused = 0
        self.resumed = 0

    def pause_run(self):
        self.paused += 1

    def resume_run(self):
        self.resumed += 1


def make_service(cdp, config=None, jr=None, logger=None):
    return WatcherService(config=config or WatcherConfig(enabled=True),
                          cdp_controller_getter=lambda: cdp,
                          job_runner_getter=lambda: jr,
                          logger=logger or (lambda msg, level="info": None))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_once_without_cdp_stays_watching():
    svc = make_service(None)
    state = await svc.check_once()
    assert state["status"] == "watching" and state["checks_count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_captcha_detected_draws_overlay_and_pauses_jobs():
    cdp, jr = FakeWatcherCDP(captcha=True), FakeJobRunner()
    svc = make_service(cdp, WatcherConfig(enabled=True, captcha_timeout_sec=300), jr)
    state = await svc.check_once()
    assert state["status"] == "waiting_captcha" and state["captcha_waits"] == 1
    assert cdp.overlays == [("wait for user. Captcha", "captcha", 300)]
    assert jr.paused == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_captcha_still_waiting_logs_timeout_when_elapsed():
    cdp, jr = FakeWatcherCDP(captcha=True), FakeJobRunner()
    svc = make_service(cdp, WatcherConfig(enabled=True, captcha_timeout_sec=50), jr)
    logs = []
    svc.set_logger(lambda msg, level="info": logs.append((level, msg)))
    await svc.check_once()
    svc.state.waiting_since = time.time() - 100  # pretend 100s have passed
    state = await svc.check_once()
    assert state["status"] == "waiting_captcha" and state["captcha_waits"] == 1  # no double wait
    assert cdp.overlays and len(cdp.overlays) == 1  # overlay not re-shown
    assert any("timeout" in msg for level, msg in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_captcha_cleared_hides_overlay_and_resumes_jobs():
    cdp, jr = FakeWatcherCDP(captcha=True), FakeJobRunner()
    svc = make_service(cdp, WatcherConfig(enabled=True), jr)
    await svc.check_once()
    cdp.captcha = False
    state = await svc.check_once()
    assert state["status"] == "watching" and cdp.hides == 1
    assert jr.paused == 1 and jr.resumed == 1
    assert svc.state.waiting_kind is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generation_detected_with_details_and_resume():
    cdp = FakeWatcherCDP(gen=True, gen_details={"details": [{"label": "img1"}, {"label": "img2"}]})
    jr = FakeJobRunner()
    svc = make_service(cdp, WatcherConfig(enabled=True, generation_timeout_sec=600), jr)
    state = await svc.check_once()
    assert state["status"] == "waiting_generation" and state["generation_waits"] == 1
    assert cdp.overlays == [("wait for finish generation", "generation", 600)]
    assert jr.paused == 1
    cdp.gen = False
    state = await svc.check_once()
    assert state["status"] == "watching" and cdp.hides == 1 and jr.resumed == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generation_timeout_logged_but_waits_continue():
    cdp, jr = FakeWatcherCDP(gen=True), FakeJobRunner()
    svc = make_service(cdp, WatcherConfig(enabled=True, generation_timeout_sec=50), jr)
    logs = []
    svc.set_logger(lambda msg, level="info": logs.append((level, msg)))
    await svc.check_once()
    svc.state.waiting_since = time.time() - 60
    state = await svc.check_once()
    assert state["status"] == "waiting_generation"
    assert any("timeout" in msg for level, msg in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_errors_are_fail_open_and_logged():
    cdp = FakeWatcherCDP(raise_captcha=True, raise_gen=True)
    svc = make_service(cdp)
    logs = []
    svc.set_logger(lambda msg, level="info": logs.append((level, msg)))
    state = await svc.check_once()
    assert state["status"] == "watching"  # broken probes never block
    assert state["last_generation_details"] == {"error": "gen probe broken"}
    assert any("captcha check error" in msg for _, msg in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_force_clear_resets_waiting_state():
    cdp, jr = FakeWatcherCDP(captcha=True), FakeJobRunner()
    svc = make_service(cdp, WatcherConfig(enabled=True), jr)
    await svc.check_once()
    await svc.force_clear()
    assert cdp.hides == 1 and svc.state.waiting_kind is None
    assert svc.state.status == "watching"
    await svc.force_clear()  # idempotent, no CDP error
    assert svc.state.waiting_kind is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_loop_runs_checks_until_stopped_and_settles_idle():
    cfg = WatcherConfig(enabled=True, check_interval_ms=5)
    svc = make_service(None, cfg)
    svc.start()
    await asyncio.sleep(0.08)
    svc.stop()
    await asyncio.sleep(0.02)
    assert svc.state.checks_count >= 1
    assert svc.state.status == "idle"


@pytest.mark.unit
def test_start_without_loop_defers_task_and_update_config_toggles():
    # C9 split: the task/running flags live on the loop object the facade delegates to
    svc = WatcherService(config=WatcherConfig(enabled=False))
    svc.start()  # no running loop here
    assert svc._loop._task is None and svc._loop._running is True
    svc.update_config(enabled=False)  # stop transition
    assert svc._loop._running is False and svc.state.status == "idle"
    assert not WatcherService(config=WatcherConfig(enabled=False))._loop._running


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_task_starts_when_enabled_and_loop_ready():
    svc = WatcherService(config=WatcherConfig(enabled=False, check_interval_ms=5))
    svc.ensure_task()  # disabled: no task
    assert svc._loop._task is None
    svc.update_config(enabled=True)
    svc.ensure_task()
    assert svc._loop._task is not None
    svc.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_callbacks_sync_async_and_raising_are_not_fatal():
    hits = []
    svc = make_service(None)

    def sync_cb(payload):
        hits.append(("sync", payload["status"]))

    async def async_cb(payload):
        hits.append(("async", payload["config"]["check_interval_ms"]))

    def bad_cb(payload):
        raise RuntimeError("cb broken")

    svc.add_callback(sync_cb)
    svc.add_callback(async_cb)
    svc.add_callback(bad_cb)
    await svc.check_once()
    assert ("sync", "watching") in hits
    assert ("async", 2000) in hits


@pytest.mark.unit
def test_get_state_reports_waiting_duration_and_human_time():
    svc = WatcherService()
    svc.state.last_check = time.time()
    svc.state.waiting_since = time.time() - 5
    state = svc.get_state()
    assert state["waiting_duration"] >= 4
    assert state["last_check_human"] != "never"
