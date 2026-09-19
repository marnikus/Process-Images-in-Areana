# Implementation Record — 2026-09-19

**Branch:** `arena/01a0b800-process-images-in-areana`. **Area B implemented** (B1–B6) per
`area-plans-prioritized.md`. Design + deadness proof: `../2026-09-19-area-b-dead-code-purge/design.md`.
Round 0 (metrics tooling) not yet started; B used the existing `tools/verify_quality.py` + radon/cognitive/vulture/jscpd directly.

## Commits

| Step | Commit | Scope |
|---|---|---|
| B1 | `2f92dea` | deadness proof (3 detectors) + Area B design doc — no prod code |
| B2 | `e24c298` | delete 4 modules + 2 test-only tests |
| B3 | `82daa9d` | RULE 21: site_adapter single source + probe_selectors + lint/wiring tests |
| B4 | `79f5904` | unused imports + vulture triage → @90 clean |
| B5 | `3214aa3` | json_store.py + output_probes payload dedup (characterization first) |
| B6 | this commit | baseline regen + SYSTEM_OF_RECORD/README/DOM_SELECTORS + this record |

## Before → After (full suite, `--branch --source=app`)

| Metric | Before (8529d6b) | After B | Δ |
|---|---|---|---|
| verify_quality fails (global) | 149 | **128** | −21 (plan projected −16 from a 121 baseline; baseline had drifted +28) |
| pytest | 459 passed | **459 passed** (13 test-only removed, 13 added: 8 probe-selectors, 5 json-store) | 0 |
| node tests | 99 pass +1 jsdom-fail file | **111 pass, 0 fail** (npm ci fixed jsdom; +6 output-probe characterization) | +12 |
| Line coverage | 41.21% (5,112/11,721) | **43.09%** (5,010/10,999) | +1.88 pts, stmts −722 |
| Branch coverage | 32.28% (1,020/3,160) | **33.76%** (979/2,900) | +1.48 pts |
| jscpd app+tests | 55 clones, 1.50% dup lines (1.60% tokens) | **44 clones, 1.22% dup lines (1.25% tokens)** | plan target 1.25% tokens hit |
| vulture @90 | 2 unused imports + 11 shim findings | **0** (`vulture app tools/vulture_whitelist.py --min-confidence 90`) | clean |
| Dead LOC | 1,239 in 4 modules | **0** (modules deleted) | −1,239 |
| site_adapter gate fails | 1 (`build_js_find` 37 LOC) | **0** | −1 |

Coverage never decreased at any step (per-step gate: B2 41.21→42.80, B3 held, B5 →43.09).

## B1 deadness proof (summary — full table in the design doc)

| Module | Import graph | Symbol refs | Runtime |
|---|---|---|---|
| `browser/controller.py` | imported only by dead `services/job_runner.py` | `BrowserController` unreferenced outside the dead pair | 0.0% (0/297) |
| `services/job_runner.py` | zero importers (`job_runner_getter` in watcher/bridge returns the **Bridge**) | `JobRunner` zero refs | 0.0% (0/226) |
| `browser/output_detector.py` | only its own test | all symbols only in own test; live `output_wait`/`output_state` have own implementations | 67.4% → **0.0%** without own test |
| `services/job_state_machine.py` | only its own test | wraps live `core/state_machine.py` | 96.5% → **0.0%** without own test |

No dynamic/string import of any deleted path (checked app/tests/tools/web-JS/configs).

## B4 vulture @60 triage (decisions + evidence)

**Deleted (zero refs in app/tests/tools/web-JS):** `CDPArenaController.clear_highlights` + `CDPClient.clear_highlights` (bridge clears via its own slot + `build_clear_js`), `CDPArenaController.set_log_callback`, `visual_click.find_and_click_exact`, `dom_highlight.build_highlight_rect_js` (was C6's 7-param refactor target — dead beats refactored), `output_state` 5 dead helpers (only `flatten_diagnostics` live), `output_probes.{is_layout_reverse_js,get_selectors}`, `site_adapter.{list_selectors,build_js_find}`, `probe_requests.{COLOR_ATTACH,COLOR_SECURITY}` (match no RULE 1 colour); cdp_arena highlights now use `COLOR_PROMPT`/`COLOR_SUBMIT`.

**Kept (protocol/callback signatures, RULE 16 §16.4):** Qt `except ImportError` shim `*a/**kw/*args` in `cdp_client.py`, `bridge.py`, `captcha_recordings_bridge.py` — mirror Qt signal/slot signatures for headless import; whitelisted in `tools/vulture_whitelist.py`.

**Deferred to owning areas (inventory, not licence):** `cdp_client` API surface + `page_pool` methods (C2), `preset_store` settings-preset methods + `config_manager.get_session_data` (C6), `core/persistence.reconcile_with_filesystem` (C5), `models`/`state_machine`/`undo_service`/`cooldown` helpers referenced only by tests (C5/D4 decide test-only vs live), bridge internals (A).

## RULE 16 §16.7 self-review (Area B exit)

```
[x] No new function >30 LOC; new funcs 2–15 LOC (probe_selectors 11×≤6, json_store 2×≤15, _inject 4)
[x] No new class; new files are function modules with docstring ownership + import direction
[x] No new function with >4 params (_inject uses **payloads = the placeholder map, not a settings dodge)
[x] CC/cognitive/nesting within limits on every new/edited function; legacy hotspots NOT increased
    (cdp_arena class 371/30 methods, highlight_selector CC13/cog18 — identical before/after)
[x] Coverage 43.09%/33.76% ≥ baseline 41.21%/32.28% (never decreased per step)
[x] Every new unit has a test that fails if deleted (probe_selectors lint+wiring, json_store unit,
    output-probe characterization — node suite fails if payloads or wiring regress)
[x] vulture @90 = 0 with whitelist; no new duplication groups (net −11 clones)
[x] No quality-override added; no metric gaming (deletion + named-concept extraction only)
[x] RULE 18: probe_selectors.py 73 LOC, json_store.py 47 LOC (leaf shims under 150 = "normal and good");
    site_adapter.py 270 LOC (data module, within 150–300)
[x] RULE 19 order: nesting→CC→cognitive untouched (no new decisions), size last via deletion
[x] SYSTEM_OF_RECORD.md §7/§8/§9/§10 + docs/README.md + DOM_SELECTORS.md updated; baseline regenerated
```

## Handover to Area A

Round 0 (metrics_report, JS gate, ratchet, lanes) still pending. Area A starts from:
128 gate fails (bridge 64, cdp_client 17, output_wait 7, layout_service 5, cdp_arena 4, …), bridge
max func 1,209 LOC / class 5,000 / 221 funcs (fresh `tools/quality_baseline.json`), line 43.09% /
branch 33.76%. Dead stack gone from its map; selectors now single-sourced (A's block defaults in
`core/action_blocks.py` are preset data by design — see design.md §B3.4).
