# Rate-limit penalty (3rd URL-window field) — research + design (2026-09-19)

## 1. User request (verbatim intent)

> "in url win add new option **penalty** — add new **3rd field** with penalty set up
> for the user. This error [the rate-limit banner] means to set up a **custom
> penalty like 30 min** for example, to **wait a bit longer** now. Add this feature."

Screenshot: the red in-page banner `You've reached a rate limit. Please try again
in a moment.` shown in the URL window after a job was cut off by a site rate limit.

Interpretation: the URL window's cooldown bar already has **two** numeric fields
(⏳ base pause `m` and 🛡 `+m/captcha`). The user wants a **third** numeric field —
a **rate-limit penalty** (minutes, user-set, e.g. **30**) — so that when a job is
failed by a **rate/limit/quota** banner, the affected tab waits that much **longer**
than today's short base pause.

## 2. Evidence / current behaviour

* The URL window (`winUrlList`) cooldown bar renders
  `⏳ pause [urlCooldownMin]m · 🛡 +[urlCooldownPenalty]m/captcha · [on] · Save`
  (`app/ui/web/index.html`). There is **no** rate-limit field.
* Cooldown is **per-tab**: after every job `finish_page_after_job` →
  `start_cooldown(base)` pauses the tab for `min_seconds + pending_penalty`
  (`app/services/cooldown_service.py`). Default base = **5 min** (`cooldown_min_seconds=300`).
* The captcha penalty is the closest analogue: each solved captcha calls
  `note_captcha_event` → `add_captcha_penalty` which stacks
  `cooldown_captcha_penalty_seconds` (default **15 min**) onto that tab's
  `pending_penalty` (or extends a live cooldown). Default 15 min.
* A rate-limit banner is detected as a **page error**:
  `cdp_arena.scan_page_errors` → `match_page_error` (patterns include
  `rate\s*-?\s*limit`, `limit\s+reached`, `quota\s+exceeded`, …) →
  `raise PageErrorAbort("Page error: You've reached a rate limit…")`.
* That abort propagates to the job: parallel path
  `multi_page_dispatcher.run_one_image_on_page` ← `_run_image_job` ←
  `run_blocks_for_image` ← `_loop_blocks` ← `_run_one_checked`
  (`err = str(e)`); single path `bridge._do_run_batch` block loop
  (`job_error = str(e)`). The image is marked FAILED with that text.
* **Gap:** after a rate-limit failure the tab only cools for the base pause
  (~5 min) + any captcha debt. There is no way to tell the app "when the site says
  *rate limit*, back off for 30 min". The user must watch and reset manually.

## 3. Design

### New setting (one control per decision, RULE 10)

* Key `cooldown_rate_limit_penalty_seconds`, **default 1800 (30 min)** — matches the
  user's example. `0` = disabled. Part of the same `on` toggle (no extra switch;
  set the field to 0 to turn the wait off). Persisted in `config/session.json`
  (same store as the other cooldown keys).

### Changes

1. **`app/core/cooldown.py`** (pure, ~91 → ~97 lines)
   * `DEFAULT_RATE_LIMIT_PENALTY_SECONDS = 1800`.
   * `CooldownConfig.rate_limit_penalty_seconds` field (default 1800).
   * `config_from_dict` reads + clamps it; `config_to_dict` emits
     `rate_limit_penalty_seconds` + `rate_limit_penalty_minutes` (UI in minutes).

2. **`app/utils/page_errors.py`** (leaf, ~89 → ~104 lines)
   * `RATE_LIMIT_PATTERNS` — the *strong* limit/quota signals only (rate limit,
     limit reached, reached your/the limit, usage/daily limit, too many requests,
     quota exceeded, out of credits/quota, free tier/plan limit). Deliberately
     **excludes** generic failures (`something went wrong`, `generation failed`,
     `service unavailable`, `try again…`) so a transient error does not burn a 30-min
     backoff.
   * `is_rate_limit_error(text) -> bool` — True when the job error string carries one
     of those signals. Stdlib only, no new imports beyond `re` (already imported).

3. **`app/browser/page_status.py`** (~106 → ~108 lines)
   * `PageInfo.rate_limit_count: int = 0` (+ `to_dict` entry) — mirrors
     `captcha_count`; per-tab history, load-balancing/UI, never pruned.

4. **`app/services/cooldown_service.py`** (mirrors the captcha-penalty trio)
   * `load_config` reads `cooldown_rate_limit_penalty_seconds`.
   * `_rate_limit_penalty_from(bridge)` — read the seconds, default 1800.
   * `add_rate_limit_penalty(pool, tab_id, penalty_seconds) -> int` — identical shape
     to `add_captcha_penalty` but bumps `rate_limit_count`: extend a live cooldown or
     stack `pending_penalty`. Returns the per-tab count (`-1` unknown tab).
   * `note_rate_limit_event(pool, tab_id, bridge) -> int` — read the configured
     seconds; **`0`/absent pool/tab → no-op (0)**; else `add_rate_limit_penalty`,
     one `⛔ Rate limit +{N}m tab … (x{count})` log line, persist + live emit.
   * `maybe_note_rate_limit(pool, tab_id, bridge, error) -> int` — the single call
     site uses: `is_rate_limit_error(error)` gate, then `note_rate_limit_event`.
     Centralises detection so **neither** call site (nor the Bridge hotspot) grows.

5. **Call sites (one line each)**
   * Parallel: `multi_page_dispatcher.run_one_image_on_page` — after
     `_handle_result(…)`, call `maybe_note_rate_limit(pool, tab_id, bridge, err)`.
   * Single: `bridge._do_run_batch` — immediately before
     `await self._finish_primary_tab(…)`, call
     `maybe_note_rate_limit(self._page_pool, primary_tab_id, self, job_error)`.
     (Lazy import, like the surrounding single-mode cooldown calls; net +1 line.)

6. **UI (the "3rd field")**
   * `index.html` cooldown bar: add
     `⛔ +[urlCooldownRateLimit]m/limit` between the captcha field and the `on` box.
   * `url-list.js` `loadCooldownConfig`: `setVal('urlCooldownRateLimit',
     c.rate_limit_penalty_minutes ?? round(rate_limit_penalty_seconds/60))`.
   * `url-list.js` `saveCooldownConfig`: read `urlCooldownRateLimit` (default 30),
     add `rate_limit_penalty_seconds` to the payload + log text.
   * `bridge.set_cooldown_config`: parse + persist `rate_limit_penalty_seconds`.
   * `bridge` preset save/load: carry `rate_limit_penalty_seconds` (round-trips).

### Why the penalty lands in the *next* cooldown

`maybe_note_rate_limit` runs while the page is still BUSY (the job just failed,
before `finish_page_after_job`). `add_rate_limit_penalty` therefore stacks onto
`pending_penalty`, and the immediately following `start_cooldown(base)` consumes
`base + pending_penalty` → the tab cools for **base + rate-limit penalty** (300 +
1800 = 35 min by default). This reuses the exact mechanism the captcha penalty uses;
no new timer state is introduced. If the site is still limiting after the pause, the
retry fails with another rate-limit banner and stacks another cycle — a self-
terminating back-off.

### Rejected alternatives

* **Global (all-tab) wait** — a rate limit is account-level, but the app's cooldown
  model is strictly per-tab and per-tab load-balancing is a recorded invariant
  (I-26). Cooling only the tab that hit the limit is consistent with the captcha
  penalty; cooling every tab would block healthy tabs and is a larger behaviour
  change than requested.
* **Hook in `finish_page_after_job` via a new `FinishCtx.error` field** — would touch
  the shared finish path **and** both `FinishCtx` constructors (including the Bridge
  hotspot). Applying at the two failure sites (where the error text already exists)
  is smaller and mirrors `note_captcha_event`'s "record at the event" placement.
* **A separate enable toggle for the rate-limit penalty** — RULE 10 (one control per
  decision): the minutes field already *is* the decision (0 = off). A second checkbox
  would be redundant with the field and the shared `on` toggle.
* **New `PageStatus` field for "rate-limited"** — the existing `pending_penalty` +
  `cooldown_reason` already express the wait; a new status would ripple into the
  15-method PagePool / pool UI without adding behaviour.

## 4. Test plan (tests first, RULE 8 / 16.3)

* `page_errors.is_rate_limit_error`: True for each strong signal (incl. the exact
  screenshot line), False for generic failures, empty, and non-str; case-insensitive.
* `core.cooldown` config: default 1800; `config_from_dict` clamp + round-trip;
  `config_to_dict` exposes seconds + minutes.
* `cooldown_service.add_rate_limit_penalty`: stacks while idle, extends a live
  cooldown, unknown tab → -1, per-tab isolation (tab B untouched).
* `cooldown_service.note_rate_limit_event`: reads config, stacks + logs `⛔ … (x1)`
  + live emit; **penalty 0 → no-op (no log, no stack)**; unknown tab → warn, no ⛔.
* `cooldown_service.maybe_note_rate_limit`: non-rate error → 0 and nothing stacked;
  rate error → penalty stacked on the tab.
* **End-to-end (the behaviour the user asked for):** a job error that is a rate
  limit → after `finish_page_after_job` the tab cools for **base + rate-limit
  penalty** (longer than base alone); a non-rate failure cools for base only.
* JS: `saveCooldownConfig` payload includes `rate_limit_penalty_seconds`;
  `loadCooldownConfig` populates `urlCooldownRateLimit`.
* Equivalence gate: full existing Py + JS suites stay green.

## 5. Doc updates (same change, RULE 17)

* `SYSTEM_OF_RECORD.md` row 21 (Job cycle & cooldown) + row 8 (Settings): add the
  rate-limit penalty; note the new `rate_limit_count` and the two call sites.
* `docs/README.md`: index this design doc.
