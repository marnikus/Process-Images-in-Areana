# 2Captcha solving integration — research + design

Date: 2026-09-17 · Branch: `arena/01a0b1a7-process-images-in-areana` · Status: design → implemented
Process: user-requested feature (01 service, 02 detection & solving, 03 settings UI, 04 per-page handling)
+ "verify last added code" against `docs/current/AGENT_RULES.md`, esp. RULE 18 / RULE 16.

## 1. Current state (verified in code)

Captcha handling today is **detect → pause → user solves manually → stack cooldown penalty**:

| Site | Where | Behaviour |
|---|---|---|
| `CHECK_SECURITY` block, single run batch | `app/ui/bridge.py` run loop (~78 inline lines) | dialog visible → overlay `wait for user. Captcha` + run pause + 2 s poll until gone → `note_captcha_event` |
| Phase boundaries (after SUBMIT, before DOWNLOAD) | `Bridge._settle_boundary_captcha` → `cooldown_service.wait_captcha_cleared` | same wait + record, `RuntimeError` on stop |
| Generation-wait cycles (single path) | inline in WAIT_OUTPUT loop | overlay swap to captcha, wait + record, restore gen overlay |
| Dispatcher + block runner path | `single_job_runner.check_security` | overlay + `pool.mark_waiting` + wait + `note_captcha_penalty` via `note_captcha_event` |
| Watcher (default OFF) | `app/services/watcher.py` | passive detection, waits, **never records** (single-controller, cannot attribute a tab) |

Detection predicate (single source, in two places): `CDPArenaController.is_security_dialog_visible()` /
`JS_SECURITY_DIALOG` — open `div[role="dialog"]` containing "Security Verification", or visible
`iframe[title="reCAPTCHA"]`. Penalty recording choke point: `note_captcha_event` (2026-09-17 fix).

**Last-added code verification (user request) — measured on this branch before change:**

| Function | LOC | CC | Gate (≤30 / ≤10) | RULE 18 ideal (4–20) |
|---|---:|---:|---|---|
| `note_captcha_event` | 17 | 5 | pass | pass |
| `wait_captcha_cleared` | 18 | 7 | pass | pass |
| `add_captcha_penalty` | 14 | 5 | pass | pass |
| `_penalty_from` / `_persist_emit` / `_captcha_suffix` | 9 / 9 / 6 | 3 / 2 / 4 | pass | pass |
| `Bridge._settle_boundary_captcha` | 30 | 9 | pass (at line) | 30 > 20 — at hard line, see §9 |
| `check_security` (single_job_runner) | 25 | 6 | pass | 25 > 20 — improved by this change (§9) |
| `_wait_security_gone` / `_apply_captcha_penalty` | 12 / 8 | 5 / 2 | pass | pass |

`pytest` baseline **234 passed**; `tools/verify_quality.py --allow-legacy` reports the last-added
files clean (all 149 remaining fails are pre-existing legacy hotspots downgraded per baseline).

## 2. Research — target site captcha architecture (from saved HTML, `arena webpages/state/`)

* Page ships a **Cloudflare challenge** + **Lion bot score** + **reCAPTCHA v3 (invisible) scoring**
  on every request: `botScoreType:"recaptcha_v3"`, `recaptchaV3Score:1`,
  `recaptchaReason:"lion_above_threshold"`, `recaptchaOutcome:"accept"` (score-based, silent).
* Always-present **invisible reCAPTCHA Enterprise badge** (bottom-right, `aria-hidden`).
* When the bot score is too low the backend escalates: the **"Security Verification" dialog** with a
  **visible reCAPTCHA (Enterprise) widget** — anchor iframe (`iframe[title="reCAPTCHA"]`),
  `grecaptcha-error` div, hidden response field
  `textarea#g-recaptcha-response-100000[name="g-recaptcha-response"]` (standard widget markup).
* User clicks the checkbox → Google writes the token into the hidden field → site submits it →
  dialog closes.

Implications:
* The *visible dialog* is the detectable, actionable surface (what `is_security_dialog_visible`
  already targets). The silent v3 scoring flow has **no DOM surface** to detect or interact with —
  **out of scope** (solving it needs request interception before the request; invasive and
  site-fragile).
* 2Captcha returns a **token** (`gRecaptchaResponse`). Their documented integration: *"sent to the
  target website inside `g-recaptcha-response` form field or passed to a callback function."*
  Cross-origin Google iframe cannot be clicked from our side, so the only supported path is:
  **set the hidden response field + trigger the site's own dialog action, then verify**.

## 3. Research — 2Captcha API v2 (https://2captcha.com/api-docs)

JSON API, all `POST https://api.2captcha.com/<method>`, body JSON, `clientKey` in body
(key never in URL — good for log hygiene):

| Method | Body | Success |
|---|---|---|
| `createTask` | `{clientKey, task:{type, websiteURL, websiteKey, ...}}` | `{errorId:0, taskId}` |
| `getTaskResult` | `{clientKey, taskId}` | `{errorId:0, status:"ready"|"processing"|"waiting"|"failed", solution:{gRecaptchaResponse}}` |
| `getBalance` | `{clientKey}` | `{errorId:0, balance}` |
| `deleteTask` | `{clientKey, taskId}` | `{errorId:0}` — frees credit for unsolved/abandoned tasks |

Task type for this site: **`RecaptchaV2EnterpriseTaskProxyless`** (v2 → `RecaptchaV2TaskProxyless`).
`websiteURL` = live page URL, `websiteKey` = sitekey (from widget `data-sitekey` or anchor-iframe
`k=` param; Google sitekeys match `6L[A-Za-z0-9_-]{29,}`). Docs recommend polling `getTaskResult`
at ~5 s cadence. Known `errorId`s handled: `1 CAPTCHA_UNAVAILABLE`, `2 KEY_DOESNT_EXIST`,
`3 NOT_ENOUGH_CREDIT`, `16 TASK_NOT_FOUND`; `status:"failed"` = CAPTCHA wasn't solvable.

## 4. RULE 20 — policy change (owner-authorized)

User explicitly requested outsourcing solving to 2Captcha. RULE 20 today forbids it. Amended:

* Default (OFF): unchanged — pause with `USER_ACTION_REQUIRED`, user solves manually.
* Opt-in (ON + key): the visible Security-Verification captcha **may be sent to 2Captcha**.
  Any failure (bad key, no credit, unsolvable, timeout, stop) **falls back to the manual flow** —
  the job is never lost to a solver failure. Auto-solved captchas still stack the cooldown penalty
  (user's existing "detected ⇒ penalty" behaviour, solver is irrelevant to the rate limit).
* Keep: respect target ToS/permissions/rate limits; user-authorized URLs only; credentials out of
  logs; uploads only to user-configured destinations (the 2Captcha endpoint is the only one).

## 5. Architecture

Layering respected (`ui → browser → services → core`, no cycles):

```
app/browser/captcha_js/{detect,inject,continue_click}.js   page-side probe sources (self-contained)
app/browser/captcha_probes.py                              reads the JS files → evaluate-ready strings
app/services/captcha/
  __init__.py                                               re-exports
  api_client.py    Captcha2Client (aiohttp) — create/result/balance/delete, ApiError codes
  key_store.py     CaptchaKeyStore — config/2captcha.json, 0600, masked getters (RULE 20 hygiene)
  stats.py         CaptchaStatsStore — config/captcha_stats.json, atomic, corrupt-tolerant (RULE 13)
  solver.py        CaptchaSolver — per-tab inflight map, poll loop, inject+verify, never raises
  service.py       CaptchaCtx + handle_captcha() — THE choke point (all call sites route through it)
app/ui/bridge.py   +3 WebChannel slots, +1 lazy getter; 4 inline captcha blocks replaced by choke point
```

* **One choke point** (same pattern as `note_captcha_event`): every captcha call site
  (`CHECK_SECURITY` block, submit/download boundaries, gen-wait cycles, dispatcher path via
  `check_security`) calls `handle_captcha(CaptchaCtx)` — detect → stats → auto-solve (if enabled)
  → manual fallback (overlay + wait) → penalty record. Per-page independence falls out: each tab's
  job is its own asyncio task, the solver's inflight map is keyed by `tab_id`, so tab A's solve
  never blocks tab B (multi-tasking, requirement 02/04), and two racing checks on one tab share one
  2Captcha task (no double billing).
* **Why the JS lives in `.js` files read by Python:** target page is arena.ai — probes must be
  self-contained CDP-evaluated strings (no script tags on the target). A single source file lets
  **node tests execute the real probes** (RULE 8) instead of string-asserting, and keeps the
  browser-layer Python wrapper small.
* **Key store design ("not expose publicly"):** key in `config/2captcha.json` (git-ignored, mode
  0600 best-effort), separate from `session.json` **and** from preset export/import (presets carry
  `arena.json` settings — a shared file that must never carry the key). Bridge returns only
  `masked_key` (`abcd****wxyz`); UI input is `type=password` with an explicit show toggle; key is
  never logged (log lines use `key=****`); only ever sent to `api.2captcha.com`.
* **Injection + verify (honest limits):** 2Captcha cannot click inside Google's cross-origin
  iframe. Flow: (1) set dialog-scoped then document-scoped
  `textarea/input[name="g-recaptcha-response"]` (React-safe setter + `input`/`change` events),
  (2) click the dialog's semantic action button (`button[type=submit]`, verify/continue/confirm
  aria-label or text), (3) poll dialog-gone up to 20 s grace. Dialog gone ⇒ solved; otherwise
  `deleteTask` (refund) + manual fallback. Success rate therefore measures real end-to-end solves.

## 6. Behaviour contract (what the choke point returns)

`SolveOutcome.status`:

* `none` — no captcha visible (normal no-op; caller treats as success),
* `solved` — 2Captcha token accepted, dialog gone; penalty recorded (source-tagged),
* `manual` — auto disabled/failed/fell back, user (or prior state) cleared it; penalty recorded,
* `failed` — still visible after auto+manual wait windows; penalty **not** recorded, job-level
  error text distinguishes "captcha unsolved" (RULE 4: broken ≠ empty),
* `stopped` — stop/pause requested mid-flow (RULE 7); 2Captcha task deleted, penalty not recorded.

Penalty records exactly once per visible→gone edge (same dedup rule as the 2026-09-17 fix).

## 7. Settings UI (requirement 03)

Settings window gains a **Captcha solving (2Captcha)** section:

* Enable checkbox, API key (password field + show toggle), solve timeout (minutes, 0.5–10),
* Save → `set_captcha_settings` → key store + solver reconfig + async balance check,
* Status row: `key ****wxyz · balance $12.34 (checked 12:03) · last error: —`,
* Stats grid: detected total / auto solved / auto failed / **auto success %** / manual fallback /
  per-site counts — all local counters + `getBalance` from the API ("additional stats available
  via the API" = balance; the v2 API exposes no per-task history endpoint, so task counts are
  tracked locally and labeled as such),
* `get_captcha_status` refreshes balance when stale (>60 s); `get_captcha_stats` returns counters.

## 8. Tests (RULE 8 — failing-first)

* `tests/test_captcha_api_client.py` — fake aiohttp session: payload shape (clientKey in body,
  correct task type per kind), ready/processing/failed mapping, balance, deleteTask, errorId→ApiError
  (2 bad_key, 3 no_credit, 16 not_found, 1 unavailable), network error, **key never in URL/logs**.
* `tests/js/test_captcha.mjs` (node --test) — executes the real probe files against a purpose-built
  stub DOM: detect (dialog+iframe k=, data-sitekey fallback, no-dialog, image-captcha kind),
  inject (dialog-scoped field, document fallback, event dispatch, no-field case), continue click
  (submit button, aria verify, text match, none found).
* `tests/test_captcha_solver.py` — fake ctrl + fake API: success (poll processing→ready→inject→
  gone; stats + penalty once), API error → manual fallback (penalty once after manual clear),
  stop mid-poll (task deleted, `stopped`), inflight dedup (2 callers → 1 createTask), parallel
  tabs (2 createTask, independent).
* `tests/test_captcha_service.py` — choke point: no dialog → `none` (no penalty), enabled+solvable
  → `solved` + `note_captcha_event` called with source, disabled → `manual`, probe error → fail
  open to normal flow (RULE 9), stop → `stopped` (no penalty).
* `tests/test_captcha_stats.py` / `test_captcha_key_store.py` — persistence, corrupt file →
  defaults (RULE 13), atomic replace, masking, missing file, chmod best-effort.
* `tests/test_captcha_boundaries.py` — existing boundary contract (wait + record + stop-raise)
  must stay green through the choke-point refactor.
* `tests/test_bridge_slots.py` — new slots registered; `package.json test:js` gains the new mjs.

## 9. Size targets (RULE 18) and gates (RULE 16)

* New module `app/services/captcha/`: 6 files + `__init__` (5–15 ✓); files 110–210 lines (150–300
  band, leaves under 150 normal); `app/browser` gains 1 py + 3 js.
* Every new function 4–20 LOC (aim ~8–12), ≤4 params (Ctx dataclasses carry the rest — established
  pattern: `JobCtx`/`FinishCtx`/`ResetCtx`), CC ≤10 (aim ≤7), nesting ≤4 (aim ≤3).
* `Bridge`: +4 methods (3 WebChannel slots = wire-format constraint per §16.4, +1 lazy getter);
  **net line delta negative** — the ~130 lines of inline captcha code (CHECK_SECURITY block 78,
  gen-wait 45, boundary 24) are deleted and replaced by ~40 lines of choke-point calls. RULE 16.5
  "extract on touch" satisfied: the class shrinks in the same change that adds its slots.
* `single_job_runner.check_security`: 25 → ~14 LOC (body replaced by choke-point call).
* Legacy offenders (`CDPArenaController` 26 methods, `Bridge`) gain **zero** controller methods —
  the solver evaluates probes via `ctrl.cdp.evaluate(...)` like `reset_to_new_chat` does with the
  client, so no method is added to any class at its method limit.
* Rejected dishonest reductions: no `foo_part1` splits; the 20-line verify-grace poll stays one
  function (it is one straight-line decision); Ctx dataclass is not a param-dodge (named domain
  concept used by 4 call sites).

## 10. Deferred (with rationale)

* Watcher-side auto-solve: watcher is single-controller and cannot attribute a tab (2026-09-17
  doc); default OFF; its detection still surfaces captchas visually. Revisit if watcher gets a
  pool.
* Silent v3 scoring flow: no DOM surface; requires request interception (invasive, fragile).
* reCAPTCHA v2 (non-enterprise) task type is supported by the client (`RecaptchaV2TaskProxyless`)
  for any user-authorized site that uses it; detection kind drives the type.
