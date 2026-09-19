# 03 — Captcha: Watcher Isolation

> The app is responsible for **image processing**.
> Captcha solving is an optional service of the **Watcher window only**.

---

## 1. Before

```
single_job_runner ──► CHECK_SECURITY block ──► captcha.service.handle_captcha ──┐
batch_orchestrator ─► recovery.arm_resume / clear_resume / note_settle ─────────┤
multi_page_dispatcher ─► page_pool captcha flags ───────────────────────────────┼─► solver.py (own HTTP)
cooldown_service ──► captcha penalty timers ────────────────────────────────────┤        api_client.py
watcher ──► overlay "wait for user. Captcha" ───────────────────────────────────┘
```

Five owners, one shared solver, no single switch. Turning the Watcher off
left recovery timers, cooldown penalties and `CHECK_SECURITY` running.

## 2. After

```
              ┌──────────────── Watcher window (ON) ───────────────┐
 page tick ─► │ WatcherCaptchaStep.handle_page(cdp, tab_id, signal)│
              │        │                                          │
              │        ▼                                          │
              │  CaptchaGate.solve_if_watcher_on(tab_id, signal)   │
              │        │  watcher off ─► skipped("watcher_off")    │
              │        ▼                                          │
              │  SdkSolver.solve()  ── twocaptcha SDK ──► 2captcha │
              │        │                                          │
              │        ▼ inject token ► verify ► report good/bad   │
              └───────────────────────────────────────────────────┘

 job chain ─► sees a captcha ─► pauses the page ─► asks is_solving_enabled()
                                                  only to word the message
```

One entry point, one switch, per-page state.

## 3. Rules enforced by the code

| Rule | Where |
|---|---|
| Solving only while the Watcher runs | `CaptchaGate.why_disabled()` → `watcher_off` |
| Watcher off ⇒ zero network calls | gate returns before `SdkSolver` is constructed |
| One solve in flight per page | `GateState.in_flight[tab_id]` + lock |
| The chain cannot solve | chain imports `is_solving_enabled()` only; solver import is not reachable from `services/single_job_runner.py` |
| Never bypass, always verify | `_verify()` re-probes; unsolved ⇒ `report(task_id, False)` |
| Failures are visible | every outcome carries `reason`; the Watcher panel renders it |

## 4. Official SDK

Repository: <https://github.com/2captcha/2captcha-python> (from
<https://github.com/orgs/2captcha/repositories>)

```
pip install 2captcha-python
```

```python
from twocaptcha import TwoCaptcha

solver = TwoCaptcha(apiKey=key, defaultTimeout=180, pollingInterval=5)
result = solver.recaptcha(sitekey=sitekey, url=page_url, enterprise=1, invisible=1)
token  = result["code"]          # task id in result["captchaId"]
solver.report(result["captchaId"], True)   # or False when the token bounced
```

Supported families mapped in `sdk_client._DISPATCH`:

| `CaptchaSignal.kind` | SDK call |
|---|---|
| `recaptcha_v2`, `recaptcha_enterprise` | `solver.recaptcha(sitekey, url, enterprise=1, invisible=…)` |
| `recaptcha_v3` | `solver.recaptcha(…, version="v3", action=…, min_score=…)` |
| `hcaptcha` | `solver.hcaptcha(sitekey, url)` |
| `turnstile` | `solver.turnstile(sitekey, url)` |

Exception mapping (`sdk_client._ERRORS`):

| SDK exception | reason | retryable |
|---|---|---|
| `ValidationException` | `bad_request` | no |
| `NetworkException` | `network` | yes |
| `TimeoutException` | `timeout` | yes |
| `ApiException` | `api_error` | yes |

The SDK import is optional: when `2captcha-python` is absent the app boots
and the Watcher reports `2captcha SDK missing — pip install 2captcha-python`.

## 5. Removal map

| Delete / neutralise | Replacement |
|---|---|
| `app/services/captcha/api_client.py` (3.9 KB) | SDK |
| `app/services/captcha/solver.py` (28.6 KB) — transport, polling, retry | `SdkSolver.solve()` (~40 LOC) |
| `app/services/captcha/recovery.py` — `arm_resume`, `clear_resume`, `maybe_resume`, `note_settle` | `WatcherCaptchaStep` per-page state |
| `single_job_runner` captcha branches | pause the page; no solving |
| `cooldown_service` captcha penalty coupling | the gate reports; cooldown only reads the report |
| `CHECK_SECURITY` block "solve" path | detect + pause only |
| `#winCaptcha` controls | `js/panels/watcher/captcha-watch.js` |

Net: ≈ 1 100 LOC of protocol code removed, ≈ 470 LOC of gate + adapter +
step added, and five owners collapse to one.

## 6. Wiring

```python
# app/ui/bridge_context.py
from app.services.captcha.watcher_gate import CaptchaGate, install_gate
from app.services.captcha.sdk_client import SdkConfig

def _captcha_settings(bridge) -> SdkConfig:
    s = bridge._captcha_service().settings()
    return SdkConfig(api_key=s.api_key, timeout_sec=s.timeout_sec)

gate = install_gate(CaptchaGate(
    watcher_enabled=lambda: bridge._watcher.config.enabled,
    settings_getter=lambda: _captcha_settings(bridge),
    solving_enabled=lambda: bridge._watcher.config.captcha_solving,
    logger=bridge._log,
))
```

```python
# app/services/watcher_pkg/loop.py — inside the tick, per attached page
signal = await self.cdp_probe.detect_signal(cdp, tab_id)
await self.captcha_step.handle_page(cdp, tab_id, signal)
```

## 7. Compliance

Solving a captcha for a site you are automating may breach that site's terms.
The gate is **off by default**, requires an explicit toggle, records every
solve with a reason, and never hides a failure. When it is off the app does
exactly what its name says: it processes images.
