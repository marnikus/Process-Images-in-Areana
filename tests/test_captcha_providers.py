"""B10 — captcha provider dropdown restored: 2Captcha | CapMonster Cloud.

One official SDK, two hosts: the provider selects the SDK `server`
(2captcha.com | api.capmonster.cloud). Keys are stored per provider in
config/captcha_solvers.json (the pre-import multi-provider file); the
2026-10-02 single-provider file config/2captcha.json is folded in on the
first save. RULE 20: raw keys never cross the WebChannel; only masked forms.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.persistence.config_manager import ConfigManager
from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings
from app.services.captcha.service import CaptchaService
from app.services.captcha_watcher import providers as prov
from app.services.captcha_watcher.sdk_solver import SdkSolver, _default_factory
from app.services.captcha_watcher.signals import CaptchaSignal
from app.ui.panels import watcher_solver as ws
from app.ui.panels.watcher_captcha import WatcherCaptchaMixin
from app.ui.panels.watcher_solver import WatcherSolverMixin

pytestmark = pytest.mark.unit

K2 = "twocaptcha-key-0123456789"
KCM = "capmonster-key-0123456789"


# ------------------------------------------------------------------ registry

def test_registry_has_both_providers_with_their_hosts():
    assert prov.PROVIDER_IDS == ["2captcha", "capmonster"]
    assert prov.provider_server("2captcha") == "2captcha.com"
    assert prov.provider_server("capmonster") == "api.capmonster.cloud"
    assert prov.provider_label("capmonster") == "CapMonster Cloud"
    assert [p["id"] for p in prov.providers_summary()] == ["2captcha", "capmonster"]


@pytest.mark.parametrize("raw,expected", [
    ("2captcha", "2captcha"), (" CapMonster ", "capmonster"), ("", "2captcha"),
    (None, "2captcha"), ("anticaptcha", "2captcha"), (42, "2captcha"),
])
def test_unknown_or_blank_provider_falls_back_to_2captcha(raw, expected):
    assert prov.normalize_provider(raw) == expected


# ----------------------------------------------------------------- key store

def test_settings_keep_one_key_per_provider_and_expose_the_active_one():
    s = CaptchaSettings(provider="capmonster", keys={"2captcha": K2, "capmonster": KCM})
    assert s.api_key == KCM and s.key_for("2captcha") == K2
    switched = s.with_provider("2captcha")
    assert switched.api_key == K2 and switched.keys == {"2captcha": K2, "capmonster": KCM}
    cleared = switched.with_key("capmonster", "")
    assert cleared.keys == {"2captcha": K2} and cleared.key_for("capmonster") == ""
    explicit = CaptchaSettings(api_key="explicit-key-0123456789", keys={"2captcha": K2})
    assert explicit.keys["2captcha"] == "explicit-key-0123456789", "explicit api_key wins for the active provider"


def test_pre_import_multi_provider_file_loads_as_is(isolated_config_dir):
    # exact shape of the repo's config/captcha_solvers.json (old app)
    (isolated_config_dir / CaptchaKeyStore.FILENAME).write_text(json.dumps({
        "provider": "2captcha", "solve_timeout_sec": 180,
        "providers": {"2captcha": {"enabled": True, "api_key": K2},
                      "capmonster": {"enabled": True, "api_key": KCM}}}), encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.provider == "2captcha" and s.api_key == K2
    assert s.key_for("capmonster") == KCM and s.solve_timeout_sec == 180


def test_legacy_2captcha_json_overrides_the_2captcha_slot_until_migrated(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    (isolated_config_dir / CaptchaKeyStore.FILENAME).write_text(json.dumps({
        "provider": "capmonster",
        "providers": {"2captcha": {"api_key": "stale-2captcha-key-000"}, "capmonster": {"api_key": KCM}}}),
        encoding="utf-8")
    (isolated_config_dir / CaptchaKeyStore.LEGACY_FILENAME).write_text(json.dumps({
        "enabled": True, "api_key": K2, "solve_timeout_sec": 240}), encoding="utf-8")
    s = store.load()
    assert s.provider == "capmonster" and s.api_key == KCM
    assert s.key_for("2captcha") == K2, "the newer single-provider file wins for 2Captcha"
    assert store.has_legacy_file
    store.save(s.with_provider("2captcha"))
    assert not store.has_legacy_file, "first save folds config/2captcha.json away"
    again = CaptchaKeyStore(isolated_config_dir).load()
    assert again.provider == "2captcha" and again.api_key == K2 and again.key_for("capmonster") == KCM
    on_disk = json.loads((isolated_config_dir / CaptchaKeyStore.FILENAME).read_text(encoding="utf-8"))
    assert on_disk["provider"] == "2captcha"
    assert on_disk["providers"] == {"2captcha": {"enabled": True, "api_key": K2},
                                    "capmonster": {"enabled": True, "api_key": KCM}}


def test_only_legacy_file_present_is_imported(isolated_config_dir):
    (isolated_config_dir / CaptchaKeyStore.LEGACY_FILENAME).write_text(json.dumps({
        "enabled": False, "api_key": K2, "solve_timeout_sec": 300}), encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert (s.provider, s.api_key, s.solve_timeout_sec) == ("2captcha", K2, 300)


def test_corrupt_providers_block_and_unknown_ids_are_tolerated(isolated_config_dir):
    (isolated_config_dir / CaptchaKeyStore.FILENAME).write_text(json.dumps({
        "provider": "nope", "providers": ["not", "a", "dict"], "api_key": K2}), encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.provider == "2captcha" and s.api_key == K2  # flat key → active provider
    (isolated_config_dir / CaptchaKeyStore.FILENAME).write_text(json.dumps({
        "provider": "capmonster", "providers": {"capmonster": 12345, "2captcha": {"api_key": None}}}),
        encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.api_key == "12345" and s.key_for("2captcha") == ""


# ---------------------------------------------------------------- SDK solver

def test_solver_hands_the_provider_host_to_the_sdk(monkeypatch):
    made = []

    class FakeSdkModule:
        class AsyncTwoCaptcha:
            def __init__(self, key, **kw):
                made.append((key, kw))
    monkeypatch.setattr("app.services.captcha_watcher.sdk_solver._import_sdk", lambda: FakeSdkModule)
    _default_factory("k", 180, server="api.capmonster.cloud")
    assert made[-1][1]["server"] == "api.capmonster.cloud"
    _default_factory("k", 180)
    assert made[-1][1]["server"] == "2captcha.com"

    SdkSolver(K2, provider="capmonster")._client()
    assert made[-1] == (K2, {"defaultTimeout": 180, "recaptchaTimeout": 180, "pollingInterval": 5,
                             "server": "api.capmonster.cloud"})
    s = SdkSolver(K2, provider="CapMonster")
    assert s.provider == "capmonster" and s.provider_label == "CapMonster Cloud"
    assert SdkSolver(K2).provider == "2captcha"
    assert SdkSolver(K2, provider="bogus").provider == "2captcha"


def test_solver_solve_uses_the_injected_client_regardless_of_provider():
    seen = {}

    class Client:
        async def recaptcha(self, **kw):
            seen.update(kw)
            return {"captchaId": "77", "code": "tok"}
    solver = SdkSolver(K2, provider="capmonster", client_factory=lambda k, t: Client())
    sig = CaptchaSignal(visible=True, kind="recaptcha_v2", sitekey="sk", page_url="https://arena.ai", invisible=False)
    res = asyncio.run(solver.solve(sig))
    assert res.ok and res.token == "tok" and seen["sitekey"] == "sk"


# ------------------------------------------------------------------ slots

class Host(WatcherSolverMixin, WatcherCaptchaMixin):
    pass


def make_host(cfg):
    host = Host()
    host.config = cfg
    host.logs = []
    host._log = lambda m, l="info": host.logs.append((m, l))
    host._watcher = None
    return host


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


def test_provider_switch_keeps_each_providers_key(cfg):
    host = make_host(cfg)
    assert json.loads(host.set_captcha_api_key(K2))["provider"] == "2captcha"
    sw = json.loads(host.set_captcha_provider("capmonster"))
    assert sw["ok"] and sw["provider"] == "capmonster" and sw["has_key"] is False
    assert json.loads(host.set_captcha_api_key(KCM))["masked_key"] == CaptchaKeyStore.mask(KCM)
    back = json.loads(host.set_captcha_provider("2captcha"))
    assert back["has_key"] is True and back["masked_key"] == CaptchaKeyStore.mask(K2)
    by_id = {p["id"]: p for p in back["providers"]}
    assert by_id["2captcha"]["has_key"] and by_id["capmonster"]["has_key"]
    assert K2 not in json.dumps(back) and KCM not in json.dumps(back)
    assert K2 not in json.dumps(host.logs) and KCM not in json.dumps(host.logs)
    assert any("Captcha provider: CapMonster Cloud" in m for m, _ in host.logs)


def test_unknown_provider_is_rejected_without_touching_the_file(cfg):
    host = make_host(cfg)
    host.set_captcha_api_key(K2)
    res = json.loads(host.set_captcha_provider("anticaptcha"))
    assert res["ok"] is False and "unknown provider" in res["error"]
    assert CaptchaKeyStore(cfg.dir).load().provider == "2captcha"


def test_solver_factory_follows_the_active_provider(cfg):
    host = make_host(cfg)
    host.set_captcha_api_key(K2)
    host.set_captcha_provider("capmonster")
    assert ws.make_solver(host) is None, "no CapMonster key yet → no solver"
    st = json.loads(host.watcher_start())
    assert st == {"ok": False, "running": False, "error": "no api key"}
    assert any("no CapMonster Cloud key" in m for m, _ in host.logs)
    host.set_captcha_api_key(KCM)
    solver = ws.make_solver(host)
    assert solver.provider == "capmonster" and solver.has_key
    status = json.loads(host.watcher_status())
    assert (status["provider"], status["provider_label"], status["has_key"]) == ("capmonster", "CapMonster Cloud", True)


def test_legacy_settings_slot_keeps_the_other_providers_key(cfg):
    host = make_host(cfg)
    host.set_captcha_api_key(K2)
    host.set_captcha_provider("capmonster")
    res = json.loads(host.set_captcha_settings(json.dumps({"api_key": KCM, "solve_timeout_sec": 200})))
    assert res["ok"] and res["provider"] == "capmonster"
    s = CaptchaKeyStore(cfg.dir).load()
    assert s.key_for("2captcha") == K2 and s.key_for("capmonster") == KCM and s.solve_timeout_sec == 200
    assert json.loads(host.get_captcha_status())["provider"] == "capmonster"


def test_service_status_payload_reports_the_provider(isolated_config_dir):
    svc = CaptchaService(str(isolated_config_dir))
    svc.keys.save(CaptchaSettings(provider="capmonster", keys={"capmonster": KCM}))
    assert svc.status_payload()["provider"] == "capmonster"
    assert svc.status_payload()["masked_key"] == CaptchaKeyStore.mask(KCM)


def test_balance_log_names_the_provider(cfg, monkeypatch):
    host = make_host(cfg)
    host.set_captcha_provider("capmonster")
    host.set_captcha_api_key(KCM)
    monkeypatch.setattr(ws, "schedule_coro", lambda bridge, coro: asyncio.run(coro))

    async def balance():
        return 1.5
    monkeypatch.setattr(ws, "make_solver", lambda bridge: SimpleNamespace(
        has_key=True, balance=balance, provider="capmonster", provider_label="CapMonster Cloud"))
    host.captcha_balance()
    assert any("CapMonster Cloud balance $1.50" in m for m, _ in host.logs)
