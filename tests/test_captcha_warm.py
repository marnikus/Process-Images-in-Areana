"""WarmTaskPool — pre-emptive createTask, consume/discard credit hygiene.

RULE 8: real pool against fake clients (no network). Locks the Phase 4
contract: a warm task is consumed by exactly one solve, and every
abandoned warm task is deleted so it can never bill.
"""

import asyncio

import pytest

import app.services.captcha.solver as solver_mod
import app.services.captcha.warm as warm_mod
from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings
from app.services.captcha.signals import CaptchaSignal
from app.services.captcha.stats import CaptchaStatsStore
from app.services.captcha.warm import WARM_TTL_SEC, WarmTaskPool
from tests.test_captcha_solver import FakeClient

SITEKEY = "6Lsitekey00000000000000000000"
URL = "https://arena.ai/image/direct"


def signal(sitekey=SITEKEY, kind="recaptcha_enterprise"):
    return CaptchaSignal(visible=True, kind=kind, sitekey=sitekey, page_url=URL)


class FakeClock:
    """Advances `step` seconds on every monotonic() read."""

    def __init__(self, step=0.0):
        self.t = 1000.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


def make_pool(config_dir, client, step=0.0, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(warm_mod.time, "monotonic", FakeClock(step))
    keys = CaptchaKeyStore(config_dir)
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))
    logs = []
    pool = WarmTaskPool(keys, CaptchaStatsStore(config_dir),
                        lambda m, l="info": logs.append((m, l)),
                        client_factory=lambda key: client)
    return pool, logs


@pytest.mark.unit
@pytest.mark.asyncio
async def test_take_returns_created_task(isolated_config_dir):
    client = FakeClient("K")
    pool, logs = make_pool(isolated_config_dir, client)
    assert pool.start("t1", signal()) is True
    taken = await pool.take("t1", signal())
    assert taken is not None
    warm_client, task_id = taken
    assert warm_client is client and task_id == "101"
    assert len(client.created) == 1  # exactly one createTask


@pytest.mark.unit
@pytest.mark.asyncio
async def test_take_missing_tab_is_none(isolated_config_dir):
    client = FakeClient("K")
    pool, _ = make_pool(isolated_config_dir, client)
    assert await pool.take("t1", signal()) is None
    assert client.created == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_skips_duplicate_tab_and_missing_sitekey(isolated_config_dir):
    client = FakeClient("K")
    pool, _ = make_pool(isolated_config_dir, client)
    assert pool.start("t1", signal()) is True
    await asyncio.sleep(0)  # let the background createTask run
    assert pool.start("t1", signal()) is False  # already warm
    assert pool.start("t2", signal(sitekey="")) is False  # nothing to solve against
    assert len(client.created) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_skips_without_key(isolated_config_dir):
    client = FakeClient("K")
    keys = CaptchaKeyStore(isolated_config_dir)  # no key saved
    pool = WarmTaskPool(keys, CaptchaStatsStore(isolated_config_dir),
                        lambda m, l="info": None, client_factory=lambda key: client)
    assert pool.start("t1", signal()) is False
    assert client.created == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stale_ttl_task_is_deleted_not_consumed(monkeypatch, isolated_config_dir):
    client = FakeClient("K")
    pool, _ = make_pool(isolated_config_dir, client, step=WARM_TTL_SEC / 2,
                        monkeypatch=monkeypatch)
    pool.start("t1", signal())
    taken = await pool.take("t1", signal())  # ~3 clock reads later: past TTL
    assert taken is None
    assert client.deleted and client.closed is True  # credit freed


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sitekey_mismatch_discards(monkeypatch, isolated_config_dir):
    """Challenge refreshed with a new sitekey while the warm task was pending."""
    client = FakeClient("K")
    pool, _ = make_pool(isolated_config_dir, client)
    pool.start("t1", signal(sitekey="6Lold"))
    taken = await pool.take("t1", signal(sitekey="6Lnew"))
    assert taken is None
    assert client.deleted and client.closed is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discard_deletes_pending_task(isolated_config_dir):
    client = FakeClient("K")
    pool, _ = make_pool(isolated_config_dir, client)
    pool.start("t1", signal())
    await pool.discard("t1")
    assert client.deleted == ["101"] and client.closed is True
    await pool.discard("t1")  # second discard is a no-op
    assert client.deleted == ["101"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_failure_returns_none_and_closes(isolated_config_dir):
    class BrokenClient(FakeClient):
        async def create_task(self, task):
            raise RuntimeError("2captcha down")

    client = BrokenClient("K")
    pool, logs = make_pool(isolated_config_dir, client)
    assert pool.start("t1", signal()) is True
    assert await pool.take("t1", signal()) is None
    assert client.closed is True
    assert any("warm createTask failed" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_solver_consumes_warm_without_second_create(monkeypatch, isolated_config_dir):
    """Solver-level Phase 4 contract: warm_up → solve reuses the provider task."""
    from app.services.captcha.solver import SolveRequest
    from tests.test_captcha_solver import FakeCtrl

    client = FakeClient("K", results=[
        {"errorId": 0, "status": "processing"},
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, logs, _ = _make_solver(monkeypatch, isolated_config_dir, client)

    async def instant_sleep(_s):
        return None
    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    sig = signal()
    assert solver.warm_up("t-warm", sig) is True
    outcome = await solver.solve(SolveRequest(
        ctrl=FakeCtrl(visible_seq=[True, True, False]), tab_id="t-warm",
        signal=sig, stop=lambda: False))
    assert outcome.status == "solved"
    assert len(client.created) == 1  # warm's createTask reused, no second submit
    await solver.discard_warm("t-warm")  # consumed already → no-op
    assert client.deleted == []


def _make_solver(monkeypatch, isolated_config_dir, client):
    from app.services.captcha.solver import CaptchaSolver
    keys = CaptchaKeyStore(isolated_config_dir)
    stats = CaptchaStatsStore(isolated_config_dir)
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))
    logs = []
    monkeypatch.setattr(solver_mod, "Captcha2Client", lambda key, timeout_sec=30.0: client)
    monkeypatch.setattr(solver_mod.time, "monotonic", FakeClock(5))
    solver = CaptchaSolver(keys, stats, lambda m, l="info": logs.append((m, l)))
    return solver, stats, logs, client
