# Batch B — review findings & improvement plan (2026-09-19, second pass)

Full re-review of the Batch B implementation against `docs/current/AGENT_RULES.md`
(RULE 8, 16, 17, 18, 19, 21), `SYSTEM_OF_RECORD.md` (§7, §8, I-18), `DOM_SELECTORS.md`,
and `design.md`/`implementation-2026-09-19.md` in this folder.

**Status: steps 1–6 implemented and gated (same day).** Results: pytest **455 passed**
(446 + 8 new `test_json_store` + 1 new corrupt-state test); **zero** functions >20 ln on
the new/touched surfaces; generated map still 32 entries, in lockstep, idempotent;
app/ gate fails 129 → 128 (dead `build_js_find` removed — the 1 "new vs pristine" diff is
only the same legacy violations with shifted LOC numbers); pyflakes/vulture zero unused;
node composer probes 3/3; pre-push hook installed. §8 table now literally true (added
`test_json_store.py` row, gate row points at `tools/verify_quality.py`, `tests/js/*.mjs` row).

## Review — what conforms

* **RULE 16 (no new breaches):** proven earlier by normalized finding-list diff
  (pristine vs post-B tree): 149 → 129 fails, zero new; all findings in touched files are
  `[LEGACY]` within `quality_baseline.json` limits.
* **RULE 8:** probe strings untouched (`.mjs` harness executes the real consts — 3/3 pass);
  446 pytest pass; the two pre-existing `.mjs` failures fail identically on the pristine tree.
* **RULE 21 / I-18:** generated map = 32 entries, exact live order, 100% coverage, idempotent,
  pre-push `--check` gate; `cdp_arena` reads primaries via `get_selector()`.
* **RULE 17:** SYSTEM_OF_RECORD / DOM_SELECTORS / README synced in the first pass.
* **B5 behaviour parity re-verified this pass:** `json_store.atomic_write_json` matches the
  deleted local copies byte-for-byte in semantics (`indent=2, ensure_ascii=False`,
  temp-suffix `.json.tmp`, parent-dir mkdir); `mkstemp` creates the temp 0600, so the
  key file is 0600 from the moment it appears (no readability window vs the old
  lock-before-replace order). All 9 `load_json` call sites pass dict defaults with the
  default `expect_type=dict` — consistent.
* **RULE 18 (json_store.py):** 4 functions, 5–14 lines — inside the 4–20 ideal.

## Review — gaps found (this pass)

| # | Finding | Rule | Severity |
|---|---|---|---|
| F1 | **Dead code on the B surface:** `site_adapter.build_js_find` (37 ln, zero importers — also a legacy gate fail), `site_adapter.list_selectors` (zero importers), `SelectorObject.to_dict` (zero importers), `output_probes.get_selectors()` (zero importers), `generate_selectors.RE_TRIPLE` (dead constant), `site_adapter.get_readiness_requirements` (test-only importer) | 16.4 | must fix |
| F2 | **RULE 8 test gap:** §8 promises `test_persistence.py` covers "corrupt JSON handling (RULE 13)" — no such test exists. The tolerant loader now has exactly one home (`json_store.load_json`) and deserves a direct unit test | 8, 13 | must fix |
| F3 | **RULE 18 function sizes in new tooling:** `generate_selectors.py` — `collect` 50 ln, `render_block` 29, `build_chains` 26, `main` 24; `import_graph.py` — `main` 26 (ideal 4–20) | 18 | should fix |
| F4 | **§8 table not true today:** names `tests/test_selectors.py` (actual: `test_selector.py`), `tests/test_rule16_new_code.py` (does not exist — the gate is `tools/verify_quality.py`), `tests/js_harness.js` (actual: `tests/js/*.mjs` under `node --test`) | 17 | must fix |
| F5 | **Pre-push hook not installed** in this workspace — the gate is manual-only here | 16 (CODE_VERIFICATION) | should fix |
| F6 | `site_adapter.py` 535 lines > 300 ideal — generated pure-data block (455 ln) + 4 helpers; pure-data modules are explicitly "normal and good" under 150, and §16.0 excludes generated content from the gate. After F1 the file drops to ~460 ln | 18 | accept + document |

## Steps (implementation order)

1. **F1 — delete dead code on the B surface** (zero-importer functions/constants;
   `get_readiness_requirements` + its single test in `test_selector.py` — that test file is
   **not** in the §8 mandate table). Update the generator: the readiness names
   (prompt_textarea, send_button, file_input, output_region) remain fully covered by the
   generated entries and the coverage gate, so nothing is lost.
2. **F2 — add `tests/test_json_store.py`** (unit): round-trip; `indent=2` + `ensure_ascii=False`
   byte check; `mode=0o600` applied; parent-dir auto-creation; no temp files left behind;
   `load_json` missing → deep-copied default, garbage → default, JSON-of-wrong-type → default,
   defaults not shared across calls (deepcopy). Closes the §8 "corrupt JSON" promise at the
   canonical loader.
3. **F3 — split oversized tool functions** (RULE 18, user-rechecked): `collect` →
   per-source helpers (`_collect_arena/_newchat/_output_probes/_cdp_client/_action_blocks/
   _captcha_js`), `build_chains` → chain build + `_coverage_errors`, `render_block` →
   `_render_entry`, `main` → small dispatch; `import_graph.main` → `_report`. No behaviour
   change — `--dump`, `--check`, `--write`, `--report` outputs must stay identical, verified
   by idempotent double `--write` + full test suite.
4. **F4 — fix §8 to be true today** (three line corrections; also verified
   `CODE_VERIFICATION.md` / `docs/README.md` carry no stale references to the missing files).
5. **F5 — install the pre-push hook** via `tools/install_hooks.sh` (runs
   `tools/pre_push_check.sh`, which now includes the selector-sync + dead-module gates).
6. **Final gates:** pytest, `--dump`/`--check`/`--write` idempotency, dead audit,
   pyflakes + vulture (zero unused), `verify_quality` full + `--changed --allow-legacy`
   (expect the same 3 pre-existing fails only, nothing new), node composer probes.

## Rejected / deferred (with reasons)

* **Wire `is_page_ready` to the map** (replace `get_readiness_requirements` by generating
  `JS_PAGE_READY` from map primaries): rejected for now — introduces import-time JS
  generation into a module whose sibling constants are literals; byte-identical output is
  provable but the workflow gain is small. Revisit when the map is used from more call sites.
* **Split `site_adapter.py` below 300 lines** (F6): rejected — the generated block is one
  atomic unit the writer replaces between markers; splitting a generated data table into
  multiple files complicates idempotency for zero reader benefit (455 lines of uniform
  entries, each ~14 lines).
* **Fix the 5 class-fragment-only primaries** (`--report` flags them): deferred — adding
  semantic/structural fallbacks changes probe behaviour; needs live-page verification (RULE 22).
* **Repo-wide coverage 42.7% < 80%/75% and `solver.py:362` cognitive 16:** pre-existing,
  baseline-uncovered, out of Batch B scope (RULE 19 remediation is its own effort).
* **Pre-existing `tests/js` failures** (`test_captcha_recording`, `test_title_fit`): pre-existing
  on the pristine tree; separate effort.
