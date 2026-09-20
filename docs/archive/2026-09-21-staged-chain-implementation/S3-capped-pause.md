# S3 — capped captcha pause (D-14R) + honest wait wording (D-15)

*Chain stage 3 of the staged chain per `docs/archive/2026-09-20-dynamic-urls-and-worker-debug/`,
implemented 2026-09-21 on top of S2 (`fed1bf4`). Ground contracts: pause, cap and timeout evidence
in `evidence.md` §2.1 (now CLOSED); interface split per `tdd-interfaces.md` §S3.*

## What landed

- **New `app/core/pause_clock.py`** — `PauseClock(cap_s, total)` value object: `note` (capped,
  garbage-proof), `expired` (uncapped ⇒ never), `remaining` (never negative, uncapped ⇒ `inf`),
  `paused_elapsed(start, now=None)` (floored at 0), `describe` (`"+12s captcha wait (cap 300s, 288s
  left)"`, `""` when nothing absorbed). In `core/` because both browser-layer chargers and the wait
  loop may import it only from there (rule).
- **`app/services/captcha/policy.py`** grows the cap trio (file ~55 → ~90 LOC): `pause_cap_seconds`
  (the ONE knob `watcher_captcha_timeout_sec`, clamped 10…3600, fail-closed default 300),
  `wait_reason` (D-15 2-row wording table keyed on `has_solver_key` — the "turn the Watcher ON" lie
  removed), `WaitDeadline` (`expired`, `stop_or` — the cap composed into the predicate the caller
  already passes).
- **`app/browser/output_wait.py`** — `WaitSpec` gains `pause: Optional[PauseClock] = None`
  (span 3→4 = file `max_class_loc` 4 = exactly at the ceiling, legal; `LoopState` untouched);
  `_check_timeout` measures `pause.paused_elapsed(start)` when a clock rides the spec and stamps
  `paused_s` + `pause_note` into the timeout dicts via the new `_pause_evidence` helper.
  The fallback path (`_process_fallback`) intentionally keeps wall time (documented D-13 carve-out
  — a locked test pins it). The 23-LOC wait loop itself is untouched.
- **`app/browser/cdp_arena/output.py`** — `_settle_timed(settler, clock)` (CC 2 — the extraction is
  what keeps file `max_cc` at 4); `_security_gate` charges the settle through it, reading
  `ctrl.pause_clock` (signature `(cdp, ctrl)` unchanged); `_timeout_text(result, timeout_ms)` appends
  the pause note inside parentheses; `_map_wait_result` keeps 4 params (the note/paused_s ride INSIDE
  the `result` dict, never a 5th argument); `_run_wait` passes
  `pause=getattr(spec.ctrl, "pause_clock", None)` on the PollSpec line.
- **`app/services/single_job_runner.py`** — `wait_for_output` installs
  `ctx.ctrl.pause_clock = PauseClock(pause_cap_seconds(ctx.bridge))` next to the settler, in scope
  only (D-23: OFF ⇒ no clock installed at all); both handles are removed in one new
  `_drop_wait_handles` helper from `finally:` (keeps the function at its file max_func_loc ceiling).
  `_handle_captcha_outcome` maps `wait_timeout` → `RuntimeError(outcome.reason)` (retryable failure).
- **`app/services/captcha/service.py`** — `_resolve_captcha`'s inline wording collapses to
  `wait_reason(ctx.bridge)` (D-15; `_watcher_running` remains only for the outcome's `method` label);
  `_manual_wait` builds a `WaitDeadline(_wait_timeout(ctx))`, passes
  `deadline.stop_or(_stop_pred(ctx))` as the wait's stop predicate (cooldown's 4-arg
  `wait_captcha_cleared` seam + its pinned never-gives-up test untouched), and its old 8-line
  outcome block is extracted into `_wait_outcome` (cleared ⇒ penalty+stats+`manual`; deadline
  expired ⇒ `wait_timeout` "Captcha not cleared in Ns — job failed (retryable)", **no penalty**;
  else the existing `stopped` vocabulary wins). The `🛡️ FLAG CAPTCHA_WAITING` line is byte-identical
  (golden boundary); the cap is visible via the overlay countdown (`timeout_sec`) + the reason line.

## RED → GREEN

RED witnesses (venv pytest): 2 collection errors (`wait_reason`, `WaitDeadline` import), then
5 test failures (new `WaitSpec.pause` keyword); browser pair failed 5, captcha pair 8+4 import.
After GREEN: **25/25 new tests pass** (8 clock + 6 wait-pause + 8 cap + 4 wording … 26 asserts over
25 tests); sweep of captcha/cooldown/watcher/cdp family: **629 passed**; characterization:
**14/14 goldens byte-identical** (no pause ever fires in the harness; also locked: no golden
contains "Timeout"). `tests/test_cooldown_service.py` untouched, its pinned test green.

## Adaptations vs the plan (tree ≠ plan)

1. `PauseClock` API is exactly the tdd-interfaces §S3 table (`cap_s`, methods on the clock), NOT the
   older design sketch's module-level `paused_elapsed(start, clock)` helper.
2. The clock rides `ctrl.pause_clock` (object), not the earlier evidence draft's `pause_cap_s`.
3. Two named test updates in `tests/test_captcha_service.py` (D-15): the ON-without-key expectation
   now asserts the honest no-key wording (+`"turn the Watcher ON" not in`), and
   `test_watcher_running_labels_the_wait` stores a key so "running watcher ⇒ solving wording" stays
   true to the contract.
4. `wait_for_output` kept at its recorded `max_func_loc` by extracting `_drop_wait_handles`
   (the `finally:` no longer grows) — plan-budgeted (≤22) and ratchet-clean.
5. `tests/conftest.py` `fake_clock` exists (conftest:112); the plan's warning about it doesn't apply.
6. Invariant landed as **I-47** (plans' I-44 remapped per the merge-note; I-39…I-46 are B13-era rows).

## Docs in this commit

RULE 20 (bounded-wait amendment), SYSTEM_OF_RECORD rows 8 + 12 + I-47,
`evidence.md` §2.1 marked CLOSED, this file.

## Gate

`bash tools/stage_gate.sh` — 5/5 green (quality ratchet clean on the 6 touched app files incl. the
two maxima locks: `output_wait max_class_loc` stays 4, `cdp_arena/output max_cc` stays 4; frozen
seams 89p; unit+integration green in offscreen mode; goldens 14/14; JS lane skipped — no .js).
