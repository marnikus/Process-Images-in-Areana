# Batch B — implementation record (2026-09-19)

As-built results for `design.md` in this folder. Branch: `arena/01a0b8d9-process-images-in-areana`.

## B1 — deadness proof: the closure is 8 modules, not 4

`tools/import_graph.py --dead` (AST import graph, production closure from `app.main`; tests/tools
importers don't keep a module alive; a package's verdict follows its most-advanced child)
reports **8 dead modules**:

| Module | Reachable only via | Verdict |
|---|---|---|
| `app/services/job_runner.py` | — (no importers anywhere) | **DELETED (B2)** |
| `app/browser/controller.py` | job_runner | **DELETED (B2)** |
| `app/browser/output_detector.py` | test-only | **DELETED (B2)** |
| `app/services/job_state_machine.py` | test-only | **DELETED (B2)** |
| `app/core/state_machine.py` | job_state_machine | **KEPT — doc-kept** |
| `app/services/verification.py` | job_runner | **KEPT — doc-kept** |
| `app/browser/site_adapter.py` | controller | **RESURRECTED (B3)** |
| `app/browser/selector.py` | site_adapter | **RESURRECTED (B3)** |

The two doc-kept modules are SYSTEM_OF_RECORD §8 test mandates (`test_verification.py`,
`test_state_transitions.py`); they are listed in `tools/import_graph.py` as
`DOCUMENTED_TEST_ONLY` so `--dead` (now a standing pre-push gate) reports them as
`doc-kept` instead of failing, while any NEW dead module still exits 1.

## B2 — deletions

* `git rm` the 4 modules + their 2 test files; `requirements.txt` drops `playwright>=1.40.0`.
* Zero dangling references (grep-verified). `watcher.py`'s `_job_runner_getter` is duck-typed
  (hasattr guards) against the Bridge, which has `pause_run`/`resume_run` — unrelated to the
  deleted `JobRunner`, safe.
* **Equivalence gate:** 459 passed → **446 passed** (exactly the 13 deleted tests: 7
  `test_job_state_machine` + 6 `test_output_detector`).

## B3 — RULE 21 generator (deviation from design step 5, with reason)

**Deviations:**
1. **Sync gate instead of runtime wiring (design step 5).** `tests/js/test_composer_probes.mjs`
   (RULE 8) extracts the REAL `JS_INSERT_PROMPT` / `JS_SEND_STATE` consts from `cdp_arena.py`
   by regex on the triple-quoted literals and executes them in a `vm` against DOM stubs keyed
   by the exact selector strings. A const built from the map at import time is no longer the
   literal the harness runs — so probe chains stay literal (zero probe-text changes) and the
   generator keeps the map in lockstep: `tools/generate_selectors.py --check` (extract →
   compare → exit 1 on drift) is in `tools/pre_push_check.sh`. Python-side references that need
   no JS literal were wired: `cdp_arena`'s two `highlight_selector(...)` calls now use
   `get_selector("prompt_textarea").primary` / `get_selector("send_button").primary` — giving
   `site_adapter`/`selector` a genuine production import edge (B1 closure now alive).
2. **Send-button unification dropped.** Design planned merging the two send chains
   (`:not([disabled])` redundant with the JS `el.disabled` check). As-built the two real chains
   are recorded as-is as separate entries `send_button` and `send_button_click` — no probe-text
   change, and the redundancy is visible in the map instead of silently removed.
3. **Sources widened** beyond the design list: `cdp_client.attach_image_cdp` default chain,
   `action_blocks` `BLOCK_DEFINITIONS` selector defaults (user-configurable, RULE 3), and all
   four `captcha_js/*.js` probes.

**Result:** 32 generated entries in `site_adapter.py` between
`# >>> generated:SELECTORS begin/end` markers; coverage 100% (every extracted selector slot is
owned by exactly one entry); `--write` idempotent (second run → no diff); `--check` green.
Tier report: **19 semantic / 8 structural / 5 class-fragment** primaries — the
class-fragment primaries (`div.no-scrollbar`, `div.animate-spin`, `span.truncate`, …) are
flagged in `--report` for a FUTURE batch (adding a semantic fallback is a behaviour change,
out of scope here). `SelectorObject` gained the optional `tier` field.

## B4 — unused imports

Removed in 13 files: `cdp_arena.py` (module `build_order_check_text` + local `build_clear_js`),
`dom_highlight.py` (3× `COLOR_*`), `output_wait.py` (`Awaitable`), `page_status.py`
(`_is_cooling`), `core/layout_service.py` (`Any`), `core/scanner.py` (`os`),
`core/state_machine.py` (`UrlStatus`), `core/undo_service.py` (`copy`, `json`, `Optional`,
`MAX_HISTORY`), `persistence/config_manager.py` (`Any`), `persistence/preset_store.py` (`Any`),
`services/multi_page_dispatcher.py` (`Optional`), `services/verification.py` (`time`),
`ui/bridge.py` (`AppState`, `scan_folder`, 3 probe builders, 5 probe-spec/color names,
`BUILTIN_BLOCKS`, `BLOCK_DEFINITIONS`, local `asyncio`). Plus 2 dead locals:
`core/models.py::recalculate_progress` (`pending`) and `services/verification.py` (`new_output`).
**`pyflakes app/`: zero unused-import findings; vulture ≥90: zero (except the known PySide6
fallback-stub `*a` false positives).** `bridge.py` notes: `AppState`'s only other occurrence is
a docstring; `scan_folder` was shadowed by the Bridge method; the line-2776/2896 function-local
re-imports cover the probe builders.

## B5 — JSON-store dedup (as-built API)

`app/persistence/json_store.py`: `atomic_write_json(path, data, *, mode=None, indent=2)` and
`load_json(path, default, *, expect_type=dict)` (dict-only acceptance preserved via
`expect_type`). Six importers: `config_manager`, `preset_store`, `undo_store` (local verbatim
copies deleted), `core/persistence` (save_state/save_preset), `services/captcha/key_store`
(mode=0o600 kept, RULE 20; `_cleanup_tmp`/`_lock_mode` deleted; temp suffix → `.json.tmp`
crash-window only), `cooldown_store` (re-pointed).

## B6 — gates and docs

* **pytest: 446 passed** (~9.2–10.3 s, `QT_QPA_PLATFORM=offscreen`).
* **Coverage** (generated `coverage.json`, gitignored artifact): total 42.7% line / 33.6%
  branch — a pre-existing repo-wide gap (before this batch the gate saw "coverage.json
  [missing]" WARN; the numbers were never measured). New files are above threshold:
  `json_store.py` 87.2%, `selector.py` 95.2%; `site_adapter.py` 61.1% (generated data table).
  Closing the repo-wide gap is future work (not a B item); `--changed --allow-legacy`
  accordingly reports it as a FAIL alongside the pre-existing `solver.py:362` cognitive 16.
* **Quality gate (full run): 149 → 129 fails, ZERO new breaches** — proven by diffing the
  normalized finding lists (file + entity + metric, line numbers stripped) of the pristine
  tree vs the final tree: nothing new; 23 findings gone. The 3 raw-diff "new" lines are the
  same legacy violations with shifted LOC numbers (all `[LEGACY]` within
  `tools/quality_baseline.json` limits in `--changed` mode).
* **Baseline pruned:** `app/services/job_runner.py`, `app/browser/controller.py` entries
  removed (39 → 37); the other two deleted modules had no entries.
* **Node harness (RULE 8):** `test_composer_probes.mjs` 3/3 pass; full `tests/js/` shows 2
  failures (`test_captcha_recording.mjs`, `test_title_fit.mjs`) that fail **identically on the
  pristine tree** — pre-existing, untouched areas, out of scope.
* **`tools/pre_push_check.sh`** +2 gates before pytest: `generate_selectors.py --check`
  (selector drift) and `import_graph.py --dead` (new dead modules).
* **Docs (RULE 17):** `SYSTEM_OF_RECORD.md` ("both controllers" → `CDPArenaController`,
  job-runner phrasing → `single_job_runner.py`, I-18 now describes the generated map + sync
  gate); `DOM_SELECTORS.md` (generated-map header, §D send-button live-chain table, footer);
  `docs/README.md` (this archive mapped).

## Post-batch opportunities (future work, deliberately not done)

* Class-fragment-only primaries flagged by `--report` — add semantic/structural fallbacks
  (behaviour change, needs live verification).
* Wire `verification.py` (RULE 15) and `state_machine.py` (RULE 7) into the live path, then
  drop their `DOCUMENTED_TEST_ONLY` entries.
* Pre-existing `tests/js` failures (`test_captcha_recording`, `test_title_fit`).
* The 129 remaining legacy quality-gate fails (baseline-covered) — RULE 19 remediation order.
