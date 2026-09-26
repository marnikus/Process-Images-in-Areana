# Firefox image job — code audit + refactor design (2026-09-26)

Scope: the code added by `ef63e66` ("Firefox image job — full pipeline over
Ui.Vision phase macros", I-65) and the account-name/identify lane it shares
(`firefox_lane.run_identify`). Legacy code (`multi_page_dispatcher`,
`cooldown_service`, `single_job_runner`) is read only as integration seams and is
**not** refactored. Journal file format, public entry points
(`run_job`, `after_result`, `lane_reset`, `recover_firefox_jobs`, `run_phase`,
`run_identify`) and every user-visible log line stay as they are unless a step
below is explicitly marked **behaviour**.

Method: every file read in full; metrics measured with the gate's own code
(`tools/verify_quality.py` `node_loc` / `compute_cc_simple` /
`effective_params` / `get_nesting_depth` + `cognitive_complexity` 1.3.0);
coverage with `pytest --cov-branch` over the feature's 9 test files.

---

## 1. Code map

```
multi_page_dispatcher._run_firefox_claimed          (legacy seam: claim, bookkeeping, finish)
  └─ _firefox_and_record ─ run_job(JobStart, reset_out) ─ after_result(ResultCtx, Verdict)
                                   │
services/firefox_job.py            orchestrator: _new_job → job_gap → _pipeline → settle
  ├─ firefox_job_ctx.py            FfJob value object, JobFailure/JobCancelled, run_macro,
  │                                log/emit/mark_pool (bridge seams), config_dir/job_dir
  ├─ firefox_job_upload.py         check_source, stage_upload (ASCII copy), drop_staged
  ├─ firefox_job_phases.py         baseline (+ security wait, stale-composer reset),
  │                                attach + check_attachment, prompt + readback, reset_page
  ├─ firefox_job_result.py         phase_submit (write-ahead, guard, ack/uncertain),
  │                                phase_wait (observe loop), phase_collect/finish_save
  ├─ firefox_job_output.py         fetch/check_response, validate_image, stage_bytes,
  │                                read_staged, output_spec, save_beside, find_saved (pure I/O)
  └─ firefox_job_journal.py        JobJournal (config/firefox_jobs.json), is_post_submit
services/firefox_job_recovery.py   recover_firefox_jobs ← live/supervisor._recover (live start)
services/firefox_lane.py           run_phase / run_identify under _MACRO_LOCK, job_gap, note_job_end
browser/uivision/job_macros.py     PhaseMacro builders (probe/attach/submit/reset), base64 loader,
                                   provision, parse_replies
browser/uivision/job_scripts.py    page JS bodies (Chrome payloads verbatim + prelude helpers)
services/job_count.py              register_job_done / restore_page_stats (moved from cooldown)
core/state_machine.py              JOB_TRANSITIONS (+ needs_review edges); core/run_scope (D-15)
```

Dependency direction today: `recovery → ctx → lane → uivision`; `recovery` imports
the job *runtime* context only for two path helpers (see F4).

Tests: `test_firefox_job.py` (43 scenarios via `firefox_job_harness.Site`),
`test_firefox_job_files.py` (24, pure I/O + journal), `test_firefox_job_recovery.py`
(12), `test_uivision_job_macros.py` (14), `test_firefox_lane*.py`,
`test_firefox_dispatch.py`, `tests/js/test_firefox_job_scripts.mjs` (14, jsdom).

## 2–3. Findings (evidence, severity, risk)

| ID | Sev | Where (symbol, lines at `ef63e66`) | Evidence | Risk if left |
|---|---|---|---|---|
| F1 | **High** | `firefox_job._settle_failure` 125-134, `_settle_cancel` 137-147 | A review outcome is written with `journal.advance(→needs_review)`; if the move is **refused**, the code silently falls through to `failed` + `_forget` (record and staged bytes deleted). Safe today only because every `POST_SUBMIT` status happens to have a `→needs_review` edge — nothing pins that. The two functions also duplicate the review branch (advance, flags, warn line, Verdict) and the failed branch (advance, forget). | A future edge change (e.g. journalling `paused_user_action` after submit) deletes the evidence of a sent job. |
| F2 | **High (behaviour bug)** | `firefox_job._new_job` 179-187, `firefox_job_recovery.recover_one` 111-127 | A `needs_review` record keeps `output_src`. When the user re-queues that image, a new record (new corr) is created and the old one stays open; the next live start "salvages" the old record: fetches the old result, writes **another** `_AI_n` file and overwrites `img.output_path` / status. | Duplicate output files; a re-run's state silently replaced. |
| F3 | Medium | `firefox_job._persist` 150-155; `ctx.log` 72-76, `ctx.emit` 79-86, `ctx.mark_pool` 117-126; `recovery._log` 69-73, `recover_firefox_jobs` 141-146 | 6 `except Exception: pass` around bridge calls with no trace. RULE 5: "callback into UI must never kill pipeline — wrap in try/except **and log warning**". (3 further swallows are legitimate best-effort cleanup: `drop_staged`, `lane._fresh`, `journal_of` setattr.) | A broken persist / pool push is invisible in the log. |
| F4 | Medium | `ctx.config_dir` 106-109 vs `journal.journal_of` 117-121; `ctx.job_dir` 112-114 vs `recovery._complete` 93; `firefox_job._persist` vs recovery 141-146; `ctx.log` vs `recovery._log` | Same seam implemented twice (config dir, job folder, persist, bridge log). `recovery` imports `firefox_job_ctx` (which imports lane, captcha policy, run_state) just for `JOBS_DIR` + `config_dir`. | Drift between copies; recovery depends on the runtime layer. |
| F5 | Medium | `phases.check_attachment` CC 10; `result.phase_submit` CC 10 | Both at the RULE 16 ceiling. `check_attachment` has a redundant clause: after the success return, *any* matching preview means "multiple" (ours ⊆ previews). `phase_submit` inlines the refusal message formatting and the ack derivation. | Next edit breaches the gate; hard to read. |
| F6 | Medium (behaviour) | `job_scripts._PRELUDE.__composer` 54, `clean_js` 186 | Chrome's `JS_INSERT_PROMPT` writes into the first **visible** element of `textarea_selectors()`; readback / guard / observe / clean read `querySelector(textarea_primary())` — first match, visible or not, primary only. | A hidden primary or a fallback-only page fails every readback (safe — before submit — but the job can never run). |
| F7 | Low (behaviour) | `recovery._salvage` 58 `out.fetch(src, 60)`; `recovery._suffix` 62-66 | Recovery hard-codes the 60 s download timeout the job reads from `timeouts.download`; `_suffix` re-implements the suffix read that `output_spec` already owns. | User setting ignored on recovery; duplicate settings read. |
| F8 | Low | `firefox_lane.run_phase` 131-139 vs `run_identify` 154-168; `_phase_spec` 124-128 vs `_identify_spec` 147-151 | Same spec build → xfile gate → planned run with own savelog → `_run_locked`. | Two places to fix a launch bug. |
| F9 | Low | `job_macros` `timeout_sec=60` ×3 (= the default); `_FLAG_JS` / `_ESC_JS` hard-code `arenaGuard` / `arenaJob` that `_probe(var=…)` also names | Implicit coupling between strings in two places. | Renaming a var silently breaks a macro `if_v2`. |
| F10 | Low | `result.finish_save` docstring ("also the recovery's re-save entry" — recovery never calls it); `result._save` ("target recorded" — nothing records it); journal module docstring lists `target_path` (never written); `DOM_SELECTORS.md` Firefox table names `security_dialog_check()` (code uses `JS_SECURITY_DIALOG` = `captcha_probes.build_visible_js()`) | Code/doc drift. | Misleads the next reader. |
| F11 | Low | `tests/test_js_payload_syntax.py` | RULE 8 generated-JS corollary: every page-JS builder is in the syntax lane. `job_scripts` (`*_js` names, not `build_*`) and the `job_macros.loader` Target are executed in jsdom but not registered for the bracket / `node --check` lane — the meta-test cannot see them. | A syntax slip is caught later, by a slower lane only. |
| F12 | Low (accepted) | `run_job(start, reset_out: list)` + dispatcher `reset: list` | Mutable list as an out-channel so the finish seam (in the dispatcher's `finally`) gets the job's New Chat. Removing it means restructuring the ratcheted legacy `_run_firefox_claimed`. | Cost > benefit — **not refactored**, documented. |
| F13 | Low (accepted) | `firefox_job.after_result` 222-233 | Knows that `_handle_result` returns before its history row on cancel. Legacy coupling; changing it = touching `_handle_result`. | Documented, **not refactored**. |
| F14 | Low | `note_job_end` in `run_job` finally *and* `lane_reset` finally | Intentional (the reset's stamp wins; the first is the fallback when no reset runs) but unexplained. | Looks like a bug; comment only. |
| F15 | Low | `tests/test_firefox_job.py` 535 lines | RULE 18 file ideal 150–300. | Hard to navigate; split by concern. |

Metrics are otherwise healthy: no function > 20 LOC except the documented
`observe_js` JS literal, max nesting 2, max cognitive 8, params ≤ 4.

## 4. Proposed boundaries (only where they remove real duplication)

* **`services/firefox_job_host.py`** (new leaf, ~50 lines): the bridge seams the
  job *and* the recovery call — `say(bridge, text, level)`, `persist(bridge)`,
  `config_dir(bridge)`, `settings_of(bridge)`, `timeout_s(bridge, key, default)`.
  Each catches, and reports a failure to the `arena` logger (RULE 5), never raises.
  Removes F3 and the duplicated halves of F4. No Qt, no lane import.
* **`firefox_job_journal`** gains the job-folder rule it already implies:
  `JOBS_DIR`, `job_folder(config_dir, corr)`, and `journal_of` reads the config dir
  through `host.config_dir`. `recovery` then imports journal + host + output only.
* Nothing else: no new protocol/ABC, no provider layer — one implementation each.

## 5–7. Ordered refactor plan

Every step = one commit, suite green before and after, revertible alone with
`git revert <sha>` (no step changes the journal format or a public signature).
"Before" tests are written and green on the old code first (characterization);
"after" = the same tests + the step's own.

| Step | Kind | Change | Before (characterize, must pass on old code) | After | Rollback |
|---|---|---|---|---|---|
| **S0** | tests only | Pin current behaviour at every seam below + register `job_scripts`/loader in the syntax lane (F11) | `check_attachment` full truth table; every `POST_SUBMIT` status has a `→needs_review` edge; review failure *before* submit ⇒ `failed` + forgotten; exact guard-refusal text; recovery fetch timeout = 60 today; bridge failures in log/persist/emit/pool never break a job; lane `blocked` texts for both runners | — | drop the test commit |
| **R1** | structural | F5: `check_attachment` without the redundant clause; `phase_submit` → `_guard_refusal(guard)` + `_ack_how(guard, ack)` | S0 truth table + submit scenarios | CC ≤ 8 both | revert |
| **R2** | structural | F1: `_settle_review(job, msg) -> Verdict \| None` and `_settle_failed(job, msg)` shared by `_settle_failure` / `_settle_cancel` | S0 invariant + review/cancel scenarios | same outputs, less code | revert |
| **R3** | structural + logging | F3/F4: `firefox_job_host`; `JOBS_DIR`/`job_folder` into journal; ctx/firefox_job/recovery use them; `recovery._suffix` → `output_spec(...).suffix` (F7 half) | S0 "bridge failure never breaks a job"; recovery suite | + host unit tests (each seam logs a warning on failure) | revert |
| **R4** | structural | F8/F9: lane `_entry_spec` + `_run_on_entry`; macros drop redundant `timeout_sec`, flag scripts derive var names from constants | S0 lane texts; macro suite | same | revert |
| **R5** | docs in code | F10/F14 docstrings + one comment | — | — | revert |
| **B1** | **behaviour** | F7: recovery fetch uses `timeouts.download` (default 60) | S0 pins 60 with no setting | new test: configured value is used | revert |
| **B2** | **behaviour** | F2: `JobJournal.supersede(image_id, keep)` drops older open records (and their job folder) of the same image when a new job starts | failing test first (RED): re-queued image + old review record ⇒ no second `_AI` file on recovery | GREEN | revert (old records then linger as before) |
| **B3** | **behaviour** | F6: `__composer` / `clean_js` read the first visible element of `textarea_selectors()` — the element the insert wrote | jsdom RED: hidden primary + visible fallback ⇒ readback must see the fallback | GREEN + existing JS suite | revert |
| **R6** | tests structural | F15: split `test_firefox_job.py` by concern (pre-submit / submit-wait / collect-cancel) on the shared harness | same test ids count | same | revert |

Order follows RULE 19 (complexity before size) and puts every behaviour change
after the structural steps, each alone in its commit.

## 8. Documentation after the change

* `SYSTEM_OF_RECORD.md` I-65: module list (+ `firefox_job_host`), the supersede rule (B2), composer rule (B3).
* `DOM_SELECTORS.md` Firefox table: security row → `JS_SECURITY_DIALOG` (`captcha_js/visible.js`); composer row → first visible of `textarea_selectors()`.
* Design doc `2026-09-25-firefox-image-job/design.md`: pointer to this audit.
* `docs/README.md` changelog line.

## 9. Metrics (before → after)

Before (`ef63e66`): 11 feature modules, 1,868 lines; max CC 10 (×2), max
cognitive 8, max nesting 2, max params 4, 1 function > 20 LOC (documented JS
literal); 9 silent swallows (6 unjustified); 4 duplicated seams; feature tests
152 passed; feature coverage 97 % (line+branch combined), 23 missed lines.

After: see §10.

## 10. As built (2026-09-26) — steps, commits, after-metrics

| Step | Commit | Outcome |
|---|---|---|
| S0 | `7b5a73e` | `tests/test_firefox_job_seams.py` (23 characterization tests) + `job_scripts`/loader in the syntax lane with a meta-test (F11) |
| R1 | `9ddf36a` | `check_attachment` CC 10 → 8; `phase_submit` CC 10 → `_guard_refusal` + `_ack_how` (F5) |
| R2 | `d3f4d63` | `_settle_failed` / `_settle_review` shared by failure + cancel; the POST_SUBMIT → needs_review invariant pinned (F1) |
| R3 | `e3356d6` | new leaf `firefox_job_host` (`call`/`say`/`persist`/`config_dir`/`settings_of`/`timeout_s`, each failure → `arena` warning); `JOBS_DIR`/`job_folder` in the journal; recovery no longer imports ctx (F3, F4, F7 half) |
| R4 | `ed26643` | lane `_entry_spec` / `_blocked` / `_run_on_entry` shared by `run_phase` + `run_identify`; macros drop the 3× default `timeout_sec`, flag scripts use `_JOB_VAR`/`_GUARD_VAR` (F8, F9) |
| R5 | `cc03711` | docstrings / `note_job_end` comment / `DOM_SELECTORS.md` security row (F10, F14) |
| B1 | `f7ab07f` | **behaviour** — recovery fetch uses `timeouts.download` (default 60) (F7) |
| B2 | `4787d3c` | **behaviour** — `JobJournal.supersede(image_path, keep)`: a new job drops older open records of the same image + their job folder, logged (F2). Keyed on `image_path` (the `_AI` target's identity); a pre-submit failure of the new job still drops the old record — re-queue is a deliberate redo (D-15) |
| B3 | `db5cf58` | **behaviour** — prelude `__composerEl()` = first visible of `textarea_selectors()` (Chrome's insert rule) for readback / guard / observe / clean (F6); 3 jsdom RED → GREEN |
| R6 | `3c3ba09` | `test_firefox_job.py` 535 → 168 + `test_firefox_job_submit.py` 160 + `test_firefox_job_control.py` 226; 48 test ids identical (F15) |

F12 / F13 stay accepted as designed (legacy dispatcher ratchet).

| Metric | Before (`ef63e66`) | After (`3c3ba09`) |
|---|---|---|
| Feature modules / lines | 11 / 1,868 | 12 / 1,903 (+ `firefox_job_host` 62) |
| Max CC | 10 (×2: `check_attachment`, `phase_submit`) | 9 (`output.check_response`, untouched) |
| Max cognitive / nesting / params | 8 / 2 / 4 | 8 / 2 / 4 |
| Functions > 20 LOC | 1 (`observe_js`, documented JS literal) | 1 (same) |
| Silent `except` | 9 (6 unjustified) | 3 (all best-effort: journal setattr, `drop_staged`, `lane._fresh`) |
| Duplicated seams | 4 | 0 |
| Feature tests | 152 passed (9 files) | 205 passed (13 files) · jsdom 14 → 17 |
| Feature coverage (line+branch) | 97 %, 23 missed lines | 99 %, 8 missed lines |
| Largest feature test file | 535 lines | 226 lines |
