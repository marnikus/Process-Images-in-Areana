# URL List inline controls and cooldown reset — design

**Date:** 2026-10-01  
**Status:** implementation design; production changes follow RED-first tests.

## Problem and evidence

The URL List shows a ticking countdown plus a separate cooldown pencil in each row, while the Jobs value is read-only. The row already receives the canonical `PagePool` snapshot, so the visible values can become edit targets without changing URL ownership, run selection, or the job pipeline. The URL List cooldown value uses `MM:SS` below one hour and `H:MM:SS` at/above one hour; `app/core/cooldown.py` caps a timer at 86,400 seconds. The existing Page Pool pencil is a distinct control in the Live Debug / Page Pool table and remains out of scope.

A reset cannot be implemented by looping over `reset_page_cooldown`: that slot owns a per-tab repair path, emits/persists per call, and can repair stale job metadata. The global action must leave jobs, URL rows, enablement, errors, and connections untouched, and must publish one fresh pool snapshot after one persistence attempt. I-27 remains authoritative for active jobs: a running job keeps its stacked pending penalty; an idle worker's pending debt is cleared.

`PageInfo.jobs_completed` is the display-only worker count (I-28). The current `cooldowns.json.stats` map preserves the greatest per-URL count, which cannot represent an explicit downward correction and can conflate same-URL workers. Keep that legacy URL value as a fallback and add exact worker-key entries inside the existing `stats` object. A manual correction updates only `PageInfo.jobs_completed`; it never creates, completes, retries, or deletes a job.

## Design

1. Add one URL-List `inline-edit.js` module, shared by COOLDOWN and JOBS. Render each value as a real keyboard-focusable button; Enter/Space or click replaces it with a same-width text input. Select the prefilled value. Enter, blur/outside pointer, Escape, invalid input, and unchanged values share one guarded finish path. Invalid/empty values restore the old valid display; an active-editor token prevents Enter followed by blur from saving twice.
2. Cooldown input accepts only the existing display forms (`M:SS`/`MM:SS`, or `H:MM:SS`) and 0–24 hours inclusive. Normalize to the display form and send seconds through the existing `set_page_cooldown` slot. Jobs accepts ASCII digits only and sends a decimal string through a new slot to avoid a 32-bit Qt `int` limit. The existing URL-row reset remains; only its cooldown pencil path is deleted.
3. Add `cooldown_reset.py` as the single cooldown-field reset policy used by per-row and global reset. It changes only timer/debt state unless the existing per-row stale-job repair branch separately needs to repair stale job metadata. The global operation walks the current pool under its lock, records per-worker apply failures, preserves pending debt for a live job, and publishes/persists once if any worker changed. Failed persistence leaves successful in-memory resets applied and returns the affected worker ids.
4. Put “Reset all cooldowns” in the URL List cooldown toolbar. Disable it until an active timer or resettable pending debt exists; keep it busy/disabled through the slot reply. One completion line reports the count and, if needed, pending debt or failed worker labels. The Page Pool editor is a separate Live Debug control and remains; all other URL row actions are retained.
5. Keep worker job counts canonical in `PageInfo.jobs_completed`. Preserve the URL-keyed `stats` format as a legacy fallback, plus exact worker entries under reserved keys in the same map. Restore prefers a valid worker entry; normal increments and explicit corrections persist that exact entry through the existing pool snapshot writer.
6. Workspace restore must reapply both stats forms to already-pooled workers before the next pool autosave: `CooldownsProvider._reapply_stats` passes the complete loaded stats map to the common restore function, which checks the exact worker key first and then falls back to the normalized URL maximum. Worker entries for tabs not yet pooled stay in the file and are picked up by `restore_page_state` when those tabs connect. The reconcile path must never collapse worker values back into URL maxima or overwrite an exact correction with the legacy maximum.

## Interfaces and acceptance tests

- WebChannel: add `reset_all_cooldowns() -> JSON` and `set_page_job_count(tab_id, decimal_text) -> JSON`; no new signals.
- Shared reset primitive: clear timer fields, clear pending debt unless a live job owns it, transition only COOLDOWN→STEADY when safe; never touch the global reset's job/error/URL/enablement/connection fields.
- RED-first Python tests: zero/one/many workers; active, pending, and stacked timers; live-job debt preservation; unchanged job count and unrelated fields; one persistence/push; pool readiness; per-worker persistence across restore; partial apply and persistence failures with affected ids.
- RED-first browser tests: real page scripts; click/Enter/Space entry; prefill/select; Enter + blur once; outside click once; Escape; cooldown valid/invalid/empty/negative/malformed/range/unchanged; jobs whole-number validation and unchanged path; zero-state disable, busy guard, completion/partial log; deleted row pencil and retained Page Pool pencil.

## Size and quality budget

The committed quality baseline is the available measurement at design time; radon is not installed in this checkout, so radon itself could not be queried. Existing maxima: `page_pool.py` 339 lines / 9 methods / max method 16 LOC / CC 7; `tab_reset.py` 362 lines / max function 17 LOC / CC 5; `job_count.py` 50 lines / max function 12 LOC / CC 6; `cooldown_store.py` 254 lines / max function 17 LOC / CC 9; URL `cells.js` 92 lines / max function 18 LOC / CC 7; `render.js` 46 / 17 / CC 8; `reset.js` 145 / 12 / CC 9. New functions target 4–20 LOC, ≤4 parameters, CC≤10; new files stay cohesive and below the RULE 16 30-LOC function limit. Extract the pool snapshot slot if needed rather than growing the frozen panel; use a new JS module rather than exceeding the URL List JS ratchet.

Dishonest reductions rejected: do not implement global reset as N per-row slot calls (N persistence writes and stale-job/error side effects); do not clear pending debt from a running job; do not manipulate the image/job queue to edit a display count; do not broaden deletion to the Page Pool editor or unrelated row actions; do not log one reset line per worker; do not relax the worker counter's display-only routing invariant.

## Verification plan

Run focused RED tests before production code, then the JS lane and Python fast/full lanes, compile/type/lint and changed-file quality gates where dependencies exist. Compare touched-file metrics to the baseline and review the final diff for new slots, reset side effects, duplicate saves, and stale tests/docs. If the sandbox lacks required tooling, record the exact unavailable tool and still run dependency-free checks.