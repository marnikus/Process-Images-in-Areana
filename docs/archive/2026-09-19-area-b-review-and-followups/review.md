# Area B Review — Implementation vs Specification (2026-09-19, second pass)

**Reviewer method:** re-measured everything from a clean toolchain on `e64b30a` (pytest 459, node 111, `verify_quality` global, vulture @90, jscpd base-tree vs current-tree pair diff via `git archive 8529d6b`, per-module coverage, AST class metrics before/after, payload byte-diffs vs pre-B3, stale-reference greps, `pre_push_check.sh` end-to-end).
**Specs compared against:** `../2026-09-19-code-quality-implementation-plan/area-plans-prioritized.md` (Area B table), `../2026-09-19-code-quality-implementation-plan/verification-checklist.md`, `../2026-09-19-area-b-dead-code-purge/design.md`, `docs/current/AGENT_RULES.md` RULE 16/18.

## 1. Spec vs implementation

| Spec item | Status | Evidence (re-measured) |
|---|---|---|
| B1 deadness 3 detectors, table, no writes | **DELIVERED** | design.md table; runtime proof: all 4 modules 0.0% without own tests |
| B2 delete 4 modules + 2 tests, port predicate if needed | **DELIVERED** | −1,239 LOC; stmts 11,721→11,060 = **−661 exactly as planned**; nothing to port (live pipeline owns every predicate) |
| B2 delta fails −16, cov +1.6 | **MET in delta, different absolutes** | fails 149→130 (−19; plan's 121 baseline was stale, drift documented), line 41.21→42.80 (+1.59) |
| B3 preferred path: generate probe selectors from site_adapter + lint test | **DELIVERED** | `probe_selectors.py` + `__PLACEHOLDER__` injection; `tests/test_probe_selectors.py` lint + wiring |
| B3 "1 fail removed, prevents selector drift" | **DELIVERED** | site_adapter gate fails 1→0 |
| B3 payload behaviour preservation | **NOW BYTE-PROVEN** | 7 cdp_arena payloads: 18 diff lines vs pre-B3, **all quote-style only** (single→JSON double quotes); output_probes payloads: same (spinner/model-label lines). Selector values, order and logic identical |
| RULE 16 §16.5 legacy not grown | **DELIVERED (net down)** | CDPArenaController 371→359 LOC / 30→28 methods; CDPClient 469→456 / 22→21; `highlight_selector` unchanged 28 LOC; module-level additions (+`_inject`) are new non-offender code |
| B4 vulture @90 = 0, @60 triage | **DELIVERED** | `vulture app tools/vulture_whitelist.py --min-confidence 90` → exit 0; triage table in implementation record |
| B5 json_store (27×2→1) + output_probes internal builder | **DELIVERED** | jscpd app+tests: 55→44 clones, 1.50%→1.22% lines, **1.25% tokens = plan target**; persistence triple gone; characterization tests written FIRST |
| B6 baseline regen + SOR §7 + README | **DELIVERED** | baseline 76 files (stale values fixed: bridge max-func 1030→1209 had been invisible); SOR §7/§8/§9/§10 + README + DOM_SELECTORS + record |
| Checklist: global fails strictly lower | **MET** | 149→128, monotonic per step |
| Checklist: coverage never decreases | **MET** | 41.21/32.28 → 43.09/33.76 |
| Checklist: per-step lanes green | **MET** | pytest 459, node 111 (after `npm ci`), gate lanes |

## 2. Findings (gaps and imprecision — each becomes a follow-up step)

**F-1 (P0) Per-area coverage criterion NOT met.** Checklist: "Coverage of area's modules ≥80% line / ≥75% branch". Measured: `preset_store` **29.3/20.0**, `output_state` **3.7/0.0** (`flatten_diagnostics` has no direct test), `undo_store` 76.0/63.6, `site_adapter` 81.8/50.0, `config_manager` 82.1/50.0, `cooldown_store` 82.8/73.8. OK: probe_selectors 100/100, selector 95.7/100, json_store 86.5/83.3, page_status 100/100, output_probes 81.8/100, new_chat 82.1/86.7. The record cited only json_store+probe_selectors — incomplete evidence.

**F-2 (P0) Vulture whitelist global-name hazard.** Whitelist entries are bare `a` / `args` — vulture whitelists by NAME globally, so any future genuinely-unused variable named `a` or `args` anywhere in `app/` is silently silenced.

**F-3 (P1) RULE 21 residual holes.** (a) `single_job_runner._submit_fallback` still hardcodes `'button[aria-label="Send message"]'` — a live literal outside site_adapter (identical string to `send_presence_selector()`, pure single-source swap). (b) Action-block default selectors drifted from site_adapter: CHECK_SECURITY carries Playwright-only syntax (`div:has-text(...)` — not valid CSS for the CDP path), WAIT_OUTPUT has `div[data-testid="output"] img` (not in adapter), SUBMIT fallback list = pre-B3 send fallbacks. (c) No test locks the defaults that DO mirror site_adapter (prompt/send/attach) or the JS `getDefaultBlocks()` mirror (RULE 3). (d) `CHECK_SECURITY`/`WAIT_OUTPUT` block `selector` settings are ignored by the live handlers (handlers call the shared site_adapter-driven probes) — RULE 10 decision needed in Area A; document now. (e) DOM_SELECTORS §E "original" table lacks pointer to the authoritative list; §I example lacks `presenceSelector`.

**F-4 (P2) output_probes residual internal clones.** Pair-level jscpd diff: 13 groups removed, but 2 remain (same duplicated content as pre-B5 at shifted lines — not new content): the 8-field association shape (`matched` builder vs final return, 7 lines) and the two `job_id_mismatch_no_matching_image` mega-returns (14 lines). The record's "no new duplication groups" is true in content but imprecise; internal groups stand at 4→2.

**F-5 (P1) Stale docs (RULE 17).** `docs/action-blocks-restore-plan.md` — not in docs index AND says "Current Execution `app/services/job_runner.py`" (deleted 2026-09-19) — actively misleading. `docs/implementation_plan.md` references deleted modules (indexed "Historical" but no in-file pointer).

**F-6 (P1) Gate honesty.** (a) `verify_quality --changed` needs a merge-base with origin/main; this repo's arena branches share **no ancestry** with main → subprocess raises → **silently falls back to ALL files**, and with `--allow-legacy` + the regenerated baseline reports "0 fails on changed files" — false confidence. (b) `pre_push_check.sh` cannot pass mid-round: once `coverage.json` exists, the absolute 80/75 check fails (43.1/33.8 today; the 80/75 target is Area D's D4). (c) The script assumes `python` on PATH (breaks in fresh environments; `.venv` not picked up). The B record's "lanes green" was established by manual lane runs, not the script.

**F-7 (minor) Record imprecision.** File-size numbers in the record were corrected in B6 (probe_selectors 73, site_adapter 270). `output_state.flatten_diagnostics` untested directly (folded into F-1).

## 3. Verdict

Area B is **behaviour-correct and metric-green on every global criterion** (fails −21, coverage up, duplication down to plan target, vulture @90 clean, payload equivalence byte-proven, legacy offenders net-down), but **the per-area exit criterion on module coverage is not met** and the gate tooling has two honesty holes. Follow-up round B7–B12 defined in `plan.md` (same folder), implemented after this review.
