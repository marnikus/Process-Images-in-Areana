# Run-cycle ON/OFF badge + idle-worker instant start — design (2026-09-21)

Two owner items, one branch, two commits' worth of work delivered together
because the second is a bug and the first re-labels the badge landed the day
before (`archive/2026-09-20-run-badges-and-worker-overlay/`).

## Item A — "Run Cycle ON / OFF", always visible

### A.1 Brief
The 2026-09-20 badge showed *PAUSED / STOPPING / STOPPED* and hid itself while
running. The owner's correction: two **persistent** badges — **Run Cycle ON**
(running, paused, waiting for cooldown, solving captcha … anything but an
explicit stop) and **Run Cycle OFF** (the user stopped the cycle). Paused is
still ON. Sub-labels (paused / cooldown / captcha) appear *next to* the
badge, never instead of it. Both windows always show the same state.

### A.2 Evidence
| Fact | Where |
|---|---|
| `run_state` ∈ `idle / running / paused / stopping`; `idle` is written exactly once, in `run_live`'s `finally` — i.e. only after Cancel / Stop-after / crash. `running` is written by `run_live` on entry and by Resume. So **ON ≡ `run_state != "idle"`** already; no second flag is needed. | `live/supervisor.py:58,161-181`, `run_control.py` |
| The wait reasons ("all cooling", "no images", …) are already published per pass in `bridge._live_reason` but **not** on the wire; the Live Debug cadence line only shows `run <state>`. | `supervisor.wait_reason`, `debug_view.live_view` |
| Both windows already carry a `[data-run-badge]` slot and one painter (`js/core/run-badge.js`) fed by `progress_updated.run_state`. | 2026-09-20 D-2 |

### A.3 Decisions
| # | Decision | Why | Rejected |
|---|---|---|---|
| **A-1** | ON/OFF is a **view** of the same `run_state`: `idle` → **RUN CYCLE OFF** (red), everything else → **RUN CYCLE ON** (green). Never hidden. Unknown → OFF. | The supervisor's `finally` is literally "the cycle stopped"; one truth, one writer (D-8). | A new `cycle_on` flag on the bridge (second truth that can drift). |
| **A-2** | The **sub-label** is a second span `[data-run-sub]` next to each badge: `paused` → *paused*, `stopping` → *stopping after current*, and while running the live wait reason from `progress_updated.live.wait_reason` → *waiting for cooldown* / *no usable tab* / *0 queued* / *Chrome disconnected*; empty while a pass is actively dispatching. Python publishes the reason (`live_view["wait_reason"]` = `bridge._live_reason or ""`); the JS only maps words. | "Additional sub-labels appear alongside, never replace" — a separate element cannot replace the badge. The reason already exists in Python; publishing it is one key on the payload the window already receives (0 slots, 0 signals). | Deriving cooldown/captcha from the pool table in JS (a second rule for "why are we waiting"). |
| **A-3** | `run-badge.js` keeps its shape: `VIEWS` → `{label, mod}` becomes ON/OFF; `SUBS` maps state + reason → sub text; `apply(state, live)` paints both spans. File stays under 50 lines. | Same painter, same slots. | A second module for the sub-label. |
| **A-4** | The head-strip badge in Live Debug gets the pool-status pill's neighbour spot so the ON/OFF badge is not competing with "2 PAGES 1 STEADY … WAITING FOR COOLDOWN" — that pill stays (it is the pool, not the cycle). | Owner: "persistent and prominent, not hidden by other status labels". | Removing the pool pill. |

## Item B — idle worker does not start the next pending job

### B.1 Brief
Two pending images, worker #1 busy, worker #2 ready ⇒ #2 must pick up the
next image **immediately**. Observed: #2 sits idle (screenshot 3: `#2 steady
· idle · ready`, 2 pending, #1 `waiting_captcha`).

### B.2 Root cause (read from the code, verified by the RED test)
`dispatch_parallel` (`multi_page_dispatcher.py:343`) sizes the pass with
`Semaphore(total_allowed_pages)` and creates **one task per image up front**.
Each task then calls `_acquire_page` → `_wait_free_in`, which polls
`_acquire_free_in` every 0.5 s **up to `cooldown_aware_timeout` (≥ 600 s)**.
That is the correct *mechanics* — a free tab is claimed within 0.5 s — **but
the supervisor's pass is the unit of planning**: `plan_pass` snapshots
`queued_images` once, `run_pass` hands that list to the dispatcher, and the
pass does not return until *every* task has finished (`asyncio.gather`). The
failure mode in the screenshot is the pass boundary, not the wait:

1. Pass *n* was planned with the images that were queued **at that moment**
   (say one image, because the second was still `processing` / had just been
   reset / had just been scanned). It dispatched that one image to #1.
2. #1 hits a captcha and waits (minutes). The pass cannot end.
3. Meanwhile the queue changed — a Reset / Scan / job finished on #2 — and
   `queued` shows 2. Those images are **not in pass n's list**; nothing
   dispatches them until pass n ends, which is when #1's captcha clears.
   #2 idles for the whole captcha.

A second, narrower path with the same symptom: `_try_parallel` requires
`len(ctx.images) >= 2` — a pass planned with **one** image on a 2-tab pool
runs *sequentially on the primary tab*, and if that tab is the busy one the
image waits behind it while the other tab is free.

### B.3 Decision
| # | Decision | Why | Rejected |
|---|---|---|---|
| **B-1** | **The dispatcher re-plans from the live queue while a pass is open.** `dispatch_parallel` becomes a *feeder*: instead of `_create_tasks(ctx, images)` once, it loops `while live: image = next_unclaimed(bridge) → wait for a free allowed page → task`, re-reading `queued_images(bridge)` each time a slot opens, and stops feeding when the queue is empty **and** all tasks are done, or on Cancel / Stop-after. The wait for a free page moves *before* task creation (a task is created only when a page is already claimed for it), so idle tabs are matched with new work the moment either appears. | The bug is the frozen per-pass image list; the fix is to stop freezing it. One dispatcher, one loop, no timer. | A shorter `plan_pass` cadence (the pass still blocks on `gather`). A "pre-emptive" second supervisor loop (two writers of dispatch). |
| **B-2** | Free-page wait becomes **event-driven**: `_wait_free_in` waits on the bridge's `LiveBus` (`bus.wait(0.5)`) instead of `asyncio.sleep(0.5)`, and `finish_page_after_job` / `mark_steady` paths already emit — we add a `live_bus(bridge).wake("page free")` in the dispatcher's `_finish_page_safely` and in `commit_queue` (exists). Net: ready ⇒ pickup in the same loop tick, not ≤ 0.5 s later. | "No delay between worker becoming available and job assignment." | Polling faster (burns CPU; still a delay). |
| **B-3** | `_try_parallel`'s `len(images) >= 2` gate goes: with ≥ 2 allowed pages the parallel feeder runs for **any** number of images — with one image it simply uses the freest page. Sequential single-tab mode stays for pools of 0/1 pages. | A single image must not be forced onto a busy primary tab while another tab is idle. | Keeping the gate and adding a "which tab is free" pre-check to the sequential path (a second dispatcher). |
| **B-4** | Claim-time rule unchanged (`claim_denied` / `in_live_scope` — I-44); the feeder only asks the ONE eligibility rule (`feed.queued_images`) again; the retry cap still applies. Goldens must stay byte-identical (single-tab sequential mode untouched). | RULE 10. | — |

### B.4 Interfaces (as landed)
| Symbol | Change | Measured |
|---|---|---|
| `multi_page_dispatcher.dispatch_parallel(bridge, pool, images, urls)` | signature unchanged; `images` is the **seed** — served first, then `queued_images(bridge)` is re-read while the pass is open | 16 lines / CC 5 |
| `DispatchCtx` | `sem` → `seed`, `claimed`, `tasks` (9 lines, class ratchet kept) | — |
| `_feed_tasks(ctx)` / `_serve(ctx, img)` / `_take_next(ctx)` / `_start_on_free_page(ctx, img)` / `_feeding(bridge)` / `_pending(tasks)` | replace `_create_tasks` + `_run_with_sem` + the semaphore | 8 / 6 / 7 / 9 / 3 / 2 lines, CC ≤ 4, nest ≤ 2 |
| `run_one_image_on_page(bridge, pool, img, urls)` | unchanged entry (claims, then delegates) | 29 → 10 lines |
| `run_claimed_image(ctx, img, page)` / `_run_and_record(job)` | the feeder path; 3 params via `DispatchCtx` (no override) | 16 / 11 lines |
| `FreeWaitSpec.wake_wait` (default `asyncio.sleep`) + `_gave_up(spec, waited)` | `_acquire_page` passes `live_bus(bridge).wait` — the wake is the path, the poll the fallback; cancel check = `not _feeding(bridge)` (Stop-after stops a wait too) | `_wait_free_in` 14 → 10 lines, cog 9 → 3 |
| `_finish_page_safely` | `finally: live_bus(bridge).wake("page free")` | 11 lines |
| `batch_orchestrator._try_parallel` | `len(ctx.images) >= 2` dropped (B-3) | 16 lines / CC 5 |
| `live/debug_view.live_view` | `+ "wait_reason"` (the supervisor's `_live_reason` or `""`) | 12 lines |
| `live/__init__` | stops re-exporting `supervisor` (import it as a submodule) — the dispatcher now imports `live.bus` / `live.feed` and an eager re-export made `supervisor → batch_orchestrator → multi_page_dispatcher → live` a cycle | doc + 2 lines |
| `js/core/run-badge.js` | `ON` / `OFF` / `STATES` / `SUBS` / `REASONS`, `view`, `sub(state, live)`, `apply(state, live)` | 46 lines, max CC 6 |
| `index.html` / `arena.css` | `[data-run-sub]` beside each `[data-run-badge]`; `.run-badge--on/--off` (never hidden), `.run-sub` | markup / 7 lines |

### B.5 Tests (RED first, all landed)
`tests/test_instant_dispatch.py` (7): the reported bug (A held on one tab, B queued mid-pass → B starts on the other tab while A is still `processing`); a freed tab is taken on the wake with the poll stretched to 5 s (< 0.3 s) **and** queue order kept (base violated it: task-per-image raced); never twice + `claim_denied`; Cancel / Stop-after stop the feeder; the pass ends when queue empty and tasks done; single image + 2 tabs goes parallel (B-3); a timed-out free-page wait logs `⏰` and moves on. `tests/test_live_debug_view.py` +1 (`wait_reason`). `tests/js/test_run_badge.mjs` (6, rewritten): ON for running/paused/stopping, OFF for idle/unknown, never hidden; sub-label mapping incl. *paused wins over the wait reason* and *OFF has no sub-label*; both pairs painted; bind-once; markup + CSS contract (`.run-badge[hidden]` must not exist).

### B.6 RULE 16 / 18 recheck (measured on the final tree)
* **RULE 18** — `multi_page_dispatcher.py` 402 → 447 lines (its `ideal-size` note allows ~400 for the one lifecycle; the growth is the feeder + the split of a 29-line function), but every function is now ≤ 18 lines (was 29); `run-badge.js` 46 lines; `debug_view.py` 85.
* **RULE 16** — dispatcher file maxima: LOC 29 → **18**, cog 8 → **5**, CC 8 (unchanged, `_acquire_free_in`), nest 2 (unchanged), params 4 (unchanged); orchestrator unchanged maxima; no override used. `verify_quality --allow-legacy --changed-files`: 0 real fails — only the `max_cog`-0 baseline artefact and the two sandbox `libGL` floors.
* **Coverage** — `debug_view.py` 100 %, dispatcher 89 % (the misses are pre-existing `except: pass` guards), project **87.91 / 84.56**. **jscpd** 1.071 %. **Goldens byte-identical** (single-tab sequential path untouched). **Σ slots 135, signals unchanged.**
* Lane: pytest **1,797 / 0** (+1 after the timeout test), JS **281 / 0**.
