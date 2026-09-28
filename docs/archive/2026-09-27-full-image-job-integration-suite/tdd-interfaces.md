# TDD interfaces — per-stage split, expected files/functions, RED-first test branch

Companion to `design.md` (D-1…D-22) and `quality-budget.md` (sizes). Written the way the owner
asked for the S-chain: *pre-design the interface splitting, the expected files/functions and the
branch of tests, TDD first*. Plan only — no code exists.

---

## 0. How to use this file

* **TDD rules.** For every stage: write the RED tests listed, run them, and record the failure you
  actually saw (it must be the one predicted here — a different failure means the interface is
  wrong, not that the test is). Then GREEN with the smallest implementation, then REFACTOR under the
  stage's equivalence gate (§ per stage), then the gates (`quality-budget.md` §9), then the doc rows.
* **Sizes** are the budgets from `quality-budget.md` §3; a symbol that cannot fit is split by
  concept **before** it is written (RULE 19 step 4 is last, not first).
* **Must-not** columns are the anti-gaming rules for that symbol (§16.2). A test that only satisfies
  a must-not is not a test.
* **Frozen seams** (§A) are the app-side entry points the suite may use — nothing else. §B is the
  proof that the plan needs **zero** production change (D-20).

Test-infra inventory reused (never rebuilt): `tests/characterization/harness.py`
(`build_bridge:106`, `Recorder` — class in `tests/characterization/fakes.py:13`, `normalize:184`, `CORR_RE:33`, `run_supervisor:211`),
`tests/fakes/cdp_stub_server.py` (HTTP+WS skeleton), `tests/conftest.py` (auto-marker `:31-45`,
`isolated_*` fixtures), `tests/js/page_harness.mjs` / `fake_dom.mjs` (Node sandbox pattern),
`tests/js/test_captcha_saved_page.mjs` (skip-gated saved-page precedent).

---

## S0 — skeleton, markers, hygiene (no behaviour yet)

| New/changed | Kind | Size | Caller | Must-not |
|---|---|---|---|---|
| `pytest.ini` markers `e2e_browser`, `e2e_desktop`, `e2e_slow` | config | +3 lines | pytest | must not touch the existing 5 markers or `addopts` |
| `tests/conftest.py::pytest_collection_modifyitems` | edit | +8 LOC (func stays ≤30) | pytest | must not change the `webengine`/`integration`/`unit` rules (`:33-45`); must not import playwright |
| `.gitignore` `reports/e2e/` | config | +2 lines | git | must not un-ignore anything |
| `tests/e2e/__init__.py`, `tests/e2e/README.md` | new | ≤120 lines | humans | README must state what a skip means (RULE 4) |
| `tools/e2e_check.sh` | new | ≤40 lines | human/CI | must not run inside `pre_push_check.sh`; must not require a browser to *start* |
| `tests/e2e/test_markers.py` | new | ≤60 | pytest | — |

**RED branch (3 tests).**
1. `test_markers.py::test_e2e_markers_registered` — asserts `pytest --markers` lists the three new
   names. *Expected RED:* `--strict-markers` makes an unknown marker a collection error, so the test
   fails with `Unknown pytest.mark.e2e_browser`.
2. `::test_tests_e2e_auto_marked` — collects a temporary `tests/e2e/test_probe_x.py` and asserts the
   item carries `e2e` + `e2e_browser`. *Expected RED:* no auto-mark rule yet ⇒ markers absent.
3. `::test_reports_e2e_ignored` — `git check-ignore -v reports/e2e/x.json` succeeds. *Expected RED:*
   exit code 1.

**Equivalence gate:** `pytest tests -q` count unchanged except the 3 new tests; `pre_push_check.sh`
green; no `app/` file touched (`git diff --name-only` shows none).

---

## S1 — the fake site (browser-free, the page contract becomes executable)

### Interface split

| Symbol | Signature | Size | Caller | Must-not |
|---|---|---:|---|---|
| `fakesite.server.FakeSite` | `class FakeSite(allow_control: bool = True)` | ≤110 LOC / ≤9 methods | `conftest.fake_site` | must not hold scenario logic (the page owns it, D-17); must not bind anything but `127.0.0.1` |
| `FakeSite.start` / `.stop` | `async def start(self) -> "FakeSite"` · `def stop(self) -> None` | ≤20 | fixture | must not leave a socket in TIME_WAIT that breaks the next test (SO_REUSEADDR + explicit `server_close`) |
| `FakeSite.url` | `@property def url(self) -> str` | ≤6 | flow | — |
| `FakeSite.set_scenario` | `def set_scenario(self, name: str, session: str = "") -> None` | ≤12 | tests (control API path) | must not mutate a shared dict across tests |
| `FakeSite.events` | `def events(self, session: str = "") -> list[dict]` | ≤12 | `contract.assert_contract` | must not filter/interpret events (raw page trace) |
| `fakesite.server.SessionState` | `@dataclass scenario, state, send_count, resubmits, job_id, result_served` | ≤25 | server | must not be a second state machine (mirrors the page, is written by it) |
| `fakesite.pages.render_chat` | `def render_chat(scenario: dict, session: str) -> str` | ≤20 | handler | must not inline a selector literal that the registry owns (RULE 21); must not emit an external URL (I-56) |
| `fakesite.pages.render_signin` | `def render_signin() -> str` | ≤12 | handler (F8) | — |
| `fakesite.artifacts.result_bytes` | `def result_bytes(job_id: str) -> bytes` | ≤20 | server + `flow` assertion (ONE owner, D-7) | must not use randomness; must not require Pillow to build |
| `fakesite.artifacts.fixture_hash` | `def fixture_hash(name: str) -> str` | ≤10 | `test_fakesite_unit` | must not recompute from a live page |
| `static/fake-arena.js` | `bootPage(config)` → `goto(state)`, `onFileChange`, `onPromptInput`, `onSendClick`, `onNewChat`, `report(evt)` | ≤260 LOC, ≤20 per func | the browser | must not read `Math.random()`; must not fetch anything outside the origin; must not start a second generation for a job already generating |
| `static/chat.html` | the §2 skeleton | ≤180 | `render_chat` | must not carry inline `<script>` logic beyond the config object |

### RED branch (14 tests, all browser-free — jsdom where node exists, else `skip` with reason)

| Test | Asserts | Expected RED at base |
|---|---|---|
| `test_fakesite_unit.py::test_server_starts_and_serves_chat` | `GET /image/direct` → 200, contains `textarea[name="message"]` | `ModuleNotFoundError: tests.e2e.fakesite` |
| `::test_control_routes_absent_without_flag` | `allow_control=False` ⇒ `/__test/scenario` 404 | routes missing entirely ⇒ 404 for both (test must fail on the *positive* half first) |
| `::test_refuses_foreign_host` | `Host: evil.example` ⇒ 403 | no guard yet |
| `::test_every_registry_selector_resolves` | for all 15 keys of `site_adapter.SELECTORS`: primary resolves in the fixture DOM; each fallback either resolves or is listed in `fixtures/known-fallback-gaps.json` | no fixture DOM yet |
| `::test_state_machine_walks_all_14_states` | driving `/__test/scenario` + the page's own transitions reaches every state and reports each to `/__test/log` in order | no state machine |
| `::test_send_is_counted_and_second_is_ignored` | `sendCount == 1` after two clicks while generating; second logged as `submit_ignored` | — |
| `::test_scenario_resolver_precedence` | control API > query > cookie > default (D-5) | — |
| `::test_scenario_survives_new_chat_navigation` | cookie keeps the scenario across the real navigation | — |
| `::test_result_bytes_are_deterministic_and_decode` | `result_bytes(j) == result_bytes(j)`, differs per job, PIL opens it, size 64×64 | — |
| `::test_hashes_match_fixtures_json` | the four fixture hashes equal `fixtures/hashes.json` | — |
| `::test_no_external_urls_in_static` | grep of `static/*` finds no `http(s)://` host and no protocol-relative URL; the only `.r2.cloudflarestorage.com` occurrence is a path segment (D-6) | — |
| `::test_error_and_rate_limit_toasts_match_page_error_patterns` | the two toast texts hit `match_page_error` / `is_rate_limit_error` and the dead-request text hits `match_dead_generation` | — |
| `::test_reverse_layout_is_the_default` | the fixture `ol` has `flex-col-reverse` (fixtures.md §7) | — |
| `::test_app_never_imports_fakesite` | no module under `app/` mentions `fakesite` (AST/grep over `app/`) | passes trivially — kept as the guard for §3.1 |

**Equivalence gate:** `pytest tests -q` unchanged elsewhere; `npm run test:js` unchanged (no `.mjs`
added in S1); `git diff --name-only -- app/` empty.

---

## S1a — capture ingest (owner-run, optional; D-23 / `record-replay.md`)

Sits between S1's fixture skeleton and the fixture freeze. It is the only stage whose *input* is
produced by a human (a HAR + DOM + probe-read-back capture of the real page), which is why it is
optional: without it the fixtures stay `synthesized` (D-15) and **L-17** stays open.

| Symbol | Signature | Size | Caller | Must-not |
|---|---|---:|---|---|
| `tools/har_ingest.py::load_capture` | `def load_capture(path: Path) -> Capture` | ≤20 | CLI | must not accept a capture from inside the repo tree (raw captures live in `arena webpages/captures/` or outside — I-43) |
| `::filter_entries` | `def filter_entries(cap: Capture, hosts: tuple[str, ...]) -> list[Entry]` | ≤20 | `main` | must drop everything outside the allowlist **before** any write |
| `::sanitize_entry` | `def sanitize_entry(e: Entry) -> Entry` | ≤20 | `filter_entries` | must call `app.services.captcha_recording.sanitize.safe_url/redact_text/clean_mapping` and `app.services.recording.sanitizer.redact_url` — **never a second redaction vocabulary** (RULE 21) |
| `::extract_artifacts` | `def extract_artifacts(entries: list[Entry], out: Path) -> Manifest` | ≤25 | `main` | must be a pure function of the inputs (no clock, no random) so re-runs give identical sha256s |
| `::assert_secret_free` | `def assert_secret_free(text: str) -> None` | ≤15 | `extract_artifacts` | must **fail closed** (raise, write nothing) on `Bearer `, `eyJ`, a ≥80-char token, `signature=`/`X-Amz-`, an e-mail shape |
| `::main` | `def main(argv: list[str]) -> int` | ≤20 | owner CLI | must never be wired into `pre_push_check.sh`; must print what it wrote and what it refused |

**RED branch (5 tests, browser-free).** `tests/e2e/test_har_ingest_unit.py`:
`::test_sanitize_matches_app_helpers` (a fixture entry with a signed CDN URL + a bearer header comes
out equal to `safe_url`/`redact_text` applied directly — proves one vocabulary),
`::test_ingest_is_deterministic` (same HAR twice ⇒ identical sha256 set),
`::test_host_allowlist_drops_everything_else`, `::test_secret_free_fails_closed` (nothing is written
when a token survives), `::test_shapes_keep_keys_not_values`. *Expected RED at base:*
`ModuleNotFoundError: tools.har_ingest` — then, once the module exists, `test_sanitize_matches_app_helpers`
fails first if the ingest re-implemented redaction instead of importing it (that is the point).

**Doc rows this stage owns:** `fixtures.md` §10 provenance column flips from `synthesized` to
`recorded:<capture-id>`; `record-replay.md` §9 priorities 1–3 get their capture ids; **L-17** is
closed and **L-16** is settled (both in `fixtures.md` §9).

## S2 — contract, evidence, clock (still browser-free)

| Symbol | Signature | Size | Caller | Must-not |
|---|---|---:|---|---|
| `contract.ScenarioExpectation` | `@dataclass name, lane_capabilities_required, pool_states, block_events, log_required, log_forbidden, image_status, image_error_prefix, output_rule, send_count, resubmit_count, page_trace_prefix, cooldown_total_rule, max_wall_ms` | ≤40 | `SCENARIOS` | must not contain lane `if`s (D-10) |
| `contract.SCENARIOS` | `dict[str, ScenarioExpectation]` (data, one row per scenario) | ≤170 | tests | must not duplicate a scenario per lane |
| `contract.assert_contract` | `def assert_contract(ev: Evidence, exp: ScenarioExpectation) -> None` | ≤25 | every e2e test | must not swallow a narrowed expectation (it goes into `ev.narrowed`) |
| `contract.output_rule` helpers | `def expect_saved(job_id) -> OutputRule` · `def expect_nothing() -> OutputRule` | ≤12 each | table | `expect_nothing` must assert **absence of every `*_AI*`**, not just the expected name (I-57) |
| `evidence.EvidenceBuilder` | `class EvidenceBuilder(scenario, lane, root)` + `.note_stage/.note_counts/.note_final/.write/ .copy_on_failure` | ≤90 LOC / ≤8 methods | flow + tests | must not log a raw credential/cookie; must not write outside `tmp_path`/`reports/e2e/` |
| `evidence.normalize_ids` | `def normalize_ids(payload: dict) -> dict` | ≤12 | `.write` | must reuse `CORR_RE` semantics (`tests/characterization/harness.py:33`), not a second regex |
| `clock.VirtualClock` | `class VirtualClock(step_sec: float = 75.0)` + `.monotonic()`, `async .sleep(sec)`, `.total` | ≤50 | `install_clock` | must not patch globally; must not advance on a real `sleep` it does not own |
| `clock.install_clock` | `def install_clock(monkeypatch, step_sec=75.0) -> VirtualClock` | ≤20 | `test_timeout_contract.py` only | **must patch exactly** `output_wait.time`, `output_wait.asyncio`, `output_wait_fallback.asyncio` (D-9 — 3 monotonic reads + 3 poll sleeps + 3 fixed 3 s sleeps, the whole clock surface of the wait path) |
| `clock.patched_namespaces` | `def patched_namespaces() -> tuple[str, ...]` | ≤6 | `test_clock.py` | must not be editable per test |

**RED branch (11 tests).** `test_contract_unit.py`: `::test_every_page_state_is_covered` (each of the
14 states appears in ≥1 scenario row), `::test_every_job_state_is_covered` (each `JobStatus` value
appears in ≥1 expectation), `::test_no_lane_specific_expectations` (AST scan of `contract.py` for
`lane ==`/`if lane`), `::test_output_rules_are_positive_and_negative` (every scenario has both),
`::test_scenario_names_match_fixtures` (the table's names equal the fixture scenarios — one owner).
`test_evidence.py`: `::test_bundle_schema_round_trip`, `::test_ids_normalized`,
`::test_copy_only_on_failure_or_env`, `::test_no_secret_keys_in_bundle`. `test_clock.py`:
`::test_patch_set_is_exactly_three_namespaces`, `::test_clock_advances_only_its_own_sleeps`.
*Expected RED at base:* `ImportError` on `tests.e2e.contract` / `.evidence` / `.clock`.

---

## S3 — app instance + flow + Chromium lane (the owner's 5 steps, first real job)

| Symbol | Signature | Size | Caller | Must-not |
|---|---|---:|---|---|
| `app_instance.build_app` | `def build_app(tmp: Path, lane: "Lane", *, watcher_on: bool = False) -> AppCtx` | ≤30 | `conftest.app` | must not monkeypatch any `app.browser`/`app.services` symbol (D-3, guarded by a test) |
| `app_instance.AppCtx` | `@dataclass bridge, recs, cfg, root, lane` | ≤15 | flow/tests | must not own assertions |
| `app_instance.wait_until` | `def wait_until(pred, timeout: float, *, poll=0.05, reason="") -> None` | ≤20 | flow | must raise with the **last observed state** in the message, never a bare assert (D-4) |
| `app_instance.configure_run` | `def configure_run(ctx, *, generation_timeout=60, cooldown=0, url_pattern="", stack=None) -> None` | ≤25 | flow | must use only existing slots/keys (`evidence.md` §5) |
| `flow.FlowCtx` | `@dataclass app, site, lane, ev, source_dir` | ≤15 | steps | — |
| `flow.detect_page` / `ensure_url_row` / `join_pool` / `scan_and_select` / `dispatch` / `await_job` / `settle` | one `def step(fc: FlowCtx) -> None` each, asserting internally | ≤25 each | `test_full_image_job` | must not skip an assertion when a step is "obviously" fine; must not reach into `pool._pages` for writes (reads only) |
| `flow.run_flow` | `def run_flow(fc, scenario: str) -> Evidence` | ≤20 | tests | must not branch per lane |
| `lanes.base.Lane` | protocol: `capabilities`, `async start(scenario)`, `async open_tab(url)`, `endpoint()`, `async screenshot(name)`, `async close_tab()`, `async stop()` | ≤80 | conftest | must not know about scenarios' expectations |
| `lanes.base.CdpEndpoint` | `@dataclass host: str, port: int, tab_id: str, ws_url: str` | ≤10 | app_instance | — |
| `lanes.base.LaneUnavailable` | `class LaneUnavailable(RuntimeError)` + `def reason(self)` | ≤20 | lane factories | the reason must name the **resolution order tried** (RULE 4) |
| `lanes.chromium.ChromiumLane` | `class ChromiumLane(site_url, profile_dir)` + `find_executable() -> str`, `async start()`, `read_devtools_port(profile) -> int` | ≤150 / ≤9 methods | registry | must not hard-code a port (uses `--remote-debugging-port=0` + `DevToolsActivePort`, D-13); must not reuse a profile dir |
| `lanes.registry` | `def make_lane(name: str, site_url: str, tmp: Path) -> Lane` | ≤20 | conftest | must skip loudly, never silently fall back to another lane |

**RED branch (9 tests).** `test_app_instance.py`: `::test_build_app_has_no_patched_browser_module`
(asserts `app.browser.cdp_arena.CDPArenaController` and `app.services.single_job_runner.find_and_click`
are the real objects), `::test_wait_until_reports_last_state`, `::test_configure_run_uses_real_slots`.
`test_chromium_lane.py` (skips with reason when no executable): `::test_find_executable_reason_lists_order`,
`::test_endpoint_serves_json_list`, `::test_open_tab_loads_the_fake_page`.
`test_full_image_job.py::test_full_job_success[chromium-success_immediate]` — **the first end-to-end
job in this repo's history**; *expected RED at base:* `LaneUnavailable`/`ImportError` before S3, then
during S3 development the honest failures move step by step (detect → url → pool → scan → dispatch →
save), each naming the step (that progression is the point of §5's per-step assertions).

---

## S4 — the six core scenarios (brief §6/§7/§8 behaviour)

No new infrastructure except table rows. `contract.SCENARIOS` gains `success_immediate`,
`success_delayed`, `layout_normal`, `generation_error_terminal`, `generation_error_dead_request`,
`generation_endless`; `test_full_image_job.py` parametrizes over them × `[chromium]`.

**RED branch (12 tests).** Per scenario: one flow test + one negative test
(`::test_no_output_file_for_<scenario>`, `::test_send_count_is_<n>_for_<scenario>`).
*Expected RED at base (S3 green):* the scenario rows do not exist ⇒ `KeyError` in `SCENARIOS`; after
adding rows, the page-side flags (`endless`, `error_text`, `layout`) are unimplemented ⇒ the page
trace assertion fails first (that is the intended RED order: contract before page).

Key expectations pinned here (from `evidence.md`):
`⏳ Generating Response A spinner visible` (`output_wait.py:57-63`), `❌ JOB-ID mismatch …` never
appears in success, `Page error: Generation failed` prefix for the terminal error, `sendCount == 2`
**only** for the dead-request toast (D-18/L-14), and `⚠ Completed with warnings` never appears when
a required block failed (I-38).

---

## S5 — recovery, the 300 s contract, result/save edge scenarios

| Symbol | Signature | Size | Caller | Must-not |
|---|---|---:|---|---|
| `test_recovery_and_reset.py::test_endless_then_next_job_succeeds` | lane × `[chromium]` | ≤60 | — | must run **both** jobs in one test (the recovery is the subject) |
| `test_recovery_and_reset.py::test_new_chat_reset_failure_is_not_fatal` | — | ≤40 | — | must assert the log line `↩ New-chat reset failed:` and that the cooldown still starts |
| `test_timeout_contract.py::test_generation_timeout_300_configuration` | — | ≤45 | — | must assert settings + block-status text + overlay `timeout_sec` (D-8 part 2), not only the settings value |
| `test_timeout_contract.py::test_timeout_fires_at_300_under_virtual_clock` | — | ≤50 | — | must install the clock via `clock.install_clock` **only**; must assert `Timeout after 300000ms` |
| `test_timeout_contract.py::test_success_within_budget` | — | ≤35 | — | asserts `wall_ms <= generation_timeout_ms` for the success scenario (the owner's "within 300 sec") |
| `flow.save_edge_cases` helpers | `def precreate_output(fc) -> Path`, `def make_readonly(fc) -> None` | ≤15 each | S5 tests | must restore permissions in a finalizer (never leave an unreadable tmp dir) |

**RED branch (10 tests)** — the five above plus `result_is_old`, `result_invalid_image`,
`download_returns_html`, `output_name_exists`, `result_after_timeout`. *Expected RED:* contract rows
missing ⇒ `KeyError`; then the page flags unimplemented ⇒ page-trace mismatch; then the app-side
expectation (e.g. `_AI_2` naming) proves the production rule (RULE 23) rather than a new one.

---

## S6 — Firefox lane (+ jsdom fallback): the same contract, second browser

| Symbol | Signature | Size | Caller | Must-not |
|---|---|---:|---|---|
| `lanes.cdp_adapter.CdpAdapter` | `class CdpAdapter(driver, tabs)` + `async start() -> CdpEndpoint`, `stop()` | ≤90 / ≤8 | `FirefoxLane`, `JsdomLane` | must not translate anything outside the 8 families (`evidence.md` §2); must not swallow a JS exception into a transport error (I-36 kind fidelity) |
| `cdp_adapter.METHODS` | table `{"Runtime.evaluate": _evaluate, "DOM.getDocument": _document, …}` (dispatch by table, not if/elif — RULE 19 step 2) | ≤40 | `CdpAdapter` | must not grow a per-caller special case |
| `cdp_adapter.NodeTable` | `class NodeTable` + `register(handle) -> int`, `get(nid)`, `clear()` | ≤45 | `_query_selector`, `_set_files` | must return `0` for "not found" (the attach loop's contract); must clear on navigation |
| `cdp_adapter.discovery_server` | `def discovery_server(tabs) -> ThreadingHTTPServer` (reuses the `tests/fakes/cdp_stub_server.py:78-129` skeleton) | ≤40 | `CdpAdapter` | must serve `/json/list` **and** `/json/version` (A1/A2) |
| `lanes.firefox.FirefoxLane` | `class FirefoxLane(site_url, profile_dir)` + `async start()`, `async open_tab()`, `async set_files_via_adapter()` | ≤130 | registry | must import `playwright` lazily; must hold the serial lock (D-22) |
| `lanes.jsdom.JsdomLane` | `class JsdomLane(site_url, tmp)` + `start_sidecar()` | ≤110 | registry | must narrow `screenshot`/`fetch_bytes`/`canvas` capabilities **loudly** (D-14) |
| `tests/js/e2e/layout-shim.mjs` | `installLayoutShim(window)` | ≤120 | sidecar | must not fake `fetch` bytes (that capability stays narrowed) |
| `tests/js/e2e/jsdom_cdp_server.mjs` | the sidecar entry | ≤180 | `JsdomLane` | must be listed in `package.json test:js` (L-7 trap) |
| `tests/e2e/test_adapter_contract.py` | 8-family contract test against a fixture page | ≤150 | — | must fail when a reply shape drifts from `evidence.md` §2 (this is the adapter's own RULE 8) |

**RED branch (13 tests).** `test_adapter_contract.py`: one test per family (A1, A2, A5, A6 ok,
A6 js-exception → kind `js`, A6 protocol-error → kind `protocol`, A7 ×4, A8) + `::test_node_ids_reset_on_navigation`.
`test_full_image_job.py`: the six S4 scenarios × `[firefox]` (parametrization only — **no new
assertions**, which is the proof of D-10). `::test_jsdom_narrows_capabilities`.
*Expected RED:* `LaneUnavailable("firefox: playwright not installed …")` before the lane exists; then
adapter reply-shape mismatches (e.g. `nodeId: 0` vs missing key) fail the contract test before any
scenario runs — the intended order.

---

## S7 — operator, captcha and tab-loss scenarios + matrix completion

| Symbol | Signature | Size | Must-not |
|---|---|---:|---|
| `flow.operator_levers` | `def pause(fc)`, `def stop_after(fc)`, `def cancel(fc)`, `def abort_tab(fc)` | ≤12 each | must call the real slots (`pause_run:250`, `stop_after_current:266`, `cancel_current:274`, `stop_tab_job`) and never set the private flags directly |
| `test_operator_scenarios.py` | 4 tests × lanes | ≤180 | must assert RULE 7 (the wait exits promptly, `cancelled` ≠ `failed`) |
| `test_captcha_scenarios.py` | `captcha_before_submit`, `captcha_during_generation` (Watcher **ON**) + `watcher_off_zero_activity` (OFF) | ≤160 | must not solve anything (RULE 20/I-34); must assert the pause is charged + capped (I-47) |
| `test_tab_loss.py` | `tab_closed_mid_job` (Chromium/Firefox) | ≤90 | must assert I-36 recovery-or-honest-failure, and that no second click is dispatched |
| `coverage-matrix.md` completion | doc | ≤170 | must list every state → test id, no "covered implicitly" rows |

**RED branch (9 tests)**, one per scenario above, plus `::test_watcher_off_produces_zero_captcha_lines`
(counting test, the D-23 pattern from `tests/test_watcher_off_zero_activity.py`).

---

## §A Frozen app-side seams the suite may use (and the test that pins each)

| Seam | Entry | Pinned by |
|---|---|---|
| Slot surface (135 slots) | `tests/test_bridge_slots.py` (exact match) | unchanged — the suite adds **no** slot |
| Signals | `Recorder` swap (`harness.py:94-103`) | `test_app_instance.py::test_recorders_replace_signals` |
| Selector registry | `app/browser/probe_selectors.py` (read-only import) | `test_fakesite_unit.py::test_every_registry_selector_resolves` |
| Page-error vocabulary | `app/utils/page_errors.py:15-66` | `::test_error_and_rate_limit_toasts_match_page_error_patterns` |
| Generation timeout knob | `app_settings.apply_generation_timeout:72-84` | `test_timeout_contract.py::test_generation_timeout_300_configuration` |
| Wait arithmetic | `output_wait._check_timeout:160-176`, `PollSpec` (`cdp_arena/output.py:187`) | `test_clock.py::test_patch_set_is_exactly_three_namespaces` |
| Revival budget | `app/services/captcha/recovery.py:27-28,130-162` | `test_full_image_job.py::test_send_count_is_2_for_dead_request` |
| Post-job reset | `cooldown_service.finish_page_after_job:637` → `new_chat.reset_to_new_chat:183` | `test_recovery_and_reset.py` |
| Run gate | `run_control.check_start_ready:85-96`, `run_state.batch_active:133` | `flow.dispatch` asserts the refusal texts |

## §B Proof that zero production change is enough

Every need → an existing knob (`evidence.md` §5): timeout (`save_settings` / block `timeout_ms`),
CDP endpoint (`cdp_host`/`cdp_port`), URL matching (`url_pattern`), cooldown (`cooldown_min_seconds=0`),
stack (`config.set_state(action_blocks=…)`), Watcher (`watcher_enabled`), signals (replaceable
attributes), headless Qt (`qt_compat` dummies), async driver (the bridge's own bg loop). The three
things that would have needed a production seam — an injectable poll interval (L-12), a clock
(D-9), a readiness-probing `test_url` (L-10) — are handled by patching the **test-visible** module
namespace, by measuring instead of injecting, and by asserting current behaviour respectively.

## §C Test ledger (planned)

| Group | Files | Tests | Lane |
|---|---:|---:|---|
| browser-free infra | 6 (`test_fakesite_unit`, `test_contract_unit`, `test_evidence`, `test_clock`, `test_markers`, `test_har_ingest_unit`) | ~47 | none |
| adapter contract | 1 | 13 | none (in-process) |
| global flow | 1 × (6 scenarios × 3 lanes) | 18 | chromium/firefox/jsdom |
| recovery + timeout | 2 | 10 | chromium (+firefox for 4) |
| result/save edges | 1 | 10 | chromium |
| operator/captcha/tab-loss | 3 | 9 | chromium + firefox |
| **total** | **14** | **~107** | |

## §D Anti-gaming rules for this chain

1. A stage may not edit another stage's files (S4 adds table rows, never flow steps).
2. A RED test may not be weakened to pass: the predicted failure is recorded in the stage commit
   message; a different failure means redesign, not `xfail`.
3. No scenario is added without a `contract.py` row **and** a `coverage-matrix.md` row.
4. No lane may get its own expectation table (D-10) — the S6 Firefox tests are parametrization-only,
   which is checkable by diff.
5. No `app/` edit, ever, in this chain (D-20/§B). A stage that needs one stops and files an L-defect.
