# Docs Map — Arena Image Processor

## Current truth (read these first)

These three files in `docs/current/` are the **single source of truth** for what the system does today. If not true today, it does not belong here (RULE 17).

| File | What it is | When to read |
|---|---|---|
| [`current/SYSTEM_OF_RECORD.md`](current/SYSTEM_OF_RECORD.md) | Authoritative spec: behaviour table (22 capabilities), state machine 00-22, core flow plan→execute, invariants, storage map JSON-only, key modules & layers, tests, quality gates, UI 15 windows, history pointers | Before any code change — understand what system actually does |
| [`current/AGENT_RULES.md`](current/AGENT_RULES.md) | Detailed code-quality rules (23 rules, adapted from Old App's 19 rules + 4 new for Arena). Includes RULE 1 visual runner, RULE 16 hard gates LOC 30/150 params 4 methods 15 CC 10 cognitive 15 nesting 4 coverage 80%/75%, override format, anti-gaming, remediation order RULE 19, selector priority, CAPTCHA compliance. Executable gate: `tools/verify_quality.py`, baseline `tools/quality_baseline.json`, pre-push hook `.git/hooks/pre-push` | Before adding/changing production code — mandatory gates |
| [`current/CODE_VERIFICATION.md`](current/CODE_VERIFICATION.md) | **Mandatory verification workflow before push** — how to run `tools/verify_quality.py --changed --allow-legacy`, `tools/pre_push_check.sh`, tests, coverage, git hook enforcement, override format, remediation order. Based on Old App's rule16_gate.py | Before every `git push` — RULE 16 enforcement |
| [`current/DOM_SELECTORS.md`](current/DOM_SELECTORS.md) | Living selector reference for arena.ai: verified selectors from saved HTML, primary+fallbacks, scope, visibility, expectedCount, verification, evidence, JS probes, visual runner colours, readiness composite, missing selectors list | Before touching `app/browser/site_adapter.py` or action blocks |

**Rule numbers are stable** — production code cites them (`RULE 1` … `RULE 23`). Never renumber; append instead.

---

## Supporting docs (still relevant, but not current truth)

These are kept for context, but `docs/current/` is authoritative if conflict:

| File | What it holds | Status |
|---|---|---|
| `data_model.md` | Data structures: ImageItem, URLItem, AppState, etc. | Supporting — should match SYSTEM_OF_RECORD §6 |
| `workflow_diagram.md` | Visual workflow of scan→select→attach→prompt→submit→wait→download→save | Supporting — state machine in SYSTEM_OF_RECORD §3 is authoritative |
| `implementation_plan.md` | Step-by-step build plan | Historical — implementation done |
| `selector_map.md` | Detailed selector map with evidence (181 lines) — source for DOM_SELECTORS.md | Supporting — DOM_SELECTORS.md is living reference |
| `research_summary.md` | Findings from saved HTML inspection | Historical research |
| `risks.md` | Risks, mitigations | Supporting |
| `known_limitations.md` | Known limitations | Supporting |
| `manual_test_checklist.md` | Manual testing steps | Supporting |
| `modern_ui_integration.md` | How sash-grid, win-grip, dark-mode variables.css reused from Old App | Supporting |
| `rules.md` | Old simplified rules (40 lines) — **deprecated**, use `current/AGENT_RULES.md` (730+ lines detailed) | Deprecated — pointer to current |
| `research/` | Saved HTML + assets from arena.ai | Evidence for selectors |

---

## Archive (dated, never edited to catch up)

`docs/archive/<YYYY-MM-DD>-<topic>/` — every design/plan/root-cause doc goes here, dated by day written. Archived docs are record of what was believed then, never edited.

- `archive/2026-09-16-image-below-prompt/` — fix for image-below-prompt correlation (JOB-ID verification for reverse layout)
- `archive/2026-09-16-test-time-reduction/TEST_TIME_REDUCTION_PLAN.md` — structured plan to reduce test time: pyramid rebalance, fixture scopes, eliminate real-browser tier, xdist parallelisation, async sleep removal, DI fakes, CI 3-stage gates, roadmap with RULE 16/18 compliance
- `archive/2026-09-17-watcher-grid-bugfixes/SOLUTION.md` — root causes + fixes for the blank Watcher window, "2nd divider rescales all rows" drag bug, and sashes vanishing after drop: single sash-visibility rule, hidden-child-safe resize commit, next-visible-child drag pair
- `archive/2026-09-17-titlebar-controls-visibility/SOLUTION.md` — window ─/✕ controls can be clipped when a window narrows (title row min-content > 96px floor, `.panel{overflow:hidden}`): title text truncated via `span.win-name`, secondary title items dropped right-to-left by single-writer `_fitTitleBars()`, fixed core trimmed below the 96px minimum
- `archive/2026-09-17-2captcha-integration/` — `design.md` + `summary.md`: opt-in 2Captcha auto-solve for visible Security-Verification captchas (RULE 20 amendment), `handle_captcha` choke point, masked-only key store, statistics panel, JS probes tested under `node --test`
- `archive/2026-09-18-captcha-detection-verification/design.md` — detection verified/adapted against real arena.ai states (challenge dialog vs always-on badge: two sitekeys, `size=invisible` vs `normal`): badge exclusion, dialog-scoped sitekey, `isInvisible` in the docs-exact 2Captcha payload, real container/text signals
- `archive/2026-09-18-captcha-delivery-recovery/design.md` — round 5: token never travelled the real solve path (anchor `cb=` premise disproved by live logs) — every-field injection + `data-callback` → `___grecaptcha_cfg` → anchor chain; bounded post-settle resubmit when the blocked generation died
- `archive/2026-09-18-revival-generalize/design.md` — round 6: trigger revival on spinner loss (seen, then 20 s gone with no pixels), not only on captcha settle — covers no-dialog dead generations like the 12:08 run
- `archive/2026-09-18-grid-window-set/design.md` — grid persistence: Python/JS window sets synced (14 incl. `captcha`); invalid layouts rejected not defaulted (RULE 13); preset save→load round-trips the portable doc
- `archive/2026-09-18-resubmit-send-ready/design.md` — round 7: visible-composer insert + Send-ready click + re-attach on resubmit; `Trace ID:` in-thread errors fast-fail the wait
- `archive/2026-09-18-solve-observability/design.md` — round 8: task id, poll heartbeats, token fingerprint + time-to-token, pre-inject dialog state, provider error detail in logs
- `archive/2026-09-18-too-late-to-solve/design.md` — round 9: tokens real-but-late verdict + data-first slice (isInvisible log, mid-solve error timestamps, no behavior change)
- `archive/2026-09-18-captcha-reporting/design.md` — round 10: `CAPTCHA_SOLVE` JSON per encounter + `CAPTCHA_JOB` join at job end (outcome + page error)
- `archive/2026-09-18-captcha-session-recording/design.md` — research/design for bounded redacted DOM/network recordings, CDP event routing, auto lifecycle, Records window, and user labels
- `archive/2026-09-18-captcha-solve-comparison-diagnostic/verification-and-problem-diagnostic.md` — evidence-gated manual-pass/bot-pass/bot-fail comparison protocol, confirmed recording gaps, root-cause hypotheses, and fix verification criteria
- `archive/2026-09-18-captcha-bot-failure-analysis/verification-and-problem-diagnostic.md` — why the bot solve fails, exactly: manual-vs-bot path structural diffs (D1–D6), re-verified recorder/viewer defects (P1–P10 with current-code evidence), confirmed failure mechanisms from rounds 5–11 live logs (RC-1…RC-5) with per-session recording verification signatures, and the ordered fix plan (F-A read-model fix + F1 all-records view + F2 per-row delete implemented; F-B…F-E proposed)
- `archive/2026-09-18-recaptcha-page-mechanics/research-design.md` — research/design: Enterprise bootstrap, anchor/challenge frames, response field, callback, backend acceptance, stale tokens, page-error state machine
- `archive/2026-09-18-recaptcha-verification-architecture/design.md` — implementation architecture: probe evidence, terminal page-error/stale-token guards, acceptance candidate vs output success, penalty/report semantics, test matrix
- `archive/2026-09-18-recaptcha-verification-architecture/implementation-2026-09-18.md` — implementation record: page/document timeOrigin identity + challenge-frame identity compared before token injection
- `archive/2026-09-18-url-row-tab-ownership/design.md` — "5 links detected but only 4 tabs open" + "checked 1 link but 2 were used": root causes were run-side row re-binding (round-robin `link_tab` steals rows → next scan adds phantom rows) and dispatch ignoring the checkbox (pool dispatch/tab-resolve picked any tab); fix is invariant I-33 — one live tab ↔ one row, auto-connect owns bindings, scan repairs duplicates, and checked rows gate start/single/parallel paths
- `archive/2026-09-18-code-quality-round/` — **planning round (no production code changed)**: `metrics-baseline-2026-09-18.md` (full audit vs the given thresholds: 1,047 py functions, worst `Bridge._do_run_batch` 1,205 LOC / CC 354 / cognitive 1,097 / nesting 23, Bridge 4,991 LOC / 200 methods / LCOM4 11 / MI 0.00, 120 RULE 16 fails, 1,239 LOC dead code, line 43.4% / branch 32.0%, 55 duplicate groups, JS un-gated), `problem-priority.md` (P1…P9), four isolated area plans — `plan-area-a-run-pipeline.md` (bridge/`_do_run_batch` ↔ `single_job_runner` unification + facade split), `plan-area-b-dead-code-purge.md` (controller/job_runner/output_detector/job_state_machine deletion + RULE 21 selector single-source), `plan-area-c-complexity-hotspots.md` (watcher/cdp_client/cdp_arena/… + JS panels), `plan-area-d-verification-and-evidence.md` (coverage 43%→80%, mutation, gate ratchet, captcha recording P9/F-B/F-C) — plus `appendix-reproduction-commands.md`
- `archive/2026-09-19-code-quality-implementation-plan/` — **implementation plan, planning only, no prod code**: `design.md` (process + area map + priority table), `step1-understand-prioritized.md` (Step 1 split into 10 sub-steps 1.1–1.10 by severity P1 96→P9 33, each with measure command/evidence/decision/owner), `area-plans-prioritized.md` (Round 0 R0.1–R0.6 + Area B B1–B6 first quick win, Area A A1–A7 centre of gravity, Area C C1–C8 + D D1–D7 parallel, all ≤20 LOC steps RULE 19 order nesting→CC→cognitive→size), `verification-checklist.md` (RULE 16 hard gates + RULE 18 ideals recheck template, per-step/per-area/final), `implementation-2026-09-19.md` (empty placeholder for future implementation record) — prioritized by blast radius×3 + evidence×2 + gate×2 + defect×2 + delay×1, implementation order Round0→B→A→C/D with D1 immediate
- `archive/2026-09-18-recording-toggle-and-day-folders/design.md` — record on/off toggle (default ON, `start()` short-circuits when off) + per-day session folders `YYYY-MM-DD/<session>/` (legacy flat coexists, `drop_empty_day`, analyzer walks all layouts)
- `archive/2026-09-19-rate-limit-penalty/design.md` — 3rd URL-window cooldown field: user-set **rate-limit penalty** (default 30 min) — when a job fails on a rate/limit/quota banner (`is_rate_limit_error`), the tab stacks that penalty (`maybe_note_rate_limit` at both failure sites) so it cools base+penalty instead of base alone
- `archive/2026-09-19-area-a-bridge-pipeline/` — **Area A implementation (centre of gravity)**: `design.md` (A1–A7: golden harness → converged runner → orchestrator seam → flip+delete → 12 panel mixins → BridgeContext → sweep) + `review-and-improvement-plan.md` (R0–R12 execution record: ideals hardening, 8 panel rounds with 87/87 + 70/70 + 39/39 behavior differentials, ideals sweep, context, sweep) + `implementation-area-a.md` (per-step log with SHAs, packing table, coverage baseline, F17 follow-up). End state: 590 green, gate TOTAL 62 (bridge 0), Bridge 159 lines / 10 methods, 119 frozen slots, panels→services direction + one Qt shim
- `archive/2026-09-19-refactor-cycle-integration/design.md` — **cycle X**: how R0+A+B+C were merged into one branch (per-deliverable winners with evidence), the three regressions the integration caught (silent `@Slot` swap, `CDPClient.connect()` TypeError in real Qt, RULE 21 literal drift), the payload-equivalence check, and the RULE 18 audit of what is still >300 LOC

Old App archive: `Process Images in Areana/Old App/docs/archive/` and `Process Images in Areana/Old App/docs/current/` (source for detailed rules).

---

## How to add new doc

1. Write design into `docs/archive/<YYYY-MM-DD>-<topic>/design.md` (dated)
2. Update rows in `docs/current/SYSTEM_OF_RECORD.md` it affects (behaviour table, invariants, flows, history links)
3. Update `docs/current/AGENT_RULES.md` if new rule, or `DOM_SELECTORS.md` if new selector
4. Update this map

Do not add new top-level doc for feature — pointer outward beats wall of prose (RULE 17, RULE 18 context files 60-200 lines ideal).

---

## Quick links for agent workflow (RULE 16 §16.6)

1. Read `current/SYSTEM_OF_RECORD.md` + `current/AGENT_RULES.md` rules 1-15 + RULE 18 size ideals
2. Research saved HTML in `research/` + `selector_map.md` + `current/DOM_SELECTORS.md`
3. Design in `archive/<date>-<topic>/` if complexity moves across files — record radon numbers, target numbers, dishonest reductions rejected
4. Tests first (RULE 8)
5. Measure: `radon cc -s path/to/file.py` — any new function C or worse (CC≥11) → stop and redesign in order RULE 19
6. Update current docs in same change (RULE 17)

---

*Last updated: 2026-09-19 — Area A complete (R0–R12): SYSTEM_OF_RECORD §7 rewritten to the panel/context end-state; archive entry added. Previous: 2026-09-15 migration to detailed rules from Old App.*
