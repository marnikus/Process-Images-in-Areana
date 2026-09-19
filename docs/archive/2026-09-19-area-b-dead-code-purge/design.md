# Area B — Dead Code Purge & Selector Single-Source — Design + Proof

**Status:** Implemented 2026-09-19. Branch `arena/01a0b82e-process-images-in-areana`, base `7fc2b039`.
**Parent plan:** `docs/archive/2026-09-19-code-quality-implementation-plan/area-plans-prioritized.md` Area B (B1–B6).
**Rules invoked:** RULE 16 (§16.4 smells, §16.6 process), RULE 17 (this doc), RULE 18 (ideal sizes), RULE 19 (order), RULE 21 (selectors), RULE 8 (real-payload tests).

**Restore note.** This round was originally authored when Area B landed on `arena/01a0b800-process-images-in-areana` (base `8529d6b`, pre-change gate 149 fails). It was then restored onto `arena/01a0b82e` where the tree had drifted (C5–C6 core refactor, HEAD `7fc2b03`). Every number below was re-measured on this branch against a freshly regenerated `tools/quality_baseline.json`, so the absolute values differ from the original round while the deltas (what Area B removes) are the same shape.

## Before metrics (measured 2026-09-19 on `7fc2b03`, full gate with regenerated baseline)

| Metric | Before |
|---|---|
| verify_quality fails (global) | **278** |
| pytest | 459 passed |
| node tests | 105 pass, 0 fail |
| Line coverage | **63.46%** (10,599/16,703) |
| Branch coverage | **37.78%** (1,209/3,200) |
| jscpd (app+tests, min-tokens 60) | 56 clones, 607 dup lines, **1.517%** |
| vulture @90 | 2 unused imports (`build_order_check_text`, `_is_cooling`) |
| LOC of the 4 dead modules | 643+332+155+109 = **1,239** |

---

## B1 — Deadness proof (3 detectors, no production writes)

| Module | D1 import graph (importers in app/ tests/ tools/) | D2 symbol refs (grep whole repo) | D3 runtime coverage after full suite |
|---|---|---|---|
| `app/browser/controller.py` | only `app/services/job_runner.py` (itself dead) | `BrowserController` referenced nowhere outside the two dead modules | **0 stmts executed** |
| `app/services/job_runner.py` | zero importers | `JobRunner` zero refs; `job_runner_getter` in `watcher.py`/`bridge.py` returns the **Bridge** (`self`), never this class | **0 stmts executed** |
| `app/browser/output_detector.py` | only `tests/unit/test_output_detector.py` | `decide_ready`, `should_download`, `should_fallback_pure`, `detect_new_output`, `is_job_id_match`, `is_ready_result`, `is_mismatch_reason`, `flatten_diagnostics_pure` — refs only in own test; live `output_wait.py`/`output_state.py` have their own implementations | 67.4% — **own test only**; drops to 0 stmts when that test is omitted |
| `app/services/job_state_machine.py` | only `tests/unit/test_job_state_machine.py` | `can_job_transition`, `next_job_status_*`, `schedule_batch`, `should_stop_run`, … — refs only in own test; wraps live `app/core/state_machine.py` | 96.5% — **own test only**; drops to 0 stmts when that test is omitted |

D3 evidence (same suite, own tests excluded): `python3 -m pytest tests --cov --cov-branch --ignore=tests/unit/test_output_detector.py --ignore=tests/unit/test_job_state_machine.py` → all four modules report **no executed statements**, while the control `app/browser/output_wait.py` still measures 16.2% (proving the run itself imported the live browser layer).

Dynamic-import check: no `importlib`/`__import__`/string mention of any of the 4 module paths in `app/`, `tests/`, `tools/`, web JS, configs (only `tools/quality_baseline.json` lists the file paths — regenerated in B6).

**Port-predicate decision (B2 rule "port predicate if live needs it"):** nothing to port. The live pipeline (`single_job_runner` + `core/state_machine.py` + `output_wait.py`/`output_state.py`) already implements every decision the dead stack carried; `output_detector.py` was a parallel "pure extraction" that was never wired in (live `output_wait.py` has its own `is_ready_result`/`should_fallback`/`is_mismatch_reason`).

## B2 — Delete 4 modules + 2 tests

Files removed: `app/browser/controller.py`, `app/browser/output_detector.py`, `app/services/job_runner.py`, `app/services/job_state_machine.py`, `tests/unit/test_output_detector.py`, `tests/unit/test_job_state_machine.py`.

Out of scope by plan (Area C owns them): `app/services/verification.py` (live tests exist, C4 target), `new_chat.py`, `captcha_*`.

## B3 — Restore RULE 21 (preferred path: generate probe selectors from site_adapter)

Problem: `site_adapter.py` was reachable only from dead `controller.py`; live probes (`cdp_arena.py`, `output_probes.py`, `new_chat.py`) hardcoded selector literals in JS payload strings → selector drift (P4).

Design:

1. **`site_adapter.py` stays the single source.** Entries updated so `all_selectors()` equals the *live verified probe lists* byte-for-byte (the live lists are the reality; the old adapter fallbacks were stale duplicates of dead-controller behaviour):
   - `prompt_textarea` fallbacks → `['textarea[placeholder^="Describe"]', 'textarea[rows="1"]']`
   - `send_button` fallbacks → `['form button[aria-label="Send message"]', 'button[aria-label="Send message"]']`
   - `attachment_preview_image` fallbacks → `['div.flex.flex-wrap.gap-2 img[src^="blob:"]', 'form img[src^="blob:"]']`
   - `output_image` fallbacks → the 14-selector tail of the live `SELECTORS_V3` (so `all_selectors()` == old `SELECTORS_V3` exactly, 15 items)
   - `processing_spinner` fallbacks → `[]` (the live scan probes `div.animate-spin` only)
   - new `SelectorObject.presenceSelector` field: broad selector for state/presence scans (`send_button`→`button[aria-label="Send message"]`, `file_input`→`input[type="file"]`, `output_region`→`div.no-scrollbar`)
   - delete dead helpers `list_selectors()` and `build_js_find()` (removes the file's 1 gate fail)
2. **New `app/browser/probe_selectors.py`** (the plan-budgeted generator, ≤150 LOC, 73 actual): probe-facing list getters only — `textarea_selectors/textarea_primary`, `send_click_selectors/send_presence_selector`, `attachment_preview_selectors`, `output_image_selectors`, `spinner_selector`, `readiness_checks`, `security_dialog_check`, `model_label_probe`, `new_chat_selectors`. Imports: `site_adapter` only.
3. **Probes receive selectors as JSON params** (established `__PLACEHOLDER__` + `.replace()` pattern from `output_probes.py`): every site-selector literal in `cdp_arena.py` payloads (`JS_INSERT_PROMPT`, `JS_SEND_STATE`, `JS_VERIFY_PROMPT`, `JS_CLICK_SEND`, `JS_VERIFY_ATTACHMENT`, `JS_PAGE_READY`, `JS_IS_GENERATING`) and the two `highlight_selector` call sites becomes a placeholder substituted from `probe_selectors` at import/call time. `output_probes.py` list source switches from local `SELECTORS_V3` to `probe_selectors.output_image_selectors()`; its spinner + model-row scans get the spinner/scope/label selectors injected. `new_chat.py` composer probes take `textarea_primary()` and its click candidates take `new_chat_selectors()`. Dead `JS_FIND_TEXTAREA` const deleted.
4. **Out of scope, documented:** `captcha_js/*.js` probes stay self-contained (module contract: node tests execute the exact file strings — RULE 8; their recaptcha selectors are not in the element-probe path). Action-block default selectors in `core/action_blocks.py` are preset data (RULE 3), and `core` may not import `browser` (layer rule).
5. **Enforcement (lint test):** `tests/test_probe_selectors.py` asserts (a) no selector literal from the site_adapter inventory appears in the probe file sources (drift-proof single source), (b) the built payloads contain exactly the site_adapter lists (wiring proof), (c) readiness/security checks derive from `get_readiness_requirements()`/`security_dialog`. `tests/js/test_composer_probes.mjs` updated to substitute the placeholders before executing the real templates (still RULE 8: it runs the actual payload text from `cdp_arena.py`).

Payload equivalence: same selectors, same order, same JS logic — only quote style of injected lists changes (JSON double quotes). No test asserted payload bytes; the JS payloads were additionally parsed with `new vm.Script(...)` (all 11 payloads parse).

## B4 — Unused imports + vulture triage

- Delete @90 unused imports: `build_order_check_text` (cdp_arena), `_is_cooling` (page_status), `MATCH_EXACT` (visual_click).
- Delete dead symbols proven by payload/call-site grep (no call site in app/tests/tools/web-JS):
  `CDPArenaController.clear_highlights`, `CDPArenaController.set_log_callback`, `CDPClient.clear_highlights` (bridge clears via its own slot + `build_clear_js`), `visual_click.find_and_click_exact`, `dom_highlight.{HighlightRectSpec, build_highlight_rect_js_from_spec, build_highlight_rect_js}` (C6's 7-param target was dead — deleting beats refactoring), `output_state.{build_order_check_text, should_use_below_pool, extract_rect, extract_src, is_job_id_match, is_mismatch_error}` (only `flatten_diagnostics` live), `output_probes.{is_layout_reverse_js, get_selectors}`, `site_adapter.{list_selectors, build_js_find}`, `cdp_arena.JS_FIND_TEXTAREA`, `probe_requests.{COLOR_ATTACH, COLOR_SECURITY}` (match no RULE 1 colour); cdp_arena highlights now use `COLOR_PROMPT`/`COLOR_SUBMIT`.
- Keep (RULE 16 §16.4 "unused args on protocol/callback signatures may stay"): Qt `except ImportError` shim `*a`/`**kw`/`*args` signatures in `cdp_client.py`, `bridge.py`, `captcha_recordings_bridge.py` — they mirror the Qt signal/slot signature so headless imports work. Recorded in `tools/vulture_whitelist.py` so `vulture app tools/vulture_whitelist.py --min-confidence 90` → **0**.
- Defer to owning areas (triage table in implementation record): bridge internals (A), cdp_client/page_pool/preset_store/models @60 candidates (C), captcha @60 (D).

## B5 — Duplication

1. **`app/persistence/json_store.py`** — extract the 27-line `_atomic_write`+`_load_json` pair (copied in config_manager, preset_store, undo_store; cooldown_store imported config_manager's copy). One `load_json`/`save_json_atomic` implementation; all four stores import it. Behaviour identical (incl. deep-copy default, dict-only acceptance, temp+replace atomicity). New unit test `tests/unit/test_json_store.py` (round-trip, corrupt → default, non-dict → default, default not shared by reference, no .tmp residue).
2. **`output_probes.py` internal JS dedup** — characterization FIRST (RULE 8 + §16.5): new `tests/js/test_output_probes.mjs` executes the real `JS_BASELINE_V3`/`JS_CHECK_NEW_OUTPUT_V3` templates against a stub DOM (ready / mismatch / spinner / no-new / old-not-ready scenarios). Then extract inside the payload: shared `oldWasNotReady(old)` predicate (2 clones) and the repeated matched-expected result object (2 clones, now `matched(c)`) in `findAssociatedJobForImage`.
3. Deferred (per plan): bridge undo cluster 19 clones → A5/A7; `cdp.js`↔`url-list.js` → C8; test clones → D.

## B6 — Baseline + docs

- Regenerate `tools/quality_baseline.json` (single writer, integrator) from the post-B tree — deleted files gone, new files (`probe_selectors.py` 73 lines, `json_store.py` 47 lines) added with current maxima.
- Update `docs/current/SYSTEM_OF_RECORD.md` §7 module table, §8 test rows, §10 history pointer; `docs/README.md` archive map; `docs/current/DOM_SELECTORS.md` rows that changed (prompt probe fallbacks, attachment preview list, send_button fallbacks, output_image list, presence selectors) + "generated from site_adapter" note.
- Fill implementation record: `docs/archive/2026-09-19-code-quality-implementation-plan/implementation-2026-09-19.md`.

## RULE 18 / RULE 19 notes

- New files: `probe_selectors.py` (73 LOC, under 150 ideal for a leaf shim), `json_store.py` (47 LOC, leaf), both carry module docstrings naming ownership + import direction. No new function >20 LOC (`_inject` is 4); no new decisions added — B deletes decisions (RULE 19 order satisfied trivially: nesting→CC→cognitive untouched, size last via deletion).
- Payload templating adds zero Python control flow (module-level `.replace()` chains), keeping the embedded-JS exception (§16.1.5) intact.

## Verification per step (checklist template)

Each commit: `pytest tests -q` green; `npm run test:js` green; `verify_quality` global fails strictly lower (278 → 260); coverage never below Before (63.46% → 63.63% line, 37.78% → 37.82% branch). Final: Before→After table in the implementation record.
