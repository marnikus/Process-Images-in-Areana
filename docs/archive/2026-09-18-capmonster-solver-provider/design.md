# CapMonster Cloud as a second solver provider — research + design

Date: 2026-09-18 · Branch: `arena/01a0b61b-process-images-in-areana` · Status: design → implemented
Process: user-requested — add `https://docs.capmonster.cloud/docs/category/api/` (CapMonster Cloud) as a
**second solver option**, selected via a **provider drop-down** in the Captcha window, with **the same
fields as 2Captcha** (enable, API key, solve timeout). Per RULE 16 §16.6: doc first, tests first,
then code; re-check RULE 18 / RULE 16 at the end.

## 1. Problem, verified in code

Auto-solve is hardwired to 2Captcha at six points:

| Point | File | Coupling |
|---|---|---|
| Wire client | `app/services/captcha/api_client.py` | `API_BASE = "https://api.2captcha.com"`, numeric `errorId` classifier, `POLL_INTERVAL_SEC = 5.0`, `deleteTask` |
| Task types | `app/services/captcha/solver.py` `_TASK_TYPES` / `task_type_for` | `RecaptchaV2EnterpriseTaskProxyless` / `RecaptchaV2TaskProxyless` |
| Store | `app/services/captcha/key_store.py` | one file `config/2captcha.json`, one key, `FILENAME = "2captcha.json"` |
| Service | `app/services/captcha/service.py` | `apply_settings(api_key, enabled, timeout)`, `refresh_balance` builds `Captcha2Client`, log texts say "2Captcha" |
| Bridge slot | `app/ui/bridge.py` `set_captcha_settings` | passes key/enabled/timeout only |
| UI | `app/ui/web/index.html` (`winCaptcha`) + `js/panels/captcha.js` | fixed "2Captcha" labels, no provider control |

Everything else — detect probe, inject probe, choke point `handle_captcha`, stats, recordings,
recovery, penalty — is provider-agnostic already (they consume `SolveOutcome`, never the client).

## 2. Research — CapMonster Cloud API (official docs, fetched 2026-09-18)

Sources: `docs.capmonster.cloud` — `docs/api/methods/get-task-result/`, `docs/api/api-errors/`,
`docs/captchas/no-captcha-task/` (reCAPTCHA v2), `docs/captchas/recaptcha-v2-enterprise-task/`.

Same anti-captcha-style JSON protocol as 2Captcha v2: all `JSON POST`, `clientKey` travels in the
body (never in a URL — same RULE 20 hygiene as today).

| Aspect | 2Captcha (today) | CapMonster Cloud |
|---|---|---|
| Base URL | `https://api.2captcha.com` | `https://api.capmonster.cloud` |
| Methods | `createTask`, `getTaskResult`, `getBalance`, `deleteTask` | `createTask`, `getTaskResult`, `getBalance` — **no `deleteTask`**; unsolved tasks are not charged |
| Enterprise task type | `RecaptchaV2EnterpriseTaskProxyless` | `RecaptchaV2EnterpriseTask` (proxyless is the default; no `Proxyless` suffix) |
| v2 task type | `RecaptchaV2TaskProxyless` | `RecaptchaV2Task` |
| `isInvisible` | documented for v2 **and** enterprise | documented for `RecaptchaV2Task` only; **not** a documented enterprise field (their Go client omits it) → do not send it there |
| `taskId` | string | **integer** → echo the raw `createTask` value back, never re-type it |
| Result | `{errorId, status: processing\|ready\|failed, solution.gRecaptchaResponse}` | `{errorId, status: "processing"\|"ready", solution.gRecaptchaResponse}` (+ optional `userAgent`/`cookies` — ignored by our injector) |
| Errors | numeric `errorId` (2 = key, 3 = credit, 16 = not found, 1 = unavailable) | string `errorCode`: `ERROR_KEY_DOES_NOT_EXIST`, `ERROR_ZERO_BALANCE`, `ERROR_NO_SUCH_CAPCHA_ID`/`WRONG_CAPTCHA_ID`, `ERROR_CAPTCHA_UNSOLVABLE`, `ERROR_SERVICE_NOT_AVAILABLE`, `ERROR_TOO_MUCH_REQUESTS`, `CAPTCHA_NOT_READY`, … |
| Poll cadence | ~5 s (docs-recommended) | ≥2 s between polls, ≤120 requests per task → we use 3 s |
| Pending signal | `status:"processing"` | `status:"processing"` **or** error `CAPTCHA_NOT_READY` (must keep polling, not fail) |

Both solve the same site widget with the same payload fields we already send (`websiteURL`,
`websiteKey`, enterprise type, `isInvisible` where documented). The injection/verification flow after
the token arrives is provider-independent.

## 3. Design

One new leaf module + provider param threaded through the existing seams. No choke-point change,
no probe change, no `SolveOutcome.status` change.

```
app/services/captcha/
  providers.py   NEW  ProviderSpec (id/title/api_base/poll/task types/error classifier/
                      can_delete/pending codes) + PROVIDERS + provider_for(); unknown id → 2Captcha
  api_client.py       Captcha2Client → SolverApiClient(key, spec, timeout_sec): base URL, error
                      classifier, poll interval and delete support come from spec; taskId echoed raw
  key_store.py        CaptchaSettings gains provider; per-provider creds {enabled, api_key};
                      store file config/captcha_solvers.json (git-ignored, 0600); legacy
                      config/2captcha.json migrated on load (read-only, never deleted)
  solver.py           spec-driven task types, poll interval, log titles, payload builder
                      (isInvisible only where the provider documents it); outcome carries task_type
                      + poll_interval_s so the CAPTCHA_SOLVE report stays honest
  service.py          apply_settings(provider, …), status_payload gains provider + per-provider
                      masked list, refresh_balance uses active provider, provider titles in logs
app/ui/bridge.py      set_captcha_settings passes provider through (1 line) + provider in log line
app/ui/web/           Captcha window: solver-provider <select> (2Captcha / CapMonster Cloud) above
                      the unchanged enable/key/timeout fields; switching reloads that provider's
                      masked status; save posts the selected provider
```

### 3.1 Why a spec dataclass, not an if-chain

Every provider difference is **data** (URL, type names, error table, cadence) except two tiny
classifiers. RULE 19 step 2: lookup tables instead of if/elif chains — tables are data, not
branches. A `ProviderSpec` with two instances keeps every downstream function signature unchanged
(`SolverApiClient(key, spec)` = 2 params) and lets the solver/service treat providers uniformly.
Adding a third provider later = one new spec instance + one `<option>`, zero branch edits.

### 3.2 Stable error reasons (contract preserved)

CapMonster string codes map onto the **same reason tokens** 2Captcha uses today, so solver/service
fallback logic (`bad_key`, `no_credit`, `not_found`, `unavailable`, `task_error`, `network`) is
untouched: `ERROR_KEY_DOES_NOT_EXIST`→`bad_key`, `ERROR_ZERO_BALANCE`→`no_credit`,
`ERROR_NO_SUCH_CAPCHA_ID`/`WRONG_CAPTCHA_ID`→`not_found`,
`ERROR_SERVICE_NOT_AVAILABLE`/`ERROR_IP_NOT_ALLOWED`/`ERROR_IP_BANNED`/`ERROR_TOO_MUCH_REQUESTS`→`unavailable`,
`CAPTCHA_NOT_READY`→`pending` (client converts to a `processing` result — poll continues),
everything else→`task_error` (terminal, same as 2Captcha `status:"failed"`).

### 3.3 Key store v2 — same fields, per provider

"Same fields as the previous" ⇒ each provider owns **enabled + API key**; **solve timeout** is one
shared field (it is a single "how long do we wait" control, RULE 10). Store document:

```json
{"provider": "2captcha", "solve_timeout_sec": 180,
 "providers": {"2captcha":     {"enabled": true,  "api_key": "…"},
               "capmonster":   {"enabled": false, "api_key": ""}}}
```

* `CaptchaSettings` keeps `.api_key` / `.enabled` as **properties of the active provider**, so
  solver/auto_enabled code reads identically to today.
* **Migration:** missing new file + legacy `2captcha.json` present → import enabled/key/timeout as
  the 2Captcha entry (RULE 13: never lose readable state). The legacy file is left on disk untouched.
* **Empty key field on Save = keep the stored key** for that provider (the UI clears the field after
  every save; with two providers, "re-save wipes key" would become a footgun — a deliberate,
  documented behaviour change). Enabled still requires a key.
* Raw keys still never leave the store; only `masked_key` (`abcd****wxyz`) crosses the WebChannel.

### 3.4 RULE 20 wording follows reality

RULE 20 says the key lives only in `config/2captcha.json` and that 2Captcha is the only upload
endpoint. With owner-authorized opt-in extended to a second provider, `docs/current/AGENT_RULES.md`
RULE 20 is amended in the same change (docs must state today's truth, RULE 17): keys live only in
`config/captcha_solvers.json`; tasks go only to the **configured** provider endpoint
(`api.2captcha.com` **or** `api.capmonster.cloud`). Default OFF and manual fallback unchanged.

## 4. Behaviour contract (unchanged where possible)

`handle_captcha` statuses stay exactly: `none | solved | manual | stopped | page_error | token_stale |
auto_failed`. New in reports/logs only: provider title in log lines; `CAPTCHA_SOLVE` report gains the
provider-true `task_type` (e.g. `RecaptchaV2EnterpriseTask`) and the provider's real `poll_interval_s`.
Provider switch is live per save; a job in flight keeps the provider it started with (settings are
read at solve start). Failure of one provider never touches the other's credentials.

## 5. Measurements (before → target)

Radon `cc -s`, physical LOC (AST span). Gate: RULE 16 fail >30 LOC / >4 params / CC >10; ideal RULE 18
4–20 LOC, CC ≤7.

| Function | Before (LOC/CC) | After target |
|---|---|---|
| `api_client._post` | 16/4 | ≤18, CC ≤5 (spec classifier call) |
| `api_client.create_task` | 7/2 | ≤9 (echo raw id) |
| `api_client.get_result` | 3/1 | ≤8 (pending → processing) |
| `api_client.delete_task` | 7/2 | ≤8 (spec.can_delete guard) |
| `key_store.load/_from_dict/save/_to_dict` | 8/4 · 7/3 · 11/1 · 6/2 | +migration ≤12 LOC each, CC ≤6 |
| `solver._solve_once` | 15/— | ≤17 (spec lookup line) |
| `solver._create_task` | 17/— | ≤18 (spec.task_type_for) |
| `solver._task_payload` | 8/— | ≤10, CC ≤3 (spec-gated isInvisible) |
| `solver._poll_task` | 29/10 (legacy, at gate) | **not worsened**; interval from spec (0 net branches) |
| `service.apply_settings` | 7/3 | ≤12, CC ≤4 (provider param) |
| `service.status_payload` | 7/— | ≤10 |
| `service._resolve_captcha` | 20/10 (legacy, at gate) | **not worsened** — provider title via existing `_log` arg text |
| NEW `providers.py` functions | — | ≤20 LOC, CC ≤5, file ≤120 LOC |
| `Bridge.set_captcha_settings` | legacy | +≤2 lines (provider passthrough) |

New files target RULE 18 bands: `providers.py` ≤120 (leaf), edited files stay within current+15.
Rejected dishonest reductions: no per-provider subclass of the client (adds methods to dodge a data
table); no `foo_part1` splits; `_poll_task`'s existing 29 LOC / CC 10 is legacy — this change must
not add a branch to it (interval comes from the plan's spec, `plan.spec.poll_interval_sec`).

## 6. Tests (RULE 8 — behaviour, fake transport)

* NEW `tests/test_captcha_providers.py` — spec lookup + unknown→default; task types per provider per
  kind; `isInvisible` presence per provider payload; CapMonster error table → stable tokens;
  `CAPTCHA_NOT_READY` → pending; poll interval values; `can_delete` flags.
* `tests/test_captcha_api_client.py` — rename to `SolverApiClient` + spec; CapMonster flows: int
  taskId echoed untouched into getTaskResult, errorCode→ApiError reason, no `deleteTask` request when
  `can_delete` false, base URL per spec, key still never in URL.
* `tests/test_captcha_key_store.py` — new store round-trip per provider; shared timeout; legacy
  `2captcha.json` migration; new-file precedence; enabled-requires-key per provider; empty-key save
  keeps stored key; still 0600 + atomic.
* `tests/test_captcha_solver.py` — solve flow under CapMonster spec (fake client): task type from
  spec, outcome carries task_type/poll interval; `no_key` message names the provider.
* `tests/test_captcha_service.py` — `apply_settings` routes per provider; `auto_enabled` follows the
  active provider; balance via active provider; status payload exposes per-provider masks only.
* `tests/test_bridge_slots.py` — slot list unchanged (provider travels inside the existing payload).

## 7. UI copy

Window title `Captcha — 2Captcha` → `Captcha — Solver`. New first row: `Solver provider` select
(`2Captcha`, `CapMonster Cloud`). Enable/Key/Timeout rows unchanged (they act on the selected
provider). Status line shows the selected provider's state; switching provider reloads status and
clears the key field. Footnote updated: tasks go only to the selected provider's official endpoint.

## 8. Explicitly out of scope

Balance-driven provider failover, mixed-provider retries, CapMonster `userAgent`/`cookies` echo
(our injector sets the page's own fields), and any proxy-bearing task type (we stay proxyless —
CapMonster's proxyless default is built-in proxies on their side).
