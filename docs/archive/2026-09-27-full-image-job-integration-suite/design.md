# Design — Full Image-Job Integration Suite (PLAN ONLY, no production code)

Companion to `evidence.md` (what exists, with `file:line`), `fixtures.md` (the fake pages),
`quality-budget.md` (RULE 16/18 numbers), `tdd-interfaces.md` (per-stage interfaces + RED-first
tests), `coverage-matrix.md` (state → test matrix). Written at `02e0240`, 2026-09-27.

---

## 0. How to read this plan

* One **global behaviour test** per (scenario × lane). Each test runs the *whole* app pipeline —
  detect page → URL row → pool join → scan/select → dispatch → attach → prompt → submit → wait →
  download → validate → save → reset → cooldown — against a deterministic fake page. Steps are
  asserted **in order inside one test**, never split into 16 tests that would each test the
  harness instead of the app (RULE 8).
* Three layers stay separate (§3.4): unit (exists), component/contract (exists: goldens +
  `FakeCtrl`), and this new **full application integration** layer. The new layer replaces
  nothing; it is the only place where the three frozen contracts in `evidence.md` §2–§4 meet.
* Staged: S0…S7 (§13), each stage separately committable, gate-green and useful on its own.
* Test-only: **no file under `app/` changes** (D-20). If a stage discovers it needs one, it stops
  and files a defect (L-n) instead.

---

## 1. Contract — one sentence per deliverable

| # | Deliverable | One-sentence contract |
|---|---|---|
| 1 | Fake site (`tests/e2e/fakesite/`) | A local HTTP server + hand-rebuilt interactive HTML/JS that reproduces the arena.ai page contract of `app/browser/site_adapter.py` and can be driven into every state in `fixtures.md` §3 deterministically, with no external network, no credentials and no live service. |
| 2 | Page state machine + scenario schema | 14 explicit states, transitions chosen by a scenario name resolved from a test-only control endpoint / query / cookie, and every transition reported by the page to a server-side event log the test can assert on. |
| 3 | Sanitized fixtures | 10 saved-state fixtures rebuilt from `docs/research/Directly Chat….html` + `docs/current/DOM_SELECTORS.md`, secrets/personal data removed, external assets localized, selectors kept byte-identical to the registry. |
| 4 | Shared browser behaviour contract (`tests/e2e/contract.py`) | One lane-independent table of expected pool statuses, block statuses, log markers, queue outcome, output-file outcome, submit count and page-state trace per scenario — the same expectations are asserted on Chromium, Firefox and jsdom. |
| 5 | Chromium lane | Real Chromium launched with `--remote-debugging-port=0`, so the app speaks **native CDP** with zero translation. |
| 6 | Firefox lane | Real Firefox behind a CDP-shaped adapter (Playwright + a websocket server implementing the 8-family surface of `evidence.md` §2), so the *same* app code path runs unchanged. |
| 7 | jsdom fallback lane | The same fake page in jsdom behind the same adapter shape + a deterministic layout shim, for machines with no browser; never the only lane for a scenario. |
| 8 | Test clock / timeout control | A virtual clock installed **only** in the two modules that own the wait arithmetic, letting the production 300 s configuration be proven in milliseconds, next to fast tests that inject a short `timeout_ms`. |
| 9 | Failure artifact / report format | One JSON evidence bundle per test (scenario, lane, ids, ordered transitions, action counts, timings, final states, output path/size/dims/sha256, safe logs) + screenshot on failure where the lane supports it. |
| 10 | Docs for local + CI execution | `tests/e2e/README.md`: how to install browsers, which markers run what, what skips mean, how to read an evidence bundle. |
| 11 | Coverage matrix | `coverage-matrix.md`: every page state and every job state mapped to the tests that prove it, plus the brief's §6/§7/§8/§9 checklists line by line. |

---

## 2. Decisions (D-1…D-22) with rejected alternatives

### D-1 Lane topology — three lanes, one protocol, Chromium default
`Lane` is a small protocol (`tests/e2e/lanes/base.py`): `capabilities`, `async start(scenario)`,
`async open_tab(url) -> TabHandle`, `endpoint() -> CdpEndpoint(host, port)`, `async screenshot()`,
`async stop()`. Implementations: `ChromiumLane` (default), `FirefoxLane`, `JsdomLane`.
*Rejected:* (a) a production `BrowserLane` abstraction inside `app/browser/` — owner chose
test-side; it would also touch the frozen hotspots `CDPArenaController`/`Bridge` (RULE 16.5).
(b) jsdom-only default — owner chose real Chromium; jsdom cannot prove `fetch`/canvas/blob/layout.
(c) attaching to the user's already-running Chrome on 9222 (`start-arena-chrome.bat`) — kept as a
manual debug override (`ARENA_TEST_CDP_PORT`), never the suite's default: it breaks isolation
(§11) and makes results depend on the user's tabs.

### D-2 One global test per (scenario × lane)
`tests/e2e/test_full_image_job.py` is parametrized `lane × scenario`; the scenario table lives in
`contract.py`. A test = `arrange(scenario) → run_flow() → assert_contract(scenario)`.
*Rejected:* one test per pipeline step (proves the harness, not the app); one mega-test that loops
all scenarios internally (a failure hides which scenario broke, and pytest cannot report per
scenario).

### D-3 The app instance is the real app, wired like `tests/characterization`
`tests/e2e/app_instance.py::build_app(tmp_path, lane, scenario)` returns a real
`Bridge(config_manager=ConfigManager(tmp/cfg), state_path=tmp/arena.json,
cdp_client=CDPClient(host=lane.host, port=lane.port))` with real `PagePool`, real bg loop,
real action-block stack from `config.set_state(action_blocks=…)`, and `Recorder` signals.
**Nothing under `app/browser` or `app/services` is monkeypatched** — no `FakeCtrl`, no
`install_patches`, no patched `find_and_click`: the visual runner really runs its JS in the page.
*Rejected:* reusing `tests/characterization/fakes.install_patches` — that is the component lane;
here it would delete the thing under test (RULE 8, `evidence.md` §6).

### D-4 The driver is synchronous + deadline polling
E2E tests are plain `def test_…` functions. All app async work happens on the bridge's own daemon
loop (`app/services/run_state.py:83-131`), so the test drives slots and waits with
`wait_until(pred, timeout, poll=0.05, reason=…)`, which on timeout raises with the last observed
state (never a bare `assert False`). `pytest-asyncio` stays `auto` but is not used here.
*Rejected:* `async def` tests — the test's loop and the bridge's loop would be different loops;
every await would need `run_coroutine_threadsafe`, adding a second source of races and making
timeouts unattributable (L-15 shows the scan already completes on a worker thread).

### D-5 Scenario control — one resolver, four inputs, test-only by construction
Precedence: `POST /__test/scenario` (control API) → `?scenario=` (query) → cookie
`arena_fake_scenario` (survives the New Chat navigation) → default `success_immediate`. The
server binds `127.0.0.1` only, and the control routes exist only when it was constructed with
`allow_control=True` (always, in `tests/`); the fake site lives under `tests/` and is never
importable from `app/`, so "disabled outside the test environment" is structural, not a flag.
*Rejected:* per-test fixture files (cannot change mid-test, e.g. the recovery job); query only
(lost on navigation).

### D-6 The fake CDN is a **path segment** on the local origin
Result images are served at `http://127.0.0.1:<port>/cdn/.r2.cloudflarestorage.com/<job-id>.png`.
`img.src` resolves to an absolute URL that contains the literal `.r2.cloudflarestorage.com/`, so
the **primary** output selector (`site_adapter.py:167`) matches and the 13 fallbacks stay unused;
the request is same-origin, so `fetch(url,{credentials:'include',mode:'cors'})` in
`JS_DOWNLOAD_IMAGE` succeeds with no preflight and the Python `urllib` fallback works too.
*Rejected:* HTTPS with a self-signed cert (trust prompts, per-lane flags, non-determinism);
`/etc/hosts` alias (needs root); letting the probe fall back to `main img` (would silently stop
testing the primary selector — RULE 21 evidence lost).

### D-7 Result bytes are a deterministic function of the job id
`fakesite/artifacts.py::result_bytes(job_id)` = committed base PNG
(`tests/e2e/fixtures/result-base.png`, 64×64, sha256 recorded in `fixtures.md` §5) + one PNG
`tEXt` chunk `arena-job-id=<job_id>` inserted before `IEND`. The test computes the same bytes and
asserts `sha256(saved_file) == sha256(expected)` — proof the app saved *this job's* image
(brief §5), not a name coincidence. The page also always carries an **older baseline image**
(`fixtures/baseline-old.png`, 32×32, different bytes) that must never be accepted.
*Rejected:* identical bytes for every job (cannot prove correlation); random bytes per run
(no expected value to assert); serving the source image back (indistinguishable from the
`result_is_old` failure mode).

### D-8 The 300-second contract has two parts (and one opt-in soak)
1. **Behaviour (fast, every lane):** `WAIT_OUTPUT.timeout_ms = 6000` injected through the real
   block stack (`single_job_runner.py:493`) + scenario `generation_endless` ⇒ job fails with
   `Timeout after 6000ms`, no output file, page reset, next job succeeds.
2. **Production configuration (fast, virtual clock):** `save_settings({"generation_timeout":300})`
   ⇒ assert `state.settings.timeouts["generation"] == 300`,
   `config.get_state("watcher_generation_timeout_sec") == 300`, the block-status line
   `Waiting for generation — timeout 300000ms` (`single_job_runner.py:494`), the overlay's
   `timeout_sec=300` (`_show_gen_overlay:322-330`), and — with the clock advanced — that the wait
   ends at 300 s with `Timeout after 300000ms`.
3. **Soak (opt-in `-m e2e_slow`, Chromium only, one test):** the real 300 s wait, off by default.
Every success test additionally measures wall time around the job and asserts
`elapsed <= generation_timeout` and records it in the evidence (`coverage-matrix.md` S-1 row 5e).
*Rejected:* actually waiting 300 s in the default suite (brief §8 forbids it); asserting only the
settings value (would pass with the wait loop deleted).

### D-9 Virtual clock — three patched namespaces in two modules, asserted
`tests/e2e/clock.py::VirtualClock` is installed by `monkeypatch.setattr` on exactly
`app.browser.output_wait.time`, `app.browser.output_wait.asyncio`,
`app.browser.output_wait_fallback.asyncio` — the two modules that own the wait arithmetic
(`output_wait.py:161,193,200` read `time.monotonic()`; `:115,182,221` sleep on `spec.poll_interval`;
`output_wait_fallback.py:69,75,103` sleep the fixed 3 s recheck delays — 3 + 3 + 3 call sites,
nothing else in the wait path touches a clock). `monotonic()` advances by a
configured step per `sleep()`, so a 300 s wait costs ~4 real polls. A dedicated test asserts the
patch set is exactly those three namespaces (so the clock can never silently widen), and the clock
is never installed while a real browser websocket is in flight elsewhere (the CDP transport keeps
real `asyncio`).
*Rejected:* `freezegun`/global patching (breaks websockets heartbeats and the browser);
a production clock seam (D-20 forbids `app/` changes); patching `PollSpec.poll_interval`
(L-12: it is hard-coded inside `_run_wait`, so patching it means patching `cdp_arena/output.py`
too — one more namespace than the arithmetic needs).

### D-10 One shared behaviour contract, capabilities narrow it explicitly
`contract.py::SCENARIOS[scenario] = ScenarioExpectation(...)` holds: ordered pool statuses,
ordered `(block_id, status)` pairs, required log markers, forbidden log markers, final image
status/error, output-file expectation (name + bytes rule), `sendCount`, page-state trace prefix,
cooldown expectation, and the max wall time. A lane declares capabilities
(`layout`, `file_upload`, `fetch_bytes`, `canvas`, `screenshot`, `navigation`); an expectation
that needs a missing capability is **reported as narrowed** in the evidence, never silently
dropped.
*Rejected:* per-lane assertion copies (drift is the whole risk the brief §11 names).

### D-11 Evidence bundle — one JSON per test, artifacts only on request
`tests/e2e/evidence.py` writes into the test's `tmp_path`: `evidence.json` (schema in §10),
`page-trace.json` (from `GET /__test/log`), `app-log.txt` (recorder dump), `cdp-methods.json`
(counts per CDP family), and `failure-<n>.png` when the lane supports screenshots. Copies into
`reports/e2e/<test-id>/` only on failure or `ARENA_E2E_ARTIFACTS=1`; `.gitignore` gains
`reports/e2e/`.
*Rejected:* committing artifacts (I-43 hygiene); asserting on log text alone (the page's own trace
is independent evidence — D-17).

### D-12 Firefox lane = Playwright Firefox behind a CDP-shaped adapter
`tests/e2e/lanes/cdp_adapter.py` is a `websockets` server + `ThreadingHTTPServer` that presents
A1/A2 (`/json/list`, `/json/version`) and one `/devtools/page/<id>` per tab, translating the
A5–A8 families to Playwright calls:

| App sends | Adapter does | Reply |
|---|---|---|
| `Runtime.evaluate {expression, returnByValue, awaitPromise}` | `page.evaluate(expression)` | `{result:{result:{value}}}`; a JS throw → `{result:{exceptionDetails:{exception:{description}}}}` so `transport._decode_reply` reports kind `js` (I-36), never a swallowed `None` |
| `DOM.getDocument {depth:0}` | no round-trip | `{result:{root:{nodeId:1}}}` |
| `DOM.querySelector {nodeId, selector}` | `page.query_selector(selector)` → register handle | `{result:{nodeId:n}}`, `0` when not found (the attach loop's contract, `cdp/dom.py:79-84`) |
| `DOM.querySelectorAll` | `page.query_selector_all` | `{result:{nodeIds:[…]}}` |
| `DOM.setFileInputFiles {nodeId, files}` | `handle.set_input_files(files)` — **real Firefox upload** | `{result:{}}` |
| `Page.reload {}` | `page.reload()` | `{result:{}}` |
| `Page/DOM/Runtime/Network.enable` | no-op | `{result:{}}` |

Node ids are per-session monotonic ints in a `{id: ElementHandle}` map, dropped on navigation
(the app re-queries the document every attach). Playwright is already a declared dependency
(`requirements.txt:2`) and gives one API for both browsers.
*Rejected:* geckodriver/Marionette (a second binary + protocol; `set_input_files` semantics differ);
Firefox's own CDP endpoint (removed upstream, gone in every supported release); Selenium BiDi
(no stable `setFiles` surface); driving Firefox from Node (splits the suite across two runtimes).

### D-13 Chromium lane = a real browser speaking native CDP
`tests/e2e/lanes/chromium.py` spawns the executable — resolution order `ARENA_TEST_CHROME` →
`playwright.chromium.executable_path` → `google-chrome`/`chromium`/`chrome.exe` → **skip loudly**
— with `--remote-debugging-port=0 --user-data-dir=<tmp> --headless=new --no-first-run
--no-default-browser-check --disable-gpu --disable-dev-shm-usage --remote-allow-origins=*
--window-size=1440,900`, then reads `<user-data-dir>/DevToolsActivePort` for the port. No adapter
is in the path: the app connects to Chrome exactly as in production.
*Rejected:* `playwright.chromium.launch()` (owns the CDP endpoint itself and does not expose the
browser-level `/json/list` the app's discovery needs); `launch_persistent_context` + a fixed port
(port collisions under xdist).

### D-14 jsdom fallback lane (Stage S6, optional)
`tests/js/e2e/jsdom_cdp_server.mjs` serves the same adapter shape over the same fake page, with a
**layout shim** (`tests/js/e2e/layout-shim.mjs`, ~120 LOC): `offsetParent` non-null unless inside
`[hidden]`/`.hidden`/`display:none`; `getBoundingClientRect()` from a document-order vertical flow
(80 px per block, so "below the prompt" geometry holds); `naturalWidth/Height/complete` from the
`data-w`/`data-h` attributes the fake page always writes; `getComputedStyle().opacity` = `1`.
Rule: a scenario that passes **only** in jsdom is reported as unproven (D-10 narrowing), because
jsdom cannot prove `fetch` bytes, canvas fallback or real navigation.
*Rejected:* making it the default (owner chose real Chromium); skipping it entirely (CI boxes with
no browser would then run zero page-level tests — RULE 4 wants a loud, useful fallback).

### D-15 Fixtures are rebuilt **from recorded evidence**, never served verbatim *(amended 2026-09-27 by D-23)*
The 10 fixtures in `fixtures.md` §1 are hand-rebuilt interactive HTML (~300 lines total) derived
from the committed saved page + `DOM_SELECTORS.md` **plus the recorded captures of
`record-replay.md` §9** (each fixture row carries a provenance: `committed-dump` /
`recorded:<capture-id>` / `synthesized`); the owner's local `arena webpages/state*`
dumps and raw captures are read at design time only and never committed (I-43,
`tests/test_repo_hygiene.py`).
One skip-gated cross-check (`tests/js/test_e2e_fixtures_vs_saved_page.mjs`, modelled on
`tests/js/test_captcha_saved_page.mjs`) re-runs the real probes against the dumps **when present**
and asserts the rebuilt fixtures agree on the selector facts that matter.
*Rejected:* serving the saved dumps verbatim (account e-mails, external scripts, no state machine,
386 KB each × 10); screenshots as page implementation (brief §4 forbids it).

### D-16 The fake site is one small Python package under `tests/`
`tests/e2e/fakesite/` = `server.py` (routes + per-test state + request log), `pages.py` (HTML
assembly from the static template), `artifacts.py` (PNG fixtures + `result_bytes`),
`static/fake-arena.js` (the state machine), `static/fake-arena.css`, `static/chat.html`.
`ThreadingHTTPServer` on `127.0.0.1:0`; no external asset, no font, no analytics (brief §1).
*Rejected:* a Node/Express server (splits the runtime for the two browser lanes); reusing
`tests/fakes/cdp_stub_server.py` (that is the CDP side, not the page side — but its HTTP skeleton
is reused for the adapter's discovery surface).

### D-17 The page owns its state machine and reports it
`static/fake-arena.js` performs the transitions with the scenario's timings and `POST`s each one
to `/__test/event` (`{t, from, to, trigger, detail}`); the server appends to a per-session log
served at `GET /__test/log`. The test asserts the **ordered transition list** and the **submit
count** from the page's own point of view — independent of the app's logs (brief §13: assert both
positive and negative behaviour).
*Rejected:* inferring page states from the app's log (circular: a broken probe would produce a
plausible-looking trace).

### D-18 Submit-count contract is per scenario, not a blanket "once"
L-14: the dead-generation toast and the spinner-loss signature arm **one** bounded resubmit
(`app/services/captcha/recovery.py:27-28,130-162`, armed at `single_job_runner.py:266`). So:
`sendCount == 1` for success, endless/timeout, terminal page error, upload-rejected,
send-disabled; `sendCount == 2` for `generation_error_dead_request` and `spinner_lost_no_output`
(one revival, never three); `sendCount == 0` for `submit_ignored`/`captcha_before_submit`.
The page distinguishes the first Send from a revival in its event log (`trigger: "send"` vs
`"resubmit"`), and refuses to start a second generation for a job that is already generating.
*Rejected:* asserting `sendCount == 1` everywhere (would fail on real, intended behaviour);
disabling revival in tests (would delete a production path from coverage).

### D-19 Markers and lanes policy — the default push budget is untouched
New markers in `pytest.ini`: `e2e_browser` (needs a real browser), `e2e_desktop` (needs a visible
desktop — reserved, nothing uses it yet), `e2e_slow` (the real 300 s soak). `conftest.py`'s
auto-marker gains: `tests/e2e/**` → `e2e` + `e2e_browser` (except `test_fakesite_unit.py`,
`test_contract_unit.py`, `test_clock.py`, which are `unit` and browser-free). Default
`pytest tests -q` therefore **skips** every browser test with a loud reason; `bash tools/e2e_check.sh`
(new, ~40 lines) runs `-m e2e_browser` then `-m e2e_slow` when asked. Missing browser ⇒ `skip`
with the resolution order in the reason (RULE 4).
*Rejected:* running browser tests by default (breaks the 3-minute push budget and CI boxes with no
browser); hiding them behind an env var only (invisible = unrun, the L-7 defect class).

### D-20 Zero production change — the seam list is closed
Every knob used is listed in `evidence.md` §5. A stage that needs an `app/` change stops and files
a defect. Two consequences accepted deliberately: the poll interval stays 2 s (L-12) and
`test_url` stays a stub (L-10) — the suite asserts what exists.
*Rejected:* "small" production seams (a clock parameter, an injectable poll interval) — the owner
chose test-only, and each seam would need its own RULE 16 budget + tests.

### D-21 Naming, ids and determinism
Fixture job ids come from the real `generate_correlation_id()`; the evidence normalizes them with
the golden harness's `CORR_RE` (`tests/characterization/harness.py:33`) so bundles are comparable.
Fake-site session ids are `s<port>-<n>`; temp roots are `tmp_path`-only; output names follow the
production rule (`<base>_AI.png`, `<base>_AI_2.png` …) and are never invented by the test.
*Rejected:* fixed job ids (would hide correlation bugs — RULE 22 is the point of the exercise).

### D-22 Firefox serialization
Firefox lane tests run one at a time (`@pytest.mark.serial`, `--dist loadgroup` under xdist) and
each owns its profile dir and port; the adapter refuses to start a second instance while one holds
the lock file. Chromium lanes may run in parallel (one browser per test, own user-data-dir).
*Rejected:* parallel Firefox (profile lock contention is the classic flake source the brief §11
warns about).

### D-23 HAR-first fixture provenance *(added 2026-09-27 — research round)*
Fixture **evidence** is captured as **HAR 1.2** (bytes + response shapes) with the browser's own
sanitized DevTools export or Playwright's built-in HAR recorder, plus the repo's existing sanitized
DOM-snapshot recorder for structure; a small owner-run ingest (`tools/har_ingest.py`, S1a) reduces a
capture to sanitized artifacts under `tests/e2e/fixtures/recorded/` (result-image bytes + sha256,
API shape skeletons, probe read-backs, element facts). **Replay stays with the fake-site server of
D-16/D-17** — HAR is passive and cannot own a state machine. Full research, the scored comparison,
the rejected candidates (Polly.js, WireMock, Mountebank, Nock, Cypress, BrowserMob, Percy/Chromatic,
Mocky), the capture instructions and the ethics/rules: **`record-replay.md`**.
This closes **L-17** (real result bytes + the real `.r2.cloudflarestorage.com/` URL shape) and
settles **L-16** with a fact (the recorded New Chat `href`).
*Rejected:* a service virtualizer (WireMock/Mountebank — JVM/Node runtime, and it would pull
behaviour out of the page against D-17); in-page interception (Polly.js — a JS app under test, which
this is not); Playwright `route_from_har` as the replay engine inside the app-driven lane
(`connect_over_cdp` is lower fidelity, cannot record on an existing context, and does not support
`page.route()` interception — it survives only as an optional S6 asset-fidelity check in a
Playwright-owned context); mitmproxy as the primary recorder (machine-wide CA for something DevTools
does with zero install).

---

## 3. Architecture

### 3.1 New tree (all under `tests/`, out of RULE 16 size scope, inside RULE 18 ideals)

```
tests/e2e/
  README.md                 how to run locally + in CI, what skips mean, evidence format   (~120)
  __init__.py
  app_instance.py           real Bridge builder + Recorder signals + wait_until driver     (~180)
  flow.py                   the 16-step flow: detect → url → pool → scan → select → run    (~200)
  contract.py               SCENARIOS table + ScenarioExpectation + assert_contract        (~260)
  evidence.py               EvidenceBuilder: bundle schema, normalization, artifact copy   (~180)
  clock.py                  VirtualClock + install_clock (3 namespaces, asserted)          (~90)
  conftest.py               fixtures: fake_site, lane(params), app, source_folder, evidence(~200)
  fakesite/
    __init__.py
    server.py               routes, per-session state, event log, control API              (~230)
    pages.py                HTML assembly + sanitization guard                             (~120)
    artifacts.py            PNG fixtures, result_bytes(job_id), hashes                     (~110)
    static/chat.html        the page skeleton (all contract elements)                      (~180)
    static/fake-arena.js    the state machine + event reporting                            (~260)
    static/fake-arena.css   visibility rules the probes depend on                          (~80)
  lanes/
    __init__.py             lane registry + capability table + resolution/skip reasons     (~90)
    base.py                 Lane protocol, CdpEndpoint, TabHandle, LaneUnavailable         (~80)
    chromium.py             spawn + DevToolsActivePort + open_tab + screenshot             (~150)
    firefox.py              Playwright Firefox + adapter wiring                            (~130)
    cdp_adapter.py          the 8-family CDP translation (used by firefox, reused by jsdom)(~240)
    jsdom.py                Node sidecar control + capability narrowing                    (~110)
  fixtures/
    result-base.png  baseline-old.png  source-1.png  source-2.png  hashes.json             (tiny)
  test_full_image_job.py    the global test: lane × scenario parametrization               (~160)
  test_recovery_and_reset.py  endless → reset → next job succeeds; New Chat failure        (~140)
  test_timeout_contract.py  the two-part 300 s contract + virtual clock                    (~150)
  test_fakesite_unit.py     state machine + scenario resolver + artifacts (browser-free)   (~180)
  test_contract_unit.py     the contract table is complete for every state (browser-free)  (~120)
  test_clock.py             the clock patches exactly 3 namespaces (browser-free)          (~70)
tests/js/e2e/
  jsdom_cdp_server.mjs      jsdom lane server                                              (~180)
  layout-shim.mjs           deterministic geometry for the probes                          (~120)
  test_e2e_fixtures_vs_saved_page.mjs  skip-gated cross-check vs the owner's dumps         (~90)
tools/e2e_check.sh          marker-driven runner + artifact switch                         (~40)
```

Import direction inside the suite: `test_* → flow/app_instance/contract/evidence/clock →
lanes → fakesite`. `lanes/*` and `fakesite/*` never import each other; only `conftest.py` knows
both. Nothing in `tests/e2e/` is imported from `app/` (guard test in `test_contract_unit.py`).

### 3.2 Runtime picture (one test, Chromium lane)

```
pytest (sync test)
  ├─ fakesite.server  ── 127.0.0.1:<P1>   chat.html + fake-arena.js + /cdn/.r2…/<job>.png + /__test/*
  ├─ ChromiumLane     ── 127.0.0.1:<P2>   real Chromium, --remote-debugging-port=0, tab on <P1>/image/direct
  └─ build_app()      ── Bridge(ConfigManager tmp, CDPClient(127.0.0.1, <P2>))
        │  slots: set_folder_path → scan_folder → bulk_select → set_prompt → save_settings
        │         auto_connect_scan / add_url / connect_page_pool → start_run
        ▼  (bridge bg loop thread — app/services/run_state.py:83)
     run_live → plan_pass → prepare_batch → _run_sequential/_try_parallel
        → run_blocks_for_image → CDPArenaController → CDPClient → real CDP → the fake page
        → SAVE → <tmp source folder>/pic1_AI.png
  assertions: contract.py (app side) + /__test/log (page side) + evidence.json (both)
```

Firefox lane swaps the middle box for `FirefoxLane + cdp_adapter` (the app still dials
`ws://127.0.0.1:<P2>/devtools/page/<id>`); jsdom lane swaps it for the Node sidecar.

### 3.3 What is deliberately NOT built
No new production module, no `app/` edit, no second selector registry (the fixtures import
`app.browser.probe_selectors` read-only in `test_fakesite_unit.py` to prove every registry
selector resolves in the fake page — the same trick `tests/test_probe_selectors.py` uses for
literals), no second state machine in Python (the page owns it, D-17).

### 3.4 Layer map (brief §12)

| Layer | Where | Uses | Status |
|---|---|---|---|
| A unit | `tests/test_*.py`, `tests/unit/`, `tests/js/` | pure logic, stub DOM | exists (136 files) |
| B component/contract | `tests/characterization/` (goldens + `FakeCtrl`), `tests/test_cdp_client*.py`, `tests/fakes/cdp_stub_server.py` | one fake page state, mocked browser | exists |
| **C full application integration** | **`tests/e2e/`** | real app + real local page + real browser + real temp folders | **this plan** |
| B′ fake-site unit | `tests/e2e/test_fakesite_unit.py`, `test_contract_unit.py`, `test_clock.py` | the new infrastructure itself, browser-free | this plan (S1) |

Layer C does not replace A/B; it is the only layer where a deleted probe, a drifted selector or a
broken download path fails a test (`coverage-matrix.md`).

---

## 4. Fake site + page state machine

Full spec in `fixtures.md`. Summary: 14 states
(`ready, attachment_uploading, attachment_ready, prompt_ready, submit_enabled, submitted,
generating, generation_success, generation_error, generation_endless, security_required,
authentication_required, rate_limited, new_chat_ready`) and 20 scenarios
(`success_immediate, success_delayed, layout_reverse, upload_rejected, attachment_preview_missing,
stale_attachment_preview, prompt_value_modified, send_disabled, submit_ignored,
generation_error_terminal, generation_error_dead_request, generation_endless, spinner_lost_no_output,
result_after_timeout, result_is_old, result_invalid_image, download_returns_html,
captcha_before_submit, authentication_expired, rate_limited, new_chat_reset_failure`).
Each scenario names: the state sequence, the timings, the bytes served, and the expected app
outcome — one row in `contract.py`, one row in `coverage-matrix.md`.

---

## 5. The one global flow (`tests/e2e/flow.py`)

Each step is a function with an assertion inside it, so a failure names the step (brief §16:
"failures produce enough evidence to diagnose the exact stage").

| Step | Call | Asserted |
|---|---|---|
| 1 start fake site | fixture `fake_site(scenario)` | `/json`-style health route answers; scenario resolver reports the requested scenario |
| 2 start lane | fixture `lane(name)` | endpoint host/port; one tab on `<site>/image/direct?scenario=…`; capability set recorded |
| 3 build app | `build_app(tmp_path, lane)` | real `Bridge`; `cdp_host/cdp_port` point at the lane; bg loop alive |
| 4 **detect the page** | `bridge.auto_connect_scan("manual")` then `wait_until(rows_linked)` | `GET /json/list` really served the tab (lane counter ≥1); `_url_pass_count` grew; log `🤖 Auto-connect: +1 rows, 1 linked, 1 joined…` |
| 5 **create/reconcile URL** | (auto) or explicit `bridge.add_url(site_url)` | one `UrlRow`, `enabled=True`, `tab_id == lane.tab_id`, `receiver=True` and `receiver_reason == ""` (I-51); no duplicate row on a second pass (I-33) |
| 6 **add page to pool** | reconciler join, or explicit `bridge.connect_page_pool(ws_url)` | `get_page_pool_status()` → `total=1, steady=1`; `pool.get_clients(tab_id)` returns a real client + controller |
| 7 select image | `set_folder_path(src)` → `scan_folder()` → `wait_until(queue_filled)` → `bulk_select(True,"pending")` | 2 real PNGs discovered, `*_AI` ignored (RULE 6), statuses `selected`, progress recalculated |
| 8 configure | `set_prompt("a red circle")`, `save_settings({"generation_timeout": …})`, block stack | final prompt preview contains `[JOB-ID: …]`; `timeouts["generation"]` as requested |
| 9 **dispatch the job** | `bridge.start_run()` | `_run_state == "running"`; `job_started` emitted once; the expected worker took it (`📤 pic1.png -> page …` parallel, or `_run_sequential` single); pool → `busy` then `waiting_generation` |
| 10 upload | — | page trace `ready → attachment_uploading → attachment_ready`; `DOM.setFileInputFiles` seen once (lane counter); `ATTACH_IMAGE`/`VERIFY_ATTACHMENT` = success; preview `alt == "pic1.png"` |
| 11 prompt | — | page textarea value **equals** `[JOB-ID: <corr>]\na red circle` (read from the page, not the app); `VERIFY_PROMPT` success |
| 12 Send | — | page trace `submit_enabled → submitted`; `sendCount == expected (D-18)`; `SUBMIT` success exactly once |
| 13 generation | — | page trace `generating`; app log `⏳ Generating Response A spinner visible`; pool `waiting_generation` |
| 14 result | — | page trace `generation_success`; app log `✅ New output verified: … associated <corr> == expected <corr>`; GREEN collect rect emitted |
| 15 download+validate+save | — | `<src>/pic1_AI.png` exists; `sha256 == sha256(result_bytes(corr))` (D-7); PIL size 64×64; no `.partial_*` left (RULE 23) |
| 16 settle | — | image `completed` + `output_path`; `progress.completed == 1`; `job_finished` payload status `completed`; New Chat clicked → page trace `new_chat_ready`; pool → `cooldown` → `steady` after the test cooldown; `jobs_completed == 1`; wall time ≤ generation timeout (D-8) |

Negative assertions in the same flow: no second `job_started`, no `*_AI_2.png`, no output for the
unselected second image, no `Page error:` line, `sendCount` exactly as contracted, and (Watcher
OFF) **zero** captcha activity of any kind — no `waiting_captcha` pool row, no `🛡️ FLAG
CAPTCHA_WAITING` log, no overlay (D-23/I-34).

---

## 6. The three owner scenarios in detail

### 6.1 `success_immediate` (brief §6) — the happy path
Flow §5 with scenario `success_immediate` (generation delay 300 ms). Extra expectations:
`OBSERVE_BASELINE` records 1 baseline image (`baseline-old.png`) and the result is **not** it;
`VALIDATE` reports the PIL format; the second image stays `pending`/unselected; a second Start
after the cooldown picks the same tab (load balancing counter = 1, I-28).
Also run as `success_delayed` (generation 4 s, inside the timeout) and `layout_reverse`
(`ol.flex-col-reverse`, exercising `output_probes.py:96-108`).

### 6.2 `generation_error_terminal` (brief §7 — "the page refuses")
Page: after submit → `generating` (1 s) → an `[role="alert"]` toast **"Generation failed —
internal error. Trace ID: 8f3a-2c"** (matches `ERROR_PATTERNS` `page_errors.py:15-39`, does
**not** match `DEAD_GENERATION_PATTERNS` `:64-66` ⇒ no revival, L-14/D-18).
Expected: upload + prompt steps still succeed; `sendCount == 1`; the wait aborts **fast** (well
before the timeout, I-30); job `failed` with error starting `Page error: Generation failed`;
**no** `*_AI.png` anywhere; image status `failed`, `attempt_count` incremented; pool released via
`finish_page_after_job` (New Chat reset attempted, then cooldown); retry (`retry_image`) does not
reuse stale page state — the page trace shows a fresh `ready` before the second attempt.
Sibling `generation_error_dead_request` uses the exact site toast **"Something went wrong while
generating… Please try again."** ⇒ `sendCount == 2` (one bounded revival), then the same failure.
Sibling `rate_limited` uses **"Daily limit reached — try again tomorrow"** ⇒ failure text carries
the rate-limit signal and `cooldown_total == base + rate_limit_penalty`
(`maybe_note_rate_limit` `cooldown_service.py:438`, I-28/row 21).

### 6.3 `generation_endless` (brief §8 — "out of 300 → restart into preparing state")
Page: submit → spinner visible **forever**, no result, no error.
Fast behaviour run (`WAIT_OUTPUT.timeout_ms = 6000`): the app polls (≥3 polls, 2 s apart — L-12),
never clicks Send again (`sendCount == 1`, spinner alive stands the revival down,
`recovery.py:107-124`), then fails with `Timeout after 6000ms`; **no** output file; pool is not
left busy — `finish_page_after_job` → New Chat click → page trace `new_chat_ready` → `cooldown`
→ `steady` (test cooldown 0–2 s); then the **same test** queues a second image with scenario
`success_immediate` and asserts it completes (brief §8: "next job can run successfully after
recovery"). Production-configuration run: D-8 part 2 with the virtual clock at 300 s.
Documented deviation (L-11): "restart page" is the New Chat reset that exists today, **not**
`Page.reload`; `new_chat_reset_failure` asserts the honest path when the reset itself fails
(logged `↩ New-chat reset failed: …`, cooldown still starts, pool never stuck busy).

---

## 7. Additional state tests (brief §9), scoped

| Group | Scenarios | Stage | Note |
|---|---|---|---|
| Attachment | `upload_rejected`, `attachment_preview_missing`, `stale_attachment_preview` | S4 | preview never appears ⇒ `VERIFY_ATTACHMENT` fails; stale preview ⇒ the app must not accept the old tile |
| Prompt | `prompt_value_modified` | S4 | page truncates the value ⇒ `VERIFY_PROMPT` mismatch (RULE 22 read-back) |
| Submit | `send_disabled`, `submit_ignored` | S4 | `submit_when_ready` reports `send disabled`; ignored click ⇒ no `submitted` transition, no generation |
| Result | `result_is_old`, `result_invalid_image`, `download_returns_html`, `result_after_timeout` | S5 | old bytes ⇒ rejected by baseline+JOB-ID; HTML bytes ⇒ `VALIDATE` fails, nothing saved; late result ⇒ timeout already reported, no save after the fact |
| Save | `output_name_exists`, `destination_readonly` | S5 | `_AI_2` unique suffix (RULE 23); read-only dir ⇒ honest failure, no partial file |
| Reset | `new_chat_reset_failure` | S5 | §6.3 |
| Captcha | `captcha_before_submit`, `captcha_during_generation` | S7 | Watcher **ON** for these two only (`harness.build_bridge(watcher_on=True)` pattern); Watcher OFF asserted zero-activity in every other scenario (D-23) |
| Operator | `pause_mid_wait`, `stop_after_current`, `cancel_during_generation`, `tab_abort` | S7 | `pause_run`/`stop_after_current`/`cancel_current`/`stop_tab_job` slots; RULE 7 stop honour inside the wait |
| Browser loss | `tab_closed_mid_job` | S7 (Chromium/Firefox only) | lane closes the tab ⇒ transient-loss recovery (I-36) or honest failure; jsdom narrows |
| App restart | `restart_after_submit` | out of scope | needs a second app instance mid-generation; recorded as a follow-up (§15) |

---

## 8. Evidence + report format (brief §13)

`evidence.json` (schema frozen in `tdd-interfaces.md` §S2):

```json
{"schema": 1, "scenario": "generation_endless", "lane": "chromium",
 "capabilities": ["layout","file_upload","fetch_bytes","canvas","screenshot","navigation"],
 "narrowed": [], "url_row_id": "url_…", "tab_id": "…", "worker_jobs_completed": 1,
 "job_id": "20260927-…-A7F3", "correlation_id": "<same>", "attempt": 1,
 "page_transitions": [["ready","attachment_uploading",12], …],
 "block_events": [["OBSERVE_BASELINE","success"], …],
 "counts": {"send": 1, "resubmit": 0, "setFileInputFiles": 1, "runtime_evaluate": 41,
            "dom_querySelector": 3, "page_reload": 0, "job_started": 1},
 "clock": {"wall_ms": 8123, "virtual": false, "generation_timeout_ms": 6000},
 "final": {"image_status": "failed", "image_error": "Timeout after 6000ms",
           "pool_status": "steady", "cooldown_total": 0, "run_state": "running",
           "progress": {"completed": 0, "failed": 1}, "output_path": null},
 "output": {"exists": false}, "logs": ["…"], "artifacts": []}
```
Ids/paths normalized with `CORR_RE` (D-21). On failure the bundle is copied to `reports/e2e/<id>/`
with `failure-1.png` where the lane supports screenshots (jsdom: `narrowed: ["screenshot"]`).

---

## 9. Isolation + cleanup (brief §14)

Per test: own `tmp_path` (config, source folder, output folder, browser profile), own ephemeral
fake-site port, own lane port, own scenario session, deterministic fixture bytes,
`cooldown_min_seconds=0` unless the scenario tests cooldown. Teardown order (fixture finalizers,
innermost first): stop the run (`cancel_current` + wait for the batch future) → close only
lane-owned tabs → stop the lane (browser process killed by its own handle) → stop the fake site →
remove temp files → release the Firefox lock. Nothing touches the user's Chrome profile, the repo's
`config/`, or any folder outside `tmp_path`/`reports/e2e/`. Tests run in any order and in parallel
except the `serial` Firefox group (D-22). Failure artifacts are preserved only on failure or
`ARENA_E2E_ARTIFACTS=1` (D-11).

---

## 10. Invariants to land with the code (append to SYSTEM_OF_RECORD §5; I-52…I-54 are taken)

| ID | Invariant | Enforcement |
|---|---|---|
| **I-55** | One behaviour contract, three lanes — the expected job/page states live in `tests/e2e/contract.py` only; a lane provides transport and capabilities, never assertions. A capability gap narrows an expectation **loudly** in the evidence bundle | `test_contract_unit.py` (no lane-specific expectation tables), `evidence.json.narrowed` |
| **I-56** | The fake page is the only page — the suite never contacts a live arena.ai host, never loads an external asset, never reads credentials; the fake site binds `127.0.0.1` and its control routes exist only under `tests/` | `test_fakesite_unit.py` (route table + no-external-URL guard over `static/*`), `tests/test_repo_hygiene.py` unchanged |
| **I-57** | Saved bytes are the job's bytes — a completed job's `*_AI` file hashes to `result_bytes(correlation_id)`; a scenario that must not save asserts the **absence** of every `*_AI*` file, not just of the expected one | `flow.py` step 15 + `contract.py` output rules |
| **I-58** | One initial submit per job, at most one revival — `sendCount` is contracted per scenario (D-18) and read from the page's own log; revival only on the documented death signatures | page event log + `contract.py.counts` |
| **I-59** | The 300 s configuration is proven without waiting 300 s — the production knob is asserted end to end (settings → block status → overlay → wait outcome) under a virtual clock confined to three module namespaces | `test_timeout_contract.py`, `test_clock.py` (patch-set allowlist) |

---

## 11. Staged delivery (S0…S7, plus the owner-run S1a) — each stage gate-green and useful alone

| Stage | Delivers | Proves on its own | Depends on |
|---|---|---|---|
| **S0** | folder skeleton, markers, `tools/e2e_check.sh`, `.gitignore` `reports/e2e/`, `tests/e2e/README.md` | `pytest tests -q` unchanged (all new tests skip/absent), gate green | — |
| **S1** | fake site (`fakesite/*`, `fixtures/*`) + `test_fakesite_unit.py` | every registry selector resolves in the fake page; the state machine walks all 14 states; `result_bytes` hashes are stable | S0 |
| **S1a** *(owner-run, optional but recommended before the fixture freeze)* | `tools/har_ingest.py` + `tests/e2e/test_har_ingest_unit.py`; the owner's captures become `tests/e2e/fixtures/recorded/**` (D-23, `record-replay.md` §6) | a capture reduces to sanitized artifacts with stable sha256s; **L-17 closed** (real result bytes), **L-16 settled** (recorded New Chat `href`) | S1 skeleton; a capture taken per `record-replay.md` §9 |
| **S2** | `contract.py`, `evidence.py`, `clock.py` + their unit tests | the contract table covers every state; the bundle schema round-trips; the clock patches exactly 3 namespaces | S1 (S1a if taken) |
| **S3** | `app_instance.py`, `flow.py`, `conftest.py` + `ChromiumLane` | **the owner's 5 steps run end to end on real Chromium for `success_immediate`** — the first job ever saved from a page in this repo | S1,S2 |
| **S4** | `test_full_image_job.py` × the 6 core scenarios (success, delayed, reverse layout, terminal error, dead-request error, endless) | brief §6/§7/§8 behaviour, D-18 submit counts | S3 |
| **S5** | `test_recovery_and_reset.py`, `test_timeout_contract.py` + result/save scenarios | endless → reset → **next job succeeds**; the 300 s contract; unique suffix; HTML bytes rejected | S4 |
| **S6** | `cdp_adapter.py` + `FirefoxLane` (+ `JsdomLane`, `tests/js/e2e/*`) | the **same** contract on real Firefox; jsdom fallback where no browser exists | S4 |
| **S7** | operator/captcha/tab-loss scenarios + `coverage-matrix.md` completion + docs rows | pause/stop/cancel/abort, Watcher-ON captcha states, I-36 tab loss | S6 |

Un-splittable groups: S1's `static/*` + `pages.py` + `artifacts.py` (one page contract);
S3's `app_instance.py` + `flow.py` + `chromium.py` (a lane without the flow proves nothing);
S6's adapter + Firefox lane (the adapter has no other caller).

---

## 12. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | Chromium download unavailable/offline ⇒ S3+ cannot run | S1/S2 are browser-free and still valuable; `e2e_check.sh` prints the resolution order; jsdom lane (S6) covers the page contract |
| R2 | Playwright Firefox version drift changes `set_input_files`/evaluate semantics | the adapter's contract test (S6) pins the 8 families against a fixture page before any scenario runs |
| R3 | Real-browser flake (timing, focus, fonts) | all timings come from the scenario JSON, never `sleep` guesses; every wait is deadline-based with the last state in the message; artifacts on failure |
| R4 | 2 s poll interval (L-12) makes the fast lane slow | budget computed in `quality-budget.md` §5: 6 core scenarios ≈ 45 s total on Chromium; parallel lanes where safe |
| R5 | The virtual clock leaks into a real wait | patch-set allowlist test (D-9) + the clock is only installed in `test_timeout_contract.py` |
| R6 | Fake page drifts from `site_adapter.py` **or from the real site** | `test_fakesite_unit.py` resolves **every** registry selector (primary + fallbacks) in the fixture DOM; a registry edit fails the suite until the fixture follows. Site-side drift is now dated and detectable: D-23 records a capture with a MANIFEST (browser + date), the skip-gated saved-page test re-runs the real probes, and the optional S6 `route_from_har(not_found="abort")` check replays the recorded shell offline |
| R7 | Fixture bytes/HTML bloat the repo | 4 tiny PNGs (<2 KB each) + ~1 000 lines of HTML/JS; `hashes.json` instead of extra images; nothing from `arena webpages/` (I-43) |
| R8 | Coverage floor movement | browser tests skip by default ⇒ floors unchanged; when they run they only add hits (`quality-budget.md` §4) |
| R9 | Duplicate-row / ownership surprises (I-33) when the reconciler and `add_url` both run | step 5 asserts one row per tab and runs the reconciler twice |
| R10 | Revival resubmit misread as a double-submit bug | D-18 contracts it per scenario and the page labels `send` vs `resubmit` |
| R11 | Firefox profile locks under parallel runs | D-22 `serial` + lock file |
| R12 | The fake page becomes a second source of selector truth | it imports nothing; the guard test reads the registry from `app/browser/probe_selectors` (one direction only) |
| R13 | Windows paths / `DOM.setFileInputFiles` absoluteness | `cdp/dom.py:72-74` resolves; fixtures use `tmp_path` only; the flow asserts the page saw the exact basename |
| R14 | Suite rots because it is opt-in | `tools/e2e_check.sh` is referenced from `tests/e2e/README.md` + the docs row; the contract table is checked for completeness by a browser-free unit test, so it cannot silently shrink |

---

## 13. Out of scope (explicit follow-ups)

1. Production Firefox/Ui.Vision worker (L-9) — would be a real feature, not a test.
2. Wiring `reload_page` into the post-timeout recovery (L-11) — behaviour change.
3. Making `test_url` a real reachability/auth/readiness probe + unifying `UrlStatus` with
   SYSTEM_OF_RECORD row 1 (L-10).
4. Injectable poll interval (L-12).
5. App-restart-mid-job scenario (`restart_after_submit`) — needs a second app instance and a
   persisted-job contract that does not exist yet.
6. Live arena.ai smoke runs (RULE 20: user-authorized URLs only, never in an automated suite).
7. Visual/screenshot regression of the app's own UI (the sash lane owns that).
8. Mutation testing of the new infrastructure (`tools/mutmut_scope.sh` scopes `app/` only).
9. Native-input / visible-desktop lane (`e2e_desktop` marker reserved, unused): with in-page
   clicks (`evidence.md` §2) nothing in this suite needs a desktop.

---

## 14. End-of-plan recheck (required by the brief)

| Rule | Verdict |
|---|---|
| **RULE 16** (gates) | No `app/` change ⇒ no new gated symbol, no ratchet movement, no override needed. New test files are out of scope for size/CC (RULE 16.0) but every one carries a RULE 18 budget in `quality-budget.md` §3; `tools/verify_quality.py --changed --allow-legacy` + `pytest` + coverage stay green at every stage (§11). New production paths: none ⇒ §16.3 "uncovered new functions = 0" holds trivially; the new *test* infrastructure gets its own browser-free tests (S1/S2) so it is not trusted blindly. |
| **RULE 18** (ideals) | Every planned file is inside 150–300 lines except `contract.py` (260, one table + one asserter) and `static/fake-arena.js` (260, one state machine — a single JS literal family, the §16.1.5 spirit); functions planned ≤20 lines, params ≤4 (`ScenarioExpectation`/`FlowCtx`/`EvidenceBuilder` are the parameter objects). Deviations carry `ideal-size:` reasons in `quality-budget.md` §3. Context files: `tests/e2e/README.md` ≤120 lines; `docs/current/*` untouched (this plan lives in the archive, RULE 17/18.4). |
| **RULE 19** (order) | Nothing is over a fail line, so no remediation. Should a stage hit one, the order is nesting → CC → cognitive → size, and the plan's parameter objects exist precisely so size is never the first lever. |
| **RULE 17** (docs) | This folder is the record; `docs/README.md` gains one archive row now; `SYSTEM_OF_RECORD.md` §8 (tests table) + §5 (I-55…I-59) + `DOM_SELECTORS.md` (a "fake-page contract" pointer) are updated **with** the landing stage, not before. |
| **RULE 8** (real thing) | The suite executes the real app, the real probes, the real CDP client, real browsers and real files; the only fakes are the page and the clock, and the clock's scope is itself tested. A test that would pass with the feature deleted was rejected by design (D-3, §3.4). |
| **RULE 4/7/15/21/22/23** | Empty vs broken: loud skips with reasons, no-output asserted as absence (I-57). Stop: operator scenarios honour `_cancel_requested`/`_stop_after` inside the wait. Two-step gate: baseline + JOB-ID + byte validation + atomic save are all asserted, and the fail-closed side is asserted by the error/timeout scenarios. Selectors: fixtures resolve the registry, never a copy. Correlation: real `generate_correlation_id()`, read back from the page. Save: `_AI`/`_AI_2`, no partial file, output is not the queue. |
| **RULE 20** (compliance) | No live site, no captcha bypass: captcha scenarios only assert detect/pause/wait with the Watcher ON, and zero activity with it OFF (D-23). The fake reCAPTCHA is a placeholder frame, never a Google asset. |

### 14.1 Planning-round verification (2026-09-27, this round only)

RULE 16 asks for claims that can be checked, so the plan itself was checked:

* **Every `file:line` citation in this folder was re-resolved against the tree at `02e0240`** with a
  script (path exists, line inside the file, quoted symbol on the quoted line). It corrected 20+
  drifted numbers inherited from research notes — e.g. `CORR_RE` is `harness.py:33` not `:35`,
  `build_bridge` is `:106` not `:96`, `run_supervisor` is `:211` not `:236`, `_arm_revival` is
  `single_job_runner.py:266` not `:267`, `RESUME_GRACE_SEC`/`MAX_RESUBMITS` are
  `recovery.py:27-28`, the `js_snippets.py` constant spans are `63/89/111/130/182/203`,
  `get_output_path` is `app/core/naming.py:65` with `AI_SUFFIX` at `:14` and the unique template at
  `:24`, `"generation": 180` is `app/core/models.py:159`, the port-probe message is `tabs.py:89`, and the
  wait's clock surface is exactly 3 `time.monotonic()` reads + 3 poll sleeps in `output_wait.py`
  and 3 fixed 3 s sleeps in `output_wait_fallback.py` (which is what makes D-9's three-namespace
  patch set complete rather than approximate).
* **Doc sizes (measured):** `README.md` 50 · `evidence.md` 203 · `design.md` 588 · `fixtures.md`
  245 · `quality-budget.md` 198 · `tdd-interfaces.md` 274 · `coverage-matrix.md` 116. None of these
  is a *context file* in RULE 18's sense (§18: files in `docs/current/`, root `CLAUDE.md`/`AGENTS.md`,
  package README — the ones a reader must load whole); they are read section-wise through
  `README.md`, which is the 50-line entry point. The sibling plan folder is the same shape
  (`2026-09-20-dynamic-urls-and-worker-debug/design.md` = 656 lines).
* **No code, tooling, config or `docs/current/` file was created or edited in this round** — the
  round's whole diff is this folder plus one `docs/README.md` archive row and one `*Last updated*`
  sentence (RULE 17: current docs move with the code, not before it).
* **Deferred to the landing stages** (recorded, not hidden): `SYSTEM_OF_RECORD.md` §5 (I-55…I-59) +
  §8 test rows, the `DOM_SELECTORS.md` fake-page pointer, `pytest.ini` markers, `.gitignore`
  `reports/e2e/`, and the `package.json test:js` listing (the L-7 trap).
