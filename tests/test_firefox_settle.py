"""How a Firefox page is settled when a job saved nothing (2026-09-25, steps 14–16).

A failed job and an uncertain one both keep their page: the macro may have left a
native file dialog, a half-typed composer or a security dialog behind, and the
in-flight evidence is what the operator has to look at. Neither may be cooled
down, handed the next job, or silently reset — and a page that was already asking
the operator for something (a captcha) keeps that instruction instead of "error".
"""

from types import SimpleNamespace as NS

import pytest

from app.browser.page_status import PageStatus
from app.services import firefox_settle as fs

pytestmark = pytest.mark.unit

TAB = "9THrgpBc.Profile1_tab1"


class Bridge:
    def __init__(self):
        self.logs = []
        self.emits = 0

    def _emit_pool_status(self):
        self.emits += 1

    def _log(self, message, level="info"):
        self.logs.append((level, message))

    @property
    def text(self) -> str:
        return " ".join(m for _lvl, m in self.logs)


class Pool:
    """Only what a settle touches: one page, its state and the error field."""

    def __init__(self, status=PageStatus.BUSY, alias="Tab 2", page=True):
        self.page = NS(tab_id=TAB, status=status, alias=alias, error="") if page else None
        self.errors = []

    def get_page(self, tab_id):
        if self.page is None or tab_id != TAB:
            raise KeyError(tab_id)
        return self.page

    def mark_error(self, tab_id, reason):
        if self.page is None:
            return False
        self.errors.append((tab_id, reason))
        self.page.status = PageStatus.ERROR
        self.page.error = reason
        return True


def test_a_failed_job_leaves_its_page_in_error_with_the_named_reason():
    pool, bridge = Pool(), Bridge()
    fs.settle_failed(pool, bridge, TAB, "attachment not verified: wrong file attached")
    assert pool.page.status == PageStatus.ERROR
    assert pool.page.error == "attachment not verified: wrong file attached"
    assert bridge.emits == 1
    assert "left in error" in bridge.text
    assert "no cooldown, no new job until reset" in bridge.text
    assert bridge.logs[0][0] == "warn"


def test_a_settle_without_a_reason_still_says_something_useful():
    pool, bridge = Pool(), Bridge()
    fs.settle_failed(pool, bridge, TAB)
    assert pool.page.error == "the job failed"
    assert "the job failed" in bridge.text


def test_an_uncertain_job_keeps_the_page_in_error_and_its_evidence():
    pool, bridge = Pool(), Bridge()
    fs.settle_for_review(pool, bridge, TAB)
    assert pool.page.status == PageStatus.ERROR
    assert pool.page.error == fs.REVIEW_NOTE
    assert "kept for review" in bridge.text
    assert "no reset, no cooldown, no new job" in bridge.text
    assert bridge.emits == 1


def test_review_never_erases_a_pages_waiting_instruction():
    """The captcha dialog is the operator's instruction — 'error' would hide it (step 14)."""
    for waiting in (PageStatus.WAITING_CAPTCHA, PageStatus.WAITING_GENERATION):
        pool, bridge = Pool(status=waiting), Bridge()
        fs.settle_for_review(pool, bridge, TAB, "security dialog visible")
        assert pool.page.status == waiting
        assert pool.errors == []
        assert "kept for review" in bridge.text


def test_a_captcha_instruction_wins_even_for_a_failed_job_reason():
    pool, bridge = Pool(status=PageStatus.WAITING_CAPTCHA), Bridge()
    fs.settle_for_review(pool, bridge, TAB, "manual action required")
    assert pool.page.status == PageStatus.WAITING_CAPTCHA


def test_a_settle_never_raises_when_the_pool_or_the_bridge_is_broken():
    class Dead(Pool):
        def get_page(self, tab_id):
            raise RuntimeError("pool gone")

        def mark_error(self, tab_id, reason):
            raise RuntimeError("pool gone")

    class Deaf(Bridge):
        def _emit_pool_status(self):
            raise RuntimeError("no ui")

        def _log(self, message, level="info"):
            raise RuntimeError("no log")

    fs.settle_failed(Dead(), Deaf(), TAB)          # nothing may escape into the lane
    fs.settle_for_review(Dead(page=False), Deaf(), TAB)


@pytest.mark.asyncio
async def test_the_reset_runs_the_firefox_new_chat_macro(monkeypatch):
    """Step 15: the post-job New Chat goes through the lane's own macro, never CDP."""
    from app.services import firefox_lane as fl
    pool, bridge = Pool(), Bridge()
    pool.page.browser = "firefox"
    calls = []

    async def fake_reset(b, page):
        calls.append(page.tab_id)
        return True, "composer empty, nothing attached, no spinner, no dialog"

    monkeypatch.setattr(fl, "reset_page", fake_reset)
    ok, reason = await fs.reset_page(bridge, pool, TAB)
    assert ok is True and calls == [TAB]
    assert "composer empty" in reason


@pytest.mark.asyncio
async def test_a_cancelled_run_never_clicks_new_chat(monkeypatch):
    from app.services import firefox_lane as fl
    pool, bridge = Pool(), Bridge()
    pool.page.browser = "firefox"
    bridge._cancel_requested = True
    monkeypatch.setattr(fl, "reset_page", lambda *a: pytest.fail("must not reset"))
    ok, reason = await fs.reset_page(bridge, pool, TAB)
    assert ok is False and "cancelled" in reason


@pytest.mark.asyncio
async def test_a_page_without_the_firefox_lane_says_so_and_never_raises(monkeypatch):
    from app.services import firefox_lane as fl

    async def boom(*_a):
        raise RuntimeError("extension not answering")

    pool, bridge = Pool(), Bridge()
    pool.page.browser = "firefox"
    monkeypatch.setattr(fl, "reset_page", boom)
    assert await fs.reset_page(bridge, pool, TAB) == (False, "extension not answering")
    assert await fs.reset_page(bridge, Pool(page=False), TAB) == (
        False, "no CDP controller — Firefox lane (New-chat reset not applicable)")


def test_the_log_uses_the_pages_alias_not_its_tab_id():
    pool, bridge = Pool(alias="Tab 7"), Bridge()
    fs.settle_failed(pool, bridge, TAB, "boom")
    assert "Page Tab 7 left in error" in bridge.text
    assert TAB[:12] not in bridge.text
