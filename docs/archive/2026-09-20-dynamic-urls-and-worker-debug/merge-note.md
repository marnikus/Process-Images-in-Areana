# Merge note — 2026-09-20 — plan chain S1…S10 merged onto B10–B13

**Read this before S0.** Both plan folders — `2026-09-20-live-processing-and-watcher-scope/` (round 1)
and this one (round 2, the staged chain) — were written on branch `arena/01a0bc3b-…` (five plan-only
commits `e1e916b`, `04c1306`, `a5f69ee`, `5c60425`, `11751e1`) against the tree at **`6bbaf8b` (B9)**.
They were merged into `arena/01a0bba4-…` after **B10–B13 and the B13 validation pass** had landed there
(`1b33f05` B10, `7ebfc04` B11, `a64fa27` B12, `54cb501` B13a, `3a5ee06` B13b, `510f74b` validation,
`0cc134a` hygiene). The plan text is a dated record and was **not edited** (RULE 17); this note records
what the code truth changed under it, so that S0 *re-measures* instead of trusting the plan's base numbers.
Every claim below was verified against the merged tree (commands in §6).

## 1. Invariant numbers — the plan's I-39…I-46 are already taken

`docs/current/SYSTEM_OF_RECORD.md` already holds I-39…I-46 for delivered behaviour. When a stage lands,
add its invariant under the **next free number** — the mapping below is the one to use, so that the stage
docs, the tests' docstrings and the SoR agree:

| Plan invariant (stage) | Plan meaning (short) | Number already used by | **Land as** |
|---|---|---|---|
| round-1 I-39 (S5) | a live run ends only on an explicit user stop | I-39 — UI picture never depends on a disk write (B10) | **I-47** |
| round-1 I-40 (S2) | captcha work only while the Watcher switch is ON, one predicate | I-40 — one SDK, provider registry (B10) | **I-48** |
| round-1 I-41 (S4) | one queue write funnel + one eligibility rule | I-41 — a panel renders only into ids that exist (B11) | **I-49** |
| round-1 I-42 (S6) | URL rows reconciled by Python, never removed under a live job | I-42 — a wait block waits for what its name says (B12) | **I-50** |
| round-2 I-43 (S8) | Python/JS window registries are one contract; unregistered panel is destroyed (L-5) | I-43 — `config/` never enters Git (B13a) | **I-51** |
| round-2 I-44 (S3) | generation timeout paused during a captcha wait, capped | I-44 — one run scope, re-checked at claim (B13b) | **I-52** |
| round-2 I-45 (S7) | URL-row receiver eligibility has one owner | I-45 — one batch at a time (B13b) | **I-53** |
| round-2 I-46 (S4) | every reset re-queues and ends in `commit_queue` | I-46 — resume on scan (B13b) | **I-54** |

## 2. The eligibility rule the plan wants to create already exists (S4, round-1 §"`eligible_images`")

* Plan: `app/services/live/feed.eligible_images` replaces the two clones `queue_scan.selected_images:28`
  and `batch_orchestrator._selected_images:398`; `queue_scan.selected_images` "stays as a 2-line delegation
  (frozen slot surface + 6 test imports)".
* Tree now: **both clones are gone** (`3a5ee06`, `510f74b`). `queue_scan.selected_images` does not exist
  and nothing imports it (it was never a slot). The one rule is **`app/core/run_scope.py`**
  (`RUNNABLE_STATUSES` = pending/selected/failed/needs_review/processing, `is_runnable`, `in_run_scope`,
  `run_scope`, `claim_denied`), evaluated at Start (`_load_run_settings`, `check_start_ready`) **and again
  at claim time** in `batch_orchestrator._run_sequential` and `multi_page_dispatcher._run_with_sem`
  (I-44); pinned by `tests/test_run_scope.py`, `tests/test_run_control_gate.py`, `tests/test_scan_resume.py`.
* Consequence for S4/S5 (RULE 10, one owner): `eligible_images` must **not** become a third rule. Extend
  `core/run_scope.py` — the plan's "exclude `processing` while live" is a second predicate *in the same
  module* (or a mode flag), `recover_stale_processing` sits next to it, and the claim-time re-check stays.
  Re-budget S4's symbol table accordingly (`run_scope.py` is 44 lines; there is room).
* `check_start_ready` now also refuses Start while `run_state.batch_active(bridge)` (error text
  `"batch still active"`, I-45). S5's always-live loop must decide what "Start while live" means and
  change that refusal deliberately — the test that pins it is `tests/test_run_control_gate.py`.
* Reset: `run_control.reset_image_state(img, selected: bool)` still has the parameter S4 deletes; B13's
  I-46 (a newly scanned source whose `_AI` sibling exists enters as `completed`) is compatible with the
  D-6 reversal — a reset image goes back to `pending` regardless of its `output_path`.

## 3. Frozen contracts and base numbers that moved

| Plan says | Tree now | Where |
|---|---|---|
| 134-slot surface | **135** — `set_captcha_provider` added in B10; §B's "0 new slots" still holds, the number to assert is 135 | `tests/test_bridge_slots.py:272` |
| coverage floors 86.09 / 82.01 | **86.36 / 82.33** (last full run 86.99 / 83.25 at `510f74b`) | `tools/quality_baseline.json` `coverage` |
| "stale soft baseline" `single_job_runner.py` 902→939, `undo_entries.py` 404→406 | **resolved** — the recorded baseline is 939 / 406; `single_job_runner.py` max CC is now **7** (was 9) | `tools/quality_baseline.json` |
| §C test ledger: 116 `.py` test files; 25 of 30 `.mjs` listed | **125** `.py` test files; **29 of 35** `.mjs` listed (the 6 unlisted: 4 harnesses + L-7's two tests) | `git ls-files tests`, `package.json` |
| config files in the repo | `config/` is **untracked** since B13a (I-43); `config/captcha_solvers.json` (provider registry, B10) replaced `2captcha.json` | `.gitignore`, `tests/test_repo_hygiene.py` |
| `layout_state.emit_arena_state` "stays 11 lines" | B10 changed `layout_state.py` (281→307 lines, 25→26 funcs; `save_arena_state` always emits, I-39) — re-measure before S6/S9 add their line | `app/ui/panels/layout_state.py` |

**§D headroom table — re-measure these 10 files** (changed since `6bbaf8b`; the other 15 rows are
byte-identical and still valid):

| File | at `6bbaf8b` | now | what changed |
|---|---:|---:|---|
| `app/core/models.py` | 292 lines / 14 funcs | **272 / 11** | `core/progress.py` extracted; `from_scan_dict`, `_discovered_status` added (B13) |
| `app/ui/panels/queue_scan.py` | 315 / 25 | **310 / 24** | `selected_images` deleted; `run_scan_merge` / `run_scan_new_batch` (B13) |
| `app/ui/panels/run_control.py` | 275 / 20 | **279 / 20** | `check_start_ready` (I-45); class still at **10 methods** |
| `app/services/batch_orchestrator.py` | 492 / 38 | **489 / 37** | `_selected_images` deleted; claim-time skip in `_run_sequential` |
| `app/services/multi_page_dispatcher.py` | 397 / 27 | **402 / 27** | claim-time skip in `_run_with_sem` |
| `app/services/run_state.py` | 417 / 33 | **423 / 34** | `batch_active` |
| `app/services/single_job_runner.py` | 939 / 79, CC 9 | **939 / 79, CC 7** | B12 (`AWAIT_PROCESSING_IMAGE` → `app/services/await_processing.py`) |
| `app/services/captcha/service.py` | 310, class 31 | **313, class 34** | B10 provider plumbing |
| `app/ui/panels/layout_state.py` | 281 / 25 | **307 / 26** | B10 state push (I-39) |
| `app/core/layout_service.py` | 300 / 25 | **300 / 25** (2 lines changed) | still `GRID_VERSION = 5`, `WINDOW_IDS` = 15 — S8's bump to 6 is still free |

New modules the plan does not know about (touch-points, not conflicts): `app/core/run_scope.py`,
`app/core/progress.py`, `app/browser/processing_probe.py`, `app/services/await_processing.py`,
`app/services/job_events.py`, `app/services/captcha_watcher/providers.py`,
`js/panels/action-blocks/block-fields.js` + `block-views.js`; tests `test_run_scope.py`,
`test_run_control_gate.py`, `test_scan_resume.py`, `test_queue_thumbnails.py`, `test_repo_hygiene.py`,
`test_progress.py`, `test_await_processing.py`, `test_captcha_providers.py`, `test_state_push_resilience.py`,
`js/test_queue_live_status.mjs`, `js/test_action_blocks_render.mjs`, `js/test_captcha_provider_panel.mjs`,
`js/test_processing_probe.mjs`, `js/page_harness.mjs`.

## 4. Latent defects L-1…L-8 — status at the merge

| Defect | Status | Evidence in the merged tree |
|---|---|---|
| L-1 `_schedule_coro` | **open** | `app/ui/panels/page_pool.py:147` still calls `self._schedule_coro(...)`; `grep -rn _schedule_coro app/` ⇒ that one hit |
| L-5 unregistered `page_pool` panel | **open** | `index.html:263` `data-window="page_pool"`; `WINDOW_IDS` in `app/core/layout_service.py:11` and `_collectPanels` in `js/sash-grid-windows/store.js:5` list 15 windows, none `page_pool` |
| L-6 test doubles the seam | **open** | `tests/test_panel_browser_tabs.py` builds hosts with `_schedule_coro=` 5 times |
| L-7 unlisted `.mjs` tests | **open** | `test_captcha_saved_page.mjs`, `test_title_fit.mjs` on disk, absent from `package.json` `test:js` |
| L-8 dead `WIN_ICONS` | **open** | `js/sash-grid.js:41` |

None were fixed by B10–B13; **S1 (L-1) is still the first stage** and its RED test still fails at base.

## 5. What this merge did and did not do

* Merged the seven plan files verbatim and resolved the one textual conflict (`docs/README.md` archive
  list — both sides' entries kept, this note linked from the round-2 entry).
* Added two pointer bullets in `SYSTEM_OF_RECORD.md` §10 (history pointers only — no row, no invariant;
  the plan lands its own rows with its code, RULE 17).
* Re-untracked the runtime `config/` files that the owner's local merge `889aa59` had brought back
  (`0cc134a`, I-43) — that commit is part of the same push.
* Did **not** touch the plan text, `AGENT_RULES.md`, the baseline, or branch `arena/01a0bc3b-…`.

## 6. How the facts above were measured

```
git merge-base arena/01a0bba4-… origin/arena/01a0bc3b-…            # 6bbaf8b
git diff --name-only 6bbaf8b <merge> -- app tests tools               # touched files / new files
python -c "from tools.verify_quality import current_maxima; ..."      # per-file maxima (same helper as the gate)
grep -n 135 tests/test_bridge_slots.py; python -c "json.load(open('tools/quality_baseline.json'))['coverage']"
grep -rn _schedule_coro app tests; grep -n page_pool app/core/layout_service.py js/sash-grid-windows/store.js
ls tests/js/*.mjs | wc -l; grep -o 'tests/js/[a-z_0-9]*\.mjs' package.json | sort -u | wc -l
```
