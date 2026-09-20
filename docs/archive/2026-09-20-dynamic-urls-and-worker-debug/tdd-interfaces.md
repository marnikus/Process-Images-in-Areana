# TDD interface plan — per-stage interface split, expected files/functions, and the test branch that comes first

**Written:** 2026-09-20 · **Branch:** `arena/01a0bc3b-process-images-in-areana` · **Base:** `6bbaf8b`
**Status:** plan. **No production code, tool or test was changed by this document.**
**Siblings:** `design.md` (decisions D-11…**D-27**, stage chain §9) · `evidence.md` (every claim with
`file:line`; §8 = why the stages sit in this order; §9 = the interface-level research behind this file) ·
`quality-budget.md` (RULE 16/18 numbers, the JS net-zero ledger, the test matrix).

This file answers one question per stage: **which interfaces does the stage split out, into which files
and functions, and which tests are written before them?** It is the working document for RULE 16.6
steps 3-4 (tests first, then measure) and for RULE 8 (a test executes the real thing).

---

## 0. How to use this document

Every stage S1…S10 has the same five blocks:

| Block | What it fixes | Rule it serves |
|---|---|---|
| **A-E · Appendices** | §A frozen seams (and the test pinning each), §B the slot/signal budget (0 new), §C the test ledger with measured base counts, §D the measured headroom table for all 25 touched files, §E the anti-gaming rules, §F the RULE 16/18 recheck for this document | RULE 16.5-16.7, RULE 18, D-20/D-24a/D-27 |
| **0 · Scope** | the one behaviour the stage adds, and the stage's *interface boundary* (what it exposes to later stages) | D-24 (separable, shippable) |
| **1 · Interface split** | every symbol added/changed: signature, size budget, who calls it, what it must **not** do | RULE 16.1-16.2, RULE 18, RULE 10 |
| **2 · Expected files & functions** | the new files with their complete symbol inventory (signatures only — bodies are the implementation's job) | RULE 18.2/18.3, D-24a |
| **3 · RED — the tests written first** | test file, test name, arrange/act/assert, and the **exact failure expected at `6bbaf8b`** | RULE 16.6 step 3, RULE 8 |
| **4 · GREEN + REFACTOR + equivalence** | the minimal production edits (with line anchors), what gets tidied afterwards, and which existing tests must stay green **unedited** / must change **with a recorded reason** | RULE 16.5-16.7, RULE 17 |

Notation used throughout:

```
symbol(a, b) -> T        ⟨≤14 LOC · CC ≤4 · params 2 · nest ≤2⟩   owner: <who may call it>
```

* Budgets are **RULE 16 hard limits first** (func ≤30 LOC, class ≤150 LOC, params ≤4, methods ≤15,
  CC ≤10, nesting ≤4) and **RULE 18 ideals second** (function 4-20 LOC, file 150-300 LOC,
  module 5-15 files). Every budget below is written against the *recorded maximum of the file it
  lands in* (`evidence.md` §9.3), because with `--changed` the ratchet compares against
  `tools/quality_baseline.json`, not against the ideal.
* `RED at base:` states what the test does **before** the stage's production edit. A RED test that
  passes at `6bbaf8b` is not a RED test — it is an equivalence test, and it is labelled as one.

### 0.1 The three TDD rules this plan adds on top of RULE 16.6

1. **The first artefact of a stage is a failing test, committed or at least run and recorded.** The
   stage's commit description quotes the RED failure line (§4 of each stage names it).
2. **No test may double the seam it tests.** `L-6` (`evidence.md` §9.4) is exactly that mistake: the
   pool host in `tests/test_panel_browser_tabs.py` is given a `_schedule_coro` attribute that exists
   nowhere in production, so a broken slot looked tested for months. S1 removes the double.
3. **A counting test needs a positive control.** Every "nothing happened" assertion (D-23's
   zero-activity test, S2's no-probe tests) is paired with a test that makes the same counter
   non-zero through the real path — otherwise the test passes with the feature deleted, which
   RULE 16.0 explicitly rejects.

### 0.2 Test infrastructure that already exists (verified — use it, do not reinvent it)

| Asset | Where | What a stage uses it for |
|---|---|---|
| Session fixtures `event_loop`, `qapp` | `tests/conftest.py:46,59` | any async or Qt-touching test (no per-test loop churn) |
| Worker isolation `worker_id`, `tmp_config_path`, `isolated_config_dir`, `isolated_media_root`, `isolated_log_file`, `fake_preset_store` | `tests/conftest.py:74-160` | S6's config-key test, S7's persistence round-trip, S9's payload test — never touch real `config/` |
| `fake_clock`, `page_pool_with_event` | `tests/conftest.py:111,130` | S3's cap timing and S4/S5's wait loops **without real sleeps** |
| `cdp_server` / `make_client` | `tests/conftest.py:240,249` + `tests/fakes/cdp_stub_server.py` (129 LOC) | S3's browser-layer test over a real socket (RULE 8: the real `CDPClient`, not a mock) |
| `FakeBridge` (records `log`/`emit_state`/`emit_job_status`, plus a `connect`/`emit` signal bus) | `tests/fakes/fake_bridge.py:12-55` | S2/S3's side-effect counting, S9's payload assertions |
| `FakeActionRunner` (canned per-block results) | `tests/fakes/fake_runner.py:11-32` | S5's pass planning without CDP |
| Golden harness: **real `Bridge`** on tmp dirs + recorders | `tests/characterization/harness.py:105-121` (`build_bridge`), `:158-172` (`collect_trace`), `:181-192` (`check_golden`) | the equivalence gate for S4/S5 |
| Golden trace fields | `events`, `clicks`, `evals`, `signals`, `images`, `files`, `run_state` — **`logs` is collected but excluded from the compare** (`harness.py:184`) | S5 may add log lines freely; it may **not** change `run_state`, `evals` or `events` |
| Golden stop lever | `arm_hooks(env, after_finish=…)` sets `_stop_after` (`harness.py:211-231`, read at `batch_orchestrator.py:133`, `multi_page_dispatcher.py:364`) | the only way a golden run ends — S5's supervisor must honour the same flag |
| Pinned log markers | `"Starting"`, `"Job completed"`, `"Batch complete"`, `"Completed with warnings"`, `"Prompt verification failed: Mismatch"` (`tests/characterization/test_batch_goldens.py:37,47,81`) | S5 must keep emitting `🏁 Batch complete` on a `_stop_after` finish |
| Runner registry | `RUNNERS = {"orchestrator": run_orchestrator}` (`harness.py:205-208`) | S5 swaps the runner to `run_live` (see S5 · block 4) |
| JS harness **A** — module sandbox | `tests/js/test_url_cooldown.mjs:14-45` (read a file list, `vm.runInContext`, assert on the published object) | S6 `test_url_interval_control.mjs`, S7 `test_url_list_receiver_icon.mjs` |
| JS harness **B** — whole-page boot | `tests/js/test_boot_all_panels.mjs:29-99` (every `<script>` of the real `index.html` in order; `fakeBridge` is a Proxy whose every member is callable **and** connectable; then `DOMContentLoaded`) | S8 mount test, S9 panel-content test |
| JS harness **C** — grid | `tests/js/sash_harness.mjs:16-49` (`ALL_WINDOW_IDS`, `PANEL_IDS`, `panelIdOf`, `TITLE_SECONDARIES`, `BADGE_LIKE`) + `tests/js/fake_dom.mjs` (323 LOC, flexbox engine) | S8 registry test, title-fit guard |
| Slot-contract locks | `tests/test_bridge_slots.py` (Σ=134), `tests/test_bridge_metaobject.py` | **never edited** — D-20; every stage runs them |
| Pinned cooldown behaviour | `tests/test_cooldown_service.py:604-618` (`wait_captcha_cleared` never gives up) | **never edited** — S3 composes the cap into the caller's `stop` instead (D-14R) |

### 0.3 Three latent defects found while pre-designing these interfaces

Recorded here (and in `evidence.md` §9.2) because each one changes what a stage must do.

| ID | Defect | Evidence | Consequence for the chain |
|---|---|---|---|
| **L-6** | A test double hides L-1: the pool host is built with `_schedule_coro=…`, an attribute that exists **nowhere** in production (`grep -rn "_schedule_coro" app/` ⇒ exactly one hit, the broken call itself) | `tests/test_panel_browser_tabs.py:82,156,168,180,211` vs `app/ui/panels/page_pool.py:147` | S1 must de-mask the double, otherwise `test_pool_slots_connect_and_cooldowns` keeps asserting against a seam the app does not have (RULE 8) |
| **L-7** | Two JS test files exist but are **not** in `package.json`'s explicit `test:js` list, so `npm run test:js` never runs them: `test_captcha_saved_page.mjs`, `test_title_fit.mjs` (25 listed / 28 test files present; `fake_dom.mjs`, `sash_harness.mjs`, `user_layout.mjs` are harnesses) | `package.json → scripts["test:js"]` vs `ls tests/js/*.mjs` | S8's title-fit guard must be invoked explicitly; S10 decides whether to adopt both orphans (only after they are green) |
| **L-8** | Dead + drifting window metadata: `WIN_ICONS` is declared and **never read anywhere** in the repo (title-bar icons are hard-coded in `index.html`), and it already omits `recordings`/`block_config`; separately `layout_service.WINDOWS` lists `recordings` last while `WINDOW_IDS` lists it 11th — harmless only because `WINDOW_TITLES` is a dict | `app/ui/web/js/sash-grid.js:41-49` (single hit repo-wide) · `app/core/layout_service.py:11-15` vs `:16-32` | S8's `window_catalog.py` becomes the **one** ordered table (ids ≡ order ≡ titles) and deletes `WIN_ICONS` (−9 lines on a frozen 123-line file ⇒ ratchet-safe) instead of extending a dead registry |

---

## S1 · L-1 — the pool join works

### 0 · Scope

One word: `page_pool.py:147` calls `self._schedule_coro(...)`, an attribute no production object has,
so `connect_page_pool` — the slot behind **Add Selected Tab to Pool** and the path S6's reconciler uses
to join tabs (`LiveDeps.join_tab`) — always returns an error JSON. Interface boundary after S1: the
pool join is reachable through the *real* scheduler helper, and nothing else changes.

### 1 · Interface split

| File | Symbol | Signature after S1 | Budget | Called by | Must **not** |
|---|---|---|---|---|---|
| `app/ui/panels/page_pool.py` | `PagePoolMixin.connect_page_pool` (slot) | `(self, ws_url: str) -> str` — unchanged | span 12 → **12** · CC 4 → **4** · params 1 (file max `max_func_loc` 16, `max_params` 4) | JS `poolConnectBtn` (`js/panels/page-pool/actions.js`) · S6 `LiveDeps.join_tab` | grow a line; gain a `try` layer; be split |
| same | import line `:27` | `from app.services.run_state import cooldowns_path, resolve_tab_info, restore_page_state, schedule_coro` | +0 lines (same physical line, alphabetical) | — | add a second import block |
| same | body `:147` | `schedule_coro(self, do_connect_page_pool(self, ws_url))` | 1 line replaced | — | keep or re-add any `_schedule_coro` compatibility attribute (that is L-6's mistake) |
| `app/services/run_state.py` | `schedule_coro(bridge, coro)` | **unchanged** (`:194-207`) | — | now also `page_pool` | be edited at all — the helper is already correct |
| `app/ui/panels/page_pool.py` | `do_connect_page_pool(bridge, ws_url)` | **unchanged** (`:78-93`) | span 16 = under file max | the coroutine S1 now actually schedules | be rewritten; S1 only makes it reachable |

**Net production diff: 2 lines in 1 file. No new file, no new symbol, no new slot.**

### 2 · Expected files & functions

None new. New **test** file: `tests/test_page_pool_join.py` (~60 LOC, 4 tests, `@pytest.mark.unit`).

### 3 · RED — tests written first

`tests/test_page_pool_join.py`

1. `test_connect_page_pool_schedules_on_the_real_helper(monkeypatch)`
   *Arrange:* `host = SimpleNamespace(spec-ish)` built exactly like `test_panel_browser_tabs.make_host`
   **minus** `_schedule_coro` (that omission is the point): `_page_pool=PagePool()`, `_log=…`,
   `page_pool_updated=Emitter()`; `monkeypatch.setattr(page_pool, "schedule_coro", spy)` where `spy`
   records `(bridge, coro)`.
   *Act:* `reply = json.loads(host.connect_page_pool("ws://127.0.0.1:9222/devtools/page/t1"))`.
   *Assert:* `reply["ok"] is True`; `len(spy.calls) == 1`; `spy.calls[0][0] is host`;
   `spy.calls[0][1].cr_code.co_name == "do_connect_page_pool"`; then `coro.close()`.
   **RED at base:** `reply == {"ok": False, "error": "'SimpleNamespace' object has no attribute '_schedule_coro'"}`
   and `spy.calls == []` — the slot's `except Exception` swallows the `AttributeError` (`:148-150`).
2. `test_no_private_scheduler_survives_in_the_pool_panel()`
   *Arrange/Act:* read `Path("app/ui/panels/page_pool.py").read_text()`.
   *Assert:* `"_schedule_coro" not in text` and `"schedule_coro(self," in text`.
   **RED at base:** the first assertion fails (the string is on line 147). This is the cheap
   regression lock that keeps L-6 from coming back.
3. `test_connect_page_pool_error_branches_unchanged()` — *equivalence, green at base:*
   `connect_page_pool("")` ⇒ `{"ok": False, "error": "empty ws_url"}`; with `_page_pool=None` ⇒
   `{"ok": False, "error": "pool not initialized"}`. Pins the reply vocabulary the JS already parses.
4. `test_scheduled_coroutine_joins_the_pool(event_loop, monkeypatch)` — *equivalence, green at base:*
   `monkeypatch` `page_pool.connect_pool_client` → a fake client, `run_state.resolve_tab_info` →
   `("T", "https://arena.ai")`; `await do_connect_page_pool(host, "ws://x/devtools/page/t9")`.
   *Assert:* `host._page_pool.get_page("t9") is not None`, its `title == "T"`, and
   `page_pool_updated` fired once. Proves the coroutine S1 schedules is the one that does the work
   (it is the second half of the "does the button work" question, and it must not be the RED half).

### 4 · GREEN + REFACTOR + equivalence

* **GREEN:** the 2-line edit of block 1. Run `pytest tests/test_page_pool_join.py -q` ⇒ 4 passed.
* **REFACTOR — de-mask L-6 (same commit, test-side only):** in `tests/test_panel_browser_tabs.py`
  delete the five `_schedule_coro=…` host attributes (`:82,156,168,180,211`) and give
  `test_pool_slots_connect_and_cooldowns` a real spy instead:
  `monkeypatch.setattr(page_pool, "schedule_coro", lambda bridge, coro: queued.append(coro))`,
  keeping `assert len(queued) == 1`. Reason recorded in `quality-budget.md` §6.2: *the double was the
  reason L-1 survived; the test now exercises the production seam.*
* **Equivalence (must stay green, unedited):** `tests/test_page_pool.py` (15 tests, pool semantics),
  `tests/test_run_state.py:40` (`schedule_coro` tracking), `tests/test_bridge_slots.py`,
  `tests/test_bridge_metaobject.py`, all 12 goldens (no pool join in any golden scenario).
* **Gate:** `python tools/verify_quality.py --changed --allow-legacy --coverage-ratchet`
  (`page_pool.py` `max_func_loc` 16 unchanged, `func_count` 14 unchanged).
* **Docs in the same commit:** SYSTEM_OF_RECORD row 19 note ("Add tab to pool" repaired) + this
  folder's `evidence.md` §4 marked closed + `docs/README.md` footer line.

---

## S2 · Captcha scope — Watcher OFF means zero captcha activity

### 0 · Scope

One predicate owns the question "is captcha work allowed right now?", and five existing call sites ask
it. With the Watcher OFF there is **no** probe, overlay, `waiting_captcha` row, stat, recording,
penalty or `🛡` line (D-23), and no settler is installed inside the generation wait (round-1 D-1).
Interface boundary after S2: `app/services/captcha/policy.py` exists and is the only place that reads
the switch — S3 (cap + wording) and S9 (window silence) both build on it.

### 1 · Interface split

**New module (the split itself):**

| Symbol | Signature | Budget | Owner / caller | Must **not** |
|---|---|---|---|---|
| `policy.watcher_enabled(bridge) -> bool` | reads `config.get_state("watcher_enabled", False)` | ≤6 LOC · CC 2 · 1 param | the only reader of the switch | import `ui`, touch the SDK, cache the value |
| `policy.solver_running(bridge) -> bool` | `getattr(bridge, "_captcha_watcher", None)` and `.running`, fail-closed | ≤6 · CC 2 · 1 | `captcha/service._watcher_running`, `wait_reason` (S3) | start/stop anything |
| `policy.has_solver_key(bridge) -> bool` | the stored 2Captcha key via `bridge._captcha_service()` | ≤8 · CC 3 · 1 | `wait_reason` (S3), the debug window (S9) | log the key, decrypt, call the API |
| `policy.captcha_in_scope(bridge) -> bool` | `== watcher_enabled(bridge)` | ≤4 · CC 2 · 1 | **all five gates** | grow a second condition (RULE 10: one control per decision) |
| `policy.out_of_scope() -> SolveOutcome` | `SolveOutcome(status="out_of_scope", reason="watcher off")` | ≤3 · CC 1 · 0 | `handle_captcha`'s choke gate | return `None` (callers map statuses, not `None`) |

File budget: `app/services/captcha/policy.py` ≈ **35 LOC after S2** (55 after S3 adds the cap trio) —
deliberately under the 150-300 band because it is one decision (`quality-budget.md` §5, row 18.2b).
Import direction: `policy` imports only `.signals` (same package, acyclic); **services never import
panels** (`app/ui/panels/__init__.py:1-8`).

**Existing symbols that change (5 gate edits, all inside existing functions):**

| Site | Edit | Span / CC after | Why here |
|---|---|---|---|
| `single_job_runner.check_security:107-116` | first line `if not captcha_in_scope(ctx.bridge): return False` | 10 → **12** · CC 3 → **4** (file maxima 26 / 9) | kills the probe, the wait, the overlay, the penalty and the stats in one place (RULE 9: returns "no captcha", the stack continues) |
| `single_job_runner._handle_security:402-411` | scope guard **before** `is_security_dialog_visible()`; the block reports `success` with `"Skipped (Watcher off)"` | 10 → **13** · CC 2 → **4** | the `CHECK_SECURITY` block must not claim a dialog it never looked for |
| `single_job_runner.wait_for_output:246-262` | install `security_settler` **only** when in scope (`if captcha_in_scope(ctx.bridge):` around `:249`) | 18 → **19** · nest 2 → **3** (limit 4) | `cdp_arena/output.py:115-125` `_security_gate` then never evaluates the dialog predicate ⇒ one CDP round-trip less per poll |
| `captcha/service.handle_captcha:210-231` | choke gate before `detect_signal`: `if not captcha_in_scope(ctx.bridge): return out_of_scope()` | 22 → **24** · CC 4 → **5** (file max `max_func_loc` **27** = `_manual_wait`) | the last line of defence: any future caller is scoped too |
| `captcha/service._watcher_running:242-249` | body → `return solver_running(ctx.bridge)` | 8 → **3** (file max drops 27 → 27, unchanged) | one owner for the `getattr` dance |

**Deliberately *not* changed** (research result, saves an edit and a risk):

* `_handle_captcha_outcome` (`single_job_runner.py:75-85`) needs **no** `out_of_scope` branch: it
  raises only on `stopped` / `page_error` and warns on `token_stale`, so an unknown status already
  falls through as "no failure" — exactly the required mapping.
* `SolveOutcome.status` is a free-form `str` with default `"none"` (`captcha/signals.py:94-99`) ⇒
  `"out_of_scope"` needs **no** enum/dataclass change, only a docstring line (vocabulary).
* `captcha_watcher/watcher.py:159` (`🛡️ Captcha Watcher OFF — …`) and `watcher_solver.py:131`
  (`no 2Captcha key …`) stay: the first is the switch's own confirmation at the transition, the second
  only fires while ON (round-1 §4.3).

### 2 · Expected files & functions

```
app/services/captcha/policy.py            (new, ~35 LOC after S2)
    watcher_enabled(bridge) -> bool
    solver_running(bridge) -> bool
    has_solver_key(bridge) -> bool
    captcha_in_scope(bridge) -> bool
    out_of_scope() -> SolveOutcome
tests/test_captcha_scope.py               (new, ~120 LOC, 8 tests)
tests/test_watcher_off_zero_activity.py   (new, ~115 LOC, 3 tests — D-23's counting test)
```

`app/services/captcha/` goes 6 → **7 files** (RULE 18.3 ideal 5-15 ✓). No panel, no slot, no signal.

### 3 · RED — tests written first

`tests/test_captcha_scope.py` (host = `SimpleNamespace` with a `config` stub, like
`test_captcha_boundaries.make_bridge:25-38`, which already supports a `session` override dict):

1. `test_watcher_enabled_mirrors_the_switch` — `{"watcher_enabled": True}` ⇒ True; `{}` ⇒ **False**
   (fail-closed default, `config_manager.DEFAULT_SESSION:22`); a `config` that raises ⇒ False.
   **RED at base:** `ImportError: cannot import name 'policy'` — the module does not exist.
2. `test_captcha_in_scope_is_the_switch_and_nothing_else` — both states, plus
   `solver_running`/`has_solver_key` variations: scope must **not** depend on the key or on the loop
   (D-23's "OFF means off", D-15's "ON without a key still waits").
3. `test_check_security_does_not_probe_when_off` — fake ctrl with a counting
   `is_security_dialog_visible`; assert `await sjr.check_security(ctx) is False` **and** `calls == []`.
   **RED at base:** `calls == ["visible"]` (the probe runs regardless — `:110`).
4. `test_handle_security_block_reports_skipped_when_off` — spy `_emit_action`; assert the emitted
   pairs are `[("CHECK_SECURITY","success")]` with message `"Skipped (Watcher off)"`, 0 probes.
   **RED at base:** message is `"Security done"` and the probe ran (`:405-411`).
5. `test_handle_captcha_returns_out_of_scope_when_off` — a ctrl scripted **visible**; assert
   `outcome.status == "out_of_scope"`, `outcome.reason == "watcher off"`, and that no recording,
   stat or overlay happened.
   **RED at base:** `status == "manual"` with an overlay + stats + penalty (`service.py:210-231`).
6. `test_settler_is_not_installed_when_off` — drive `wait_for_output` with a stubbed pipeline and
   assert `hasattr(ctrl, "security_settler") is False` **during** the wait (checked from inside the
   stubbed `_poll_generation`) and after it.
   **RED at base:** the attribute is present during the wait (`:249`).
7. `test_scope_is_evaluated_per_call` — OFF ⇒ no probe; flip the config to ON; second call probes.
   Pins round-1 §4.4 ("live in both directions", no restart, no cached flag).
8. `test_watcher_running_delegates_to_policy` — watcher absent / present-stopped / present-running /
   raising ⇒ `_watcher_running(ctx)` equals `policy.solver_running(bridge)` in all four cases.

`tests/test_watcher_off_zero_activity.py` (D-23 — the counting test):

9. `test_watcher_off_produces_zero_captcha_side_effects` — one fake stack (`FakeBridge` from
   `tests/fakes/fake_bridge.py`, a counting `PagePool` wrapper, a counting ctrl, spy
   `_captcha_service` whose `stats.record` / `recordings.start|finish|abort` count, spy
   `cooldown_service.note_captcha_event`), a dialog scripted **visible forever**, then
   `await handle_captcha(ctx)` with the switch OFF. Assert one dict equals all zeros:
   `{"detect_probes": 0, "dialog_polls": 0, "overlays": 0, "mark_waiting": 0, "stats": 0,
   "recordings": 0, "penalties": 0, "shield_lines": 0, "captcha_solve_lines": 0}` — plus
   `not hasattr(ctrl, "pause_clock")` (S3 forward-lock) and no captcha wording in the S9 payload
   (added as an assertion in S9, not here).
   **RED at base:** every counter is ≥1 and two `🛡️` lines were logged (`service.py:216-219,253`).
10. `test_the_same_counters_do_count_when_on` — **positive control** (RULE 16.0: a test that passes
    with the feature deleted is not a test): identical stack with `watcher_enabled=True` ⇒
    `detect_probes ≥ 1`, `overlays ≥ 1`, `mark_waiting == 1`, `stats ≥ 2`, `shield_lines ≥ 1`.
11. `test_zero_activity_holds_through_the_whole_job` — the same counters around a full
    `single_job_runner` block loop (`CHECK_SECURITY` + `WAIT_OUTPUT`) with the switch OFF and a
    visible dialog: still all zeros, and the job **completes** (the timeout runs untouched —
    the OFF half of item 02's contract).

### 4 · GREEN + REFACTOR + equivalence

* **GREEN:** create `policy.py` (5 functions), apply the 5 gate edits, add the `"out_of_scope"`
  vocabulary line to `captcha/signals.py`'s docstring.
* **REFACTOR:** none required — `_watcher_running` shrinking 8 → 3 lines is the refactor. Confirm
  `captcha/service.py` `max_func_loc` stays **27** and `func_count` stays **23** (no new function in
  that file: the gate is 1 line inside `handle_captcha`).
* **Existing tests that must change (recorded reason, `quality-budget.md` §6.2):**
  | Test | Change | Reason |
  |---|---|---|
  | `tests/test_captcha_boundaries.py:89-109,217` | `make_bridge(pool)` → `make_bridge(pool, {"watcher_enabled": True})` at the three captcha call sites (the helper already accepts a `session` dict, `:25-28`) | the switch is now load-bearing; without arming it these tests would assert the OFF path while intending the ON path |
  | `tests/test_single_job_runner.py:400,464` | same arming on the ctx bridge | idem |
  | `tests/characterization/harness.py:105-121` (`build_bridge`) | add `watcher_on: bool = False` param ⇒ `cfg.set_state(watcher_enabled=True)`; `test_batch_goldens.py:124-132` (`test_captcha_pause_resume`) passes `watcher_on=True` | the harness builds a **real** `Bridge` with a real `ConfigManager`, whose `DEFAULT_SESSION` has `watcher_enabled: False` (`config_manager.py:22`) — without arming, `goldens/captcha.json` would lose one `["CHECK_SECURITY","running"]` event. Armed, the golden stays **byte-identical** |
* **Equivalence (must stay green, unedited):** the other 11 goldens (no visible dialog in any of
  them), `tests/test_captcha_service.py`, `tests/test_captcha_watcher.py`,
  `tests/test_cooldown_service.py:604-618`, `tests/test_bridge_slots.py`.
* **Gate:** fast lane + `captcha/service.py` coverage must not drop below its recorded floor;
  `single_job_runner.py` gains ≤4 lines (legacy 902-line file — RULE 18.2 direction acknowledged in
  `quality-budget.md` §5, no symbol worsens: spans 12/13/19 vs file max 26, CC 4/4/3 vs max 9).
* **Docs in the same commit:** RULE 20 amendment (OFF ⇒ captcha out of scope), I-19/I-34/I-40,
  SYSTEM_OF_RECORD row 12.

---

## S3 · Captcha ⇄ generation timeout — the capped pause

### 0 · Scope

A captcha wait stops burning the page's generation timeout, and both the wait and the pause end at the
user's `watcher_captcha_timeout_sec` (D-14R). At the cap the job fails honestly as `wait_timeout`
(retryable, no penalty, normal cooldown). Interface boundary after S3: one value object
(`PauseClock`) that the browser layer charges and the wait loop reads, one deadline object
(`WaitDeadline`) that the captcha layer composes into the predicate it already passes, and one new
outcome status.

### 1 · Interface split

**Why `PauseClock` cannot live in `output_wait.py`** (this is the split the ratchet dictates):
`app/browser/output_wait.py` records `max_class_loc = 4` — its two dataclasses `WaitSpec` (span 3) and
`LoopState` (span 4) — and `verify_quality.py:172-175,296-309` fails **any growth of a recorded
maximum, even inside a baselined file**. A ~50-line class there would take `max_class_loc` 4 → ~50.
`app/core/` is the only layer both chargers may import (`SYSTEM_OF_RECORD.md:228`:
`ui → ui-services/browser → services → core`), so:

| Symbol | Signature | Budget (new file ⇒ RULE 16 hard limits only) | Called by | Must **not** |
|---|---|---|---|---|
| `core/pause_clock.PauseClock` | class, `cap_s: float = 0.0` | ≤60 LOC · ≤6 methods (limits 150/15) | `single_job_runner.wait_for_output` creates it; `cdp_arena/output._settle_timed` charges it; `output_wait._check_timeout` reads it | import browser/services; hold a lock (one wait, one coroutine); raise |
| `.note(seconds)` | `(self, seconds: float) -> None` | ≤8 · CC ≤4 | `_settle_timed` | charge more than `cap − total` (R22: a second settle in the same wait absorbs nothing) |
| `.expired()` | `(self) -> bool` | ≤3 · CC ≤2 | `_check_timeout`, `describe` | return True when `cap_s <= 0` (uncapped = never expires) |
| `.remaining()` | `(self) -> float` | ≤3 · CC ≤2 | `describe`, S9's worker line | go negative |
| `.paused_elapsed(start, now=None)` | `(self, start: float, now: float \| None = None) -> float` | ≤6 · CC ≤3 | `_check_timeout` | return < 0; call `time.monotonic()` twice |
| `.describe()` | `(self) -> str` | ≤6 · CC ≤3 | the timeout text + S9 | include token material or the sitekey (RULE 20) |
| `.total` | attribute (float) | — | tests, S9 | be reset by anything but a new wait |

**Existing symbols that change** (measured at `6bbaf8b` with `tools/verify_quality.current_maxima`;
"room" = recorded file maximum − current symbol value):

| Site | Now | Edit | After | Room check |
|---|---|---|---|---|
| `output_wait.WaitSpec:23-26` | span **3** | `+ pause: Optional[PauseClock] = None` | span **4** | file `max_class_loc` **4** ⇒ exactly at the ceiling, legal. `LoopState` (span 4) must **not** gain a field |
| `output_wait.wait_for_new_output_with_spec:189-211` | loc **23** · CC **8** · nest **3** · params **4** | **none** | unchanged | all four are the file maxima ⇒ this function has *zero* headroom; the clock rides on `spec`, so the loop body never changes |
| `output_wait._check_timeout:151-162` | loc 11 · CC 4 · nest 1 · params 3 | `elapsed = spec.pause.paused_elapsed(state.start) if spec.pause else time.monotonic() - state.start`; stamp `paused_s` + `pause_note` into the returned dicts | loc ≤16 · CC ≤6 · params **3** | file maxima 23 / 8 / 3 / 4 ⇒ room +12 loc, +4 CC, +1 param (unused) |
| `cdp_arena/output._security_gate:115-125` | loc 10 · **CC 4** · **nest 1** | call `_settle_timed(settler, clock)` instead of `await settler()` | loc 12 · CC **4** · nest 1 | CC 4 and nest 1 **are** the file maxima ⇒ not one branch may be added here; hence the extraction below |
| `cdp_arena/output._settle_timed` **(new)** | — | `t0 = time.monotonic(); await settler(); if clock is not None: clock.note(time.monotonic() - t0)` | loc ≤8 · CC ≤2 · nest ≤1 · params 2 | new symbol in a baselined file: hard limits + must not raise the file maxima (CC 2 ≤ 4 ✓, loc 8 ≤ 16 ✓) |
| `cdp_arena/output._run_wait:158-172` | loc 14 · CC 2 · params 3 | `PollSpec(..., pause=getattr(spec.ctrl, "pause_clock", None))` **on the existing line** | loc **14** | file `max_func_loc` 16 ⇒ a 2-line version would also fit, but the same-line form keeps `_run_wait` away from the ceiling |
| `cdp_arena/output._map_wait_result:127-136` | loc 10 · CC 3 · **params 4** | error text via a new `_timeout_text(result, timeout_ms)` helper | loc 11 · CC 3 | params 4 = file max ⇒ the pause note must ride **inside `result`**, never as a 5th argument |
| `cdp_arena/output._timeout_text` **(new)** | — | `f"Timeout after {ms}ms" + (f" ({note})" if note else "")` | loc ≤6 · CC ≤3 · params 2 | keeps `_map_wait_result`'s CC at 3 |
| `captcha/policy.pause_cap_seconds(bridge)` **(new)** | — | `watcher_captcha_timeout_sec`, clamped 10…3600, default 300 | ≤8 · CC ≤3 · 1 param | add a second config key (D-14R: one knob; §12 item 6 is the follow-up) |
| `captcha/policy.wait_reason(bridge)` **(new)** | — | ON+key / ON+no-key wording (D-15) | ≤10 · CC ≤4 · 1 param | mention solving when there is no key |
| `captcha/policy.WaitDeadline` **(new)** | `__init__(cap_s)`, `expired()`, `stop_or(stop)` | class ≤30 LOC · 3 methods | `_manual_wait` | touch `cooldown_service.py`; add a param to `wait_captcha_cleared` |
| `captcha/service._manual_wait:251-277` | loc **27** (file max) · CC 5 · **params 4** | compose the deadline into the `stop` it already passes; replace the 8-line outcome block with `_wait_outcome(...)` | loc **~21** · CC ≤5 · params 4 | the file's `max_func_loc` **drops** 27 → ~21 (shrink is always legal) |
| `captcha/service._wait_outcome` **(new)** | — | `solved` ⇒ `manual` (+stats +penalty); `deadline.expired()` ⇒ `wait_timeout`; else `stopped` | loc ≤14 · CC ≤5 · params **4** | exceed 4 params (file max); record a penalty on the timeout path |
| `single_job_runner.wait_for_output:246-262` | loc 19 · CC 5 · nest 1 | install `ctx.ctrl.pause_clock = PauseClock(pause_cap_seconds(ctx.bridge))` next to the settler (in scope only) and `delattr` it in the same `finally` | loc ≤22 · CC ≤6 | install the clock when the Watcher is OFF (D-23's counting test asserts its absence) |
| `single_job_runner._run_security_captcha:89-105` | loc 17 · CC 3 · params 1 | build the `WaitDeadline` and pass `deadline.stop_or(stop)` as `CaptchaCtx.stop` | loc ≤19 · CC ≤4 | change `CaptchaCtx`'s field list |
| `single_job_runner._handle_captcha_outcome:75-85` | loc 11 · CC 6 · params 2 | `if outcome.status == "wait_timeout": raise RuntimeError(outcome.reason or …)` | loc ≤13 · CC ≤7 | mark the job non-retryable; skip the cooldown |

**Untouchable in this stage (proved by numbers, not by taste):**
`cooldown_service.wait_captcha_cleared` — loc 18 · CC 7 · nest 2 · **params 4 = file maximum** and its
"never gives up" behaviour is pinned by `tests/test_cooldown_service.py:604-618`; the cap therefore
rides the caller's `stop` predicate. `page_pool.add_page` — loc 23 · **CC 10** · nest 3, all three at
the file maxima *and* CC at the RULE 16 hard limit ⇒ no stage may edit `PagePool`.

### 2 · Expected files & functions

```
app/core/pause_clock.py                  (new, ~55 LOC — the value object; core 13 → 14 files)
    class PauseClock: __init__, note, expired, remaining, paused_elapsed, describe
app/services/captcha/policy.py           (S3 additions, file 35 → ~55 LOC)
    pause_cap_seconds(bridge) -> int
    wait_reason(bridge) -> str
    class WaitDeadline: __init__, expired, stop_or
app/browser/cdp_arena/output.py          (+2 functions, +~14 lines)
    _settle_timed(settler, clock) -> None
    _timeout_text(result, timeout_ms) -> str
app/services/captcha/service.py          (+1 function, −6 lines net)
    _wait_outcome(ctx, signal, solved, deadline) -> SolveOutcome
tests/test_pause_clock.py                (new, ~95 LOC, 8 tests)
tests/test_output_wait_timeout_pause.py  (new, ~115 LOC, 5 tests)
tests/test_captcha_wait_cap.py           (new, ~125 LOC, 6 tests)
tests/test_captcha_wait_reason.py        (new, ~70 LOC, 4 tests)
```

### 3 · RED — tests written first

`tests/test_pause_clock.py` (pure value object, no fakes):

1. `test_note_accumulates_and_ignores_garbage` — `note(1.5); note(2.5)` ⇒ `total == 4.0`;
   `note(0)`, `note(-3)`, `note(float("nan"))` change nothing and never raise.
   **RED at base:** `ModuleNotFoundError: app.core.pause_clock`.
2. `test_cap_is_cumulative_per_wait` — `PauseClock(cap_s=10)`; `note(6); note(6)` ⇒ `total == 10`
   (the second settle absorbs 4, not 6) and `expired() is True`. This is R22's lock.
3. `test_uncapped_clock_never_expires` — `PauseClock()` (`cap_s=0`): `note(10_000)` ⇒ `expired()` False,
   `remaining()` is `inf`-like (assert `remaining() > 10_000`).
4. `test_paused_elapsed_subtracts_and_floors_at_zero` — `paused_elapsed(start=100, now=130)` with
   `total == 12` ⇒ `18`; with `total == 40` ⇒ `0` (never negative).
5. `test_paused_elapsed_defaults_to_now` — a real `time.monotonic()` start ⇒ result ≥ 0 and monotone
   across two calls (uses `fake_clock` from `conftest.py:111` to stay deterministic).
6. `test_describe_names_absorbed_and_cap` — `"+12s captcha wait (cap 300s, 288s left)"` shape: contains
   the absorbed seconds, the cap, and the remaining budget; empty string when `total == 0`.
7. `test_remaining_never_negative`.
8. `test_clock_is_not_shared_between_waits` — two clocks are independent (the per-generation-wait rule).

`tests/test_output_wait_timeout_pause.py` (real `wait_for_new_output_with_spec`, real `WaitSpec`, a
`check_fn` that blocks — no mock of the loop itself, RULE 8):

9. `test_a_long_settle_does_not_time_out_when_a_clock_absorbs_it` — `spec.timeout = 0.2`,
   `check_fn` sleeps 0.6 s on the first poll while `clock.note(0.6)` is charged, then returns ready ⇒
   `result["ready"] is True`.
   **RED at base:** `TypeError: WaitSpec.__init__() got an unexpected keyword argument 'pause'`.
10. `test_the_same_wait_times_out_without_a_clock` — identical `check_fn`, `pause=None` ⇒
    `result["reason"] == "timeout"`. *Equivalence: this is the Watcher-OFF half of the contract and it
    is green at base once the field exists* — it is the test that proves the pause is the only change.
11. `test_the_timeout_result_carries_the_pause_evidence` — on timeout with a charged clock:
    `result["paused_s"] == pytest.approx(0.6, abs=0.05)` and `"captcha wait" in result["pause_note"]`.
12. `test_an_exhausted_cap_times_out_even_with_the_dialog_up` — `PauseClock(cap_s=0.1)`, a `check_fn`
    that never becomes ready and keeps settling ⇒ `reason == "timeout"` and `paused_s <= 0.1 + eps`.
13. `test_wait_spec_pause_defaults_to_none` — `WaitSpec(timeout=1).pause is None` ⇒ every existing
    caller (`output_wait_fallback`, `cdp_arena`) is untouched.

`tests/test_captcha_wait_cap.py` (D-14R end to end; real `handle_captcha`, real
`wait_captcha_cleared`, fake ctrl whose dialog never clears, `fake_clock` for the cap):

14. `test_a_dialog_that_never_clears_ends_at_the_cap` — config `watcher_captcha_timeout_sec = 1`,
    watcher ON ⇒ `outcome.status == "wait_timeout"` and the reason names the cap.
    **RED at base:** the call never returns (the wait is unbounded) — the test is written with
    `asyncio.wait_for(..., 5)` so at base it fails with `TimeoutError`, which *is* the defect.
15. `test_wait_timeout_maps_to_a_retryable_job_failure` — `_handle_captcha_outcome(ctx, outcome)`
    raises `RuntimeError` whose text carries the cap; the image ends `failed` with
    `attempt_count` unchanged (retryable) and **no** penalty recorded
    (`note_captcha_event` spy: 0 calls).
16. `test_stop_before_the_cap_still_yields_stopped` — `ctx.stop` returns True at 0.2 s with a 10 s cap
    ⇒ `status == "stopped"` (the existing vocabulary wins over the new one).
17. `test_the_cap_moves_with_the_setting_without_a_restart` — 1 s ⇒ capped at ~1 s; set 2 s mid-test ⇒
    the next wait is capped at ~2 s (per-call read, no cached value).
18. `test_wait_captcha_cleared_is_called_unchanged` — a spy on
    `app.services.cooldown_service.wait_captcha_cleared` asserts **exactly 4 positional arguments**
    and that the second one is a callable that becomes True at the cap. This is the lock that keeps
    `cooldown_service.py` and `tests/test_cooldown_service.py:604-618` unedited.
19. `test_the_cooldown_still_applies_after_a_wait_timeout` — the tab enters its normal job-cycle
    cooldown (the failure is honest, not a free pass).

`tests/test_captcha_wait_reason.py` (D-15 wording):

20. `test_on_with_key_says_the_watcher_is_solving` · 21. `test_on_without_key_says_solve_it_in_chrome`
    (and names the paused generation timeout) · 22. `test_off_never_reaches_the_wording`
    (`wait_reason` is not called when out of scope — S2's gate returns first) ·
    23. `test_the_overlay_receives_timeout_and_sub` — `show_watcher_overlay` spy asserts
    `timeout_sec == cap` and `sub == wait_reason(...)`, i.e. the visible countdown and the cap are the
    same number (D-14R's "the cap is visible while it runs").

### 4 · GREEN + REFACTOR + equivalence

* **GREEN:** create `core/pause_clock.py`; add the three `policy` symbols; add `_settle_timed` +
  `_timeout_text`; thread `pause` through `WaitSpec` → `_check_timeout`; extract `_wait_outcome`;
  install/clear the clock in `wait_for_output`; add the `wait_timeout` branch.
* **REFACTOR:** `_manual_wait` 27 → ~21 lines (the file's `max_func_loc` drops with it);
  `handle_captcha`'s S2 split (`_handle_captcha_scoped`) stays; no new if/elif chains anywhere —
  the outcome decision is a 3-branch function, the wording a 2-row lookup (RULE 19).
* **Equivalence (green, unedited):** `tests/test_cooldown_service.py:604-618` (the pinned
  never-gives-up behaviour), `tests/test_output_wait*.py`, `tests/test_cdp_arena*.py`,
  all 12 goldens — verified safe because **no golden contains the string `Timeout`**
  (`grep -l "Timeout" tests/characterization/goldens/*.json` ⇒ empty) and the harness ctrl stubs
  `wait_for_new_output` wholesale (`tests/characterization/fakes.py:125-135`).
* **Gate:** fast lane; `output_wait.py` `max_class_loc` must still read **4**, `max_func_loc` **23**,
  `max_cc` **8**; `cdp_arena/output.py` `max_cc` must still read **4** (the `_settle_timed` extraction
  is what keeps it there); `captcha/service.py` `max_func_loc` must read **≤21** (it drops).
* **Docs in the same commit:** RULE 20 (the wait is bounded; the pause is capped), I-44,
  SYSTEM_OF_RECORD rows 8 and 12, `evidence.md` §2.1 marked closed.

---

## S4 · Live queue core + every reset re-queues (D-6R)

### 0 · Scope

One eligibility rule, one queue-write funnel, one wake event. Every queue mutation — Reset, Reset All,
Retry, Retry Failed, select/bulk-select, clear, scan, preset load — ends in `commit_queue`, which
recalculates, saves, pushes undo, emits, and wakes the (S5) loop. D-6R: both resets return images to
`pending` **and** `selected=True`. Interface boundary after S4: `app/services/live/` exists with
`bus` + `feed`, and every later stage writes through them.

### 1 · Interface split

| Symbol | Signature | Budget (new files ⇒ hard limits; RULE 18 targets in brackets) | Called by | Must **not** |
|---|---|---|---|---|
| `live/bus.LiveBus` | class: `attach(loop)`, `wake(reason)`, `wait(timeout_s) -> str`, `throttle(key, ms) -> bool`, `reasons() -> list` | ≤90 LOC · ≤6 methods · each method ≤18 LOC / CC ≤5 [RULE 18: 4-20] | `commit_queue`, `commit_urls` (S6), pool emits, S5's loop | import Qt or panels; hold `_state_lock` across an `await` |
| `live/bus.live_bus(bridge) -> LiveBus` | one per bridge, created in `bridge_context.init_run_state` | ≤8 · CC ≤3 | everyone | create a second bus |
| `live/feed.ELIGIBLE` | `("pending", "failed", "selected", "needs_review")` | constant | the only rule | include `"processing"` (double-dispatch protection; the crash case moves to `recover_stale_processing`) |
| `live/feed.eligible_images(images) -> list` | snapshot copy, filter | ≤6 · CC ≤2 | `plan_pass` (S5), `next_queued` (S9), `queue_scan.selected_images` (delegation) | mutate the list it is given |
| `live/feed.commit_queue(bridge, reason, undo=True) -> int` | recalc → save → undo → emit → `wake(reason)`; returns the pending count | ≤14 · CC ≤4 · **3 params** | the 8 panel slots + 2 scan workers + 2 preset sites | take a 4th positional param; skip the emit; push undo when `undo=False` (system changes, I-37) |
| `live/feed.recover_stale_processing(bridge) -> int` | `processing` with no live tab job → `pending` + `selected` | ≤14 · CC ≤5 | `start_run` (S4) and `run_live` (S5) | touch images whose tab has a live job (`cooldown_service.tab_has_live_job:163-175`) |
| `live/feed.clear_row_assignments(bridge, row_ids) -> int` | drop dangling `assigned_url_id` | ≤12 · CC ≤4 | S6's reconciler | delete images |
| `run_state.schedule_batch(bridge, coro)` | submit + **always** track + done-callback | ≤10 · CC ≤3 · 2 params | `start_run` (S4 keeps `run_batch`, S5 passes `run_live`) | sniff `coro.cr_code.co_name` (that is `_track_batch_future:118-125`, deleted here) |

**Existing symbols that change** (measured):

| Site | Now | After | Note |
|---|---|---|---|
| `run_control.reset_image_state:46-53` | loc 8 · params **2** | `(img) -> None`, `selected=True` inside · loc 8 · params **1** | D-6R; the parameter disappears, so no caller can pass `False` again |
| `run_control.reset_all:187-195` | loc 8 · CC 2 | tail → `count = commit_queue(self, "reset_all")` + `↻ Reset all: {count} images re-queued` · loc ≤8 | `RunControlMixin` has **10 methods = file max** ⇒ no new methods, module funcs only |
| `run_control.reset_image:210-219` | loc 9 · CC 3 · nest 2 | same tail · loc ≤8 | the count line makes D-6R observable (RULE 2) |
| `run_control.retry_image:197-208` / `retry_failed:164-170` | loc 11 / 6 | same tail · loc ≤9 / ≤6 | one funnel, four call sites |
| `run_control.start_run:221-238` | loc 17 · CC 4 | `recover_stale_processing(self)` before scheduling (keeps the `ELIGIBLE` change behaviour-preserving **before** S5 lands) · loc ≤19 | file max loc 19 ⇒ keep it at ≤19 |
| `queue_scan.selected_images:28-31` | loc 4 · CC 3 | 2-line delegation to `feed.eligible_images` · loc 3 | 6 test modules import this name ⇒ it stays |
| `queue_scan.set_image_selected:283-292` / `bulk_select:294-300` / `clear_queue_images:83-92` | loc 11 / 6 / 9 | tails → `commit_queue` · loc ≤8 / ≤5 / ≤7 | net LOC **decrease** in the panel |
| `queue_scan.run_scan_merge:96-108` / `run_scan_new_batch:111-127` | loc 14 / 17 | tail → `commit_queue(bridge, "scan", undo=False)` | worker threads: `wake` must be thread-safe (`call_soon_threadsafe`) |
| `app_settings.import_preset:286-301` / `load_arena_preset:326-344` | loc 16 / **18 = file max** | 2 lines → 1 (`commit_queue(self, "preset", undo=False)`) · loc 15 / 17 | `load_arena_preset` is at the file ceiling, so the funnel must *shrink* it |
| `batch_orchestrator._selected_images:374-377` | loc 4 · CC 3 | **deleted**; `_load_run_settings:379-382` calls `feed.eligible_images` | removes the L-4 clone (jscpd floor improves) |
| `run_state._track_batch_future:118-125` | loc 7 · CC 4 | **deleted** (name sniffing) | `_submit_tracked:159-164` keeps tracking; `schedule_batch` tracks deliberately |
| `bridge_context.init_run_state:32-39` | loc 8 · CC 1 · nest 0 | `+ bridge._live_bus = LiveBus()` `+ bridge._state_lock = threading.RLock()` · loc 10 | file max loc 19 ⇒ ample |

### 2 · Expected files & functions

```
app/services/live/__init__.py   (new, ~30 LOC — re-export facade, RULE 16.0 waiver comment)
app/services/live/bus.py        (new, ~90 LOC)   LiveBus(attach, wake, wait, throttle, reasons) · live_bus(bridge)
app/services/live/feed.py       (new, ~150 LOC)  ELIGIBLE · eligible_images · commit_queue · recover_stale_processing · clear_row_assignments
tests/test_live_bus.py          (new, ~110 LOC, 6 tests)
tests/test_live_feed.py         (new, ~130 LOC, 7 tests)
tests/test_reset_requeues.py    (new, ~95 LOC, 5 tests)
```

`app/services/` gains a package: 12 files + 6 packages → `live/` with 3 files now, 7 after S6
(RULE 18.3 module ideal 5-15 ✓).

### 3 · RED — tests written first

`tests/test_live_bus.py`:

1. `test_wake_from_another_thread_releases_wait` — a real `threading.Thread` calls `wake("queue")`
   while the loop thread sits in `wait(5)` ⇒ returns `"queue"` in < 100 ms (uses `event_loop` +
   `fake_clock`; no real sleeping). **RED at base:** `ModuleNotFoundError: app.services.live`.
2. `test_wait_times_out_with_an_empty_reason` — no wake ⇒ `wait(0.05) == ""`.
3. `test_reasons_drain_once` — two wakes before a wait ⇒ one wait returns both reasons (or the joined
   reason) and the next returns `""` (no sticky wake).
4. `test_throttle_allows_one_line_per_window_and_one_per_change` — `throttle("no tab", 300)` True once,
   False immediately after, True again after the window (fake clock).
5. `test_wake_without_an_attached_loop_is_safe` — `wake` before `attach` neither raises nor loses the
   reason (the loop may start after a slot fired).
6. `test_one_bus_per_bridge` — `live_bus(bridge) is live_bus(bridge)` and a second bridge gets its own.

`tests/test_live_feed.py`:

7. `test_eligible_images_is_the_only_rule` — a queue with one image per status ⇒ exactly the four
   `ELIGIBLE` statuses come back, `processing` excluded, and the input list is **not** mutated
   (snapshot copy).
8. `test_commit_queue_recalculates_saves_pushes_undo_emits_and_wakes` — a `FakeBridge`
   (`tests/fakes/fake_bridge.py`) with spies: after `commit_queue(bridge, "reset_all")` all five
   happened **in that order**, and the return value is the pending count.
   **RED at base:** `ModuleNotFoundError`.
9. `test_commit_queue_without_undo_pushes_nothing` — `undo=False` ⇒ `undo_service.push` not called
   (system changes stay out of the user's history, I-37/`browser_tabs.py:319-336`).
10. `test_recover_stale_processing_skips_live_jobs` — an image `processing` on a tab with
    `current_image` set stays; one on a tab without a live job goes `pending` + `selected`
    (real `PagePool` + `cooldown_service.set_tab_image`, RULE 8).
11. `test_clear_row_assignments_only_touches_the_removed_rows`.
12. `test_commit_queue_is_thread_safe_from_a_worker` — called from a thread while the main thread
    reads `bridge.state.images` ⇒ no torn state (`_state_lock`), and the lock is **never** held across
    an `await` (asserted by a spy that records lock ownership around the coroutine boundary).
13. `test_queue_scan_selected_images_delegates` — `queue_scan.selected_images(images) ==
    feed.eligible_images(images)` for a mixed queue (kills the L-4 clone: if either copy comes back,
    the equality fails).

`tests/test_reset_requeues.py` (D-6R, real `Bridge` via `tests/characterization/harness.build_bridge`):

14. `test_reset_all_requeues_every_image_selected` — after a run leaves images `completed`/`failed`,
    `reset_all()` ⇒ every image `status == "pending"` **and** `selected is True`, `error is None`,
    `attempt_count == 0`, and `eligible_images` returns all of them.
    **RED at base:** `selected is False` (`reset_image_state(img, False)`, `run_control.py:190`).
15. `test_reset_image_requeues_that_image_selected` — same for the single-row slot
    (`run_control.py:214`).
16. `test_reset_wakes_the_loop_and_logs_the_count` — `live_bus(bridge).wait(0.05) == "reset_all"` and
    one log line matches `r"Reset all: \d+ images re-queued"`.
    **RED at base:** no bus, no wake, no count line.
17. `test_reset_is_undoable` — `undo()` restores the prior statuses (the funnel's undo push).
18. `test_reset_image_state_has_no_selection_parameter` — signature lock:
    `inspect.signature(reset_image_state).parameters == {"img"}` (so `False` can never come back).

### 4 · GREEN + REFACTOR + equivalence

* **GREEN:** the three `live/` files, the funnel tails, the parameter deletion, `schedule_batch`,
  `_live_bus`/`_state_lock` in `init_run_state`.
* **REFACTOR:** both panels get **shorter** (`run_control.py` 275 → ~268, `queue_scan.py` 315 → ~308);
  the duplicated eligibility rule is gone (jscpd 1.240 % floor must not rise).
* **Existing tests that must change:** `tests/test_run_control*.py` / `tests/test_panel_*.py` cases
  that assert `selected is False` after a reset (D-6R reverses it — reason recorded), and any test that
  calls `reset_image_state(img, False)` positionally (the signature lock above).
* **Equivalence (green, unedited):** all 12 goldens — the harness never resets mid-run, and
  `check_golden` excludes `logs` (`harness.py:184`), so the new count line cannot drift a golden;
  `tests/test_bridge_slots.py` (Σ=134: `commit_queue` is a module function, **not** a slot).
* **Gate:** fast lane + `run_control.py`/`queue_scan.py` `max_methods` must stay **10** (no new
  mixin methods), `app_settings.py` `max_func_loc` must stay **18**.
* **Docs:** I-41, I-46, SYSTEM_OF_RECORD rows 6/8/11.

---

## S5 · The always-live run

### 0 · Scope

`run_live` replaces "one batch then idle": the run survives no-work / no-tab / all-cooling / CDP-down
by waiting on S4's bus, and exactly one writer owns `run_state` (D-8, which also fixes L-2 —
`AppState.run_state` is persisted but never written today, `models.py:244,260`). Interface boundary
after S5: `plan_pass` is the only place that reads queue/URL/pool liveness, and the orchestrator and
dispatcher are pass bodies with no lifecycle opinions.

### 1 · Interface split

| Symbol | Signature | Budget (new file) | Called by | Must **not** |
|---|---|---|---|---|
| `live/supervisor.run_live(bridge)` | `async (bridge) -> None` | ≤28 LOC · CC ≤8 · nest ≤3 · 1 param | `start_run` via `schedule_batch` | write `_run_state` anywhere but `set_run_state`; swallow `CancelledError` |
| `live/supervisor.set_run_state(bridge, value)` | `(bridge, value: str) -> None` | ≤10 · CC ≤3 | **the only writer** (D-8) | be called from the orchestrator/dispatcher afterwards |
| `live/supervisor.plan_pass(bridge) -> PassPlan` | fresh read every pass | ≤20 · CC ≤6 · 1 param | `run_live` | hold `_state_lock` across an `await`; cache the plan |
| `live/supervisor.PassPlan` | dataclass `images, urls, allowed, tab_id, reason` | span ≤8 (new file) | `prepare_batch`, `run_pass`, `pass_tail` | carry a bridge reference |
| `live/supervisor.is_live(bridge) -> bool` | `not _cancel_requested and not _stop_after` | ≤4 · CC ≤2 | the loop | read `_run_state` (flags are the truth) |
| `live/supervisor.wait_reason(bridge, plan, bus)` | throttled line + `bus.wait(1.0)` | ≤14 · CC ≤4 · 3 params | the no-work branch | end the run; spin without waiting |
| `live/supervisor.run_pass(bridge, plan)` | dispatch to the existing lane | ≤16 · CC ≤5 | the work branch | duplicate the sequential/parallel decision (it stays in `prepare_batch`) |
| `live/supervisor.pass_tail(bridge, plan)` / `cancelled_tail(bridge)` / `completed_tail(bridge)` | log-only tails | ≤10 each | end of pass / end of run | write run state |
| `live/supervisor.REASON_LINES` | `{reason: (template, level)}` lookup | constant | `wait_reason` | become an if/elif chain (RULE 19) |

**Existing symbols that change:**

| Site | Now | After |
|---|---|---|
| `batch_orchestrator.run_batch:~385` / `_cancel_batch` / `_crash_batch` | loc 9 / 5 / 10 | **move to `supervisor`** (the pass body stays); `batch_orchestrator.py` 492 → ~445 |
| `batch_orchestrator.prepare_batch:15 loc · CC 4` | reads a snapshot | takes the `PassPlan` (no re-snapshot) |
| `batch_orchestrator._run_sequential:10 loc · CC 4 · nest 2` | ends the batch | drops its tail call (the supervisor owns the loop) |
| `batch_orchestrator._finish_batch:8 loc` | writes run state + logs | → `pass_complete(ctx)` (log only) |
| `batch_orchestrator._abort_no_tab:5 loc` | ends the run when no tab | **deleted** — the supervisor waits instead |
| `batch_orchestrator._claim_tab:8 loc · CC 2` | resolves once | refreshes `ctx.allowed` from live state before resolving (per-image URL liveness) |
| `multi_page_dispatcher._finalize_batch:8 loc · CC 2` | writes `_run_state` | log + emits only |
| `run_control.start_run:221-238` | `schedule_coro(self, run_batch(self))` | `schedule_batch(self, run_live(self))`; when already live ⇒ `wake` + `🟢 Run already live — queue re-checked (N queued)` instead of `⚠ Already running` |
| `queue_scan.run_folder_ai_request:135-152` | refuses unless `_run_state == "idle"` | refuses only when an image is `processing` (D-5 makes the old guard permanently closed) |
| `layout_state.emit_arena_state:38-47` | patches `prog["run_state"]` from the attribute | unchanged — the attribute is now honest (D-8/L-2) |

### 2 · Expected files & functions

```
app/services/live/supervisor.py   (new, ~230 LOC — live/ 3 → 4 files)
tests/test_live_supervisor.py     (new, ~180 LOC, 9 tests)
```

### 3 · RED — tests written first

`tests/test_live_supervisor.py` (real `Bridge` from the golden harness + `FakeActionRunner`; the loop
is driven with `fake_clock`, never with real sleeps):

1. `test_no_work_waits_and_never_ends` — an empty queue: run `run_live` as a task, advance the fake
   clock 60 s ⇒ the task is **still pending**, `_run_state == "running"`, and the throttled
   `🟢 Run live — 0 queued images` line appeared **once**.
   **RED at base:** `ModuleNotFoundError: app.services.live.supervisor`.
2. `test_new_work_is_picked_up_without_a_restart` — while waiting, `commit_queue(bridge, "reset_all")`
   ⇒ the next pass dispatches the image within one bus wait (≤ ~50 ms of fake time).
3. `test_no_tab_all_cooling_and_cdp_down_are_wait_states` — parametrised over the three reasons ⇒
   still running, one throttled line each, `plan.reason` equals the expected key.
4. `test_stop_is_the_only_way_out` — `cancel_current()` ⇒ the task ends, `_run_state == "idle"`,
   `🏁 Batch cancelled` logged (the pinned marker substring survives).
5. `test_stop_after_current_finishes_the_pass_then_ends` — `arm_hooks(after_finish=…)`-style:
   `_stop_after = True` mid-pass ⇒ the in-flight image completes, then `🏁 Batch complete`
   (**pinned marker**, `test_batch_goldens.py:37,47`) and `idle`.
6. `test_run_state_has_exactly_one_writer` — monkeypatch `set_run_state` with a spy and run a full
   pass: every `_run_state` change came through the spy; `batch_orchestrator` and
   `multi_page_dispatcher` contain no `_run_state =` assignment (source-level assertion, the L-2 lock).
7. `test_start_while_live_wakes_instead_of_refusing` — a second `start_run()` ⇒ no
   `⚠ Already running`, one `🟢 Run already live` line, and a `wake` recorded.
8. `test_folder_ai_is_refused_only_while_an_image_processes` — with the run live but idle ⇒ allowed;
   with an image `processing` ⇒ `{"ok": False, "error": "stop the run first"}`-class refusal.
9. `test_goldens_are_byte_identical_under_the_supervisor` — the 12 characterization scenarios re-run
   with `RUNNERS = {"supervisor": run_supervisor}` ⇒ `check_golden` passes for all 12 **without**
   `UPDATE_GOLDENS=1`.

### 4 · GREEN + REFACTOR + equivalence

* **GREEN:** `supervisor.py`, the orchestrator/dispatcher tail surgery, `start_run`'s new schedule.
* **REFACTOR:** `batch_orchestrator.py` 492 → ~445 lines and its `max_func_loc`/`max_cc` can only
  shrink (the moved functions were 9/5/10 LOC); `run_state.py` loses the name-sniffing tracker.
* **Existing tests that must change (recorded reasons):**
  | Test | Change | Reason |
  |---|---|---|
  | `tests/characterization/harness.py:205-208` | `RUNNERS` gains `run_supervisor` (`await live.supervisor.run_live(env.bridge)`), and the golden tests keep `_stop_after` as the stop lever (`arm_hooks`, `:211-231`) | `run_batch` no longer writes `_run_state`, and the trace **does** record `run_state` (`harness.py:167`) — without the supervisor runner every golden would drift to `"?"` |
  | `tests/test_batch_orchestrator.py` | cases that assert the batch ends the run move to `test_live_supervisor.py` | the lifecycle moved; the pass body assertions stay |
* **Equivalence:** the 12 goldens must be **byte-identical** (`logs` are excluded from the compare, so
  the new live-run lines are free); `evals` must not change (the supervisor adds no probes).
* **Gate:** fast lane + goldens; `multi_page_dispatcher.py` `max_func_loc` must stay **29**.
* **Docs:** I-39, SYSTEM_OF_RECORD rows 6/11, `QUALITY_RECHECK.md` note.

---

## S6 · Dynamic URLs + the interval setting (D-12R)

### 0 · Scope

Python owns the URL reconcile cadence: the JS 15 s timer dies, a reconciler loop runs at a
user-set interval in every run state, rows follow Chrome (add/claim/remove with a reason), tab joins
go through S1's repaired path, and every change commits through S4's funnel + `wake("urls")`. The
setting ships **with** its control (D-12R): a new `url-list/interval.js` in the URL List job-cycle bar.

### 1 · Interface split

**New modules (services never import panels — `LiveDeps` is the seam, round-1 D-10):**

| Symbol | Signature | Budget | Called by | Must **not** |
|---|---|---|---|---|
| `live/reconcile.LiveDeps` | dataclass `fetch_tabs, join_tab, commit, log` (4 callables) | span ≤8 | built in ui land, injected at start | import `app.ui.*` or `app.browser.*` inside `live/` |
| `live/reconcile.start_reconciler(bridge, deps)` | idempotent start via `schedule_coro` | ≤12 · CC ≤4 · 2 params | `browser_tabs.start_url_reconciler` | start a second loop (mirror `watcher_solver.solver_start:128-138`) |
| `live/reconcile.reconcile_loop(bridge, deps)` | `async`, reads the interval **every pass** | ≤16 · CC ≤5 | `start_reconciler` | cache the interval; remove rows on an empty fetch |
| `live/reconcile.reconcile_once(bridge, deps, source) -> Report` | one pass (= today's `auto_scan_pass`) | ≤28 · CC ≤9 · **3 params** (a spec object, not 6 args) | the loop, the `auto_connect_scan` slot, the Reparse buttons | write rows without `deps.commit`; abort a live job |
| `live/reconcile.Report` | dataclass `added, linked, removed, joined, revived, stale, deferred` | span ≤10 | `report_auto_plan`, S9's cadence | — |
| `live/reconcile.last_pass_at(bridge) -> float` | timestamp of the previous pass | ≤4 · CC ≤2 | `debug_view.cadence` | touch the loop |
| `live/url_policy.RemovalSpec` / `Removal` | dataclasses (rows, live_keys, pattern, busy_tabs, misses) / (row_id, url, reason) | span ≤8 each | `removable_rows` | carry a bridge |
| `live/url_policy.removable_rows(spec) -> list[Removal]` | **lookup over 4 `(reason, predicate)` pairs**, not if/elif | ≤20 · CC ≤8 | `reconcile_once` | remove a row whose tab has a live job (deferral instead) |
| `live/url_policy.advance_misses(rows, live_keys, misses) -> dict` | hysteresis counters, drop on reappearance | ≤14 · CC ≤5 | the loop | persist across restarts (§12 item 2) |
| `live/url_policy.dedupe_rows(rows)` / `add_rows(rows, adds, memory)` | **moved** from `panels/url_queue._dedupe_state_rows:~180` / `_add_missing_rows:~190` | ≤12 each | `reconcile_once`, panel delegations | change behaviour (they are moved, not rewritten) |
| `live/url_policy.remember` / `restore_enabled` / `removal_lines` | bounded memory (200), checkbox restore, log lines | ≤10 each | the pass | grow unbounded |
| `live/debug_view.interval_ms(bridge) -> int` | reads the config key | ≤8 · CC ≤3 | the loop, `cadence` | clamp here (one clamp owner: `clamp_interval_ms`) |
| `live/debug_view.clamp_interval_ms(value) -> int` | `max(500, min(int(value or 5000), 60000))` | ≤5 · CC ≤2 | `apply_url_interval`, JS parity test | raise on garbage (return the default) |
| `live/debug_view.cadence(bridge) -> dict` | `{url_interval_ms, last_pass_at, passes}` | ≤8 · CC ≤2 | `emit_arena_state` | read the pool (S9 merges that client-side) |
| `panels/browser_tabs.live_deps(bridge) -> LiveDeps` | wires `do_fetch_tabs`, `do_connect_page_pool`, `commit_urls`, `_log` | ≤12 · CC ≤2 | `start_url_reconciler` | put the wiring inside `live/` |
| `panels/browser_tabs.start_url_reconciler(bridge)` | boot-time start | ≤8 · CC ≤3 | `main_window._build_ui` (+1 line) | block the UI thread |

**Existing symbols that change:**

| Site | Now | After | Room check |
|---|---|---|---|
| `panels/browser_tabs.auto_scan_pass:374-387` | loc 13 · CC 4 | body **moves** to `reconcile_once`; a 2-line delegation stays | `browser_tabs.py` 544 → ~440; its `max_cc` (7, from `report_auto_plan`) is untouched |
| `panels/browser_tabs.do_auto_connect_scan:389-399` | loc 11 · CC 3 | calls `reconcile_once(bridge, deps, source)` | loc ≤11 |
| `panels/url_queue._dedupe_state_rows` / `_add_missing_rows` | loc 10 / 9 | 2-line delegations to `url_policy` | `url_queue.py` `max_methods` **11** ⇒ no new mixin methods |
| `persistence/config_manager.DEFAULT_SESSION:9-31` | dict literal | `+ "url_reconcile_interval_ms": 5000` | module-level dict ⇒ **no** function/class metric moves |
| `panels/app_settings.save_settings:258-273` | loc 16 · CC 2 · params 2 | `+ apply_url_interval(self, data)` | loc 17 ≤ file max **18** ✓ |
| `panels/app_settings.apply_url_interval` **(new)** | — | `if key in data: config.set_state(...clamped...); live bus wake("interval"); one log line` | ≤10 · CC ≤3 · 2 params (precedents: `apply_highlight_duration:82-86` loc 5, `apply_watcher_timeouts:89-100` loc 12 · CC 5 · nest 3) |
| `panels/layout_state.emit_arena_state:38-47` | loc 10 · CC 2 | `+ prog["live"] = debug_view.cadence(bridge)` | loc 11 ≤ file max **19** ✓ |
| `web/js/panels/cdp.js:33` | `setInterval(() => this.autoConnectScan(), 15000);` | **deleted** (the Python loop is the single periodic writer, RULE 10) | `file_lines` 135 → **134**, `func_count` 55 → **54** ⇒ both move *down* |
| `web/js/panels/cdp.js:32,34` | the 4 s boot kick and the 500 ms `ensurePrimary` tick | **kept** | §12 item 5 (the tick is a follow-up) |
| `web/js/arena-app.js:29-34` | `_PANEL_INITS` (17 names) | `+ 'UrlInterval'` **appended to the existing last line** | `file_lines` **176** and `func_count` **28** must not move |
| `web/index.html:68-75` (the `urlCooldownBar`) | cooldown knobs | `+ <span>🔁 every <input id="urlIntervalMs" …>ms</span><button id="urlIntervalSaveBtn">Save</button>` inside the same bar | HTML is outside both ratchet lanes |
| `web/js/panels/url-list/listeners.js:20-34` | `bind()` — loc **15 = file `max_func_loc`** | **untouched** | this is the proof D-12R needs a new file: the bar's binding function has zero headroom, so the new control binds its own ids |

**New JS module (the D-12R control), modelled on `url-list/cooldown.js` (48 LOC / 9 funcs):**

```
web/js/panels/url-list/interval.js  (~60 LOC, new file ⇒ JS hard limits: func ≤30 LOC, params ≤4, nest ≤4, CC ≤10)
  window.UrlInterval = {
    MIN_MS: 500, MAX_MS: 60000, DEFAULT_MS: 5000,
    init()          ⟨≤14 · CC ≤4⟩  Boot.bindOnceById('urlIntervalSaveBtn','click',…) + Boot.onBridgeReady(load)
    clamp(v)        ⟨≤6  · CC ≤3⟩  parseInt → default → MIN/MAX
    applyValue(ms)  ⟨≤6  · CC ≤2⟩  write the input
    load(live)      ⟨≤10 · CC ≤3⟩  read progress_updated.live.url_interval_ms (push, no bridge round-trip)
    save()          ⟨≤16 · CC ≤5⟩  Boot.needBridge('save_settings')({url_reconcile_interval_ms: clamp(...)})
    _bindLive()     ⟨≤10 · CC ≤3⟩  self-connect progress_updated (precedent: arena-presets.js:39-48)
  }
```

There is **no settings getter slot** (`app_settings.py` exposes only `set_theme`, `set_prompt`,
`save_settings`, preset import/export/list/save/load/delete, `refresh_users`) and D-20 forbids adding
one ⇒ the control's value can only arrive on the pushed `progress_updated.live` payload. That single
fact fixes the interface: `save_settings` writes, `progress_updated` reads.

### 2 · Expected files & functions

```
app/services/live/reconcile.py     (new, ~215 LOC — live/ 4 → 5 files)
app/services/live/url_policy.py    (new, ~185 LOC — live/ 5 → 6 files)
app/services/live/debug_view.py    (new, ~45 LOC after S6: interval_ms, clamp_interval_ms, cadence; grows to ~90 in S9)
app/ui/web/js/panels/url-list/interval.js  (new, ~60 LOC)
tests/test_live_reconcile.py       (new, ~170 LOC, 8 tests)
tests/test_url_policy.py           (new, ~150 LOC, 9 tests)
tests/test_url_interval_setting.py (new, ~90 LOC, 6 tests)
tests/js/test_url_interval_control.mjs (new, ~110 LOC, 6 tests) + package.json (+1 listed file)
```

### 3 · RED — tests written first

`tests/test_url_policy.py` (pure, no bridge — 100 % unit-testable by construction):

1. `test_removable_rows_names_a_reason_for_every_removal` — parametrised over the four reasons
   (`tab_gone`, `pattern_mismatch`, `invalid`, `duplicate`) ⇒ each removal carries its reason and only
   the matching row is returned. **RED at base:** `ModuleNotFoundError: app.services.live.url_policy`.
2. `test_a_row_whose_tab_has_a_live_job_is_deferred_not_removed` — real `PagePool` +
   `cooldown_service.set_tab_image(pool, "t1", "a.png")` ⇒ `removable_rows` returns nothing for that
   row and the spec reports it as deferred (RULE 15).
3. `test_never_linked_user_rows_are_kept` — a row with `tab_id == ""` and `last_status == "unchecked"`
   survives every pass (D-4 confirmed).
4. `test_misses_give_hysteresis_and_reset_on_reappearance` — a tab missing once ⇒ kept; missing
   `miss_threshold` times ⇒ removed; reappearing ⇒ counter dropped to 0.
5. `test_dedupe_keeps_one_row_per_tab` — the moved `_dedupe_state_rows` behaviour, byte-for-byte
   (equivalence for the move; green at base **only** after the delegation exists ⇒ written as a
   pair: old function and new function return the same `(kept, dropped)` for 6 shapes).
6. `test_restore_enabled_reuses_the_remembered_checkbox` — a closed tab's row is remembered
   (unchecked) and reopens unchecked; the memory is bounded at 200 entries.
7. `test_removal_lines_are_one_per_row_and_carry_the_reason` (RULE 2 vocabulary).
8. `test_removable_rows_is_a_table_not_a_chain` — source-level lock: the function body contains no
   `elif` (RULE 19 step 2).
9. `test_enabled_rows_gate_matches_auto_connect` — `mark_receivers`' predicate (S7) and
   `auto_connect.enabled_tab_ids:203-209` agree on 8 row shapes (this test is written in S6 and
   extended in S7 — it is the seam between the two stages).

`tests/test_live_reconcile.py` (real `Bridge` via `build_bridge`, `LiveDeps` injected with fakes):

10. `test_the_interval_is_read_every_pass` — a deps whose config value changes between passes
    (5000 → 700) ⇒ the second sleep is 0.7 s (fake clock), no restart.
    **RED at base:** `ModuleNotFoundError`.
11. `test_an_empty_fetch_never_removes_rows` — `fetch_tabs` returns `[]`/raises ⇒ 0 removals
    (the existing safety, kept).
12. `test_a_new_tab_is_added_claimed_and_joined` — one new matching tab ⇒ `Report.added == 1`,
    `deps.join_tab` called with its ws url (S1's repaired path), `wake("urls")` recorded.
13. `test_a_closed_tab_is_removed_with_a_reason_and_wakes_the_loop`.
14. `test_reconcile_runs_in_every_run_state` — parametrised `_run_state` ∈ {idle, running, paused} ⇒
    the pass behaves identically (item 02's "on the fly").
15. `test_the_manual_slot_and_reparse_buttons_trigger_an_immediate_pass` — `auto_connect_scan()` ⇒
    one pass now, and the loop's next sleep is unchanged (the interval is a floor, not a schedule).
16. `test_commit_goes_through_the_single_row_funnel` — every row change ends in `commit_urls`
    (I-37) and pushes **no** undo entry (system change).
17. `test_the_js_timer_is_gone` — source-level lock: `"autoConnectScan(), 15000" not in
    cdp.js` and `setInterval` appears exactly once in that file (the 500 ms `ensurePrimary` tick).

`tests/test_url_interval_setting.py`:

18. `test_default_is_5000` — a fresh `ConfigManager(tmp)` returns 5000 (`DEFAULT_SESSION`).
    **RED at base:** `KeyError`/default fallback — the key does not exist.
19. `test_clamp_bounds_are_500_and_60000` — parametrised: 1 → 500, 60001 → 60000, `"abc"` → 5000,
    `None` → 5000, `2500` → 2500.
20. `test_save_settings_persists_only_when_the_key_is_present` — `save_settings("{}")` leaves the
    value; `save_settings('{"url_reconcile_interval_ms": 1200}')` writes 1200 and logs one line.
21. `test_the_value_is_published_in_progress_updated` — `emit_arena_state` ⇒ the payload's
    `live.url_interval_ms == 1200` (this is the control's only read path).
22. `test_the_setting_wakes_the_loop` — after `save_settings`, `live_bus(bridge).wait(0.05)` reports
    the interval reason ⇒ the next pass uses it immediately.
23. `test_no_new_slot_and_no_new_signal` — `tests/test_bridge_slots.py` Σ=134 re-run **plus** a source
    assertion that `app_settings.py` gained no `@Slot` (D-20).

`tests/js/test_url_interval_control.mjs` (harness A — module sandbox):

24. `test_save_clamps_and_calls_save_settings` — load `interval.js` into a sandbox with a fake
    `document.getElementById` for `urlIntervalMs`/`urlIntervalSaveBtn` and a fake bridge; type `99999`,
    click Save ⇒ the bridge received `{"url_reconcile_interval_ms": 60000}`.
    **RED at base:** the file does not exist (`ENOENT`).
25. `test_save_rejects_garbage_and_falls_back_to_5000`.
26. `test_load_repopulates_from_the_pushed_payload` — `UrlInterval.load({url_interval_ms: 1200})` ⇒
    the input reads 1200, with **no** bridge call (the Proxy counts calls).
27. `test_it_publishes_itself` — `window.UrlInterval` exists after the script runs (I-35/B6 lock).
28. `test_init_binds_the_save_button_exactly_once` — two `init()` calls ⇒ one listener
    (`Boot.bindOnceById`, `core/boot.js:66-68`).
29. `test_the_frozen_url_list_files_did_not_grow` — a net-zero guard: read
    `url-list/{listeners,cooldown,actions,store,matching}.js` + `url-list.js` and assert their line
    counts equal the recorded baselines (63/49/163/39/106/138). This is D-24a's cheap early warning,
    runnable without `npm ci`.

### 4 · GREEN + REFACTOR + equivalence

* **GREEN:** the three Python modules, `live_deps`/`start_url_reconciler`, the config key, the
  settings applier, the `prog["live"]` line, `interval.js`, the bar markup, the `_PANEL_INITS` append,
  the `cdp.js` deletion, `package.json` +1.
* **REFACTOR:** `browser_tabs.py` 544 → ~440 (RULE 18.2 direction), `url_queue.py` loses two helper
  bodies, `cdp.js` shrinks. No new if/elif chains: `removable_rows` is a predicate table.
* **Existing tests that must change:** `tests/test_panel_browser_tabs.py` cases that assert the
  idle-only prune (`auto_prune_allowed`) — the passive prune is replaced by `removable_rows`
  (reason recorded: D-4/round-1 §5.1); `tests/js/test_cdp_store*.mjs` if they assert the 15 s timer.
* **Equivalence (green, unedited):** `tests/test_auto_connect*.py` (the planner is untouched —
  `auto_connect.py` stays at 100 % coverage), the 12 goldens (no reconcile pass runs inside a golden),
  `tests/test_bridge_slots.py`, `tests/test_bridge_metaobject.py`.
* **Gate:** fast lane **+ `npm run test:js`** (this stage touches JS ⇒ the JS lane measures **every**
  baselined `.js` file, `verify_quality.py:201-234,252-270,1032-1034`): `arena-app.js` must still read
  176/28, `cdp.js` 134/54 (both **down**), `listeners.js` 63/18, `cooldown.js` 49/9.
* **Docs:** I-42 (cadence is the user setting), SYSTEM_OF_RECORD rows 8/11/21.

---

## S7 · Receiver flag + the ⊘ icon

### 0 · Scope

One Python owner decides whether a row can currently receive a job; the web UI only reflects it.
Interface boundary after S7: `UrlRow.receiver` is part of the row contract (persisted, serialized,
undo-safe), and `mark_receivers` is called by the single row writer.

### 1 · Interface split

| Symbol | Signature | Budget | Called by | Must **not** |
|---|---|---|---|---|
| `core/models.UrlRow.receiver` | `receiver: bool = False` — appended **last** (after `tab_id`) | class span 26 → 27 (file `max_class_loc` **74**) | serializer, undo builders, JS | be inserted mid-field (positional constructors exist in tests); be a computed property (RULE 13: it must round-trip) |
| `live/url_policy.mark_receivers(rows, allowed, pooled) -> int` | the one writer; returns the changed count | ≤10 · CC ≤4 · **3 params** | `reconcile_once`, `commit_urls` | recompute the run gate (it *reads* `auto_connect.enabled_tab_ids:203-209`) |
| `live/url_policy.receiver_reason(row, allowed, pooled) -> str` | `""` when it is a receiver, else `"unchecked"` / `"not linked"` / `"offline"` / `"busy"` | ≤8 · CC ≤4 | the icon's `title`, S9's counters | return a reason for a receiver |
| `ui/services/arena_serialize.urls_to_js:12-25` | `+ "receiver": u.get("receiver", True)` | loc 14 → 15 (file max **23**) | every state emit | default to `False` (an unmarked row must not flash an icon) |
| `ui/services/undo_entries.url_rows_from_js:21-32` | `+ receiver=bool(u.get("receiver", True))` | loc 11 → 12 (file max **17**) | undo/redo of `urls` | drop the flag (that is B7's class of bug: `tab_id` was lost the same way) |
| `ui/services/undo_entries.arena_url_rows_from_js:34-41` | same | loc 7 → 8 | snapshot restore | idem |
| `web/js/panels/url-list/render.js:6-9` (`rowHtml`) | one `<span class="url-not-receiver" title="…">⊘</span>` inside the **existing single-line template**, right after the status chip | file **74 lines / 12 funcs unchanged**, `rowHtml` span **19** unchanged | `render()` | add a second template line, a helper function, or a JS-side eligibility computation |
| `web/css/arena.css` | `+ .url-not-receiver { … }` (6 lines: muted colour, 11 px, `cursor:help`) | ungated (already linked at `index.html:13`) | the icon | live in a new stylesheet before S8 creates one |

Persistence round-trip (RULE 13) is already guaranteed by the existing code shape: `AppState.to_dict`
writes `asdict(u)` (`models.py:253`) and `from_dict` reads `UrlRow(**u)` (`models.py:266`) ⇒ the new
field is saved and restored with **no** migration, and an old `arena.json` without the key still loads
(the dataclass default).

### 2 · Expected files & functions

```
tests/test_url_receivers.py               (new, ~120 LOC, 8 tests)
tests/js/test_url_list_receiver_icon.mjs  (new, ~85 LOC, 5 tests) + package.json (+1 listed file)
```

No new production file: S7 is 6 small edits + 1 CSS rule (that is why it can follow S6 immediately).

### 3 · RED — tests written first

`tests/test_url_receivers.py`:

1. `test_unchecked_unlinked_and_offline_rows_are_not_receivers` — parametrised over the four reasons
   ⇒ `receiver is False` and `receiver_reason` names it. **RED at base:** `UrlRow` has no `receiver`
   attribute (`AttributeError`).
2. `test_a_checked_row_on_a_connected_pooled_tab_is_a_receiver` — real `PagePool` +
   `PageInfo(is_connected=True)` ⇒ `receiver is True`, `receiver_reason == ""`.
3. `test_mark_receivers_reports_only_changes` — calling it twice returns `0` the second time (so the
   log line and the emit are not spammed).
4. `test_the_flag_survives_serialization` — `arena_to_js(state)["urls"][0]["receiver"] is False`.
5. `test_the_flag_survives_persistence` — save → `load_state` → the flag is still there (RULE 13,
   real `tmp_path` state file).
6. `test_the_flag_survives_undo_and_redo` — flip a checkbox, `undo()`, `redo()` ⇒ the receiver flag
   matches the row each time (both builders).
7. `test_commit_urls_recomputes_the_flag` — a checkbox flip through the real slot ⇒ the flag follows
   instantly (item 03's "icon follows the checkbox").
8. `test_the_run_gate_is_not_reimplemented` — source lock: `url_policy.py` contains
   `enabled_tab_ids(` and does **not** contain `for u in` + `.enabled` filtering of its own
   (one owner, RULE 10).

`tests/js/test_url_list_receiver_icon.mjs` (harness A):

9. `test_row_html_contains_the_icon_only_for_non_receivers` — load `url-list/{store,render}.js`;
   `rowHtml({id:'u1',url:'x',receiver:false})` contains `url-not-receiver` and a `title`;
   `receiver:true` does not. **RED at base:** the class never appears.
10. `test_the_icon_sits_in_the_status_cell` — the `<span class="url-not-receiver"` index is inside the
    third `<td>` (so the table's column count is unchanged — the `url-table` header has 8 columns).
11. `test_render_js_did_not_grow` — line count of `render.js` is still **74** and its function count
    still **12** (the net-zero guard, D-24a).
12. `test_the_reason_is_the_title` — the `title` attribute equals the Python `receiver_reason`
    wording for all four reasons (cross-layer vocabulary lock; the expected strings are copied from
    `test_url_receivers.py`).
13. `test_no_js_side_computes_eligibility` — source lock: `render.js` contains no `.enabled` test and
    no `tab_id` check for the icon (the flag is authoritative).

### 4 · GREEN + REFACTOR + equivalence

* **GREEN:** the field, the two policy functions, the serializer key, the two undo builders, the
  template span, the CSS rule.
* **REFACTOR:** none needed; `receiver_reason` is a lookup, not a chain.
* **Existing tests that must change:** none expected — the field is additive with a default. If
  `tests/test_models*.py` asserts an exact `asdict` key set, add the key there (reason: new persisted
  field).
* **Equivalence:** the 12 goldens (`images`/`files`/`events` do not include URL rows; `urls` are built
  by `make_urls` in the harness and never asserted field-by-field), `tests/test_url_list*.py`,
  `tests/js/test_url_list_{esm,listeners,add_persists}.mjs`.
* **Gate:** fast lane + `npm run test:js`; `models.py` `max_class_loc` must stay **74**,
  `undo_entries.py` `max_func_loc` must stay **17**, `arena_serialize.py` must stay **23**,
  `render.js` must stay **74/12**.
* **Docs:** I-45, SYSTEM_OF_RECORD rows 19/21.

---

## S8 · The window contract 15 → 16, and the L-5 rescue

### 0 · Scope

One ordered window table owned by Python and mirrored exactly by JS, a 16th registered window
(`live_debug`), and the rescue of the Page Pool markup that `SashGrid.render()` currently destroys
(`index.html:262-263` declares `data-window="page_pool"`, an id no registry knows ⇒
`sash-grid.js:88-94` `replaceChildren` discards it). Interface boundary after S8: adding a window is a
one-row change in `window_catalog.py` + one same-line append in three JS registries + markup.

### 1 · Interface split

| Symbol | Signature | Budget | Called by | Must **not** |
|---|---|---|---|---|
| `core/window_catalog.WINDOWS` | the **one** ordered list of `{"id","title"}` (16), ids ≡ order ≡ titles | module constant (~45 LOC file) | `layout_service` (re-export), JS parity test | be duplicated anywhere (L-8 fixes the drift: today `WINDOWS` and `WINDOW_IDS` disagree on `recordings`' position) |
| `core/window_catalog.WINDOW_IDS` | `[w["id"] for w in WINDOWS]` | derived | `parse_grid_payload:227`, `migrate_grid_tree:284`, `layout_state.py:14` | be hand-written (that is how the drift happened) |
| `core/window_catalog.WINDOW_TITLES` | `{w["id"]: w["title"] for w in WINDOWS}` | derived | `test_grid_layout.py:118`, the JS title bar | — |
| `core/window_catalog.LEGACY_WINDOW_IDS` | `{"captcha_records": "recordings"}` | moved | `_rename_legacy_windows:265-279` | gain `page_pool` (the orphan is rescued, not registered — D-21) |
| `core/window_catalog.GRID_VERSION` | `6` | moved | `default_payload:71-73`, `parse_grid_payload:221`, `window_preset_service.py:13` | stay 5 (a stored v5 layout must migrate, not be rejected) |
| `core/window_catalog.default_grid_tree()` | the tree + `leaf("live_debug")` in the last column split | loc 21 → ~23 (new file, hard limit 30) | `layout_service` re-export, `test_file_dialogs.py:6`, `test_layout_state.py:8` | leave sizes that do not sum to 100 (`_normalize_sizes:99-105` rescales, but the default should be exact) |
| `core/layout_service` | re-export shim: `from app.core.window_catalog import GRID_VERSION, LEGACY_WINDOW_IDS, WINDOW_IDS, WINDOW_TITLES, WINDOWS, default_grid_tree` | +1 import line; file 300 → ~272 | the 3 production importers (`layout_state.py:14`, `undo_entries.py:15`, `window_preset_service.py:13`) and 6 test modules | break any of those imports (that is what the shim is for) |
| `js/sash-core/constants.js:4-23` | `WINDOWS` gains `{ id: 'live_debug', title: 'Live Worker & Queue Debug' }` **on the existing `arena_presets` line**; `VERSION: 5` → `6` on line 23 | `file_lines` **25** and `max_func_loc` **22** must not move ⇒ same-line edits only | `SashCore.WINDOWS` consumers, `test_grid_layout.js_windows():32-52` | add a line (the IIFE body span is the file's `max_func_loc`: 22 → 23 fails) |
| `js/sash-grid-windows/store.js:5-11` | `winElIds` gains `live_debug: 'winLiveDebug',` on the existing last entry line | `file_lines` **122**, `_collectPanels` span **14 = file max** | `_collectPanels:4-17` | add a line inside `_collectPanels` |
| `js/arena-app.js:29-34` | `_PANEL_INITS` gains `'LiveDebugPanel'` on the last line | `file_lines` **176**, `func_count` **28** | `Boot.bootPanels`, `test_boot_all_panels.mjs:104-112` | add a line (S6 already appended `'UrlInterval'` to the same line — the two appends commute) |
| `js/sash-grid.js:41-49` | **delete** the dead `WIN_ICONS` table (L-8) | `file_lines` 123 → **114** (down ⇒ ratchet-safe) | nobody (verified: one hit repo-wide) | gain a `live_debug` icon entry — extending a dead table is how L-8 happened |
| `web/index.html:262-263` | `id="winPagePool" data-window="page_pool"` → `id="winLiveDebug" data-window="live_debug"`, title text → *Live Worker & Queue Debug*, the pool markup (ids `poolStatusBadge`, `poolRefreshBtn`, `poolConnectBtn`, `poolClearBtn`, `poolTotal/Steady/Busy/Cooling/Free`, `poolTableBody`) **kept inside it** | ungated | `PagePoolPanel` (binds by id with `?.`, `page-pool.js:18-20`) and S9's strips | rename any inner id (that would break the frozen pool panel) |
| `tests/js/sash_harness.mjs:16-19` | `ALL_WINDOW_IDS` + `'live_debug'` | test file (out of scope for size gates) | every grid test | — |
| `tests/test_grid_layout.py:245-247,253` | four `== 15` → `== 16` | test file | the preset/doc contract | be loosened to `>= 15` |

### 2 · Expected files & functions

```
app/core/window_catalog.py        (new, ~45 LOC — core 13 → 14 files; a table, no function > 5 LOC)
app/ui/web/css/live-debug.css     (new, ~25 LOC in S8: the window shell; grows in S9)
tests/test_window_catalog.py      (new, ~90 LOC, 7 tests)
tests/js/test_live_debug_panel.mjs (new, ~150 LOC — part 1 in S8: mount; part 2 in S9: content) + package.json (+1)
```

### 3 · RED — tests written first

`tests/test_window_catalog.py`:

1. `test_python_and_js_tables_identical` — parse the real `constants.js` (the way
   `test_grid_layout.js_windows():32-52` already does) ⇒ ids **and order** equal `WINDOW_IDS`, titles
   equal `WINDOW_TITLES`. **RED at base:** `ModuleNotFoundError: app.core.window_catalog`.
2. `test_every_registered_window_has_a_mountable_element` — for each id, `panelIdOf(id)` (the harness
   rule) has a `data-window="<id>"` element in the real `index.html` ⇒ this is the **L-5 regression
   test**: at base it fails for `page_pool`'s orphan markup and would fail for `live_debug`.
3. `test_ids_and_titles_have_no_duplicates_and_no_legacy_names` — 16 unique ids, `captcha_records`
   absent, `recordings` present.
4. `test_default_tree_leaf_set_equals_the_registry` — `sorted(leaf_ids(default_grid_tree())) ==
   sorted(WINDOW_IDS)` and the sizes of every split sum to 100 ± 0.01.
5. `test_grid_version_is_six_and_v5_layouts_migrate` — a stored v5 payload (15 leaves) parses, migrates
   (`migrate_grid_tree:281-297` appends the missing leaf with its own column) and re-validates; a v6
   payload round-trips unchanged.
6. `test_legacy_rename_still_works` — a stored tree using `captcha_records` keeps its position under
   `recordings` (`_rename_legacy_windows:265-279`).
7. `test_the_layout_service_reexport_is_complete` — `layout_service.WINDOW_IDS is
   window_catalog.WINDOW_IDS` and the six existing importers still resolve (import each module).

`tests/js/test_live_debug_panel.mjs` — **part 1 (S8)**:

8. `test_the_grid_mounts_winLiveDebug_and_does_not_destroy_it` — harness B (whole-page boot) + the
   sash harness: after `SashGrid.init(); SashGrid.render()`, `document.getElementById('winLiveDebug')`
   is inside `#sashGrid` (not discarded). **RED at base:** the element is outside the grid after
   `render()` — the exact L-5 mechanism (`replaceChildren`, `sash-grid.js:88-94`).
9. `test_the_pool_panel_still_finds_its_ids_after_the_rescue` — `poolTableBody`, `poolRefreshBtn`,
   `poolConnectBtn`, `poolClearBtn`, `poolStatusBadge` all resolve, and `PagePoolPanel.init()` binds
   3 click listeners (the frozen panel is untouched).
10. `test_panel_inits_includes_LiveDebugPanel_and_it_publishes_itself` — `_PANEL_INITS` contains the
    name and `Boot.panel('LiveDebugPanel')` returns an object without a warning (I-35/B6 lock; the
    module may be a stub in S8 — its content lands in S9, but the *registration* must be complete).
11. `test_title_fit_still_passes_with_sixteen_windows` — run `tests/js/test_title_fit.mjs` explicitly
    (**L-7**: it is not in `package.json`'s list) with `TITLE_SECONDARIES` extended for `live_debug`.

### 4 · GREEN + REFACTOR + equivalence

* **GREEN:** the catalog + shim, the tree leaf, `GRID_VERSION 6`, the three same-line JS appends, the
  markup move, the `WIN_ICONS` deletion, the CSS shell, the harness/test-list updates.
* **REFACTOR:** `layout_service.py` 300 → ~272 (back inside the RULE 18.2 band); the `WINDOWS` /
  `WINDOW_IDS` order drift (L-8) is gone because ids are now *derived*; `sash-grid.js` −9 lines.
* **Existing tests that must change (recorded reasons):** `tests/test_grid_layout.py:245-247,253`
  (four counts 15 → 16 — the window set genuinely changed), `tests/js/sash_harness.mjs:16-19`
  (`ALL_WINDOW_IDS` + `TITLE_SECONDARIES`), `package.json` (+1 listed `.mjs`).
* **Equivalence (green, unedited):** `tests/test_layout_state.py`, `tests/test_file_dialogs.py`,
  `tests/test_window_presets*.py`, `tests/integration/test_sash_webengine.py` (marked `slow`/`e2e`),
  `tests/js/test_sash_{core,grid_tree,split,bugfixes}.mjs`, `tests/js/test_window_presets.mjs`,
  `tests/test_bridge_slots.py` (no slot touched).
* **Gate:** fast lane + `npm run test:js` + the explicit `node --test tests/js/test_title_fit.mjs`;
  `constants.js` must still read **25 lines / `max_func_loc` 22**, `store.js` **122/14**,
  `arena-app.js` **176/28**, `sash-grid.js` **114** (down), `layout_service.py` `max_func_loc` **≤21**
  and `file_lines` ~272.
* **Docs:** I-43, SYSTEM_OF_RECORD row 19 (16 windows, the stale `captcha_records` name, L-5 recorded
  as fixed), `data_model`/storage notes if the preset doc shape is quoted.

---

## S9 · Live Worker & Queue Debug — the window's content

### 0 · Scope

The registered window becomes useful: every worker with its live job status, the pending count and the
**first image's name**, receiver counts, and the reconcile cadence — all in real time, with newly
added/removed webpages appearing and disappearing. Pure observability: **no** pipeline behaviour
changes, **no** slot, **no** signal (D-20/D-22).

### 1 · Interface split

The payload is deliberately split in two, because both halves already exist and merging them in Python
would duplicate the pool snapshot (jscpd risk) and bloat every state emit:

| Payload | Producer | Signal it rides | Consumer |
|---|---|---|---|
| **workers** — `total/steady/busy/cooling/free` + per page `tab_id, title, url, status, is_connected, current_job_id, current_image, busy_since, cooldown_remaining, cooldown_reason, jobs_completed, captcha_count, rate_limit_count` | `PagePool.status_snapshot()` (`page_pool.py:191-198`) via `_snapshot_entry` + `PageInfo.to_dict()` (`page_status.py:88-106`) — **already complete, zero new fields** | `page_pool_updated` (`bridge.py:100-108`) | `LiveDebugStore.onPool` |
| **queue + cadence** — `queued`, `next_image`, `receivers`, `run_state`, `url_interval_ms`, `last_pass_at`, `passes` | `live/debug_view.live_view(bridge)` (new) | `progress_updated` (the `prog["live"]` line S6 added) | `LiveDebugStore.onLive` |

| Symbol | Signature | Budget | Called by | Must **not** |
|---|---|---|---|---|
| `live/debug_view.live_view(bridge) -> dict` | `{**cadence(bridge), "queued":…, "next_image":…, "receivers":…, "run_state":…}` | ≤20 · CC ≤6 · **1 param** | `emit_arena_state` (a same-line swap of `cadence` → `live_view`) | mutate state; read the pool (the JS merges `page_pool_updated`); duplicate `status_snapshot` |
| `live/debug_view.next_queued(images) -> str` | **pure**: first `feed.eligible_images(images)` entry's file name (`""` when empty) — takes the list `live_view` already read, so it is unit-testable without a bridge | ≤6 · CC ≤2 · 1 param | `live_view` | sort or filter (S4's rule is the only one); take a bridge (that would make it untestable in isolation) |
| `live/debug_view.receiver_counts(rows) -> dict` | `{"total": n, "receivers": k, "not_receivers": n-k}` | ≤6 · CC ≤2 | `live_view` | recompute eligibility (S7 owns it) |
| `js/panels/live-debug.js` | `window.LiveDebugPanel = { init, onPool, onLive, refresh }` | ~90 LOC · `init` ≤20 · CC ≤6 | `_PANEL_INITS` (S8) | touch `arena-app/listeners.js` (**168 lines / 51 funcs**, frozen) — it self-connects like `arena-presets.js:39-48` |
| `js/panels/live-debug/store.js` | `LiveDebugStore = { pool, live, tick(), queueHead(), workerLines() }` + a 1 s ticker | ~80 LOC · `tick` ≤12 · CC ≤4 | the panel | call the bridge from the ticker (elapsed time is recomputed locally) |
| `js/panels/live-debug/render.js` | `queueHead()`, `workers()`, `cadence()` string builders | ~130 LOC · `workers` ≤24 · CC ≤8 · params ≤2 | the panel | share a template with `page-pool/render.js` (jscpd 1.240 % floor): job-centric lines vs the pool's tab-centric table |
| `js/panels/live-debug/actions.js` | `refresh()` — one bridge read (`get_page_pool_status`), **no writes** | ~60 LOC · `refresh` ≤12 · CC ≤3 | the Refresh button | own a writable cadence control (D-12R: the bar in S6 is the only writer) |
| `web/index.html` (inside `winLiveDebug`) | queue-head strip, worker job-line list, cadence readout | ungated | the render module | reuse a pool id (`poolTableBody` etc. belong to the rescued panel) |
| `web/css/live-debug.css` | the strips (~35 more lines) | ungated, one new `<link>` | — | — |

### 2 · Expected files & functions

```
app/services/live/debug_view.py     (grows ~45 → ~90 LOC: + live_view, next_queued, receiver_counts — live/ stays 7 files)
app/ui/web/js/panels/live-debug.js          (new, ~90 LOC)
app/ui/web/js/panels/live-debug/store.js    (new, ~80 LOC)
app/ui/web/js/panels/live-debug/render.js   (new, ~130 LOC)
app/ui/web/js/panels/live-debug/actions.js  (new, ~60 LOC)
tests/test_live_debug_view.py               (new, ~110 LOC, 7 tests)
tests/js/test_live_debug_panel.mjs          (part 2 appended: +~90 LOC, 6 tests — the file was created in S8)
```

**D-24a note:** `test_live_debug_panel.mjs` is *appended to* in S9 although S8 created it. That is
allowed for **test** files (they are out of scope for both ratchet lanes, `AGENT_RULES.md` §16.0) — the
freeze rule applies to production `.js` only, and S9's four production files are new.

### 3 · RED — tests written first

`tests/test_live_debug_view.py` (real `Bridge` via `build_bridge` + a real `PagePool`):

1. `test_live_view_is_read_only` — deep-copy `bridge.state` before/after ⇒ identical; no pool mutation
   (`status_snapshot` is not even called: a spy on it asserts 0 calls).
   **RED at base:** `ModuleNotFoundError: no attribute 'live_view'` (S6 created the module without it).
2. `test_next_queued_is_the_first_eligible_image_name` — a queue of 5 with mixed statuses ⇒ the name
   of the first `ELIGIBLE` one; an empty/all-`processing` queue ⇒ `""`.
3. `test_queued_count_equals_the_eligibility_rule` — `live_view["queued"] ==
   len(feed.eligible_images(bridge.state.images))` (kills a second counting rule).
4. `test_receiver_counts_match_the_flag` — 3 receivers / 2 not ⇒ the dict, and no recomputation
   (monkeypatching `mark_receivers` to a spy asserts 0 calls).
5. `test_cadence_keys_are_present_and_typed` — `url_interval_ms` int, `last_pass_at` float,
   `run_state` str; the payload is JSON-serializable (`json.dumps` does not raise).
6. `test_the_payload_rides_progress_updated` — `emit_arena_state(bridge)` ⇒ the emitted
   `progress_updated` JSON has `live.queued` and `live.next_image`; `arena_state_updated` is
   **unchanged** (no new top-level key — the JS contract stays put).
7. `test_no_captcha_wording_while_the_watcher_is_off` — with the switch OFF and a dialog up (S2's
   stack), `live_view` contains no captcha field or wording (D-23's observability half).

`tests/js/test_live_debug_panel.mjs` — **part 2 (S9)**:

8. `test_queue_head_renders_count_and_first_image_name` — feed the store a `live` payload ⇒ the strip
   reads `3 pending · first: a.png`. **RED at base (S8 state):** the panel is a stub, no strip.
9. `test_a_waiting_captcha_worker_renders_the_paused_timeout_line` — a pool payload with
   `status: "waiting_captcha"`, `busy_since` 90 s ago ⇒ the line shows the absorbed pause and the
   remaining cap (I-44's "never silent").
10. `test_new_and_removed_webpages_appear_and_disappear` — two successive pool payloads (3 pages, then
    2) ⇒ the rendered list has 3 then 2 lines, with no stale line and no bridge call in between
    (item 05's "webpage add/remove reflected").
11. `test_the_ticker_recomputes_elapsed_without_a_bridge_call` — advance the fake clock 5 s ⇒ the
    elapsed text changed and the Proxy bridge recorded **0** calls.
12. `test_cadence_is_read_only_text` — the panel renders `reconcile every 5.0 s · last pass 2 s ago`
    and contains **no** input and no `save_settings` call (D-12R lock: a writable control here would
    be a second writer).
13. `test_the_panel_publishes_itself_and_self_connects` — `window.LiveDebugPanel` exists; after boot,
    `progress_updated`/`page_pool_updated` handlers are registered without
    `arena-app/listeners.js` changing (assert its line count is still **168**).

### 4 · GREEN + REFACTOR + equivalence

* **GREEN:** the three `debug_view` functions, the one-line swap in `emit_arena_state`, the four JS
  files, the markup strips, the CSS, `package.json` +1.
* **REFACTOR:** none required; confirm `render.js` shares no template string with
  `page-pool/render.js` (jscpd).
* **Existing tests that must change:** `tests/js/test_boot_all_panels.mjs` expectations only if they
  enumerate panels (they read `_PANEL_INITS` dynamically, `:104-112` ⇒ no edit expected);
  `package.json` (+1).
* **Equivalence:** all 12 goldens (the payload is additive and `arena_state_updated` is untouched),
  `tests/test_bridge_slots.py` (Σ=134 — **no new slot**), `test_bridge_metaobject.py`,
  `tests/test_layout_state.py`, the whole JS suite.
* **Gate:** fast lane + `npm run test:js` (28 listed files); `layout_state.py` `max_func_loc` must stay
  **19** and `emit_arena_state` must stay **11** lines.
* **Docs:** SYSTEM_OF_RECORD row 19 (what the window shows), I-43/I-44/I-45 enforcement pointers,
  `QUALITY_RECHECK.md`.

---

## S10 · Consolidation

### 0 · Scope

No feature. The chain is verified as a whole, the docs are made consistent, and the baseline decision
is taken once, with reasons.

### 1-2 · Interfaces / files

```
docs/current/QUALITY_RECHECK.md   (refreshed: the ten stages, the numbers, the baseline decision)
docs/current/SYSTEM_OF_RECORD.md  (verified against the code: rows 6/8/11/12/19/21, I-39…I-46, module tables)
docs/README.md                    ("UI 15 windows" → 16; the round-2 entry marked integrated)
this folder                       (§8.0/§8.1 checklists filled in, per stage)
```

### 3 · RED — the checks that must fail if the chain is incomplete

1. `test_the_docs_match_the_code` — a documentation-consistency pass, run by hand but recorded:
   every invariant I-39…I-46 names an enforcement file that exists; every `docs/current/` row quoted
   in §9.3 was updated in its stage's commit (`git log --format=%s` per stage).
2. `test_no_stage_grew_another_stages_js` — re-run the net-zero guard of
   `tests/js/test_url_interval_control.mjs::test_the_frozen_url_list_files_did_not_grow` and
   `tests/js/test_url_list_receiver_icon.mjs::test_render_js_did_not_grow` against the **final** tree.
3. `test_the_orphan_js_tests_are_adopted_or_explained` (L-7) — either `package.json` lists
   `test_captcha_saved_page.mjs` and `test_title_fit.mjs` (28 → 30) and both are green, or
   `QUALITY_RECHECK.md` records why they stay out.

### 4 · GREEN — the full lane

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt   # S0 bootstrap
npm ci                                                                             # S0 bootstrap (acorn ⇒ the JS lane)
bash tools/pre_push_check.sh                                                       # the whole gate
python tools/verify_quality.py --changed --allow-legacy --coverage-ratchet
npm run test:js && node --test tests/js/test_title_fit.mjs
QT_QPA_PLATFORM=offscreen python -m pytest tests -q                                # 132 py test files (116 at base + 16 new)
radon cc -s app/services/live app/core/pause_clock.py app/core/window_catalog.py   # RULE 16.6 step 4
```

* Coverage floors: line **86.09 %**, branch **82.01 %**, jscpd **1.240 %** — none may drop
  (`quality-budget.md` §2); per-file floors for every touched file (`§3.1`).
* Baseline re-record: **only** with a stated reason per maximum (`verify_quality.py:762-812`,
  RULE 16 §16.5). The expected legitimate moves are *downwards* (`captcha/service.py` `max_func_loc`
  27 → ~21, `layout_service.py` `file_lines` 300 → ~272, `cdp.js` 135 → 134, `sash-grid.js` 123 → 114)
  plus the new files' first recording.
* RULE 18 recheck: `quality-budget.md` §5 re-run against the final tree (module counts
  `core` 13 → **15** (`pause_clock.py`, `window_catalog.py`), `services/live` **7**, `captcha` **7**,
  `browser` **23** unchanged, `ui/panels` **16** unchanged).

---

## A. Frozen seams — what no stage may edit, and the test that pins each

| Seam | Why it is frozen | Pinned by |
|---|---|---|
| The 134-slot bridge contract | D-20: no stage needs a slot; `live_view` rides `progress_updated`, the workers ride `page_pool_updated` | `tests/test_bridge_slots.py` (exact match), `tests/test_bridge_metaobject.py` — run in **every** stage |
| `cooldown_service.wait_captcha_cleared` (loc 18 · CC 7 · **params 4 = file max**) | the cap must not become a 5th parameter, and "never gives up" is intentional | `tests/test_cooldown_service.py:604-618` — green **unedited** in all ten stages |
| `browser/page_pool.PagePool` (`add_page` loc 23 · **CC 10 = hard limit** · nest 3 · params 2) | every metric is at its ceiling; S4/S6/S9 only read it | `tests/test_page_pool.py` (15 tests) |
| `js/panels/settings.js` (252 lines / 48 funcs) | the interval control is a bar control (D-12R), not a settings-page field | `tests/js/test_boot_all_panels.mjs`, the net-zero guard |
| `js/panels/url-list/{listeners,cooldown,actions,store,matching}.js`, `url-list.js`, `url-list/render.js` | `listeners.bind()` is at its own `max_func_loc` **15**; `render.js`'s `rowHtml` is one line | `test_url_interval_control.mjs::…did_not_grow`, `test_url_list_receiver_icon.mjs::test_render_js_did_not_grow` |
| `js/arena-app/listeners.js` (168 / 51) | new panels self-connect (`arena-presets.js:39-48`) | `test_live_debug_panel.mjs::…self_connects` |
| `js/sash-core/constants.js` (25 / `max_func_loc` 22), `js/sash-grid-windows/store.js` (122 / 14), `js/arena-app.js` (176 / 28) | zero line headroom ⇒ same-line appends only | the JS lane itself (global with `--changed`, `verify_quality.py:252-270,1032-1034`) |
| `output_wait.wait_for_new_output_with_spec` (loc 23 · CC 8 · nest 3 · params 4 — all four are the file maxima) | the clock rides on `WaitSpec`, so the loop body never changes | `tests/test_output_wait*.py` |
| The 12 characterization goldens | the equivalence gate for S4/S5 | `tests/characterization/test_batch_goldens.py` (`check_golden` excludes `logs`) |
| The pinned log markers `"Starting"`, `"Job completed"`, `"Batch complete"`, `"Completed with warnings"`, `"Prompt verification failed: Mismatch"` | user-visible vocabulary | `assert_markers` (`test_batch_goldens.py:37,47,81`) |

## B. Slot / signal budget — the proof that none is needed

| Stage | Data it needs | How it travels | New slots | New signals |
|---|---|---|---:|---:|
| S1 | — | existing `connect_page_pool` slot starts working | 0 | 0 |
| S2/S3 | scope, cap, outcome | return values + existing `arena_log` | 0 | 0 |
| S4 | queue wake | in-process `LiveBus` (Python-only) | 0 | 0 |
| S5 | run state | `AppState.run_state` → existing `progress_updated` | 0 | 0 |
| S6 | interval write / read | existing `save_settings` slot / existing `progress_updated.live` | 0 | 0 |
| S7 | receiver flag | existing `arena_state_updated` (a key inside `urls[]`) | 0 | 0 |
| S8 | window set | `grid_layout` persistence (existing slots) | 0 | 0 |
| S9 | workers + queue + cadence | existing `page_pool_updated` + `progress_updated` | 0 | 0 |

`Σ slots = 134` before S1 and after S10; `tests/test_bridge_slots.py` is the executable form of this
table and is never edited.

## C. Test ledger (what each stage adds, and the count the gate must show)

| Stage | New test files | New test functions | Existing tests edited | Suite after |
|---|---|---:|---|---|
| S1 | `test_page_pool_join.py` | 4 | `test_panel_browser_tabs.py` (de-mask L-6) | **117** py files (base **116**, measured) |
| S2 | `test_captcha_scope.py`, `test_watcher_off_zero_activity.py` | 11 | `test_captcha_boundaries.py`, `test_single_job_runner.py`, `characterization/harness.py` (+`watcher_on`), `test_batch_goldens.py` (1 call) | **119** py |
| S3 | `test_pause_clock.py`, `test_output_wait_timeout_pause.py`, `test_captcha_wait_cap.py`, `test_captcha_wait_reason.py` | 23 | — | **123** py |
| S4 | `test_live_bus.py`, `test_live_feed.py`, `test_reset_requeues.py` | 18 | the reset-expectation cases in `test_run_control*.py` / `test_panel_*.py` | **126** py |
| S5 | `test_live_supervisor.py` | 9 | `characterization/harness.py` (`RUNNERS`), `test_batch_orchestrator.py` (lifecycle cases move) | **127** py |
| S6 | `test_live_reconcile.py`, `test_url_policy.py`, `test_url_interval_setting.py`, `js/test_url_interval_control.mjs` | 29 | `test_panel_browser_tabs.py` (idle-only prune), maybe `js/test_cdp_store*.mjs` | **130** py + **26** js |
| S7 | `test_url_receivers.py`, `js/test_url_list_receiver_icon.mjs` | 13 | — | **131** py + **27** js |
| S8 | `test_window_catalog.py`, `js/test_live_debug_panel.mjs` (part 1) | 11 | `test_grid_layout.py` (4 counts), `js/sash_harness.mjs`, `package.json` | **132** py + **28** js |
| S9 | `js/test_live_debug_panel.mjs` (part 2, appended) | 13 | `package.json` | **132** py + **28** js (the `.mjs` grows, the file count does not) |
| S10 | — | 3 checks (doc/consistency, net-zero re-run, orphan adoption) | `package.json` (only if the orphans are adopted: 28 → 30) | final: **132** py + **28** js (→ **30** js only if L-7's two orphans are adopted) |

Measured base counts (so the ledger is checkable): **116** `tests/**/test_*.py` files and **30**
`.mjs` files on disk, of which only **25** are listed in `package.json`'s `test:js` ⇒ **5 unlisted**:
three harnesses (`fake_dom.mjs`, `sash_harness.mjs`, `user_layout.mjs` — correctly unlisted) and
**two real test files that never run** (`test_captcha_saved_page.mjs`, `test_title_fit.mjs` — L-7,
D-27b). The chain adds **16** new `.py` test files and **3** new `.mjs` files ⇒ 19 new test files,
134 new test functions.

Every new production function in §1-§2 of each stage has at least one test above that fails if the
function is deleted (RULE 16.7 line 6); the mapping is `quality-budget.md` §4/§6.1.

## D. Measured headroom for every file a stage touches

Measured at `6bbaf8b` with `tools/verify_quality.current_maxima` (the same function the gate uses;
`radon` is absent in this checkout, so CC comes from `compute_cc_simple` — re-measure at S0 after
`pip install -r requirements.txt`). "Room" is what the ratchet still allows **in that file**.

| File | loc | class | methods | CC | nest | params | lines | funcs | Stages |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `app/ui/panels/page_pool.py` | 16 | 139 | 9 | 7 | 1 | 4 | 234 | 14 | S1 |
| `app/services/run_state.py` | 18 | 7 | 0 | 7 | 2 | 3 | 417 | 33 | S4 |
| `app/services/single_job_runner.py` | 26 | 18 | 0 | 9 | 2 | 4 | **939** (baseline says 902) | **79** (76) | S2, S3 |
| `app/services/captcha/service.py` | 27 | 31 | 4 | 7 | 1 | 4 | 310 | 23 | S2, S3 |
| `app/services/captcha/signals.py` | 16 | 44 | 2 | 8 | 1 | 2 | 115 | 5 | S2 (docstring) |
| `app/browser/output_wait.py` | 23 | **4** | 0 | 8 | 3 | 4 | 211 | 17 | S3 |
| `app/browser/cdp_arena/output.py` | 16 | **7** | 0 | **4** | **1** | 4 | 182 | 14 | S3 |
| `app/services/cooldown_service.py` | 22 | 11 | 0 | 10 | 3 | 4 | 787 | 62 | **untouched** |
| `app/ui/panels/run_control.py` | 19 | 115 | **10** | 6 | 2 | 3 | 275 | 20 | S4, S5 |
| `app/ui/panels/queue_scan.py` | 19 | 86 | **10** | 7 | 2 | 3 | 315 | 25 | S4, S5 |
| `app/services/batch_orchestrator.py` | 17 | 10 | 0 | 7 | 2 | 3 | 492 | 38 | S4, S5 |
| `app/services/multi_page_dispatcher.py` | 29 | 9 | 0 | 8 | 2 | 4 | 397 | 27 | S5 |
| `app/ui/bridge_context.py` | 19 | 7 | 0 | 4 | 1 | 3 | 196 | 13 | S4 |
| `app/ui/main_window.py` | 26 | 123 | **10** | 6 | 1 | 2 | 154 | 11 | S6 (+1 line) |
| `app/ui/panels/browser_tabs.py` | 20 | 76 | 7 | 7 | 2 | 4 | 544 | 41 | S6 |
| `app/ui/panels/url_queue.py` | 14 | 115 | **11** | 6 | 2 | 3 | 251 | 22 | S6 |
| `app/persistence/config_manager.py` | 13 | 44 | 7 | 4 | 2 | 3 | 124 | 17 | S6 |
| `app/ui/panels/app_settings.py` | 18 | 118 | **10** | 7 | 3 | 3 | 359 | 28 | S6 |
| `app/ui/panels/layout_state.py` | 19 | 136 | **14** | 6 | 2 | 3 | 281 | 25 | S6, S9 |
| `app/core/models.py` | 28 | 74 | 3 | 3 | 2 | 3 | 292 | 14 | S7 |
| `app/ui/services/arena_serialize.py` | 23 | 0 | 0 | 5 | 1 | 1 | 91 | 5 | S7 |
| `app/ui/services/undo_entries.py` | 17 | 0 | 0 | 7 | 2 | 3 | **406** (404) | 35 | S7 |
| `app/core/layout_service.py` | 21 | 4 | 0 | 9 | 4 | 3 | 300 | 25 | S8 |
| `app/browser/page_status.py` | 22 | **79** | 6 | 3 | 1 | 2 | 106 | 7 | **untouched** (S9 needs no field) |
| `app/services/auto_connect.py` | 19 | 9 | 0 | 9 | 4 | 4 | 286 | 22 | **untouched** (read by S6/S7) |

Two files carry a **stale soft baseline** (`file_lines`/`func_count` only — those two metrics are
recorded but not enforced, `verify_quality.py:171-175`): `single_job_runner.py` 902 → 939 and
`undo_entries.py` 404 → 406. Every **enforced** maximum in the whole baseline still matches the tree
(a full re-measure of all 222 entries found **0 ratchet breaches at `6bbaf8b`**), so the chain starts
from a gate-clean tree — that is S0's equivalence claim, and it is verified, not assumed.

## E. TDD anti-gaming rules for this chain (in addition to `quality-budget.md` §9)

1. **A RED test that passes at base is not a RED test.** Each stage's block 3 states the expected
   failure; if the failure does not appear, the test is asserting the wrong thing (or the defect is
   already fixed — then the stage is re-scoped, not silently skipped).
2. **No test double may replace the seam under test** (L-6). Fakes are allowed at the *boundary*
   (CDP, dialogs, the network, the clock) and forbidden at the *subject* (the scheduler, the funnel,
   the predicate, the registry).
3. **Every counting/zero-activity test ships with a positive control** (S2 test 10, S3 test 18).
4. **Source-level locks are allowed and encouraged** where the property is structural, not
   behavioural: "no `_schedule_coro` in `page_pool.py`" (S1), "no `_run_state =` in the
   orchestrator/dispatcher" (S5), "no `elif` in `removable_rows`" (S6), "no JS 15 s timer" (S6),
   "`render.js` is still 74 lines" (S7), "no `save_settings` in the debug panel" (S9).
5. **A stage is not green until its own tests *and* the frozen seams are green** — the seam list in
   §A is run every stage, not only at S10.
6. **Goldens are regenerated only with a reviewed reason** (`UPDATE_GOLDENS=1` + the diff pasted into
   the commit message). The expectation for this chain is: S2 keeps them identical by arming the
   Watcher in the harness; S5 keeps them identical by running the supervisor runner; every other stage
   does not touch them.

---

## F. RULE 16 / RULE 18 recheck for this document (the brief asks for it at the end)

| Rule | Where this document satisfies it | Status |
|---|---|---|
| **RULE 16.6 step 3 — tests before code** | §S1…§S10 each open their test block with **`RED at base:`** and the exact expected failure (`ModuleNotFoundError`, `AttributeError`, a missing registry entry, a byte-diff on a golden, a line-count guard). 134 new test functions in 19 new files (§C), and no stage lists a production edit before its RED block | ✓ |
| **RULE 16.6 step 4 — measure after** | Every budget in §1/§2 is written against the **measured** maximum of the file it lands in (§D), measured with the gate's own `current_maxima()`/`node_loc`/`compute_cc_simple` at `6bbaf8b` (0 breaches today; `evidence.md` §9.1). S10 §4 is the full-lane command list incl. `radon cc -s` on the new modules | ✓ |
| **RULE 16.0-16.5 hard limits** | No new symbol in this plan exceeds 30 LOC / 4 params / CC 10 / nesting 4; the two documented deviations (`run_live` 28, `reconcile_once` 28) stay under 30 and carry an `# ideal-size:` reason. Legacy offenders are **not grown**: `single_job_runner.py` (939 actual), `cooldown_service.py` (787, untouched), `PagePool` (CC 10 = hard limit, untouched), `PageInfo` (span 79 = file max, no new field) | ✓ |
| **RULE 16.7 acceptance checklist** | Mirrored per stage in `quality-budget.md` §8.0/§8.1; this document adds the two checklist lines that are easy to fake: "every new function has a test that fails if it is deleted" (§C mapping) and "no test doubles the seam it tests" (§E 2, D-27) | ✓ |
| **RULE 17 docs in the same change** | Each stage's block 4 ends with the exact `docs/current/` rows it updates (SYSTEM_OF_RECORD rows 6/8/11/12/19/21, I-39…I-46, `QUALITY_RECHECK.md`), and S10 only *verifies* consistency (§S10 block 3, check 1) | ✓ |
| **RULE 18.1 function 4-20 LOC** | All new symbols are budgeted ≤ 20 except the two loops above; the chain **shrinks** three over-ideal functions: `_manual_wait` 27 → ~21 (S3), `handle_captcha` 21 → 4 + a moved body (S2), `auto_scan_pass` 13 → 2 (S6) | ✓ |
| **RULE 18.2 file 150-300 LOC** | New files: `pause_clock.py` 60, `window_catalog.py` 45, `debug_view.py` 45 → 90, `bus.py` 90, `policy.py` 55 — each sub-150 with a one-decision reason (`quality-budget.md` §5 row 18.2b); existing files move **towards** the band: `layout_service.py` 300 → ~272, `browser_tabs.py` 544 → ~440, `batch_orchestrator.py` 492 → ~445, `cdp.js` 135 → 134, `sash-grid.js` 123 → 114 | ✓ |
| **RULE 18.3 module 5-15 files** | `core` 13 → **15**, `services/live` 0 → **7**, `captcha` 6 → **7**, `services` 12 unchanged; the two already-over-ideal modules (`browser` 23, `ui/panels` 16) are **not worsened** — D-25 is precisely the decision that keeps `browser` at 23 while still giving `PauseClock` a legal home | ✓ |
| **RULE 18.4 context 60-200 LOC per reading unit** | The debug window is read as 4 files × 60-130 LOC; `window_catalog.py` (45) is read together with `layout_service.py`'s re-export; `pause_clock.py` (60) is read with `output_wait._check_timeout` (11) — every pairing is named in §1 of its stage | ✓ |
| **RULE 8 tests execute the real thing** | §0.2 inventories the real fixtures (real `Bridge` + `ConfigManager` in the characterization harness, real `PagePool`, real socket CDP stub, real `index.html` script list in harness B) and §E 2 forbids doubling the subject; the five L-6 doubles are removed in S1 | ✓ |
| **RULE 10 one control per decision** | one interval writer (`url-list/interval.js` → `save_settings`; the debug window is read-only, D-12R, locked by §S9 test 12), one receiver writer (`mark_receivers`), one pause owner (`PauseClock`), one queue funnel (`commit_queue`), one run-state writer (`set_run_state`), one window table (`window_catalog.WINDOWS`) | ✓ |
| **RULE 19 complexity before size** | Every stage's §1 introduces **data** before branches: `WaitSpec.pause`/`PauseClock` (S3), `RemovalSpec`/`Removal` + a predicate table (S6), `receiver` flag + `receiver_reason` (S7), `WINDOWS` table (S8), `PassPlan` + `REASON_LINES` (S5); two source-level locks forbid if/elif chains (§S6 test 8, §E 4) | ✓ |
| **Plan-only constraint** | This document changed no file under `app/`, `tools/`, `tests/`, `web/` — `git status` for the revision shows docs only (`design.md`, `evidence.md`, `quality-budget.md`, `tdd-interfaces.md`, `docs/README.md`) | ✓ |

**Open owner question (unchanged, §12 item 6 of `design.md`):** whether the pause cap deserves its own
`captcha_pause_cap_sec` key instead of sharing `watcher_captcha_timeout_sec`. This plan defaults to
sharing it (D-14R was stated in terms of the existing knob) and the interface keeps the choice cheap:
`policy.pause_cap_seconds(bridge)` is the single read site, so a second key is a one-function change in
S3 with no test churn beyond one parametrised case.
