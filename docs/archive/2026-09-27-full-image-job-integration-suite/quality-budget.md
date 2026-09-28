# Quality budget — RULE 16 / RULE 18 numbers for the suite

Companion to `design.md`. Plan-time budget: every number here is a **target to be measured at the
stage that lands it**, not a claim. Baselines quoted from `tools/quality_baseline.json`
(coverage floor line **86.36** / branch **82.33**), `tools/jscpd_baseline.json` (1.240 % over
`app/`) and `pytest.ini` at `02e0240`.

---

## 1. What the gates actually see (measured scope)

| Gate | Scans | Consequence for this plan |
|---|---|---|
| `tools/verify_quality.py` size/complexity | `APP_DIR.rglob("*.py")` (`:162`) — **`app/` only** | `tests/e2e/**` is out of scope for LOC/CC/params/methods (RULE 16.0 row 3). No new gated symbol, no ratchet movement, no `quality-override` needed |
| JS lane | `JS_DIR = app/ui/web` (`:168,179`) | `tests/js/e2e/*.mjs` is not scanned either — but see §6: it must still be **listed** so it runs |
| Coverage | `coverage run --branch --source=app -m pytest tests -q` (`tools/pre_push_check.sh:105`) | the new tests are collected in the default run ⇒ they must skip **safely and fast** (§4) |
| Duplication | `jscpd app/` (`tools/jscpd_baseline.json` note) | fixtures under `tests/` cannot move the 1.240 % floor |
| `tools/*` | **not scanned** by any size/CC lane (`verify_quality.py:162` walks `app/` only) | `tools/har_ingest.py` (D-23) therefore carries a self-imposed RULE 18 budget (§3) and its own unit tests; it is owner-run and never part of `pre_push_check.sh` |
| Repo hygiene | `git ls-files -- config logs 'arena webpages' '*.pyc'` + `api_key` grep (`pre_push_check.sh:40-46`, `tests/test_repo_hygiene.py:25-26`) | fixtures must live under `tests/e2e/fixtures/`; **`reports/e2e/` must be added to `.gitignore` in S0** (D-11) |
| `pytest tests -q` (step 2) | everything under `tests/` | marker policy (§6) decides what runs in the 3-minute push budget |

**Zero `app/` change (D-20) ⇒ the whole RULE 16 machine stays exactly where it is.** The budget
below is therefore self-imposed RULE 18 discipline plus the two hard requirements that *do* bind:
the coverage floor must not drop, and the default push run must not slow down or flake.

---

## 2. Why RULE 18 still applies to untested-by-gate test code

RULE 18 is a preference about the reader's context budget, and this suite is read constantly (it is
the executable spec of the page contract). So: files 150–300 lines, functions 4–20 lines, params
≤4 via parameter objects (`ScenarioExpectation`, `FlowCtx`, `LaneSpec`, `EvidenceBuilder`), one
responsibility per file, module docstring stating what the file owns and which way its imports go
(`design.md` §3.1). Deviations carry an `ideal-size:` reason inline.

---

## 3. Per-new-file budget

| File | Target LOC | Max func LOC | Params | The test that kills it if it is wrong |
|---|---:|---:|---:|---|
| `tests/e2e/fakesite/server.py` | 230 (`ideal-size:` one route table + one session store; splitting routes from sessions would scatter one page contract) | 20 | ≤3 | `test_fakesite_unit.py::test_control_routes_absent_without_flag`, `::test_refuses_foreign_host` |
| `tests/e2e/fakesite/pages.py` | 120 | 20 | ≤3 | `::test_every_registry_selector_resolves` (15 keys × primary+fallbacks) |
| `tests/e2e/fakesite/artifacts.py` | 110 | 20 | ≤2 | `::test_result_bytes_are_deterministic_and_decode`, `::test_hashes_match_fixtures_json` |
| `tests/e2e/fakesite/static/fake-arena.js` | 260 (`ideal-size:` one state machine; a split would put two halves of one transition table in two files) | 20 (JS lane rule) | ≤4 | `test_fakesite_unit.py` walks all 14 states through the real server |
| `tests/e2e/fakesite/static/chat.html` | 180 | — | — | same selector-resolution test |
| `tests/e2e/contract.py` | 260 (`ideal-size:` the scenario table is data; the asserter is one function) | 20 | ≤2 | `test_contract_unit.py::test_every_state_is_covered`, `::test_no_lane_specific_expectations` |
| `tests/e2e/flow.py` | 200 | 20 | ≤2 (`FlowCtx`) | every step function asserts internally; a deleted step fails its own scenario |
| `tests/e2e/app_instance.py` | 180 | 20 | ≤3 | `::test_app_instance_has_no_patched_browser_module` (guards D-3) |
| `tests/e2e/evidence.py` | 180 | 20 | ≤3 | `::test_bundle_schema_round_trip`, `::test_ids_normalized` |
| `tests/e2e/clock.py` | 90 | 20 | ≤2 | `test_clock.py::test_patch_set_is_exactly_three_namespaces` |
| `tests/e2e/lanes/base.py` | 80 | 20 | ≤3 | `::test_capabilities_narrow_loudly` |
| `tests/e2e/lanes/chromium.py` | 150 | 20 | ≤3 | S3 flow test + `::test_skip_reason_names_the_resolution_order` |
| `tests/e2e/lanes/firefox.py` | 130 | 20 | ≤3 | adapter contract test (8 families) |
| `tests/e2e/lanes/cdp_adapter.py` | 240 (`ideal-size:` one protocol table; splitting per method would create 8 files of 30 lines) | 20 | ≤3 | `test_adapter_contract.py` — a fixture page answers all 8 families with the exact reply shapes of `evidence.md` §2 |
| `tests/e2e/lanes/jsdom.py` | 110 | 20 | ≤2 | `::test_jsdom_narrows_screenshot_and_fetch` |
| `tests/e2e/conftest.py` | 200 | 20 | ≤3 | every fixture finalizer asserted by `test_isolation.py` (ports released, temp dirs gone) |
| `tests/e2e/test_full_image_job.py` | 160 | 20 | — | the scenarios themselves |
| `tests/e2e/test_recovery_and_reset.py` | 140 | 20 | — | endless → reset → next job succeeds |
| `tests/e2e/test_timeout_contract.py` | 150 | 20 | — | the two-part 300 s contract (D-8) |
| `tests/e2e/test_fakesite_unit.py` | 180 | 20 | — | browser-free; runs in the default lane |
| `tests/e2e/test_contract_unit.py` | 120 | 20 | — | browser-free |
| `tests/e2e/test_clock.py` | 70 | 20 | — | browser-free |
| `tests/e2e/README.md` | ≤120 (RULE 18.4 context-file band) | — | — | reviewed, not tested |
| `tests/js/e2e/jsdom_cdp_server.mjs` | 180 | 20 | ≤4 | the jsdom lane's own smoke test |
| `tests/js/e2e/layout-shim.mjs` | 120 | 20 | ≤4 | `test_layout_shim.mjs` — geometry facts the probes read |
| `tests/js/e2e/test_e2e_fixtures_vs_saved_page.mjs` | 90 | 20 | — | skip-gated (D-15) |
| `tools/e2e_check.sh` | 40 | — | — | shellcheck-by-reading + `--dry-run` |
| `tools/har_ingest.py` *(S1a, owner-run — D-23)* | 150 | 20 | ≤3 | `test_har_ingest_unit.py`: sanitize-equivalence with `app/services/captcha_recording/sanitize.py`, determinism (same HAR ⇒ same sha256s), host allowlist, **fail-closed on a secret pattern**, shape extraction |
| `tests/e2e/test_har_ingest_unit.py` | 110 | 20 | — | browser-free, runs in the default lane (<1 s) |

Total ≈ 3 900 lines of test infrastructure (incl. the S1a ingest) for a suite that replaces nothing. Test-to-code ratio
(RULE 16.3, warn-only) moves **up**, which is the intended direction.

---

## 4. Coverage floor — why skipping is safe, and the two rules that keep it true

The floor is computed from `coverage run --branch --source=app -m pytest tests -q`
(`pre_push_check.sh:103-106`). Skipped tests contribute nothing and subtract nothing, so
**line 86.36 / branch 82.33 are unchanged** by S0–S2 and by any machine without a browser. When the
browser lanes do run they can only add hits over the same `app/` code (they exercise the real
pipeline), so the ratchet moves up, never down.

Two rules make that true and are themselves tested:

1. **Collect without importing a browser.** `playwright`, `websockets` server bits and the Node
   sidecar are imported **inside** fixtures/functions (`pytest.importorskip` at fixture level), so
   `pytest tests -q` on a bare machine collects `tests/e2e/*` and skips. A collection error would
   fail the whole push run — `test_fakesite_unit.py` is browser-free precisely so something in the
   folder always runs.
2. **Never write to `app/`, `config/`, `logs/`.** All writes go to `tmp_path` or
   `reports/e2e/` (git-ignored). `tests/test_repo_hygiene.py` keeps passing untouched (I-43).

Deliberate exclusion: the e2e lane is **not** added to the coverage command. If a future integrator
wants it, the change is `--source=app` + an extra `-m e2e_browser` run merged into one
`coverage combine`, and the floor must be re-recorded with `--record-baseline` and a commit message
saying why (RULE 16 baseline rule). This plan does not do that.

---

## 5. Test-time budget (L-12: the wait polls every 2 s, hard-coded)

| Lane / group | Tests | Real time estimate | Basis |
|---|---:|---:|---|
| Default `pytest tests -q` delta (S0–S2) | 3 browser-free files, ~35 tests | **< 3 s** | no browser, no network beyond 127.0.0.1, jsdom only where node exists |
| Default delta (S3+) on a machine **without** a browser | all `e2e_browser` tests | **< 1 s** | skip at fixture setup, reason string only |
| `e2e_browser` Chromium, 6 core scenarios (S4) | 6 | **≈ 45 s** | per job: 1 attach + 2 prompt evals + submit + ≥2 polls × 2 s + the 3 s settle before `download_image` (`single_job_runner.py:333-336`) + reset ≤ 2 s; endless scenario 6 s timeout + reset |
| `e2e_browser` Chromium, full matrix (S5+S7, ~22 scenarios) | 22 | **≈ 2.5 min** | as above, parallel-safe (`-n 4` where the machine allows) |
| `e2e_browser` Firefox (serial, D-22) | 22 | **≈ 4 min** | one at a time + profile start ≈ 3 s each |
| jsdom lane | 22 | **≈ 40 s** | no browser start; Node sidecar ≈ 1 s |
| `e2e_slow` soak (real 300 s) | 1 | **5.5 min** | opt-in only, never in the push budget |

Rule: the **push budget** (`pre_push_check.sh`) never runs `e2e_browser`; `tools/e2e_check.sh` does,
and prints per-group timings so a regression in the budget is visible.

---

## 6. Markers, collection and the JS list (the L-7 trap)

* `pytest.ini` gains `e2e_browser`, `e2e_desktop`, `e2e_slow` (with `--strict-markers`, an
  unregistered marker fails collection — so they must land in S0, before any test uses them).
* `tests/conftest.py::pytest_collection_modifyitems` (`:33-43`) gains: path starts with
  `tests/e2e/` **and** the file is not in the browser-free allowlist ⇒ add `e2e` + `e2e_browser`;
  Firefox-parametrized tests additionally get `serial`. The existing four
  `tests/integration/test_sash_webengine.py` marks stay untouched (L-13).
* **`package.json` `test:js` must list the two new `.mjs` tests** (`layout-shim`,
  `jsdom_cdp_server` smoke) in the same commit that adds them — the L-7 defect class is "on disk
  but unlisted, so they never run". `test_e2e_fixtures_vs_saved_page.mjs` is listed too (it
  self-skips when the dumps are absent, exactly like `test_captcha_saved_page.mjs`).
* `tools/e2e_check.sh` runs: `pytest tests/e2e -q -m "not e2e_slow"` →
  `pytest tests/e2e -q -m e2e_slow` only with `--soak` → prints artifact location on failure.

---

## 7. RULE 16.7 checklist, applied to this plan

```text
[ ] No new function >30 physical LOC          → n/a for the gate (tests/), budget ≤20 (§3)
[ ] No new class >150 LOC or >15 methods      → largest planned class EvidenceBuilder ≈90 LOC / 8 methods
[ ] No new function with >4 params            → parameter objects (§2)
[ ] radon CC ≤10, cognitive ≤15, nesting ≤4   → n/a for the gate; the state machine and the adapter
                                                dispatch on TABLES (data, not branches) so CC stays ≤7
[ ] coverage ≥ baseline, branch ≥75%          → unchanged when skipping, up when running (§4)
[ ] every new function has a test that fails if deleted → §3 last column, per file
[ ] no new vulture findings / duplication     → gate scans app/ only; fixtures reuse ONE result_bytes
                                                owner (D-7) and ONE expectations owner (D-10)
[ ] quality-override comments                 → none needed, none used
[ ] did not game metrics                      → §8
[ ] RULE 18 ideals + reasons                  → §3 carries every deviation with its reason
[ ] RULE 19 order respected                   → nothing over a fail line; if a stage hits one,
                                                nesting → CC → cognitive → size
[ ] SYSTEM_OF_RECORD / docs/README updated    → docs/README row now (plan); SYSTEM_OF_RECORD §5
                                                (I-55…I-59) + §8 rows and the DOM_SELECTORS pointer
                                                land WITH the code stages (RULE 17)
```

---

## 8. Anti-gaming refusals (stated up front, per §16.2)

1. **No `foo_part1/part2`.** `flow.py` steps are named after pipeline stages that already exist in
   the domain (`detect_page`, `join_pool`, `scan_and_select`, `dispatch`, `settle`), never after a
   line quota.
2. **No assertion-free "coverage".** A scenario whose only assertion is "the run finished" is
   rejected at review; `contract.py` requires a positive **and** a negative expectation per scenario
   (brief §13).
3. **No second selector registry in the fixtures.** The guard test imports
   `app.browser.probe_selectors` read-only; the fake page never hard-codes a copy of a selector list
   that could drift (D-15/R6).
4. **No fake lane inside the e2e lane.** `FakeCtrl`/`install_patches` stay in
   `tests/characterization/`; a test that patches a browser module in `tests/e2e/` fails
   `test_app_instance_has_no_patched_browser_module`.
5. **No scenario that only passes in jsdom** (D-14) and **no capability narrowing without an
   evidence entry** (D-10).
6. **No 300 s wait in the default suite** (D-8) and no virtual clock outside
   `test_timeout_contract.py` (D-9, patch-set allowlist test).
7. **No committed artifacts** — `reports/e2e/` is git-ignored from S0 (D-11, I-43).

---

## 9. Gate commands per stage

```bash
# every stage (unchanged, must stay green):
QT_QPA_PLATFORM=offscreen python -m pytest tests -q -p no:cacheprovider
python tools/verify_quality.py --changed --allow-legacy --coverage-ratchet
bash tools/pre_push_check.sh                      # steps 0-4, incl. hygiene + node lane

# S1+ (browser-free infra):
QT_QPA_PLATFORM=offscreen python -m pytest tests/e2e -q -m "not e2e_browser"

# S3+ (real browsers; needs `playwright install chromium firefox` + `npm ci` for jsdom):
bash tools/e2e_check.sh                           # -m "e2e_browser and not e2e_slow"
bash tools/e2e_check.sh --soak                    # adds the one real 300 s run
ARENA_E2E_ARTIFACTS=1 bash tools/e2e_check.sh     # keep reports/e2e/ bundles for review

# coverage (unchanged command, unchanged floors):
QT_QPA_PLATFORM=offscreen python -m coverage run --branch --source=app -m pytest tests -q
COVERAGE_FILE=.coverage python -m coverage json -o coverage.json
```
