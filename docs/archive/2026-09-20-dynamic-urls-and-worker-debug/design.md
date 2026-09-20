# Design — Dynamic URLs & Worker Debug Panel (round 2, PLAN ONLY)

**Written:** 2026-09-20 · **Branch:** `arena/01a0bc3b-process-images-in-areana` · **Base:** `6bbaf8b`
**Status:** plan. **No production code was changed by this document.**
**Base plan:** `docs/archive/2026-09-20-live-processing-and-watcher-scope/` (round 1, D-1…D-10,
`app/services/live/` + `app/services/captcha/policy.py`). Round 2 **amends D-1, D-6 and D-9** and
adds two features; nothing in round 1 is retracted otherwise.
**Evidence:** `evidence.md` in this folder (every claim below carries a `file:line`).
**Budget:** `quality-budget.md` in this folder (RULE 16 / RULE 18 numbers, per-file headroom, tests).

---

## 0. How to read this plan (one wave, not five)

The brief for this round ends with *"Implement all steps at once — no one-by-one."* Round 1 was
sequenced S0…S5; that staging is **withdrawn**. Both rounds are now **one implementation wave (W1,
§9)**: one branch, one ordered checklist, one commit series ending in a single gate run and one
documentation update (RULE 17). Where round 1 said "stage gate", read "step in W1".

Ordering inside W1 is by **dependency**, not by release value: the L-1 fix and the window registry
come first because the debug window (item 05) is meaningless if tabs cannot join the pool
(evidence §4) and if the panel is destroyed at first render (evidence §5.2).

---

## 1. Contract (one sentence per item)

| # | Item | Contract after W1 |
|---|---|---|
| 01 | URL update interval | The user sets `url_reconcile_interval_ms` (ms, clamped) and the Python URL reconciler re-checks tabs/rows at exactly that cadence — applied from the next pass, no restart, and it is a *floor*: any wake event triggers an immediate pass. |
| 02 | Captcha ⇄ timeout | Watcher **OFF** ⇒ **no captcha activity at all** — no probe, no overlay, no `waiting_captcha` row, no stats/recording/penalty, no `🛡` line, **no pause**; the generation timeout runs exactly as if no dialog existed (round-1 D-1, made measurable by D-23). Watcher **ON** ⇒ the per-page generation timeout is **paused** while that page waits for a captcha to clear — with or without a 2Captcha key (without a key: detect, say so honestly, wait for the manual solve) — and both the wait and the pause are **capped** at the user's `watcher_captcha_timeout_sec`; at the cap the job fails honestly instead of hanging (D-13 + **D-14R**). |
| 03 | URL rows | Never-linked user rows are kept (D-4 confirmed); every row that cannot currently receive a job shows a small "not used as job receiver" icon; **all** images reset to pending (single Reset *and* Reset All) re-enter the queue immediately (D-6 **reversed**). |
| 04 | L-1 | `connect_page_pool` schedules on the real helper, so "Add tab to pool" and the reconciler's tab join work. |
| 05 | Live Worker & Queue Debug | One registered window shows every worker (page-pool tab) with its live job status, the pending-image count and the **name of the first image in the queue**, updated in real time from existing signals — and newly added / removed webpages appear and disappear in it without a restart. |

---

## 2. Decisions (D-11…D-23; amendments named explicitly)

| ID | Decision | Why | Rejected alternative |
|---|---|---|---|
| **D-11** | The interval is a **session config key** `url_reconcile_interval_ms`, default **5000**, clamped **500…60000 ms**, written through the existing `save_settings` slot by a new `apply_url_interval(bridge, data)` helper, read by the reconciler **once per pass**. | Brief item 01 (*user setting in ms*). Reusing `save_settings` keeps the frozen 134-slot surface (D-9/R8). Per-pass read = live effect, mirroring `watcher_interval_ms` (`config_manager.py:24`, clamped in `watcher_captcha.py:65-73`). | A new `set_url_interval` slot (contract churn); reading it once at loop start (needs a restart to apply — contradicts "dynamic"). |
| **D-12** | The interval **control lives in the new Live Debug window**, not in the Settings panel. | `settings.js` is frozen at 252 lines / 48 funcs — it cannot grow one line (evidence §6). The debug window is where the cadence is observable ("last pass N s ago"), so the control sits next to its effect (RULE 10 one control per decision, visible where it matters). | Growing `settings.js` (ratchet breach); putting it in the URL List title bar (that bar is already at the 96 px title-fit invariant, SYSTEM_OF_RECORD row 19). |
| **D-13** *(amends round-1 D-1)* | Watcher **ON** ⇒ the generation wait charges every second spent inside the captcha settle to a **`PauseClock`**, and `_check_timeout` subtracts it: `elapsed = now − start − paused`. Watcher **OFF** ⇒ the clock stays at 0 because the `security_settler` is never installed (round-1 D-1) ⇒ the timeout runs exactly as today. The clock carries a **cap**: `note()` charges at most `cap − total`, so one generation wait can never absorb more than the cap (D-14R). | Brief item 02 bullets 1-2, and evidence §2: today an unbounded RULE-20 wait (`wait_captcha_cleared` "never gives up") always ends in `Timeout after …ms` even after the dialog cleared. One subtraction in one function fixes it for every caller of the wait loop. | (a) Restarting the wait after a settle (re-baselines `old_srcs`, risks losing the output that appeared during the solve — RULE 15). (b) Raising `watcher_generation_timeout_sec` globally (punishes the no-captcha case). (c) A per-page deadline in the pool (two owners of one timeout). |
| **D-14R** *(owner correction — reverses the first draft of D-14)* | The pause **is capped, and so is the wait** — one knob, the existing `watcher_captcha_timeout_sec` (default 300 s, clamped 10…3600, already editable in the Watcher window), bounds **both** (a) how long one captcha wait may last and (b) how much generation timeout one wait may absorb (`PauseClock(cap=…)`, cumulative **per generation wait**). At the cap the wait ends, the job fails retryable with an honest reason (`wait_timeout`), the tab keeps its normal cooldown, and the pause stops accruing ⇒ the worst case per image is bounded: `generation_timeout + captcha_cap`. Stop/abort still wins earlier, and the pause stays observable (throttled line, `waiting_captcha` row, debug-window worker line with absorbed/remaining budget). | Owner: *"D-14 — should be capped"* + *"no activity at all if off"* (with the Watcher OFF there is nothing to cap — D-23). Reusing one existing setting keeps RULE 10 (one control per decision) and adds no config surface; the wait overlay already counts that same number down (`service.py:257-258`), so the cap is visible while it runs. | (a) **Unbounded-but-observable** pause (the first draft of D-14 — rejected by the owner: a job could hang forever). (b) A second setting `captcha_pause_cap_sec` (two knobs for one decision; kept as the follow-up in §12.6). (c) Capping inside `wait_captcha_cleared` — its signature is already at the file's `max_params` **4** and its "never gives up" behaviour is pinned by `tests/test_cooldown_service.py:604-618`, so the cap is composed into the `stop` predicate the caller already passes, leaving that module and that test untouched. |
| **D-15** *(refines round-1 D-3)* | The captcha **wait reason** comes from one pure helper `policy.wait_reason(bridge)` with three outcomes: Watcher ON + key ⇒ *"Captcha Watcher is solving it (2Captcha SDK)"*; Watcher ON + **no key** ⇒ *"Watcher ON, no 2Captcha key — solve it in Chrome; this job's timeout is paused"*; (Watcher OFF never reaches the wait — round-1 D-1 `out_of_scope`). | Brief item 02 bullet 3. Today the no-key case tells the user to *"turn the Watcher ON"* while it is ON (`service.py:235-237`) — a lie in the UI. `_manual_wait` has **zero** LOC headroom (span 27 = file max 27), so the wording must be produced by the caller (`_resolve_captcha`, span 8). | Editing the string inside `_manual_wait` (ratchet breach); branching in JS (the pipeline owns the words). |
| **D-16** *(reverses round-1 D-6)* | **Every** reset re-queues: `reset_image_state(img)` drops its `selected` parameter and always sets `status="pending"`, `selected=True`. `reset_all` and `reset_image` both end in round-1's `commit_queue(bridge)` ⇒ the live loop picks the images up on the next wake (≤ ~50 ms idle). One log line states the count: `♻️ Reset All: N images → pending + re-queued (live run picks them up)`. | Brief item 03: *"All images that are reset to pending status are automatically re-added to the processing queue."* Round 1 parked `reset_all` (destructive-surprise argument); the owner has now explicitly overruled that. Undo still exists (`push_queue_undo`) and `retry_image` already behaved this way (`run_control.py:197-208`), so the vocabulary is consistent. | Keeping `reset_all` parked (round-1 D-6 — reversed by the brief); a confirm dialog (adds a JS edit to a frozen file and still contradicts "automatically"). |
| **D-17** *(confirms round-1 D-4)* | Never-linked user-typed rows are **kept**; the reconciler keeps trying to link them. No change. | Brief item 03 confirms it; I-20 (user-authorized URLs only) — a typed row is authorisation. | Grace-period deletion (destroys user intent on a slow Chrome start). |
| **D-18** | A row is a **job receiver** iff `enabled` **and** `tab_id` **and** that tab is in the pool **and** `is_connected`. Python computes it (`live/url_policy.mark_receivers(rows, live_tab_ids)`), stores it on the row (`UrlRow.receiver`, default `False`), publishes it (`urls_to_js` +1 key), and JS only **reflects** it: an inline `<span class="url-not-receiver" title="Not used as job receiver">⊘</span>` in the existing one-line row template + a CSS rule. | Brief item 03 (icon for links "not used as job receiver"). The rule is the conjunction the run gate already applies (`enabled_tab_ids`, `auto_connect.py:203-209`) plus pool liveness (`page_pool.status_snapshot`) — duplicating it in JS would create a second owner (RULE 10) and jscpd pressure. Zero JS line growth: `rowHtml` is a single template line (`render.js:6-8`). | Computing eligibility in JS from the pool payload (two owners of one rule); a new column (the table is already 8 columns wide and the title-bar/width invariants bite); reusing the `○ checking…` connection cell (that cell is written by `cdp.js`-owned code, frozen). |
| **D-19** | Receiver flags are recomputed by the **single writer** of URL rows: every reconcile pass and every `commit_urls` (user toggle / add / remove) ⇒ the icon flips immediately on a checkbox change and within one interval on a tab connect/disconnect. A wake (`pool`, `urls`) triggers an immediate pass, so the interval is a floor, not a latency. | Round-1 I-42 (Python owns rows) + I-37 (every mutation ends in `commit_urls`). | Recomputing on a separate timer (second cadence, second writer); letting JS poll a slot (new slot — forbidden by D-9). |
| **D-20** *(amends round-1 D-9)* | Item 05 adds **one window**, and D-9's substance is kept: **no new slot, no new signal, no growth of any baselined `.js` file**. The frozen surface stays 134 slots; the window-set contract grows 15 → **16** deliberately (like the slot contract, every pinned test is updated in the same commit). New behaviour lives in **new** JS files; the three registry edits are net-zero-line (evidence §6.1). | Brief item 05 mandates a window; round-1 D-9 forbade *contract churn for information the UI already receives* — the information is still received through existing signals, only the surface that shows it is new. | (a) Refusing the window and enriching the Progress panel (frozen JS, and the brief is explicit). (b) A floating non-grid overlay (outside the sash-grid contract: no persistence, no Windows menu, no presets — a second window system). |
| **D-21** | The new window **rescues the destroyed Page Pool panel** (L-5): window id `live_debug`, title **"Live Worker & Queue Debug"**, element `winLiveDebug`, containing (a) the *existing* pool markup moved verbatim (all element ids preserved ⇒ `PagePoolPanel` and its 4 frozen JS files are untouched), (b) a new **queue-head strip** (pending count, first image name, run state, reconcile age), (c) the **URL interval control** (D-12), (d) a new **per-worker job line** list. The orphan `data-window="page_pool"` div is deleted. | One worker table, one owner (RULE 10); zero duplication (jscpd 1.240 %); the pool UI becomes visible for the first time; `PagePoolPanel` keeps its cooldown controls (its own decision) while `LiveDebugPanel` owns the live job/queue view (a different decision). | (a) Registering `page_pool` as a 16th window *and* adding `live_debug` as a 17th (two overlapping worker tables). (b) Rewriting the pool table inside the new panel (4 frozen files re-implemented ⇒ jscpd + ratchet risk). (c) Leaving the orphan markup in place (dead DOM, and `replaceChildren` keeps destroying it). |
| **D-23** *(owner correction — "no activity at all if off")* | Watcher **OFF** means **zero captcha side effects**, asserted as a measured contract rather than as an absence of code: no per-poll `is_security_dialog_visible` (the settler is never installed), no detect probe, no overlay, no pool `waiting_captcha` mark, no stats, no recording, no penalty, no `CAPTCHA_SOLVE`/`CAPTCHA_JOB` line, no `🛡` log line, **no pause** (`clock.total == 0`, no cap installed), and no captcha/pause wording in the debug window's worker line. One predicate decides it (`policy.captcha_in_scope`, round-1 D-3) and one counting test proves the zero on a spy bridge/controller. | Owner wording; round-1 D-1/I-40 intended this, D-23 makes it measurable **including the two surfaces this round adds** (the pause clock and the debug window). | A per-site suppression list (a second decision owner); muting the log only (probe, overlay, stats and penalty would still run). |
| **D-22** | The debug window's data rides **existing signals only**: `page_pool_updated` (workers), `progress_updated` (counts, run state, and a new `live` object), `arena_state_updated` (jobs for the per-worker join). The new panel **self-connects** in `init()` via `Boot.onBridgeReady` (precedent: `arena-presets.js:39-48`), so `listeners.js` (frozen, 168 lines / 51 funcs) is untouched. Sub-second liveness comes from a **1 s JS ticker** that re-renders from cached payloads (elapsed/age counters) — no bridge traffic, no CDP traffic. Python publishes the *derived* facts (`queued`, `next_image`, `receivers`, `url_interval_ms`, `last_pass_at`) in `prog["live"]` from one pure helper `live_view(bridge)`, so no ordering/eligibility rule is re-implemented in JS. | Evidence §5.3: everything needed is already emitted except the queue head, which is one dict key. The ticker pattern is the same one `url-list/cooldown.js` already uses for countdowns. | A new `live_debug_updated` signal + slot pair (contract churn, D-20); polling a slot every second from JS (bridge traffic + a new slot); computing `next_image` in JS (second owner of the eligibility rule, I-41). |

---

## 3. Architecture deltas on top of round 1

### 3.1 Modules

| Path | Status | Owns | ~LOC |
|---|---|---|---:|
| `app/core/window_catalog.py` | **new** | `WINDOWS` (16 id/title pairs), `WINDOW_IDS`, `WINDOW_TITLES`, `LEGACY_WINDOW_IDS`, `GRID_VERSION = 6`, `MIN_GRID_SIZE` — moved out of `layout_service.py` (which re-exports all five names, so `from app.core.layout_service import WINDOW_IDS` keeps working for tests/panels) | 45 |
| `app/services/live/debug_view.py` | **new** | `live_view(bridge) -> dict` (queued, next_image, next_image_id, receivers, receiver_rows, workers_busy, url_interval_ms, last_pass_at, run_state) + `interval_ms(bridge)` + `next_queued(images)`; pure reads, no writes, no Qt | 90 |
| `app/browser/output_wait.py` | existing (211 → ~245) | gains `PauseClock(cap)` (mutable `total`; `note(seconds)` charges at most `cap − total`; `expired()`; `describe()`), `paused_elapsed(start, clock)` — the pause term lives with the timeout it modifies, and `cdp_arena/output.py:13` already imports `WaitSpec` from here | +34 |
| `app/services/live/reconcile.py` | round-1 file | gains: read `interval_ms(bridge)` per pass, wake-triggered immediate pass, `mark_receivers` call, `last_pass_at` stamp | +25 |
| `app/services/live/url_policy.py` | round-1 file | gains `mark_receivers(rows, live_tab_ids) -> int` (pure) and `receiver_reason(row, live_tab_ids) -> str` (tooltip wording) | +25 |
| `app/services/captcha/policy.py` | round-1 file | gains `wait_reason(bridge) -> str` (three-way, D-15), `has_key(bridge) -> bool`, `pause_cap_seconds(bridge) -> float` (the one knob, D-14R) and `WaitDeadline` (composes user-stop + cap-expiry into the `stop` predicate `wait_captcha_cleared` already accepts) | +40 |
| `app/ui/web/js/panels/live-debug.js` | **new** | facade `LiveDebugPanel` (`init`, `onPool`, `onProgress`, `onState`, `restore`), ends with `window.LiveDebugPanel = LiveDebugPanel` (I-35) | 90 |
| `app/ui/web/js/panels/live-debug/store.js` | **new** | `LiveDebugStore`: cached payloads, 1 s ticker start/stop, selectors, `esc`/`fmt` reuse via `UIHelpers` | 80 |
| `app/ui/web/js/panels/live-debug/render.js` | **new** | `LiveDebugRender`: queue-head strip, per-worker job lines, interval control value, receiver counters | 130 |
| `app/ui/web/js/panels/live-debug/actions.js` | **new** | `LiveDebugActions`: Save interval → `Boot.needBridge('save_settings')`, clamp in JS for instant feedback, Refresh button | 70 |
| `app/ui/web/css/live-debug.css` | **new** | window styles + `.url-not-receiver` icon rule (CSS is outside both ratchet lanes) | 60 |

Module counts after W1 (RULE 18.3, 5-15 files, measured at `6bbaf8b`): `app/core` 13 → **14** ✓;
`app/services/live` 0 → **7** (round-1 six + `debug_view.py`) ✓; `app/services/captcha` 6 → **7** ✓;
`app/services` 12 top-level files, unchanged ✓. Two modules are **already over the ideal** and this
wave deliberately does not worsen them: `app/browser` **23** top-level `.py` files (so `PauseClock`
goes *into* `output_wait.py` instead of adding a 24th) and `app/ui/panels` **16** (no new panel file —
the L-1 fix and the `live` publish line are edits). `app/ui/web/js/panels` gains one folder (4 files),
each ≤ 150 lines ✓ (JS folders are not a RULE 18 module).

### 3.2 Import direction (unchanged rule, new edges)

`ui → services → core/browser`; `services` never imports `ui` (round-1 D-10). New edges:
`ui/panels/layout_state → services/live/debug_view` (emit path) ·
`services/live/reconcile → services/live/url_policy` (receivers) ·
`services/live/debug_view → services/live/feed` (eligibility, one rule — I-41) ·
`browser/cdp_arena/output → browser/output_wait` (already exists for `WaitSpec`,
`cdp_arena/output.py:13` — now also imports `PauseClock`, so **no new module edge**).

### 3.3 Runtime picture (delta on round-1 §3.2)

```
Qt thread (frozen slots)                        bg loop thread
────────────────────────                        ──────────────
save_settings{url_reconcile_interval_ms} ──► config.set_state  (clamp 500…60000)
                                                RECONCILER  live/reconcile.py
                                                  every interval_ms(bridge)  ← read per pass (D-11)
                                                  OR immediately on wake("urls"|"pool")
                                                  … → url_policy.mark_receivers(rows, live_tabs)
                                                  → commit_urls → arena_state_updated
                                                  → last_pass_at = now  (for the debug window)
                                                JOB WAIT  cdp_arena/output.py::_run_wait
                                                  clock = PauseClock()
                                                  per poll: _security_gate(cdp, ctrl, clock)
                                                             └─ settler() blocked T seconds
                                                                ⇒ clock.note(T)   (D-13)
                                                  output_wait._check_timeout:
                                                    elapsed = now − start − clock.total
SUPERVISOR (round 1) ── emit_arena_state ──► progress_updated{…, live:{queued,next_image,…}}
                                          ──► page_pool_updated{pages[…current_image,current_job_id]}
                                          ──► arena_state_updated{urls[…receiver], images, jobs}
                                                              │
Web UI (self-connected, no listeners.js edit)                 ▼
  LiveDebugPanel: onProgress → queue head + interval ; onPool → workers ; onState → job join
                  1 s ticker → elapsed / reconcile age (no bridge traffic)
  UrlListRender.rowHtml → ⊘ icon when u.receiver === false (Python-computed, D-18)
```

---

## 4. Item 01 — URL update interval (ms)

**Config.** `DEFAULT_SESSION` gains `"url_reconcile_interval_ms": 5000`
(`config_manager.py:9-31`, next to `watcher_interval_ms`). Old `session.json` files load with the
default (`SessionStore._load_json(path, DEFAULT_SESSION)`) — no migration (RULE 13).

**Write.** `save_settings` (`app_settings.py:258-273`, span 16 / file max 18 ⇒ +1 line) calls a new
module-level `apply_url_interval(bridge, data)`:

```python
# app/ui/panels/app_settings.py (new symbol, ~7 LOC, CC 2)
def apply_url_interval(bridge, data: dict) -> None:
    """Persist the URL reconcile cadence (ms) when the payload carries it."""
    if "url_reconcile_interval_ms" not in data:
        return
    ms = clamp_interval_ms(data.get("url_reconcile_interval_ms"))
    bridge.config.set_state(url_reconcile_interval_ms=ms)
```

`clamp_interval_ms` lives in `live/debug_view.py` (one owner for the range, used by the JS-facing
publish path too). Undo: `save_settings` already ends in `push_settings_undo(self)` ⇒ the interval is
undoable with the rest of the settings (no new kind).

**Read (Python).** `live/reconcile.py` asks `debug_view.interval_ms(bridge)` **at the top of every
pass** and sleeps that long; a wake short-circuits the sleep (round-1 `LiveBus.wait`). Changing the
value therefore applies from the next pass without restarting the loop, and lowering it never
starves the wake path.

**Read (UI).** `emit_arena_state` (`layout_state.py:38-47`, span 10 / file max 19) adds one line:
`prog["live"] = live_view(bridge)` ⇒ the value arrives on `progress_updated` (no new slot/signal).
The control (input + Save + "last pass N s ago") is rendered by `LiveDebugRender` into the new
window (D-12) and saved through `Boot.needBridge('save_settings')` with the payload
`{url_reconcile_interval_ms: N}` — the same slot the Settings panel uses.

**Clamp + feedback.** 500…60000 ms (below 500 ms the CDP `/json` fetch would become a hot loop;
above 60 s "dynamic" stops being true). JS clamps for instant feedback, Python clamps again on write
(never trust the wire — same shape as `parse_watcher_config`).

**Docs.** SYSTEM_OF_RECORD row 8 (Settings list) + row 11 (CDP connection: replace "scan on start +
every 15 s" with "Python reconciler at `url_reconcile_interval_ms`, default 5 s, plus immediate
passes on wake") — both amended **with** the code (RULE 17).

---

## 5. Item 02 — captcha ⇄ generation timeout

### 5.1 The pause clock (D-13)

```python
# app/browser/output_wait.py (added next to WaitSpec, ~40 LOC)
@dataclass
class PauseClock:
    cap: float = 0.0                             # seconds this wait may absorb (0 = nothing may be absorbed)
    total: float = 0.0
    def note(self, seconds: float) -> None:      # charge min(seconds, cap − total); ignore ≤ 0; never raises
    def expired(self) -> bool:                   # cap > 0 and total >= cap
    def describe(self) -> str:                   # "+37s captcha wait (cap 300s)" or ""

def paused_elapsed(start: float, clock) -> float  # now − start − (clock.total if clock else 0)
```

**Cap plumbing (D-14R, no signature changes).** `wait_for_output` installs the cap **next to the
settler** — `ctx.ctrl.pause_cap_s = policy.pause_cap_seconds(ctx.bridge)` at
`single_job_runner.py:249`, removed in the same `finally:` (`:257-261`) — and `_run_wait` builds
`PauseClock(cap=getattr(spec.ctrl, "pause_cap_s", 0.0))`. Neither
`CDPArenaController.wait_for_new_output` (`cdp_arena/mixins.py:139-146`) nor `cdp_arena.WaitSpec`
(`:29-35`) gains a parameter. With the Watcher OFF **neither** the settler nor the cap is installed,
so the clock cannot charge at all (D-23) — the OFF case is guaranteed by construction, not by a
branch inside the loop.

**`output_wait.py`** (211 → ~245 lines, `max_func_loc 23`, coverage floor 94.95 %):

* `WaitSpec` gains `pause: object | None = None` (+1 line in a 4-line dataclass — no function span).
* `_check_timeout` (span 11): the first line becomes `elapsed = paused_elapsed(state.start, spec.pause)`
  ⇒ **net-zero lines**, no CC change (the branch structure is untouched).
* `_handle_timeout_fallback` / `_process_fallback` keep using wall-clock elapsed for their own
  spinner-loss windows — deliberate: a captcha pause must not extend *revival* heuristics, only the
  hard timeout. Recorded here because it is the one place where two elapsed notions coexist.

**`cdp_arena/output.py`** (182 lines, `max_func_loc 16`):

* `_run_wait` (span 14 → 15): `clock = PauseClock()` (+1), `PollSpec(..., pause=clock)` (same line),
  `_security_gate(cdp, spec.ctrl, clock)` (same line).
* `_security_gate` (span 10 → 12): measure around the settle only —
  `t0 = time.monotonic()` before `await settler()`, `clock.note(time.monotonic() - t0)` after,
  guarded by `if clock is not None`. No charge when the dialog is not visible (the settle never ran)
  and no charge when `settler` is absent (Watcher OFF, round-1 D-1) ⇒ **item 02 bullet 1 falls out of
  the construction, not out of a branch**.
* `_map_wait_result` (span 10 → 11): the failure text becomes
  `f"Timeout after {timeout_ms}ms{clock.describe()}"` and the payload gains `"paused_s": int(clock.total)`
  ⇒ an honest post-mortem (RULE 2, RULE 4: the reason names the gate that broke *and* the wait it
  absorbed). Its signature changes from `(cdp, result, baseline, timeout_ms)` — **4 params, the file
  maximum** — to `(cdp, result, spec)`, reading `spec.baseline` / `spec.timeout_ms` / `spec.pause`
  inside (params 4 → **3**, no growth; same param-object style as `WaitSpec`/`JobCtx`/`BatchCtx`).
  The single call site is `_run_wait:171`, so the edit is net-zero lines.

### 5.2 The cases after W1 (including the cap)

| Case | Detection | Wait | Generation timeout | Cap reached (`watcher_captcha_timeout_sec`) | User-visible wording |
|---|---|---|---|---|---|
| Watcher **OFF** | **none** (round-1 D-1 + D-23: `check_security` returns False, `handle_captcha` → `out_of_scope`, no settler, no cap, no overlay, no stats, no recording, no penalty, no `🛡` line) | none | **runs** (clock 0) | n/a — nothing waits | the gate that actually broke (`WAIT_OUTPUT` timeout / page-error text) |
| Watcher **ON** + key | detect probe + stats + recording + `waiting_captcha` row | `_manual_wait` until the solver or the user clears it | **paused** for the wait, up to the cap | wait ends ⇒ `wait_timeout` ⇒ job FAILED (retryable), cooldown as usual | overlay reason: *"Captcha Watcher is solving it (2Captcha SDK)"*; throttled `⏸ Generation timeout paused for captcha wait (Ns / cap Ms)` |
| Watcher **ON**, no key | identical (detection does not depend on the key) | identical — waits for the **manual** solve | **paused**, up to the cap | identical | overlay reason (D-15): *"Watcher ON, no 2Captcha key — solve it in Chrome; this job's timeout is paused (cap Ms)"*; the existing `solver_start` warn line stays (`watcher_solver.py:130-134`) |
| Watcher **ON**, second captcha in the same generation | detected again (new encounter) | a fresh wait, bounded by the same knob | the clock is **already near/over its cumulative cap** ⇒ further settles charge nothing ⇒ the timeout counts down in real time | — | `⏸ Pause budget exhausted (cap Ms) — generation timeout running again` |

`policy.wait_reason(bridge)` is the single owner of that wording; `_resolve_captcha`
(`service.py:232-239`, span 8 → 9) calls it and passes the result to `_manual_wait` — the wording is
produced by the *caller* because `_manual_wait` has zero LOC headroom (span **27** = file `max_func_loc`
27, evidence §6.1); its own body only shrinks (§5.3: the outcome `if/else` is extracted, the cap rides
the `stop` argument it already passes).

### 5.3 Interaction with the rest of the pipeline

* **The wait is bounded by the caller, not by `cooldown_service`** (D-14R): `_manual_wait` passes
  `WaitDeadline(timeout).stop_or_expired(_stop_pred(ctx))` as the `stop` argument
  `wait_captcha_cleared` already accepts (`cooldown_service.py:446`), so that module, its
  `max_params 4` signature and its pinned "keeps waiting" test all stay untouched.
  `solved=False` **and** `deadline.expired()` ⇒
  `SolveOutcome(status="wait_timeout", reason=f"Captcha not cleared in {timeout}s — job failed (retryable)")`;
  `status` is a free-form string (`captcha/signals.py:94-99`), so no enum changes (round-1 already adds
  `out_of_scope`).
* `_handle_captcha_outcome` (`single_job_runner.py:75-85`) maps `wait_timeout` to
  `raise RuntimeError(outcome.reason)` — the exact shape its `page_error` branch already uses ⇒ the job
  fails retryable and the failure names the cap and the knob.
* `_manual_wait` **shrinks** 27 → ~21 LOC: the 7-line solved/stopped `if/else` (`:269-275`) becomes one
  call to a new `_wait_outcome(ctx, solved, expired, signal)` (~14 LOC). Required anyway — the file's
  `max_func_loc` is 27 and `_manual_wait` is at it.
* Cooldown penalty recording (`_record_penalty`, once per cleared edge) is unchanged — the pause does
  not create a second captcha event, and a cap-reached failure records no penalty (nothing was cleared).
* Post-settle **revival** (`captcha/recovery.py`, `arm_resume`/`note_settle` at
  `single_job_runner.py:265-271,279-292`) is unchanged: it is triggered by the settle, not by the
  timeout, and its own bounded resubmit is not extended by the clock (§5.1).
* The dispatcher's parallel lane gets the same behaviour for free: it calls the same
  `wait_for_new_output` path per job.
* `wait_for_free_page` / `cooldown_aware_timeout` (`page_pool.py:178-189`,
  `cooldown_service.py:549-556`) are **not** touched: the pause is scoped to one page's generation
  wait, exactly as the brief words it ("for that page").

---

## 6. Item 03 — URL rows: receiver icon + reset re-queue

### 6.1 Receiver flag (D-18/D-19)

```python
# app/services/live/url_policy.py (pure, +25 LOC)
def receiver_reason(row, live_tab_ids) -> str:   # "" | "unchecked" | "no tab" | "tab offline"
def mark_receivers(rows, live_tab_ids) -> int:   # sets row.receiver, returns changed count
```

`live_tab_ids` = `{p.tab_id for p in snapshot["pages"] if p["is_connected"]}` (from
`page_pool.status_snapshot()`), intersected with `enabled_tab_ids(rows)` semantics by construction
(`enabled` + `tab_id` are checked per row). One writer: called from `reconcile_once` (after
`sync_pool_presence`, before `commit_urls`) and from `commit_urls` itself so a checkbox flip is
instant. `UrlRow.receiver: bool = False` (`models.py:13-21`) round-trips through
`asdict`/`UrlRow(**u)` with no migration; both undo builders gain the key
(`undo_entries.py:21-41`) so undo/redo does not blank the icons.

### 6.2 Icon (zero JS growth)

* `urls_to_js` (`arena_serialize.py:12-25`, span 14 / file max 23) publishes `"receiver": bool(u.get("receiver", False))`.
* `rowHtml` (`url-list/render.js:6-8`) — inside the existing single template line, next to the URL
  text: `${u.receiver === false ? '<span class="url-not-receiver" title="Not used as job receiver">⊘</span>' : ''}`.
  The `title` carries the reason; `render()` rebuilds rows on every `arena_state_updated`, so the icon
  follows the flag with no extra JS.
* `.url-not-receiver` styling in the new `css/live-debug.css` (muted colour, 11 px, `cursor:help`).
* Rows that are receivers show nothing (absence = healthy), so the icon is a *warning* marker and the
  table does not grow a column (title-bar/width invariants, SYSTEM_OF_RECORD row 19).

### 6.3 Reset re-queue (D-16)

```python
# app/ui/panels/run_control.py — net-zero lines
def reset_image_state(img) -> None:      # parameter deleted (no caller passed False; no test used it)
    img.status = "pending"; img.selected = True; img.error = None
    img.output_path = None; img.assigned_url_id = None; img.attempt_count = 0

def reset_all(self):      # slot body: reset_image_state(img) … then commit_queue(self) (round 1)
                          # + one log line with the count
def reset_image(self, img_id):   # same call, same funnel
```

Both slots end in round-1's `commit_queue(bridge)` (recalculate + save + emit + undo + `wake("queue")`)
⇒ a live run picks the images up on the next pass (round-1 §7.2: ≤ ~50 ms when idle). `reset_all`
keeps clearing `state.jobs` and keeps `push_queue_undo` (Undo restores the previous statuses —
the destructive-surprise protection round 1 wanted now lives in Undo + the log line instead of in a
parked queue).

### 6.4 D-9 confirmation

Round-1 D-9 ("the passive re-check + live queue works") is confirmed by the brief and unchanged, with
one amendment of scope: it now also covers the new window (D-20) — the *slot* surface stays frozen,
the *window* surface grows by one, deliberately.

---

## 7. Item 04 — L-1

`app/ui/panels/page_pool.py:147`: `self._schedule_coro(...)` → `schedule_coro(self, ...)` with
`from app.services.run_state import schedule_coro` added to the module imports (the pattern used by
`browser_tabs.py:25`, `cdp_tools.py:14`, `run_control.py:16`). Same LOC in the slot body
(span 13 / file max 16), +1 import line (Python lines are not ratcheted).

Regression test `tests/test_page_pool_join.py` (round-1 budget §6.1) asserts the slot schedules on a
host that does **not** define `_schedule_coro` — i.e. the test fails on the old code by construction,
which is also the guard against the fake-bridge masking that hid the defect
(`tests/test_panel_browser_tabs.py:82,156,168,180,211` inject `_schedule_coro=`).

---

## 8. Item 05 — the Live Worker & Queue Debug window

### 8.1 Registration (16 windows, one deliberate contract change)

| Layer | Edit | Line-cost |
|---|---|---|
| `app/core/window_catalog.py` (new) | 16 `{id,title}` pairs incl. `{"id": "live_debug", "title": "Live Worker & Queue Debug"}`; `GRID_VERSION = 6`; `LEGACY_WINDOW_IDS` unchanged (`page_pool` was never valid, so no stored tree can contain it) | new file |
| `app/core/layout_service.py` | import + re-export the five names; `default_grid_tree` gains `leaf("live_debug")` **on the existing right-column line** with rebalanced sizes `[24, 20, 16, 20, 20]` (span stays 21 = file max) | −28 lines (table moved out) |
| `sash-core/constants.js` | window entry appended to the `arena_presets` line; `VERSION: 6` on the return line | **0** (25 lines / 3 funcs) |
| `sash-grid-windows/store.js` | `live_debug: 'winLiveDebug'` appended to the last map line in `_collectPanels` | **0** (122 / 19, `_collectPanels` span 14) |
| `arena-app.js` | `'LiveDebugPanel'` appended to the last `_PANEL_INITS` line | **0** (176 / 28) |
| `index.html` | the orphan `winPagePool` div (29 lines) becomes `<div class="panel" id="winLiveDebug" data-window="live_debug">` with a new title row, the moved pool body, the queue-head strip, the interval control and the worker-job list; `<link … live-debug.css>`; 4 `<script>` tags before `arena-app.js` | HTML (ungated) |
| Migration | none to write: `migrate_grid_tree` (`layout_service.py:283-297`) appends the missing leaf to every stored v≤6 layout, and JS `sashDeserialize*` (`validate.js:100-142`) does the same; `GRID_VERSION` 6 keeps old payloads acceptable (`1 <= v <= GRID_VERSION`) | 0 |
| Windows menu / presets / dock | automatic — all iterate `SashCore.WINDOW_IDS` / `WINDOW_TITLES` (`sash-grid-windows/menus.js:100`, `store.js:34,96-97`, `windows.js:52-102`); `window_preset_service` counts leaves dynamically (`:106,124`) | 0 |

### 8.2 Window content (four blocks, one owner each)

| Block | Element ids | Owner | Source |
|---|---|---|---|
| **Queue head** | `ldQueued`, `ldNextImage`, `ldRunState`, `ldReceivers` | `LiveDebugRender.queueHead()` | `progress_updated.live` (`queued`, `next_image`, `run_state`, `receivers`) |
| **URL interval** | `ldUrlInterval`, `ldUrlIntervalSave`, `ldLastPass` | `LiveDebugRender.interval()` + `LiveDebugActions.saveInterval()` | `live.url_interval_ms`, `live.last_pass_at`; write via `save_settings` |
| **Worker job lines** | `ldWorkerJobs` | `LiveDebugRender.workers()` | `page_pool_updated.pages[]` (`status`, `current_image`, `current_job_id`, `busy_since`, `jobs_completed`, `captcha_count`, `cooldown_remaining`) joined to `arena_state_updated.jobs[]` for image path/attempt/error |
| **Pool table + controls** (rescued) | `poolStatusBadge`, `poolTotal…poolFree`, `poolTableBody`, `poolRefreshBtn`, `poolConnectBtn`, `poolClearBtn` | `PagePoolPanel` (**unchanged**) | `page_pool_updated` via `listeners.js:115-118` (unchanged) |

Worker job line format (one line per pool page, job-centric — deliberately *not* a copy of the
tab-centric pool table):

```
🟦 3F2A…  arena.ai/image/direct   ▶ photo_014.jpg   generating 42s   job 20260920-141502-AB12 · attempt 1
🛑 9C11…  arena.ai/image/direct   ⏸ captcha wait 1m12s — generation timeout paused   🛡x2
🟩 7B02…  arena.ai/image/direct   idle · 12 jobs done · cooldown 3m41s
⚪ —      (no pages in pool)      waiting for a webpage: add a tab or let the reconciler join one
```

Phase is derived from the pool `status` (`busy` / `waiting_generation` / `waiting_captcha` /
`cooldown` / `steady` / `error` / `disconnected` — `page_status.py:17-25`) plus `busy_since` for the
elapsed time; the paused-timeout wording appears when `status == waiting_captcha` **and** the Watcher
is ON (from `live_view`, so JS does not re-derive policy).

### 8.3 Real-time model (D-22)

* **Push:** three existing signals; the panel self-connects in `init()` under `Boot.onBridgeReady`
  (bridge exists before panels init — `arena-app.js:167-173`), each `connect` guarded by `try` and by
  `if (bridge.X)` (the `test_boot_all_panels.mjs` fake bridge makes every member connectable).
* **Tick:** one 1 s `setInterval` in `LiveDebugStore` re-renders elapsed/age fields from the cached
  payloads — no bridge call, no CDP call (the same trick `url-list/cooldown.js` uses for countdowns).
  The ticker starts only when the window is visible (`SashGrid.isClosed/isMinimized` are readable via
  `window.SashGrid`) and stops when it is hidden ⇒ no background churn.
* **First paint:** `restore(data)` is called from `_restoreArenaPanels` **only** for the six panels
  listed there (`arena-app.js:120-126`, frozen) ⇒ the debug panel instead pulls its first payload on
  `init()` through existing slots: `Boot.needBridge('watcher_status')` is *not* used (no new
  dependency); the first `progress_updated` / `page_pool_updated` arrives within one emit cycle
  because `initWithBridge()` immediately calls `_loadArenaState()` and the pool emits on connect.
  Belt-and-braces: `LiveDebugActions.refresh()` (the Refresh button already in the rescued markup)
  calls the frozen `get_page_pool_status` slot (`app/ui/panels/page_pool.py:105-118`, which emits the snapshot itself) and waits for the next push otherwise.
* **New/removed webpages:** add ⇒ reconciler joins the tab (needs L-1, §7) ⇒ `add_page` ⇒
  `_emit_pool_status` (`app/ui/bridge.py:100-108`) ⇒ the worker list grows; remove ⇒ `sync_pool_presence` / `disconnect_page_pool`
  (`page_pool.py:153-165`) ⇒ `_emit_pool_status` ⇒ the row disappears. Both also flip URL-row
  receiver flags (§6.1) in the same pass.

### 8.4 Tests for the window (see `quality-budget.md` §6 for the full matrix)

`tests/test_window_catalog.py` (Python/JS tables identical — extends the existing desync guard),
`tests/test_live_debug_view.py` (`live_view` pure-read contract, `interval_ms` clamp, `next_queued`
order), `tests/js/test_live_debug_panel.mjs` (loads the real `index.html` scripts, asserts
`window.LiveDebugPanel` publishes itself, renders a queue head + a paused worker from fake payloads,
and that `winLiveDebug` is mounted by the grid instead of destroyed), plus the four `15 → 16` count
assertions in `tests/test_grid_layout.py:245-253` and the harness lists in `tests/js/sash_harness.mjs`.

---

## 9. W1 — the single implementation wave

One branch, one ordered checklist; every step keeps the tree buildable, the gates run **once** at the
end (plus a fast `verify_quality --changed` after each step). Tests are written **before** the code
they cover (RULE 16.6 step 3).

| # | Step | Files | Test that proves it |
|---|---|---|---|
| 0 | Bootstrap `.venv` + `npm ci`; capture the equivalence baseline (gates, coverage, jscpd, goldens) | — | numbers recorded in `quality-budget.md` §2 |
| 1 | **L-1 fix** (item 04) | `ui/panels/page_pool.py` | `tests/test_page_pool_join.py` (fails on old code) |
| 2 | **Window catalog extraction + 16th window (Python)** | new `core/window_catalog.py`; `core/layout_service.py` | `tests/test_window_catalog.py`, `test_grid_layout.py` (counts updated 15→16), `test_layout_service_full.py` |
| 3 | **Window registration (JS) + markup rescue** | `sash-core/constants.js`, `sash-grid-windows/store.js`, `arena-app.js`, `index.html`, new `css/live-debug.css` | `tests/js/test_sash_core.mjs`, `test_title_fit.mjs`, `test_boot_all_panels.mjs`, harness lists |
| 4 | **PauseClock + timeout pause** (item 02) | `browser/output_wait.py` (`PauseClock` + `paused_elapsed`), `browser/cdp_arena/output.py` | `tests/test_pause_clock.py` (incl. the cumulative cap), `tests/test_output_wait_timeout_pause.py` (pause works **and** the cap-reached wait times out), existing `output_wait` suite (94.95 % floor) |
| 5 | **Captcha scope + wait reason** (item 02, round-1 feature 01) | new `services/captcha/policy.py`; `services/captcha/service.py`; `services/single_job_runner.py` | `tests/test_captcha_scope.py`, `tests/test_watcher_off_zero_activity.py` (D-23 counting test), `tests/test_captcha_wait_reason.py`, `tests/test_captcha_wait_cap.py` (D-14R), goldens unchanged (harness arms Watcher ON) |
| 6 | **Live package** (round-1 features 02/03/04) | new `services/live/{__init__,bus,supervisor,feed,reconcile,url_policy}.py`; `run_state.py`, `run_control.py`, `queue_scan.py`, `batch_orchestrator.py`, `multi_page_dispatcher.py`, `browser_tabs.py`, `url_queue.py` | `tests/test_live_{bus,supervisor,feed,reconcile}.py`, `tests/test_url_policy.py` |
| 7 | **Interval setting** (item 01) | `persistence/config_manager.py`, `ui/panels/app_settings.py`, `services/live/debug_view.py` | `tests/test_url_interval_setting.py` |
| 8 | **Receivers + reset re-queue** (item 03) | `core/models.py`, `ui/services/{arena_serialize,undo_entries}.py`, `services/live/url_policy.py`, `ui/panels/run_control.py`, `url-list/render.js` | `tests/test_url_receivers.py`, `tests/test_reset_requeues.py`, `tests/js/test_url_list_receiver_icon.mjs` |
| 9 | **Debug window data + panel** (item 05) | new `services/live/debug_view.py` (with step 7), `ui/panels/layout_state.py`, new `js/panels/live-debug{,/store,/render,/actions}.js` | `tests/test_live_debug_view.py`, `tests/js/test_live_debug_panel.mjs` |
| 10 | **JS deletion** (round-1) | `js/panels/cdp.js` (15 s interval removed, 135 → 134) | `tests/js/test_cdp_store*.mjs` |
| 11 | **Docs in the same change** (RULE 17) | `docs/current/SYSTEM_OF_RECORD.md` (rows 8/11/12/19/21, I-19/I-33/I-34 amended, I-39…I-46 added), `docs/current/AGENT_RULES.md` (RULE 20 amendment), `docs/current/QUALITY_RECHECK.md`, `docs/README.md` | doc-consistency review; `pre_push_check.sh` |
| 12 | **Gate run + recheck** | `bash tools/pre_push_check.sh`, `verify_quality --changed --allow-legacy`, `npm run test:js`, pytest+coverage, jscpd, radon; RULE 18 ideal-size recheck of every touched/new file; baseline re-record **only** if a maximum must move, with the reason in the commit message | `quality-budget.md` §8 checklist filled in |

Goldens: the characterization harness arms `_stop_after` (round-1 R7) so traces still terminate; the
timeout-pause change alters **no** pinned log string except the failure text of a job that timed out
*after* a captcha wait, which today does not occur in any golden (no golden arms a captcha + timeout
combination) ⇒ goldens are expected **unchanged**; if a diff appears it is reviewed, then regenerated
with `UPDATE_GOLDENS=1` and the diff pasted into the commit message.

---

## 10. Invariants (append to SYSTEM_OF_RECORD §5 with the code; never renumber)

| ID | Invariant | Enforcement |
|---|---|---|
| **I-43** | The Python/JS window registries are one contract: identical ids, order and titles, and every registered window has a DOM element that the grid mounts — a panel whose `data-window` is not registered is **destroyed** by `render()` (L-5) | `core/window_catalog.py` + `tests/test_window_catalog.py`, `tests/test_grid_layout.py:117-121`, `tests/js/test_live_debug_panel.mjs` |
| **I-44** | A page's generation timeout is paused for exactly the time that page spends waiting for a captcha to clear, and only then; the pause is **capped** at `watcher_captcha_timeout_sec` per generation wait, the wait itself ends at the same cap with an honest `wait_timeout` failure, and both the absorbed pause and the cap are reported (failure text + debug window), never silent. Watcher OFF ⇒ no pause and no captcha activity of any kind (D-23) | `browser/output_wait.py` (`PauseClock`) + `captcha/policy.WaitDeadline` + `tests/test_pause_clock.py`, `test_output_wait_timeout_pause.py`, `test_captcha_wait_cap.py`, `test_watcher_off_zero_activity.py` |
| **I-45** | URL-row receiver eligibility has one owner (Python `url_policy.mark_receivers`); the web UI reflects the flag and never recomputes it | `services/live/url_policy.py` + `tests/test_url_receivers.py`, `tests/js/test_url_list_receiver_icon.mjs` |
| **I-46** | Every reset (`reset_image`, `reset_all`) returns images to `pending` **and** `selected`, ends in `commit_queue`, and is undoable; no reset parks work | `ui/panels/run_control.py` + `tests/test_reset_requeues.py` |

Amended in the same change: **I-19 / I-34 / RULE 20** (Watcher OFF = captcha out of scope; Watcher ON
= detect + wait + penalty + logs + **paused generation timeout**, solving only with a stored key),
**I-33** (row ownership keeps the receiver flag), **I-42** (round-1: reconcile cadence is now the
user-set `url_reconcile_interval_ms`, not a fixed 5 s), **I-35** (the new panel publishes itself),
**I-37** (rows stay Python-owned — the receiver flag is written by the reconciler/`commit_urls`),
**I-40** (round-1: strengthened by D-23 from "captcha work only while ON" into a *counted* zero-side-effect
contract for OFF, including the new pause clock and the debug window).

---

## 11. Risks

| # | Risk | Mitigation |
|---|---|---|
| R11 | ~~An unbounded pause hangs a job forever~~ **closed by D-14R**: the worst case per image is now `generation_timeout + watcher_captcha_timeout_sec` | cap cumulative per generation wait; wait ends at the cap with `wait_timeout`; Stop/abort still wins earlier; per-tab Stop already exists (I-31) |
| R21 | The cap is too small for a slow manual solve ⇒ a job fails that a longer wait would have saved | One user knob (default 300 s, clamp 10…3600, editable in the Watcher window, read per wait ⇒ no restart); the failure text names it (`Captcha not cleared in Ns`); the debug window shows absorbed/remaining pause budget next to the paused worker |
| R22 | Two captchas in one generation each absorb a full cap ⇒ the pause becomes unbounded again through the back door | `PauseClock.total` is cumulative **per generation wait**, so the second settle charges nothing once the budget is gone (§5.2 last row) — asserted by `test_pause_clock.py` |
| R12 | Pause clock charged for non-captcha slowness | Charged **only** around `settler()`, which only runs when the dialog is visible *and* the settler is installed (Watcher ON) — `clock.total` stays 0 otherwise; unit test asserts 0 charge on a slow-but-clean poll |
| R13 | Reset All re-queues 500 images by accident (the reason round 1 parked it) | The owner overruled it explicitly (D-16); Undo restores prior statuses (`push_queue_undo`), one log line names the count, and the live loop still respects per-tab cooldowns, so the batch cannot storm one tab |
| R14 | The 16-window contract desyncs Python vs JS again | `test_grid_layout.py:117-121` already compares the parsed JS table with Python; `tests/test_window_catalog.py` adds the element-id map (`_collectPanels`) to the same guard |
| R15 | Rescuing the pool markup breaks `PagePoolPanel` (ids, listeners) | Markup moved **verbatim** (ids preserved), the four pool JS files untouched, `tests/js/test_live_debug_panel.mjs` boots the real `index.html` script list and asserts the pool table renders into a *mounted* element |
| R16 | A frozen JS file grows by one line and the whole gate fails | Every JS edit in this wave is net-zero (evidence §6.1 ledger); `verify_quality --changed` after each step; new behaviour only in new files |
| R17 | The new panel duplicates the pool table (jscpd 1.240 %) | The job-line list is job-centric (image, phase, elapsed, job id) while the pool table stays tab-centric with cooldown controls; no shared template strings; duplication measured in step 12 |
| R18 | `next_image` misleads when the parallel lane dispatches out of order | The label reads *"next in queue"* and the worker lines show what is actually running; `live_view` documents that the dispatcher picks tabs, not images (`multi_page_dispatcher._acquire_free_in`), image order stays `eligible[0]` |
| R19 | Interval set to 500 ms hammers CDP `/json` | Clamp floor 500 ms + the pass itself is the cost (one fetch); wake-triggered passes are deduped by the round-1 `LiveBus`; the debug window shows the last-pass age so a too-small value is visible |
| R20 | Coverage floors drop in touched legacy files | Per-file floors listed in `quality-budget.md` §3; new logic lives in new fully-tested files; `--coverage-ratchet` mode for the mid-wave runs |

---

## 12. Out of scope (explicit follow-ups)

1. Registering `page_pool` as its **own** window in addition to `live_debug` (D-21 rejects it: two
   worker tables). If the owner wants the pool controls in a separate window, that is a one-line
   catalog change plus markup, in a later round.
2. Persisting `url_policy` memory and receiver history across restarts (round-1 follow-up 3).
3. A per-worker **sparkline**/history (jobs over time) in the debug window — the data
   (`jobs_completed`, `captcha_count`, `rate_limit_count`) is already in the snapshot; a chart is a
   new JS surface with its own budget.
4. Making the passive `WatcherService` retire (round-1 follow-up 1) — still a RULE 10 tension, still
   its own round.
5. Moving the JS 500 ms `ensurePrimary` tick into Python (round-1 follow-up 2).
6. **Decoupling** the two caps — a separate `captcha_pause_cap_sec` so the pause budget and the wait
   length can differ. D-14R deliberately uses one knob (`watcher_captcha_timeout_sec`); the flip is one
   config key + one clamp + one `PauseClock(cap=…)` argument.
7. Any new bridge slot or signal (D-20/D-22 forbid both; if a future feature needs one, it is a
   contract review like the 134-slot freeze).
