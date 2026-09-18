# Summary — 2Captcha auto-solve integration (opt-in) + settings UI

Date: 2026-09-17 · Branch: `arena/01a0b1a7-process-images-in-areana`

Full research + design: `design.md` (same folder). This file records the final
state after implementation + verification.

## What was delivered (user request 01–04)

1. **01 SERVICE** — `app/services/captcha/api_client.py`: 2Captcha v2 REST
   (`createTask` / `getTaskResult` / `getBalance` / `deleteTask`), `ApiError`
   with stable reason tokens (`no_credit`, `bad_key`, `unavailable`,
   `task_error`, `network`), per their api-docs (poll until `ready`,
   `solution.gRecaptchaResponse`).
2. **02 DETECTION & SOLVING** — per-page detect probe
   (`app/browser/captcha_js/detect.js`): open "Security Verification" dialog /
   visible reCAPTCHA iframe → kind (`recaptcha_enterprise` / `recaptcha_v2` /
   `image` / …) + sitekey (iframe `k=` or `data-sitekey` or script scan) +
   page URL. `CaptchaSolver`: one inflight asyncio task **per tab** (two racing
   checks share one 2Captcha task — no double billing), different tabs solve in
   parallel; poll (honours stop) → inject token into `g-recaptcha-response`
   (dialog-scoped, React-safe setter + input/change events, document fallback)
   → click dialog continue → 20 s verify-grace. Task type
   `RecaptchaV2EnterpriseTaskProxyless` (proxyless, per docs "most cases").
3. **03 SETTINGS UI** — Settings panel 2Captcha section: enable toggle, API
   key (masked display only), solve timeout 30–600 s, live balance,
   statistics (detected / auto-solved / auto-failed / manual / success rate /
   per-site). **Key structure (not exposed publicly):** separate git-ignored
   `config/2captcha.json` (0600 best-effort, never in arena.json/session.json
   so presets cannot carry it); WebChannel payloads carry `masked_key`
   (`abcd****7890`) + `has_key` only; raw key never logged, never in error
   text; saving re-reads the stored key so an empty input keeps it.
4. **04 PER-PAGE HANDLING** — every call site (CHECK_SECURITY block,
   submit/download boundaries, gen-wait cycles, dispatcher path) routes through
   ONE choke point `handle_captcha(CaptchaCtx)`: detect → stats → auto-solve
   (if enabled) → manual fallback → penalty recorded exactly once per solved
   edge. Solving is per-tab independent; a solve on tab A never blocks tab B.

## RULE 20 amendment (owner-authorized)

Default OFF = unchanged (manual `USER_ACTION_REQUIRED`). Opt-in ON + key:
visible captcha MAY be sent to 2Captcha; any failure falls back to manual —
a job is never lost to a solver failure; auto-solved captchas still stack the
cooldown penalty. `docs/current/AGENT_RULES.md` RULE 20 rewritten accordingly.

## Files

- New module `app/services/captcha/` — `api_client.py`, `key_store.py`,
  `signals.py`, `solver.py`, `service.py`, `stats.py`, `__init__.py`
- New `app/browser/captcha_js/` — `detect.js`, `inject.js`, `continue_click.js`
  (evaluated via `ctrl.cdp.evaluate`, like the existing probe pattern)
- New `app/browser/captcha_probes.py` — probe loader/builders
- `app/ui/bridge.py` — +3 WebChannel slots (`set_captcha_settings`,
  `get_captcha_status`, `get_captcha_stats`) + lazy `_captcha_service` getter;
  4 inline captcha blocks replaced by the choke point (net line delta
  negative)
- `app/services/single_job_runner.py` — `check_security` body → choke-point call
- `app/ui/web/index.html`, `app/ui/web/js/panels/settings.js` — 2Captcha panel
- Tests: `tests/test_captcha_api_client.py`, `test_captcha_key_store.py`,
  `test_captcha_signals` (in solver file), `test_captcha_solver.py`,
  `test_captcha_service.py`, `test_captcha_stats.py`,
  `tests/js/test_captcha.mjs` (15 tests, real probe files, stub DOM);
  `test_captcha_boundaries.py` (existing contract, re-verified);
  `test_bridge_slots.py` extended; `package.json` `test:js` extended
- Docs: RULE 20 amendment, SYSTEM_OF_RECORD rows 8/12/20 + storage map +
  invariant I-29 + history pointer, this folder, `docs/README.md` index

## Verification (final numbers)

- **pytest 286 passed** (baseline 234 + 52 new captcha tests) in ~6 s
- **node 71 passed** (`test:js` incl. 15 new probe tests)
- `tools/verify_quality.py --allow-legacy` → **0 fails** (exit 0); only
  pre-existing `[LEGACY]` warnings remain. The two non-captcha fails found
  mid-run (`new_chat._wait_page_loaded`, `multi_page_dispatcher._acquire_page`
  cognitive 16/20 — pre-existing on the pristine tree) were reduced by
  extracting `_check_ready` and `_acquire_via_fallback`.
- Coverage (branch): captcha module **92% lines** — `api_client` 99%,
  `stats` 96%, `signals` 95%, `service` 94%, `key_store` 89%, `solver` 84%,
  `captcha_probes` 100% (gate: 80% lines / 75% branches).
- radon: all new functions A/B; max CC 7 (`handle_captcha`); params ≤ 4
  (Ctx dataclasses carry the rest); nesting ≤ 4.

## RULE 18 recheck (final)

- New functions 4–20 LOC after final trims (`key_store.save` 27 → 14 via
  `_to_dict`/`_cleanup_tmp`/`_lock_mode` extraction; remaining sub-4-line
  functions are property accessors/probe builders).
- `solver.py` 218 / `service.py` 219 lines (in the 150–300 band); leaf files
  33–142 lines (cohesive single-purpose, under-band accepted).
- `app/services/captcha/` = 7 files (5–15 band ✓); `app/browser` +1 py +3 js.
- `Bridge` methods: +4 (3 slots + 1 lazy getter) — wire-format constraint;
  net class lines down (inline captcha code deleted, ~130 → ~40).

## Known non-goals (by design)

- Invisible v3 scoring flow — no DOM surface (design §10).
- Watcher auto-solve — watcher is single-controller, cannot attribute a tab.
- Proxy-backed `RecaptchaV2EnterpriseTask` (IP matching) — enterprise proxyless
  covers the observed arena.ai case; revisit only if 2Captcha reports IP-miss
  failures.
