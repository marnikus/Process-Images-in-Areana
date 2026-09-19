# Implementation Record — 2026-09-19

**Status:** **Area B implemented** (B1–B6) per `area-plans-prioritized.md`. Design + deadness proof:
`../2026-09-19-area-b-dead-code-purge/design.md`.
**Branch:** `arena/01a0b82e-process-images-in-areana`, base `7fc2b039` (the round was authored on `arena/01a0b800`
and restored here; all numbers below were re-measured on this branch — see the design doc's restore note).
**Gate:** 280 fails → **262** fails with a freshly regenerated `tools/quality_baseline.json` and a generated
`coverage.json` on both sides (3 warns before/after, all pre-existing JS file-length warns; no new fail metric —
see the comparison note below).
Round 0 tooling is already in the tree (`tools/metrics_report.py`, JS gate + baseline ratchet in
`tools/verify_quality.py`, `tools/pre_push_check.sh`, `tools/mutation_baseline.md`); B relied on it and
re-ran `tools/generate_baseline.py` after the deletions so the ratchet starts from the post-B tree.

## Commits

| Step | Commit | Scope |
|---|---|---|
| B1–B2 | `85d9934` | deadness proof (3 detectors) + Area B design doc + delete 4 modules + 2 test-only tests |
| B3–B5 | `6bae177` | RULE 21 single selector source + probe_selectors + lint/wiring tests + vulture triage + json_store + output_probes payload dedup |
| B6 | this commit | baseline regen + SYSTEM_OF_RECORD/README/DOM_SELECTORS + this record |

## Before → After (full suite)

| Metric | Before (`7fc2b039`) | After B | Δ |
|---|---|---|---|
| verify_quality fails (global, fresh baseline) | 280 | **262** | −18 |
| pytest | 459 passed | **459 passed** (13 test-only removed, 13 added: 8 probe-selectors, 5 json-store) | 0 |
| node tests | 105 pass, 0 fail | **111 pass, 0 fail** (+6 output-probe characterization) | +6 |
| Line coverage (gate metric `percent_covered`) | 59.33% | **59.50%** | +0.17 pts, stmts 16,703 → 16,508 |
| Statements covered | 63.46% (10,599/16,703) | **63.63%** (10,504/16,508) | +0.17 pts, −195 stmts |
| Branch coverage | 37.78% (1,209/3,200) | **37.82%** (1,189/3,144) | +0.04 pts |
| jscpd app+tests (min-tokens 60) | 56 clones, 607 dup lines (1.52%) | **44 clones, 481 lines (1.24%)** | −12 clones |
| vulture @90 | 2 unused imports (`build_order_check_text`, `_is_cooling`) | **0** (`vulture app tools/vulture_whitelist.py --min-confidence 90`) | clean; 205 findings still open at @60 (inventory in the triage table below, owned by C/D/A) |
| Dead LOC | 1,239 in 4 modules | **0** (modules deleted) | −1,239 |
| site_adapter gate fails | 1 (`build_js_find` LOC 37) | **0** | −1 |

Coverage never decreased at any step; the remaining 260 fails are the pre-existing legacy breaches
(`bridge`/`cdp_arena`/`cdp_client` class-loc + methods, output_wait/god objects, JS CC in `sash-grid-*` /
`window-presets-*`), which belong to Areas A/C.

## Gate comparison method (reproducible)

`tools/generate_baseline.py` was run on both trees (base worktree `7fc2b03`, post-B tree) so the R0.3 ratchet
starts from each tree's own current maxima; `coverage.json` was generated on both sides
(`python3 -m pytest tests -q --cov --cov-branch --cov-report=term` → `python3 -m coverage json`) so the coverage
lane is active. Every remaining fail exists in both lists except the 18 Area B removals, and the only value
changes are improvements (CDPArenaController 371→359 LOC / 30→28 methods, CDPClient 469→456 / 22→21, line
59.3%→59.5%); `diff` of the sorted fail lines contains no added entry.

## B1 deadness proof (summary — full table in the design doc)

| Module | Import graph | Symbol refs | Runtime |
|---|---|---|---|
| `browser/controller.py` | imported only by dead `services/job_runner.py` | `BrowserController` unreferenced outside the dead pair | 0 stmts executed |
| `services/job_runner.py` | zero importers (`job_runner_getter` in watcher/bridge returns the **Bridge**) | `JobRunner` zero refs | 0 stmts executed |
| `browser/output_detector.py` | only its own test | all symbols only in own test; live `output_wait`/`output_state` have own implementations | 67.4% → **0 stmts** without own test |
| `services/job_state_machine.py` | only its own test | wraps live `core/state_machine.py` | 96.5% → **0 stmts** without own test |

Control in the same run: `app/browser/output_wait.py` still measures 16.2% (the suite did import the live
browser layer). No dynamic/string import of any deleted path (checked app/tests/tools/web-JS/configs).

## B4 vulture @60 triage (decisions + evidence)

**Deleted (zero refs in app/tests/tools/web-JS):** `CDPArenaController.clear_highlights` + `CDPClient.clear_highlights`
(bridge clears via its own slot + `build_clear_js`), `CDPArenaController.set_log_callback`,
`visual_click.find_and_click_exact`, `dom_highlight.{HighlightRectSpec, build_highlight_rect_js_from_spec,
build_highlight_rect_js}` (was C6's 7-param refactor target — dead beats refactored), `output_state` 5 dead helpers
(only `flatten_diagnostics` live), `output_probes.{is_layout_reverse_js,get_selectors}`,
`site_adapter.{list_selectors,build_js_find}`, `probe_requests.{COLOR_ATTACH,COLOR_SECURITY}` (match no RULE 1
colour); cdp_arena highlights now use `COLOR_PROMPT`/`COLOR_SUBMIT`, and the unused
`build_order_check_text` / `_is_cooling` / `MATCH_EXACT` imports are gone.

**Kept (protocol/callback signatures, RULE 16 §16.4):** Qt `except ImportError` shim `*a/**kw/*args` in
`cdp_client.py`, `bridge.py`, `captcha_recordings_bridge.py` — mirror Qt signal/slot signatures for headless
import; whitelisted in `tools/vulture_whitelist.py`.

**Deferred to owning areas (inventory, not licence):** `cdp_client` API surface + `page_pool` methods (C2),
`preset_store` settings-preset methods + `config_manager.get_session_data` (C6), `core/persistence.reconcile_with_filesystem`
(C5), `models`/`state_machine`/`undo_service`/`cooldown` helpers referenced only by tests (C5/D4 decide
test-only vs live), bridge internals (A).

## RULE 16 §16.7 self-review (Area B exit)

```
[x] No new function >30 LOC; new funcs 2–15 LOC (probe_selectors 11×≤6, json_store 2×≤15, _inject 4)
[x] No new class; new files are function modules with docstring ownership + import direction
[x] No new function with >4 params (_inject uses **payloads = the placeholder map, not a settings dodge)
[x] CC/cognitive/nesting within limits on every new/edited function; legacy hotspots NOT increased
    (CDPArenaController 371→359 LOC / 30→28 methods, CDPClient 469→456 / 22→21)
[x] Coverage 59.50%/37.82% ≥ baseline 59.33%/37.78% (statements 63.63% ≥ 63.46%; never decreased per step)
[x] Every new unit has a test that fails if deleted (probe_selectors lint+wiring, json_store unit,
    output-probe characterization — node suite fails if payloads or wiring regress)
[x] vulture @90 = 0 with whitelist; net −12 duplication clones
[x] No quality-override added; no metric gaming (deletion + named-concept extraction only)
[x] RULE 18: probe_selectors.py 73 LOC, json_store.py 47 LOC (leaf shims under 150 = "normal and good");
    site_adapter.py 270 LOC (data module, within 150–300)
[x] RULE 19 order: nesting→CC→cognitive untouched (no new decisions), size last via deletion
[x] SYSTEM_OF_RECORD.md §7/§8/§9/§10 + docs/README.md + DOM_SELECTORS.md updated; baseline regenerated
```

## Handover to Area A

Round 0 audit before A branches: the tooling listed above is present — confirm R0.6's mutation runner/score
and the `pre_push_check.sh` lanes on a clean checkout, then close Round 0. Area A starts from:
260 gate fails (bridge, cdp_client, output_wait, layout_service, cdp_arena, JS panels), bridge max func
1,209 LOC / CC 356 / nesting 23, class 5,000 LOC / 200 methods / 221 funcs (fresh `tools/quality_baseline.json`),
line 59.50% (statements 63.63%) / branch 37.82%.
Dead stack gone from its map; selectors now single-sourced (A's block defaults in `core/action_blocks.py`
are preset data by design — see design.md §B3.4).
