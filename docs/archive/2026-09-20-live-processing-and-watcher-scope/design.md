# Design — Live processing & Watcher scope (2026-09-20)

**Status: PLAN ONLY — no production code changed yet.**
Companions: [`evidence.md`](evidence.md) (current truth, `file:line`) · [`quality-budget.md`](quality-budget.md) (RULE 16/18 numbers, test matrix, gates).

Four requested changes, one theme: **the app must react while it runs, not at the next Start.**

| # | Request | One-line design answer |
|---|---|---|
| 01 | Captcha detection/solving/logs only when Watcher is ON | One scope predicate (`captcha/policy.py`) checked at the 4 pipeline sites + the choke point; Watcher OFF ⇒ no probe, no wait, no penalty, no recording, no stats, no log line |
| 02 | URLs added/removed dynamically by passive rechecking; queue follows on the fly | A Python-owned reconciler loop (`live/reconcile.py`) replaces the JS 15 s timer; a pure removal policy (`live/url_policy.py`) decides *why* a row goes; every change ends in `wake("urls")` |
| 03 | Run never turns itself off; loops until the user stops it | `live/supervisor.py::run_live` — pass-based loop, one writer of run state, waits on a wake event instead of ending |
| 04 | Reset/pending images re-enter the queue immediately; URL status applies live | One eligibility read model + one queue write funnel (`live/feed.py::commit_queue`) that ends in `wake("queue")`; `allowed` tabs re-read per pass **and per image** |

---

## 1. Contract (the one sentence)

> While a run is live, **every** state change the user can make — queue reset/retry/scan/select,
> URL row add/claim/remove, tab open/close, Watcher ON/OFF — is picked up by the running loop
> **without a restart**, and captcha work exists **only** inside the Watcher ON window.

---

## 2. Decisions (taken from the brief; alternatives recorded)

The four clarifying questions came back as a re-paste of the brief, so each open point is decided
here from the literal wording + the repo rules. **Every decision is a one-line flip if the owner
disagrees — say so before implementation starts.**

| ID | Decision | Why | Rejected alternative |
|---|---|---|---|
| **D-1** | Watcher OFF ⇒ **hard gate**: no probe, no pause, no overlay, no penalty, no recording, no stats, no captcha log line. The job keeps running and fails on its own verification gates (`WAIT_OUTPUT` timeout, page-error fast-fail I-30, `VALIDATE`). | Brief: *"no detection, no solving, no captcha logs"* + *"Do not show captcha detection signs in logs if Watcher is not running"*. RULE 4 is still honoured: the failure reason comes from the gate that actually broke, never from a guess. | "Silent wait" (keep the 300 s pause, drop the wording) — keeps RULE 20 intact but contradicts *no detection*; kept as fallback if the owner prefers safety over silence. |
| **D-2** | RULE 20, I-19 and I-34 are **amended in the same change** (append, never renumber). New wording: *Watcher OFF = captcha out of scope; Watcher ON = detect + wait + penalty + logs, and solve only with a stored key.* | RULE 17 (docs updated in the same change); rules must describe reality. | Leaving the rules untouched — would make the code contradict `docs/current/` on day one. |
| **D-3** | The scope gate reads the **Watcher switch** (`config.watcher_enabled`, mirrored by `start_watcher`/`stop_watcher`/`set_watcher_config`), *not* the solver loop's `running`. | A Watcher ON with no 2Captcha key must still detect + pause for a manual solve (RULE 20 opt-in is the switch, the key only enables *solving*). Gating on `solver.running` would silently switch detection off for every key-less user. | `bridge._captcha_watcher.running` (today's `_watcher_running`) — kept, but only for the amber reason line + `method` label. |
| **D-4** | Auto-remove a URL row when: **(a)** its tab is gone for 2 consecutive reconciles (hysteresis), **(b)** its URL no longer matches `url_pattern`, **(c)** its `last_status` is `error` / `authentication required` / `unsupported page`, or **(d)** it is a duplicate of another row on the same tab (existing dedupe). **Never** while that row's tab has a live job. User-typed rows that never linked are **kept** (the reconciler keeps trying to link them). | Brief: *"URLs not matching requirements are auto-removed"* + I-20 *"user-authorized URLs only"* — a row the user typed is authorisation, not garbage. Hysteresis + "never delete on an empty/failed fetch" keeps the existing safety (`auto_connect.py:143` `sync_pool_presence`). | Also deleting never-linked manual rows after a grace period — destroys user intent on a slow Chrome start. |
| **D-5** | A live run **never ends by itself**: no work, no tab, all cooling, or CDP down ⇒ wait on the wake event (1 s poll fallback), one announce line, then throttled repeats (≥ 5 min). Only `cancel_current` (Stop) and `stop_after_current` (finish the in-flight image, then stop) end it. | Brief: *"Run does not turn off once started… stays live until explicitly stopped by user."* | Auto-idle after N empty minutes — re-introduces "restart the run to continue". |
| **D-6** | `reset_image` (single row) ⇒ `pending` **and `selected=True`** (re-queued, picked up in ≤ 1 s). `reset_all` ⇒ `pending` + `selected=False` (parked) **plus one explicit log line** telling the user how to re-queue. | Brief: *"Images with reset or pending status automatically re-enter the queue."* A single Reset is an explicit "do this one again"; a bulk Reset All must not silently relaunch 500 jobs (destructive-surprise rule, same reason `clear_queue`/`keep_only_ai_files` confirm first). | Both re-queue (literal maximum) — one click re-runs the whole folder; flip is one argument (`reset_image_state(img, True)`). |
| **D-7** | Cancel tracking stops using the coroutine **name** (`co_name == "run_batch"`): new explicit seam `run_state.schedule_batch(bridge, coro)`. The live entry is `live/supervisor.py::run_live`. | A rename would silently break Stop (the failure mode `tests/test_bridge_slots.py` exists for). Explicit beats stringly-typed. | Keeping `run_batch` as the entry name — works, but preserves a hidden contract. |
| **D-8** | **One writer of run state**: `supervisor.set_run_state(bridge, value)` writes `bridge._run_state` **and** `bridge.state.run_state`, then emits. Of today's 11 scattered writes (7 of them `"idle"`), the **6 self-ending ones are deleted** (the run no longer ends itself) and the 5 user-driven ones route through the single writer. Fixes L-2. | RULE 10 (one control per decision) + RULE 13 (never persist state you cannot read back — today the persisted `run_state` is always `idle`). | Leaving the 11 writes — the live loop would need to patch each one. |
| **D-9** | **No new slots, no JS growth.** The frozen surface stays 134; the JS change is a *deletion* (the 15 s scan interval). Run-liveness is displayed through the existing `progress_updated.run_state`. | `tests/test_bridge_slots.py` + the JS `file_lines`/`func_count` ratchet. | Adding `get_live_status` / a new JS panel — contract churn for information the UI already receives. |
| **D-10** | The reconciler **moves out of the panel** (`browser_tabs.py` 544 lines → ~440) into `live/reconcile.py`; the slot stays where it is and calls the service. Pure row helpers it needs (`_dedupe_state_rows`, `_add_missing_rows`) move to `live/url_policy.py` with 2-line delegations left behind, because **services never import panels** (`app/ui/panels/__init__.py:1-8`) and `app/ui/bridge.py:24-30` re-exports those names for tests. Pool-joining stays a panel/browser concern and is injected as a seam (`LiveDeps.join_tab`), mirroring `WatcherDeps`. | RULE 18.2 (a 544-line file has a second responsibility — periodic reconciliation is not "tab slots"); import direction stays `ui → services`, never the reverse. | Growing `browser_tabs.py` with loop code, or letting `live/reconcile.py` import `app.ui.panels.*` — ratchet debt + a cycle. |

---

## 3. Architecture

### 3.1 New module `app/services/live/` (6 files, ~850 LOC, cohesive: "the loops that keep the run alive")

| File | Owns | ~LOC |
|---|---|---:|
| `__init__.py` | facade re-exports (`run_live`, `start_reconciler`, `wake`, `commit_queue`, `eligible_images`) | 30 |
| `bus.py` | `LiveBus`: one `asyncio.Event` + reason set + log throttle; thread-safe `wake()` from the Qt thread via `loop.call_soon_threadsafe` (same pattern as `CaptchaWatcher.stop`, `captcha_watcher/watcher.py:163-172`) | 90 |
| `supervisor.py` | **feature 03** — `run_live` loop, `PassPlan`, `set_run_state`, tails | 230 |
| `feed.py` | **feature 04** — eligibility read model, `commit_queue`, stale-`processing` recovery, row-removal cleanup | 150 |
| `reconcile.py` | **feature 02** — the reconciler loop + one reconcile pass (moved from `browser_tabs.py`), `LiveDeps` seam for the pool-join | 190 |
| `url_policy.py` | **feature 02** — pure removal/hysteresis/memory policy + the row helpers moved out of the panel (`dedupe_rows`, `add_rows`); no I/O, no bridge, no panel import | 160 |

`app/services/` stays at 12 top-level files + 6 packages (RULE 18.3 module 5–15 ✓).
Import direction: `live → services/{auto_connect,cooldown_service,batch_orchestrator,run_state}`,
`live → core`, never `live → ui`. Panels import `live` (allowed: `ui → services`).

**Feature 01** gets its own file in the existing package: `app/services/captcha/policy.py` (~35 LOC,
package 6 → 7 files ✓) — captcha scope is captcha policy, not run-loop policy.

### 3.2 Runtime picture

```
Qt thread (frozen slots)                        bg loop thread "arena-bg-loop"
────────────────────────                        ───────────────────────────────
start_run ──────► schedule_batch(run_live(b)) ──► SUPERVISOR  live/supervisor.py
cancel_current ─► future.cancel() + flags         while live:
stop_after_current ─► _stop_after = True            plan = plan_pass(b)   ← fresh read every pass
pause/resume ───► _pause_requested                  blocked/empty → wait on bus (≤1 s poll)
                                                    work → run_pass(b, plan)
reset/retry/select/scan ─► commit_queue(b) ─┐         ├─ ≥2 pages & ≥2 images → dispatch_parallel
                                            │         └─ else → sequential per-image lane
URL slots ─► commit_urls(b) ────────────────┤
auto_connect_scan slot ─► reconcile_once ───┼──► wake(reason) ─► bus.event.set()
                                            │
                            RECONCILER  live/reconcile.py (every url_reconcile_interval_ms, default 5 s)
                              fetch tabs → dedupe → plan(add/claim/connect) → url_policy.removable_rows
                              → apply (never a row with a live job) → commit → wake("urls")

                            CAPTCHA WATCHER (unchanged, 4 s, only when ON + key)
                            PASSIVE WATCHER (unchanged, only when ON)
```

Nothing polls faster than today: the JS 15 s scan is **deleted**, the reconciler replaces it at 5 s;
the supervisor sleeps on an event, so an idle live run costs one 1 s timeout per second and no CDP
traffic (compared with today's per-poll `is_security_dialog_visible`, which feature 01 removes).

### 3.3 Wake reasons (data, not branches — RULE 19 step 2)

`queue` (image reset/retry/select/scan/clear) · `urls` (row add/claim/remove/toggle) ·
`pool` (tab ready / cooldown expired / tab joined) · `watcher` (switch flipped) · `cdp` (primary
reconnected). `LiveBus.wait()` returns the drained reason set so the supervisor can log *why* it
woke: `🟢 Run live — woke: urls (+1 row, −1 row) — 3 queued`.

---

## 4. Feature 01 — captcha scope

### 4.1 New predicate (single source)

```python
# app/services/captcha/policy.py
def watcher_enabled(bridge) -> bool:   # the user's Watcher switch (config mirror, fail-closed)
def solver_running(bridge) -> bool:    # the SDK loop (words the reason line, sets method)
def captcha_in_scope(bridge) -> bool:  # == watcher_enabled — the ONE gate the pipeline asks
```

### 4.2 Gate placement (5 edits, all in existing functions)

| Site | Edit | Effect when OFF |
|---|---|---|
| `single_job_runner.check_security:107` | first line `if not captcha_in_scope(ctx.bridge): return False` | kills sites 2, 3, 4 in one place (RULE 9: returns "no captcha", stack continues) |
| `single_job_runner._handle_security:402` | scope guard **before** the probe; block reports `success` / `"Skipped (Watcher off)"` | no probe, no "Security dialog visible" wording, stack never stalls |
| `single_job_runner.wait_for_output:249` | install `security_settler` **only** when in scope | `cdp_arena/output.py:115` `_security_gate` never evaluates the dialog predicate → one CDP round-trip less per poll |
| `captcha/service.handle_captcha:210` | choke-point gate **before** `detect_signal`: return `SolveOutcome(status="out_of_scope", reason="watcher off")` | no detect probe, no stats, no recording, no overlay, no penalty, no `CAPTCHA_SOLVE`/`CAPTCHA_JOB`, no pool `waiting_captcha` |
| `captcha/service._watcher_running:242-249` | delegate to `policy.solver_running` (behaviour identical) | one owner for the getattr dance |

`_handle_captcha_outcome` (`single_job_runner.py:75`) treats `out_of_scope` like `none` (no raise).
`SolveOutcome` vocabulary gains `"out_of_scope"` in `app/services/captcha/signals.py`.

### 4.3 Kept on purpose (visible lines with the Watcher OFF)

* `🛡️ Captcha Watcher OFF — the app no longer solves captchas` (`captcha_watcher/watcher.py:159`) —
  the switch's own confirmation, emitted once at the transition, not a detection sign.
* `🛡️ Captcha Watcher: no 2Captcha key …` (`watcher_solver.py:131`) — Watcher is ON here.
* The `CHECK_SECURITY` block's own telemetry (`running`/`success`) — block events, no captcha claim.

### 4.4 Live in both directions

The gate is evaluated **per call**, so flipping the Watcher mid-run changes behaviour on the next
block, with no restart (features 03/04 requirement, same mechanism). `stop_watcher` →
`solver_follow(False)` already stops the solver loop; nothing else to do.

---

## 5. Feature 02 — dynamic URL management

### 5.1 The reconciler loop (Python-owned, run-state independent)

```python
# app/services/live/reconcile.py
async def reconcile_loop(bridge) -> None          # started once from bridge init (schedule_coro)
async def reconcile_once(bridge, source) -> Report # one pass; also the `auto_connect_scan` slot body
```

`LiveDeps(fetch_tabs, join_tab, commit)` is injected when the loop starts — the service never
imports `app.ui.panels.*` or `app.browser.*` (D-10); `join_tab` is today's `do_connect_page_pool`
(`app/ui/panels/page_pool.py:78`).

One pass = today's `auto_scan_pass` (`browser_tabs.py:374-387`) with the idle-only prune replaced:

1. `fetch_tabs()` — an empty/failed fetch **never** removes (existing safety, kept).
2. `url_policy.dedupe_rows` (I-33 repair) → `plan_auto_connect` (add/claim/connect/stale) — unchanged planner.
3. `url_policy.removable_rows(spec)` — the new decision (D-4), spec = rows, live keys, pattern,
   busy tabs, miss counters.
4. Apply: claim → add (with `url_policy.restore_enabled` memory) → remove → `join_new_tabs` →
   `sync_pool_presence`.
5. Commit through the existing funnel (`_save_arena` + `_emit_arena_state`; no undo entry for system
   changes — `browser_tabs.py:319-336` decision kept, I-37 respected).
6. `feed.clear_row_assignments(bridge, removed_ids)` — images pointing at a removed row lose the
   dangling `assigned_url_id` (one log line with the count).
7. `wake("urls")` when anything changed.

Log vocabulary (one line per change, reason included — RULE 2):

```
🔺 URL added https://arena.ai/… (tab 3F2A…) — new matching tab
🔗 URL linked row 4 → tab 3F2A… — exact URL match
🔻 URL removed https://arena.ai/… — tab closed (2 reconciles)
🔻 URL removed https://example.com/… — does not match pattern 'arena.ai'
🔻 URL removed https://arena.ai/… — status 'authentication required'
⏸ URL removal deferred tab 3F2A… — job running on it (next reconcile)
🤖 Reconcile: +1 added, 1 linked, −2 removed, 3 joined, 1 revived, 0 stale   (manual: always answered)
```

### 5.2 Pure policy (`live/url_policy.py`, no bridge, no I/O — 100 % unit-testable)

```python
@dataclass
class RemovalSpec:  rows; live_keys; pattern; busy_tabs; misses
@dataclass
class Removal:      row_id; url; reason          # tab_gone | pattern_mismatch | invalid | duplicate

def advance_misses(rows, live_keys, misses) -> dict   # hysteresis counters (drop on reappearance)
def removable_rows(spec: RemovalSpec) -> list[Removal]
def dedupe_rows(rows) -> tuple[list, int]             # moved from panels/url_queue._dedupe_state_rows
def add_rows(rows, adds, memory) -> int               # moved from panels/url_queue._add_missing_rows
def remember(rows, memory) -> None                    # url → enabled/last_status (bounded 200)
def restore_enabled(adds, memory) -> list             # re-opened tab gets its previous checkbox
def removal_lines(removals) -> list[str]
```

`removable_rows` is a lookup over reason predicates (a table of 4 `(reason, predicate)` pairs), not
an if/elif chain — RULE 19 step 2, CC target ≤ 8.

### 5.3 Live-run guards (the part that makes it "on the fly")

| Situation | Behaviour |
|---|---|
| Row removed while its tab is idle | immediate; the next pass re-reads `allowed` and never assigns it |
| Row removed while its tab has a live job (`tab_has_live_job`, `cooldown_service.py:163`) | **deferred** to a later reconcile (logged once); the in-flight job is never aborted mid-verification (RULE 15) |
| Tab closed while a job runs on it | the job fails through the CDP error path (I-36 recovery already re-attaches or fails honestly); the row goes on the next reconcile |
| New tab appears mid-run | joined to the pool + row added + `wake("urls")` → the **next pass** can dispatch to it in parallel (no restart) |
| Row unchecked by the user mid-run | `allowed` shrinks at the next image boundary (sequential lane) / next dispatch (parallel lane) |

### 5.4 JS

Delete `setInterval(() => this.autoConnectScan(), 15000)` (`cdp.js:33`) — the Python loop is now the
single periodic writer (RULE 10). The boot kick at 4 s (`cdp.js:32`) and both Reparse buttons stay
(they call the frozen slot, which now triggers an immediate `reconcile_once`). `file_lines` 135 → 134
(shrink ⇒ ratchet-safe).

---

## 6. Feature 03 — the always-live run

### 6.1 The loop

```python
# app/services/live/supervisor.py
async def run_live(bridge) -> None:
    bus = live_bus(bridge); bus.attach(asyncio.get_running_loop())
    recover_stale_processing(bridge)            # one sweep: crashed 'processing' → pending
    set_run_state(bridge, "running"); _announce_live(bridge)
    try:
        while is_live(bridge):                  # not _cancel_requested and not _stop_after
            plan = plan_pass(bridge)
            if plan.reason:                     # "no images" | "no tab" | "all cooling" | "cdp down"
                await wait_reason(bridge, plan, bus)     # throttled line + bus.wait(1 s)
                continue
            await run_pass(bridge, plan)        # existing orchestrator / dispatcher lane
            pass_tail(bridge, plan)             # 🏁 Pass complete — run stays live (N queued)
    except asyncio.CancelledError:
        cancelled_tail(bridge); raise
    finally:
        set_run_state(bridge, "idle")           # the ONLY idle writer left
```

`is_live` reads the two existing flags; `pause` is honoured **inside** the pass
(`batch_orchestrator.await_pause_or_abort:139`, `_wait_pause` in the dispatcher) so Pause/Resume keep
working unchanged (RULE 7).

### 6.2 Pass planning (fresh every pass — this is what makes 02/04 "live")

```python
@dataclass
class PassPlan:
    images: list; urls: list; allowed: set; tab_id: str; reason: str
```

`plan_pass(bridge)` re-reads `bridge.state.images` (via `feed.eligible_images`),
`bridge.state.urls` (enabled rows), `allowed = enabled_tab_ids(...)` and resolves the primary tab
(`resolve_and_claim_tab`) **at every pass**, then names the blocking reason from a lookup table:

| reason | condition | throttled line |
|---|---|---|
| `""` | work + usable tab | — |
| `no images` | eligibility empty | `🟢 Run live — 0 queued images (Reset/Retry or Scan adds work instantly)` |
| `no tab` | no checked row owns a live tab | `🟡 No usable checked tab — run stays live, retrying (pool: …)` |
| `all cooling` | every allowed tab in cooldown | `⏳ All tabs cooling — next ready in MM:SS (run stays live)` |
| `cdp down` | primary client disconnected | `🔌 Chrome disconnected — run stays live, reconnecting (pool: …)` |

Each line goes through `bus.throttle(key, 300)` ⇒ at most one per 5 min per reason, plus one on every
reason *change* (so the log still tells the story without flooding).

### 6.3 What changes in the existing lanes

| File | Change |
|---|---|
| `batch_orchestrator.py` | `prepare_batch(bridge, plan)` builds `BatchCtx` **from the plan** (no re-snapshot); `_run_sequential` drops its tail call; `_finish_batch` → `pass_complete(ctx)` (log only, no run-state write); `_abort_no_tab` deleted (supervisor waits instead); `_cancel_batch`/`_crash_batch`/`run_batch` move to the supervisor; `_claim_tab` refreshes `ctx.allowed` from live state before resolving (per-image URL liveness); `_selected_images` deleted (→ `feed.eligible_images`). Net: 492 → ~445 lines |
| `multi_page_dispatcher.py` | `_finalize_batch` stops writing `_run_state` (log + emits only) — the supervisor owns it; `dispatch_parallel` takes the plan's `urls`/`allowed` (already parameters) |
| `run_state.py` | `_track_batch_future` (name check) deleted; `schedule_batch(bridge, coro)` added (submit + always track + done-callback) |
| `run_control.py` | `start_run`: gate → `recover_stale_processing` → `set_run_state("running")` → `schedule_batch(run_live(self))`; when already live ⇒ **wake + re-announce** instead of `⚠ Already running`; `cancel_current` / `stop_after_current` unchanged except they now go through `set_run_state`; queue slots end in `commit_queue` |
| `queue_scan.py` | `run_folder_ai_request` guard changes from "run is idle" to "**no image is `processing`**" (D-5 makes the old guard permanently closed); scan workers end in `commit_queue` |
| `layout_state.py` | unchanged — `run_state` now also comes from `AppState` (D-8) so the serialized value is honest |

### 6.4 End-of-run semantics (unchanged surface, new internals)

| User action | Result |
|---|---|
| **Stop** (`cancel_current`) | flags + future cancel + in-flight images fail as `Cancelled by user` + `🏁 Batch cancelled` + `run_state=idle` (today's behaviour, same log strings) |
| **Stop after current** (`stop_after_current`) | in-flight image(s) finish, pass ends, run ends: `🏁 Batch complete` + `idle` |
| **Pause / Resume** | pass-level gate, unchanged |
| **Start while live** | no-op + `wake` + `🟢 Run already live — queue re-checked (N queued)` |
| App close | bg loop is a daemon thread (`run_state.py:79-88`) — dies with the process, as today |

---

## 7. Feature 04 — live queue updates

### 7.1 One read model, one write funnel

```python
# app/services/live/feed.py
ELIGIBLE = ("pending", "failed", "selected", "needs_review")   # 'processing' excluded while live

def eligible_images(images) -> list          # snapshot copy; the ONLY eligibility rule
def recover_stale_processing(bridge) -> int  # start sweep: 'processing' with no live tab job → pending
def commit_queue(bridge) -> None             # recalculate + save + emit + undo + wake("queue")
def clear_row_assignments(bridge, ids) -> int
```

* `eligible_images` replaces **both** clones (`queue_scan.selected_images:28`,
  `batch_orchestrator._selected_images:398`) ⇒ duplication floor improves, one rule to test.
  `queue_scan.selected_images` stays as a 2-line delegation (frozen slot surface + 6 test imports).
* `processing` is out of the live read model (double-dispatch protection); the crash-recovery intent
  moves to `recover_stale_processing`, called once at `start_run` — same effect, no race.
* `commit_queue` replaces the repeated 3-line tail in 8 slots (`run_control.py` 5, `queue_scan.py` 3)
  ⇒ **net LOC decrease** in both panels, and every queue mutation now wakes the loop.

### 7.2 Latency budget ("ASAP")

| Event | Path | Worst-case delay |
|---|---|---:|
| Reset / Retry one image | slot → `commit_queue` → `wake("queue")` → supervisor `bus.wait` returns | ≤ ~50 ms if the loop is waiting; ≤ one image if a pass is in flight (the next pass picks it up) |
| Scan finished (new images) | worker thread → `commit_queue` → `wake` | same |
| URL row added/removed | reconciler → `wake("urls")` → next pass re-plans `allowed` | ≤ 5 s (reconcile interval) + pass boundary |
| Tab becomes ready (cooldown expiry) | pool emit → `wake("pool")` (from `refresh_expired` callers) | ≤ 1 s |
| Watcher flipped ON | `start_watcher` → `wake("watcher")` | next block boundary (per-call gate) |

A pass in flight is never interrupted by new work (that would break RULE 15 mid-verification);
"ASAP" therefore means *the next pass*, which for the sequential lane is the next image boundary —
i.e. seconds, not a restart.

### 7.3 Concurrency (Qt thread ⇄ bg loop)

* Reads: `eligible_images` / `plan_pass` copy the list (`list(...)`) before filtering; the pool has
  its own `RLock` (`app/browser/page_pool.py:70`).
* Writes: `bridge._state_lock` (`threading.RLock`, created in `bridge_context.init_run_state`) taken
  by `commit_queue`, `commit_urls`, `save_arena_state` and `plan_pass`. **Invariant: never hold it
  across an `await`** (the guarded regions are list/dict copies + one atomic JSON write).
* Saves stay atomic (`core/persistence.py:24-45`), so a crash mid-write cannot brick state (RULE 13).

---

## 8. Sequencing (5 stages, each independently gate-green)

| Stage | Content | Gate before moving on |
|---|---|---|
| **S0** | Bootstrap `.venv` + `npm ci`; record the current gate output (`verify_quality`, pytest, coverage, jscpd) as the equivalence baseline | numbers captured in `quality-budget.md` §6 |
| **S1** | Feature 01: `captcha/policy.py` + 5 gate edits + `out_of_scope` outcome + tests + rule/doc amendments | fast lane green; `captcha/service.py` coverage ≥ 94.69; goldens unchanged (`captcha.json` harness arms the watcher ON) |
| **S2** | `live/bus.py` + `live/feed.py` + `commit_queue` in 8 slots + eligibility merge + `schedule_batch` + `_state_lock` (no loop yet ⇒ behaviour identical except reset re-queues) | duplication ≤ 1.240 %; `run_control.py`/`queue_scan.py` coverage floors held |
| **S3** | Feature 03: `live/supervisor.py`, orchestrator/dispatcher tail surgery, `set_run_state` single writer, harness arms `_stop_after`, goldens regenerated **after review** (`UPDATE_GOLDENS=1`) | all 12 goldens green; pinned log strings intact |
| **S4** | Feature 02: `live/url_policy.py` + `live/reconcile.py` (with `LiveDeps`), `browser_tabs` move-out + panel delegations, JS interval deletion, `run_folder_ai_request` guard, **L-1 one-word fix** (`page_pool.py:147` `_schedule_coro` → `schedule_coro`) | `auto_connect.py` stays 100 %; `browser_tabs.py` coverage ≥ 89.13 |
| **S5** | Docs: SYSTEM_OF_RECORD rows 3/6/11/12/21 + I-19/I-34 amended + I-39/I-40/I-41 added, RULE 20 amendment, `docs/README.md` map, `QUALITY_RECHECK.md` refresh, baseline re-record with reasons | `bash tools/pre_push_check.sh` clean |

Each stage is a separate commit on `arena/01a0bc3b-process-images-in-areana`; S1 alone already fixes
the log-noise complaint, so it ships first.

---

## 9. New invariants (to be added to SYSTEM_OF_RECORD §5 in S5)

| ID | Invariant | Enforcement |
|---|---|---|
| **I-39** | A live run ends only on an explicit user stop; no-work / no-tab / cooling / CDP-down are **wait** states with throttled lines, never terminal | `live/supervisor.py` + `tests/test_live_supervisor.py` |
| **I-40** | Captcha work (probe, wait, overlay, penalty, recording, stats, logs) happens **only** while the Watcher switch is ON; one predicate decides it | `captcha/policy.py` + `tests/test_captcha_scope.py` |
| **I-41** | One queue write funnel (`commit_queue`) and one eligibility rule (`eligible_images`); every queue/URL change wakes the live loop | `live/feed.py` + `tests/test_live_feed.py` |
| **I-42** | URL rows are reconciled by Python on a 5 s passive pass, in any run state, and never removed while their tab has a live job; removal always carries a reason | `live/url_policy.py` + `tests/test_url_policy.py` |

---

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | Two passes dispatch the same image | single supervisor task (idempotent `start_run`), `processing` out of the read model, `_acquire_free_in` busy-claim (`multi_page_dispatcher.py:104-118`) |
| R2 | Log flooding from a loop that never ends | every repeat line through `bus.throttle(key, 300)`; one line per reason *change* |
| R3 | URL flapping on a transient empty `fetch_tabs` | 2-miss hysteresis + "empty fetch never removes" (kept from `sync_pool_presence`) |
| R4 | Removing a row mid-job corrupts a verification | live-job deferral (D-4/I-42); in-flight jobs are never aborted by reconciliation |
| R5 | Watcher OFF hides a real captcha → user sees a plain timeout | accepted trade-off of D-1, documented in RULE 20 amendment + the failure text still names the gate that broke (`WAIT_OUTPUT timeout`, page-error text). Flip to "silent wait" is one predicate if the owner prefers |
| R6 | Qt/bg races on `state.images` | `_state_lock` (never across `await`) + snapshot reads + atomic saves |
| R7 | Golden/characterization drift hides a real regression | harness arms `_stop_after` so the trace still terminates; goldens regenerated only in S3 with a reviewed diff; pinned log strings kept verbatim |
| R8 | Frozen slot/packing contract broken by accident | D-9: zero new slots; `tests/test_bridge_slots.py` runs in every stage gate |
| R9 | Coverage floor drop in touched legacy files | per-file floors listed in `quality-budget.md` §3; new logic lives in new (fully tested) files |
| R10 | `run_folder_ai_request` becomes permanently refused | guard changed to "no image `processing`" in S3 |

---

## 11. Out of scope (explicit follow-ups)

1. Retiring the **passive** `WatcherService` (it duplicates captcha detection + job pausing next to
   the supervisor and the solver loop — a RULE 10 tension worth its own round).
2. Moving the JS 500 ms `ensurePrimary` tick into the Python reconciler (`cdp.js:34`).
3. Persisting `url_policy` memory across restarts (today: in-memory, bounded 200; restart ⇒ defaults).
4. Per-row auto-enable heuristics (e.g. auto-uncheck a tab that fails twice) — needs owner policy.
5. `RunState` enum cleanup (`"stopping"` vs `"stopping_after_current"`, `core/enums.py:57-64`) —
   cosmetic; touched only if S3 needs the value.
6. A UI "live" badge beyond `run_state` text (D-9 keeps the JS surface frozen).
