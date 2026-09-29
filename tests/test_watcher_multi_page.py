"""Multi-worker Watcher regressions: page episodes and global pause are independent."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.watcher import WatcherConfig, WatcherService
from app.services.watcher_pkg.cdp import WatcherTarget


class Page:
    def __init__(self, tab_id, *, generating=False, error=""):
        self.tab_id = tab_id
        self.generating = generating
        self.error = error
        self.overlays = {}
        self.hides = []

    async def is_security_dialog_visible(self):
        return False

    async def is_generating(self):
        return self.generating, {"jobs": [self.tab_id], "details": []}

    async def scan_page_errors(self):
        return self.error

    async def show_watcher_overlay(self, msg, kind=None, timeout_sec=None, sub="", owner_key=""):
        self.overlays[owner_key] = (msg, kind, timeout_sec)
        return True

    async def hide_watcher_overlay(self, owner_key=""):
        self.hides.append(owner_key)
        if owner_key:
            self.overlays.pop(owner_key, None)
        else:
            self.overlays.clear()
        return True


class Runner:
    def __init__(self):
        self.paused = 0
        self.resumed = 0

    def pause_run(self):
        self.paused += 1

    def resume_run(self):
        self.resumed += 1


def build_service(pages):
    runner = Runner()
    targets = [WatcherTarget(tab_id=p.tab_id, label=p.tab_id, cdp=p) for p in pages]
    service = WatcherService(
        config=WatcherConfig(enabled=True, generation_timeout_sec=600),
        cdp_controller_getter=lambda: targets,
        job_runner_getter=lambda: runner,
        logger=lambda *_: None,
    )
    return service, runner


@pytest.mark.asyncio
async def test_terminal_error_hides_only_its_page_and_holds_other_wait():
    a, b = Page("A", generating=True), Page("B", generating=True)
    service, runner = build_service([a, b])

    await service.check_once()
    assert runner.paused == 1
    assert len(a.overlays) == len(b.overlays) == 1

    a.error = "Something went wrong while generating"
    await service.check_once()

    assert not a.overlays
    assert len(b.overlays) == 1
    assert runner.paused == 1 and runner.resumed == 0

    b.generating = False
    await service.check_once()
    assert not b.overlays
    assert runner.paused == 1 and runner.resumed == 1


@pytest.mark.asyncio
async def test_preexisting_error_toast_is_baseline_not_a_terminal_event():
    a = Page("A", generating=True, error="Something went wrong while generating")
    service, runner = build_service([a])

    await service.check_once()
    await service.check_once()

    assert len(a.overlays) == 1
    assert runner.paused == 1 and runner.resumed == 0


@pytest.mark.asyncio
async def test_two_page_clear_is_symmetric_and_pause_is_edge_triggered():
    a, b = Page("A", generating=True), Page("B", generating=True)
    service, runner = build_service([a, b])
    await service.check_once()

    a.generating = False
    await service.check_once()
    assert not a.overlays and len(b.overlays) == 1
    assert runner.resumed == 0

    b.generating = False
    await service.check_once()
    assert not a.overlays and not b.overlays
    assert runner.paused == 1 and runner.resumed == 1


@pytest.mark.asyncio
async def test_three_targets_remain_independent_and_one_final_resume_occurs():
    a, b, c = (Page(name, generating=True) for name in ("A", "B", "C"))
    service, runner = build_service([a, b, c])
    await service.check_once()
    assert runner.paused == 1 and len(service.state.page_states) == 3

    b.error = "Something went wrong while generating"
    await service.check_once()
    assert not b.overlays and len(a.overlays) == len(c.overlays) == 1
    assert runner.resumed == 0

    a.generating = False
    await service.check_once()
    assert not a.overlays and len(c.overlays) == 1 and runner.resumed == 0
    c.generating = False
    await service.check_once()
    assert not c.overlays and runner.paused == 1 and runner.resumed == 1


@pytest.mark.asyncio
async def test_stale_page_error_is_baselined_before_a_generation_episode():
    a = Page("A", error="Something went wrong earlier")
    service, runner = build_service([a])
    await service.check_once()  # idle baseline includes the old toast
    a.generating = True
    await service.check_once()
    assert len(a.overlays) == 1 and runner.paused == 1
    await service.check_once()
    assert len(a.overlays) == 1 and runner.resumed == 0
    a.error += "\\nGeneration failed just now"
    await service.check_once()
    assert not a.overlays and runner.resumed == 1


@pytest.mark.asyncio
async def test_unanswered_captcha_probe_holds_the_active_page_episode():
    a, b = Page("A", generating=True), Page("B", generating=True)
    service, runner = build_service([a, b])
    await service.check_once()
    async def unanswered():
        raise TimeoutError("page silent")
    a.is_security_dialog_visible = unanswered
    a.generating = False
    await service.check_once()
    assert len(a.overlays) == len(b.overlays) == 1
    assert runner.paused == 1 and runner.resumed == 0


@pytest.mark.asyncio
async def test_disconnected_target_is_unknown_and_holds_its_existing_episode():
    a = Page("A", generating=True)
    service, runner = build_service([a])
    await service.check_once()
    a.is_connected = False
    a.generating = False
    await service.check_once()
    assert len(a.overlays) == 1 and runner.paused == 1 and runner.resumed == 0
    assert service.state.page_states[0]["available"] is False


@pytest.mark.asyncio
async def test_removed_target_clears_only_its_episode_and_keeps_aggregate_pause():
    a, b = Page("A", generating=True), Page("B", generating=True)
    service, runner = build_service([a, b])
    await service.check_once()
    targets = service._cdp_probe.get()
    targets[:] = [targets[1]]
    await service.check_once()
    assert not a.overlays and len(b.overlays) == 1
    assert runner.resumed == 0
    b.generating = False
    await service.check_once()
    assert runner.paused == 1 and runner.resumed == 1


@pytest.mark.asyncio
async def test_job_overlay_hide_does_not_clear_watcher_overlay_lease():

    a = Page("A")
    await a.show_watcher_overlay("watcher", kind="generation", owner_key="watcher:A")
    await a.show_watcher_overlay("job", kind="generation", owner_key="job:A:1")

    await a.hide_watcher_overlay("job:A:1")

    assert "watcher:A" in a.overlays
    assert "job:A:1" not in a.overlays
