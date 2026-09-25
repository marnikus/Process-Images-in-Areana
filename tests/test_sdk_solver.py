"""SdkSolver — the only 2Captcha integration: SDK wrapper contract, fail-open, no key leaks."""

import asyncio

import pytest

from app.services.captcha_watcher.sdk_solver import (
    SDK_MISSING_ERROR,
    SdkSolver,
    _default_factory,
    _error_text,
    _task_id_of,
    _token_of,
    sdk_available,
)
from app.services.captcha_watcher.signals import CaptchaSignal

SIG = CaptchaSignal(visible=True, kind="recaptcha_v2", sitekey="6Lkey", page_url="https://arena.ai/x")


class Client:
    def __init__(self, result=None, exc=None, balance=3.5):
        self.result, self.exc, self._balance = result, exc, balance
        self.calls = []

    async def recaptcha(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.result

    async def balance(self):
        if self.exc:
            raise self.exc
        return self._balance


def solver(client, key="K" * 16, timeout=60):
    return SdkSolver(key, timeout_sec=timeout, client_factory=lambda k, t: client)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_solve_maps_signal_to_sdk_kwargs_and_returns_token():
    c = Client(result={"captchaId": "77", "code": "TOKEN"})
    r = await solver(c).solve(CaptchaSignal(visible=True, kind="recaptcha_enterprise",
                                             sitekey="6Lent", page_url="https://a.ai", invisible=True))
    assert r.ok and r.token == "TOKEN" and r.task_id == "77" and r.error == ""
    assert c.calls == [{"sitekey": "6Lent", "url": "https://a.ai", "version": "v2",
                        "enterprise": 1, "invisible": 1}]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_solve_fail_open_paths():
    assert (await solver(Client(), key="").solve(SIG)).error == "no api key"
    bad = CaptchaSignal(visible=True, kind="hcaptcha", sitekey="x")
    assert "unsolvable" in (await solver(Client()).solve(bad)).error
    r = await solver(Client(exc=ValueError("ERROR_WRONG_USER_KEY"))).solve(SIG)
    assert not r.ok and r.error == "ValueError: ERROR_WRONG_USER_KEY"
    r = await solver(Client(result={"captchaId": "1", "code": ""})).solve(SIG)
    assert not r.ok and r.error == "empty token from SDK" and r.task_id == "1"
    assert (await solver(Client(result="BARE")).solve(SIG)).token == "BARE"

    def factory_boom(k, t):
        raise RuntimeError(SDK_MISSING_ERROR)

    r = await SdkSolver("K" * 16, client_factory=factory_boom).solve(SIG)
    assert not r.ok and "not installed" in r.error


@pytest.mark.unit
@pytest.mark.asyncio
async def test_solve_timeout_is_bounded(monkeypatch):
    class Hang:
        async def recaptcha(self, **kw):
            await asyncio.sleep(5)

    s = SdkSolver("K" * 16, timeout_sec=30, client_factory=lambda k, t: Hang())
    s._timeout = 0  # exercise the wait_for guard without a real 30 s wait
    monkeypatch.setattr(asyncio, "wait_for", lambda coro, timeout: _instant_timeout(coro))
    r = await s.solve(SIG)
    assert not r.ok and "TimeoutError" in r.error


async def _instant_timeout(coro):
    coro.close()
    raise asyncio.TimeoutError()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_balance_paths():
    assert await solver(Client(balance=9.25)).balance() == 9.25
    assert await solver(Client(), key="").balance() is None
    assert await solver(Client(exc=RuntimeError("down"))).balance() is None


@pytest.mark.unit
def test_helpers_and_key_hygiene():
    assert _token_of({"code": "T"}) == "T" and _token_of("T") == "T" and _token_of(None) == ""
    assert _task_id_of({"captchaId": 5}) == "5" and _task_id_of("x") == ""
    assert _error_text(RuntimeError("x" * 500)).endswith("x") and len(_error_text(RuntimeError("x" * 500))) == 200
    s = SdkSolver("  secretkey12345678  ")
    assert s.has_key and "secretkey" not in repr(s.solve)  # key only in a private attr
    assert isinstance(sdk_available(), bool)
    if sdk_available():
        client = _default_factory("K" * 16, 45)
        assert type(client).__name__ == "AsyncTwoCaptcha"
    else:
        with pytest.raises(RuntimeError):
            _default_factory("K" * 16, 45)


@pytest.mark.unit
def test_import_sdk_falls_back_when_the_optional_package_is_broken(monkeypatch):
    """The SDK-missing lane — covered WITH or WITHOUT 2captcha installed.

    `test_helpers_and_key_hygiene` branches on `sdk_available()`, so the
    `except → None` path and the `None` guard were environment-dependent
    (coverage floor 98.8% only held when the optional package was absent).
    Forcing the import to fail pins that lane in every environment.
    """
    import builtins

    from app.services.captcha_watcher import sdk_solver

    real_import = builtins.__import__

    def refusing_import(name, *args, **kwargs):
        if name == "twocaptcha" or name.startswith("twocaptcha."):
            raise ImportError("twocaptcha refuses to import")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refusing_import)
    assert sdk_solver._import_sdk() is None      # except branch → None
    assert sdk_available() is False              # the gate other tests branch on
    with pytest.raises(RuntimeError, match="not installed"):
        _default_factory("K" * 16, 45)           # the None guard names the cause
