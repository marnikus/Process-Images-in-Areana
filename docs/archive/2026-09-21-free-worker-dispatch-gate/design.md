# A free `steady (ready)` worker must not read as "no usable tab" (I-61)

*2026-09-21 — branch `arena/01a0c528-process-images-in-areana`.*

## 1. The report

> "6 pending i web page ready. but it wait and not run the job but should use free web page with status ready! fix. use integration test to catch bug"

Screenshot state:

| Worker | Status | Cooldown | Row checked | Holding |
|---|---|---|---|---|
| `marnikus@gmail.com_0002` | `waiting_generation` | — | ✔ | `icon-lightbulb-gear.png` |
| `morismasolen@gmail.com_0003` | **`steady (ready)`** | `00:00` | ✔ | — |

6 images pending. Badge: `RUN CYCLE ON · no usable tab`. The ready worker idled
next to a pending queue for as long as the other worker's generation took.

## 2. Root cause

The badge sub-label `no usable tab` is `REASON_LINES["no tab"]`, written by
`supervisor.plan_pass`. Its last branch was:

```python
current = getattr(bridge.cdp, "_current_tab_id", "") or ""
plan.tab_id = await resolve_and_claim_tab(bridge, current, plan.allowed)
plan.reason = "" if plan.tab_id else "no tab"
```

So **every pass was gated on resolving a primary CDP tab**. `resolve_and_claim_tab`
answers `""` when the single primary connection cannot be pointed at a usable
checked worker — measured, the exact matrix that produces `""`:

| `cdp.connect` | `_current_tab_id` | result |
|---|---|---|
| ok | anything | `ready` ✅ |
| **fails** | `busy` | `busy` (stays) |
| **fails** | `""` | **`""` → `no tab`** ❌ |
| fails | foreign id | that id (stays) |

`_resolve_allowed_tab` picks the ready worker correctly; `_move_to_tab` then
tries `cdp.connect(ws)` and, on failure with nothing currently attached, the
chain collapses to `""`.

**But the lane that would have run the work never needed that connection.**
`batch_orchestrator._try_parallel` takes over whenever `counts_in(pool, allowed)`
reports `total >= 2 and free >= 1`, and the feeder drives each job through the
pooled page's *own* client (`pool.get_clients(tab_id)`), never `bridge.cdp`. The
gate was therefore refusing a pass that the dispatcher was fully able to run —
it asked a question about the primary tab when the pass would have been answered
by the pool.

This is the mirror image of I-57 (the feeder fix): there the dispatcher held an
image back, here the *gate before* the dispatcher held the whole pass back.

## 3. The fix

`plan_pass` now asks the question the pass will actually answer — the same
predicate `_try_parallel` uses to choose its lane:

```python
def _parallel_ready(bridge, allowed: set) -> bool:
    """The feeder lane can run this pass: 2+ checked pooled workers, 1+ of them free."""
    pool = getattr(bridge, "_page_pool", None)
    if pool is None or not allowed:
        return False
    try:
        total, free = ac.counts_in(pool, allowed)
    except Exception:
        return False
    return total >= 2 and free >= 1
```

and the reason becomes

```python
return "" if (plan.tab_id or _parallel_ready(bridge, plan.allowed)) else "no tab"
```

Deliberately narrow:

* **`counts_in` is reused, not re-implemented** (RULE 10) — one predicate decides
  "the feeder can run" for both the gate and the lane pick, so they can never
  disagree again.
* **`free` already means free** — `PageInfo.is_free()` is `steady AND connected
  AND no live timer`, so a cooling or busy worker never opens the gate, and the
  `all cooling` reason keeps its precedence above this branch.
* **The single-worker case is untouched.** One pooled tab still falls through to
  the sequential lane, which genuinely does need the primary connection, so it
  still parks on `no tab` — a real wait state, loudly reported (RULE 4).
* **A pool that cannot be counted is broken, not free**: the `except` answers
  `False`, so the run waits instead of dispatching on a guess.

`plan_pass` was also split (RULE 19 — complexity before size) into `_queue_reason`
(pre-claim reasons) and `_claim_reason` (claim + post-claim reason). Measured CC:
`plan_pass` **8 → 4**, below its own pre-change baseline.

## 4. Integration test (RED first)

`tests/integration/test_free_tab_dispatch.py` — 4 tests, real `PagePool`, real
`Bridge` from the golden harness, `UnreachableCDP` reproducing the screenshot's
primary-connection state (`_current_tab_id=""`, every `connect` fails):

| Test | Asserts |
|---|---|
| `test_a_pass_is_planned_while_a_checked_worker_is_free` | **the bug**: `free == 1` yet `plan.reason == ""` |
| `test_the_pending_image_runs_on_the_free_worker_not_the_busy_one` | end of the chain — the job runs on `READY`, the image completes, the busy worker keeps its image |
| `test_a_broken_pool_read_stays_a_loud_wait_state` | an uncountable pool waits (RULE 4) |
| `test_a_single_pooled_worker_still_needs_the_primary_tab` | the sequential lane's `no tab` is still real |

Verified RED at base: with `supervisor.py` stashed, test 1 fails with
`a free checked worker must not read as 'no tab'`; the other three pass, so the
suite pins the bug and not the scaffolding.

## 5. Verification

| Gate | Before | After |
|---|---|---|
| pytest | 2,000 passed / 4 skipped | **2,007 passed / 4 skipped** |
| JS (`npm run test:js`) | 334 (330 pass, 4 skip) | **334 (330 pass, 4 skip)** |
| `verify_quality.py --allow-legacy --changed-files …` | 0 fails | **0 fails, 1 warn** (missing `coverage.json` only) |
| Coverage total | 88.38 / 84.93 | **88.43 / 85.02** |
| `supervisor.py` coverage | 96 % | **99 %** (only pre-existing lines 63–64 missing) |
| radon max CC in `supervisor.py` | `plan_pass` 8 | **`_parallel_ready` 5, `plan_pass` 4** |
| vulture `--min-confidence 90` | clean | clean |
| File size (RULE 18) | 181 lines | 202 lines (ideal band for a services module) |

Goldens byte-identical; no slot, signal, state field or JS file touched.
