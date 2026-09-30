# New-tab handover + pool/cooldown seams — audit #4 and TDD refactor design (2026-09-30)

Follow-up to audit #3 (`docs/archive/2026-09-29-workspace-refactor-3/audit.md`, I-81), which reviewed the
**workspace save/restore** feature and explicitly left the rest of the range alone
(*"Out of scope and not touched: the new-tab / app-close / cooldown-home / unanswered-poll work in the same
range"*). This pass reviews that work — the second half of the range — at the owner's request.

**Range under review.** `1c0ff4c5…97f4ed37` (36 commits). Within it, the code this audit looks at:

| Phase | Commits | What was added |
|---|---|---|
| I-79 — "Start new chat as new tab" | `8410cb90` (feature) + 9 fixes `46bcf319`, `4f9e036b`, `7831e2bf`, `dbe1e846`, `34381d4a`, `db5f5377`, `407524c5`, `5b170314`, `b0b81fc7` (v5 profile-truth rewrite) + `97f4ed37` (tests) | the handover chain and its v5 split |
| I-80 — one home per setting, quiet countdown | `a12a262a`, `85fc8db0`, `0a848315`, `592054fa`, `217fbe87` | cooldown single-home + countdown notes |

**In scope (reviewed in depth).** `app/services/new_tab.py`, `new_tab_open.py`, `new_tab_setting.py`,
`app/browser/cdp/browser_targets.py`, `app/browser/page_popup.py`, `app/browser/cdp/tabs.py` (v5 shrank it),
`app/browser/page_pool.retarget_page`, `app/services/cooldown_service.py` (`_try_new_tab` / `_best_effort_reset`),
`app/core/cooldown.py` (`countdown_note`, `CountdownNotes`), `app/services/live/supervisor.py` (the all-cooling
wait line), `app/ui/panels/page_pool.py` (settings save), `app/ui/web/js/panels/job-cycle-setting.js`, and the
five test suites that pin them.

**Checked and deliberately kept (no action).** The URL-list reconciler itself (`services/live/reconcile*.py`,
`url_policy.add_rows` / `remove_rows` / `dedupe_rows`) and the pool join/leave slots
(`ui/panels/url_queue.enter_pool_for_checked` / `exit_pool_for_unchecked`) **predate the range**; the range only
passes through them (`page_pool.retarget_page`, `mark_receivers`). The Firefox lane, `cdp_arena`, and the six
pre-existing repo-wide gate findings are out of scope, as in audit #3.

**Method.** Read every in-scope symbol first; measured sizes, nesting, CC, duplication, dead code and per-file
coverage on the real code; each finding below was reproduced before it was written down. No production change was
made before this document.

## 1. Code map of the added code

```
app/services/new_tab.py            298  handover pipeline: _plan → _hold_reconciler → _with_browser → _run
                                         (read profile truth → open in it → connect clients → prove new chat →
                                          move worker → close old), rollback in _refuse
app/services/new_tab_open.py       135  the two openers: Target.createTarget in the context, else the job tab's
                                         own page (window.open); _proven() = the browser's own list is the judge
app/services/new_tab_setting.py     48  the option's keys, URL healing, session read/write (stdlib only)
app/browser/cdp/browser_targets.py 168  BrowserTargets: dial (via /json/version), targets/create/close/aclose;
                                         pure helpers endpoint_of_ws, context_of, target_of, matching_targets
app/browser/page_popup.py           75  the page opener: JS builder + reply verdict (userGesture = allowed)
app/browser/cdp/tabs.py            129  (v5 removed open_tab_sync/close_tab_sync; now sync /json/list only)
app/browser/page_pool.py           299  retarget_page + _rekey: the worker keeps identity, moves key in order
app/core/cooldown.py               123  countdown_note + CountdownNotes (2 lines max per wait) + format_remaining
app/services/live/supervisor.py    224  the run-live wait states; the all-cooling line uses CountdownNotes
app/services/cooldown_service.py   848  _try_new_tab (the seam), _best_effort_reset, wait_for_tab_ready
app/ui/panels/page_pool.py         339  Settings → Job Cycle save/read through new_tab_setting
js/panels/job-cycle-setting.js      83  the Settings box; save sends only {enabled, new_tab, new_tab_url}
tests/                             1 225  test_new_tab_handover (36), test_new_tab_open (11),
                                         test_browser_targets (24), test_page_popup (8), test_new_tab_setting (13),
                                         test_cooldown_single_home (10), test_cooldown_countdown_log (17),
                                         test_live_supervisor (12), jsdom test_job_cycle_setting.mjs (12)
```

## 2–3. Findings, evidence, severity

### Duplication — the same rule written twice

| id | Sev / risk | File · symbol | Evidence |
|---|---|---|---|
| **N1** | **Medium** / a probe that must behave identically (RULE 4: one home) exists twice; a fix to either silently misses the other | `new_tab.py:224 _read_owner_from_client` vs `live/tab_owner.py:41 _read_owner` | byte-for-byte the same three ideas: `client.evaluate(build_owner_probe())` → `interpret_owner(reply).get("email")` → `normalize_owner(...)`; `tab_owner` (the I-79-era owner module, already the home of *when* the probe runs) keeps it private, so `new_tab` re-implemented it **and** imports the probe lazily inside the function |
| **N2** | **Medium** / latent wrong answer: a pool label that is not an email makes the guard compare unlike strings | `new_tab.py:249 _check_owner_preserved` | `new_owner == move.owner.lower()` — a **second** normalization rule next to `tab_alias.normalize_owner` (trim + lower + validate, else `""`), which `_read_owner_from_client` already applied to the other side. `_plan` stores the raw label (`owner=str(getattr(page, "owner", "") or "")`, `new_tab.py:108`, default `pattern: str = "arena.ai"`); an alias label or `Owner@Example.com` therefore produces either a false `Owner mismatch … rollback` or a false pass |
| **N3** | **Low** / a default with four homes: changing the config default leaves the log line lying | `new_tab.py:53 _Move.pattern`, `new_tab.py:60–68 _get_pattern` | `"arena.ai"` is written in `_Move.pattern`, twice in `_get_pattern`, and already had two named homes — `config_manager.DEFAULT_SESSION["url_pattern"]` and `services/live/reconcile_rows.DEFAULT_PATTERN` + `PATTERN_KEY` (legacy `ui/panels/cdp_tools.py` adds three more) |
| **N4** | **Low** / the ws URL is formatted in one module and parsed in another; the pair drifts | `new_tab.py:183 _page_ws` vs `browser_targets.py:26 endpoint_of_ws` | `f"ws://{host}:{port}/devtools/page/{target_id}"` is built in `new_tab`, while the reverse mapping (and the "unreadable socket" rule) lives in `browser_targets`; six legacy sites parse the same shape (`cdp/connect.py` ×3, `ui/panels/browser_tabs.py` ×2, `ui/panels/page_pool.py` ×1) |
| **N5** | **Low–Med** / a private attribute of another layer read in 9 places — the new code adds two | `new_tab.py:83 _clients_on`, `new_tab.py:90 _popup_client` | `getattr(client, "_current_tab_id", …)` — the attribute is owned by `cdp/transport.py:58` and set by `cdp/connect.py:181`; the same read appears in `services/live/supervisor.py:123`, `ui/panels/browser_tabs.py:279/293/311`, `ui/panels/watcher_solver.py:122` |
| **N6** | **Low** / latent display bug at the ≥1 h boundary, and a second formatter to keep in sync | `live/supervisor.py:139 _next_ready` | `f"{secs // 60:02d}:{secs % 60:02d}"` re-implements `core.cooldown.format_remaining` (the home used by `cooldown_service`, `tab_reset`, `page_pool`). Verified: `format_remaining(4500)` → `1:15:00`, the supervisor form → `75:00`; cooldown values are clamped to `DAY_SECONDS` (86 400), so a long pause prints minutes past 60 |

### Structure, typing, tests

| id | Sev / risk | File · symbol | Evidence |
|---|---|---|---|
| **T1** | **Low** / the seam is `Any`: the contract of the handover context is undocumented and unchecked | `new_tab.py` — `handover(ctx: Any, …)`, `_plan(ctx: Any, …)`, `_run(move, …)` | the pipeline uses six attributes (`bridge`, `pool`, `tab_id`, `client`, `ctrl`, `bridge.cdp`/`_auto_scan_running`) and **mutates** `ctx.tab_id`; the only real provider is `cooldown_service.FinishCtx` (+ `SimpleNamespace` in tests). A `Protocol` in `new_tab` documents it without creating the import cycle a `FinishCtx` import would |
| **S1** | **Low** / the only function over RULE 18's ideal in the area (23 LOC, 5 stages + 3 refusal exits) | `new_tab.py:148 _run` | linear but long: targets → context → log → open → connect → prove → move → close; the first three lines are one idea ("read the profile truth") and the last two another ("finish the move") |
| **C1** | **Low** / the largest function in the area is a test fixture (47 LOC, 7 keyword params) | `tests/test_new_tab_handover.py:185 _world` | over RULE 18's fail line for functions (>30) — in a test file, so it cannot fail the gate, but it is also the least readable seam in the suite: `_world(monkeypatch, old_ctx=…, other_ctx=…, host=…, port=…)` |

### Kept deliberately (re-checked, no action)

* **`_Move`'s 13 fields** (`new_tab.py:41`) — a context object is what keeps params ≤4 through an 8-stage
  pipeline (RULE 16 params rule); splitting it into `TabRef` + `Profile` would be a speculative abstraction for a
  single consumer. Documented, not changed.
* **The two `FakeBrowser` classes** (`test_new_tab_handover.py:38` = a Chrome canvas with contexts/owners;
  `test_new_tab_open.py:22` = a scripted `BrowserTargets` surface) — different fixtures for different questions;
  unifying them would couple two suites to one model.
* **`browser_targets._browser_ws_url` importing `tabs._fetch_json_sync`** — a labelled same-layer private import
  (comment in the file), and `tabs` owns the HTTP fetch.
* **Legacy, listed not touched**: the unused import `cooldown_service.py:20 restore_page_stats` (pyflakes; *not*
  introduced by the range — verified with `git log -S`), `vulture`'s `page_pool.py:139 'l'` (a lambda parameter),
  the remaining `_current_tab_id` readers and `_page_ws`-shaped strings in `cdp/connect.py`, `browser_tabs.py`,
  `page_pool.py`, `cdp_tools.py`, and `run_state.py:372`'s hand-built `MM:SS`.

## 4. Proposed interfaces — only where they remove real duplication or coupling

1. `live/tab_owner.read_owner(client) -> str` (public; today's `_read_owner` with its logging). One home for
   "email from a client"; `new_tab` calls it instead of its private copy (N1). No new module, no new layer —
   `services.new_tab` already imports `services.live.url_policy`.
2. `browser_targets.page_ws(host, port, target_id) -> str` — the formatter that `endpoint_of_ws` inverts, in the
   module that owns endpoint truth (N4). Round-trip property test.
3. `new_tab.HandoverCtx` — a `typing.Protocol` naming the six attributes the pipeline reads and the one it writes
   (T1). Runtime-free; nothing imports `cooldown_service` from `new_tab`, so no cycle.
4. Owner normalization at the boundary: `_plan` stores `normalize_owner(page.owner)` — deletes the second
   normalization rule (N2) instead of adding one.
5. Pattern default: `reconcile_rows.PATTERN_KEY` / `DEFAULT_PATTERN` used by `_get_pattern` (N3) — no new home.
6. `_next_ready` calls `core.cooldown.format_remaining` (N6) — no new home.

No other interface is proposed: nothing else in the area duplicated a rule, and the pipeline's own boundaries
(`new_tab` / `new_tab_open` / `browser_targets` / `page_popup` / `new_tab_setting`) already match their jobs.

## 5. Ordered plan — small, independently testable, reversible steps

| Step | Change | Files |
|---|---|---|
| **P1** | RED: a test that the handover's owner read goes through the one home, then promote `tab_owner.read_owner` and delete `new_tab._read_owner_from_client` | `live/tab_owner.py`, `new_tab.py`, `tests/test_new_tab_handover.py`, `tests/test_firefox_identity.py` (guard) |
| **P2** | RED: owner labels that are not emails / not lowercase must not roll back a proven profile; normalize at the boundary, compare equal strings | `new_tab.py`, `tests/test_new_tab_handover.py` |
| **P3** | Pattern default from the named home; drop the dataclass default | `new_tab.py`, tests |
| **P4** | `browser_targets.page_ws` + round-trip test; `new_tab._page_ws` deleted | `browser_targets.py`, `new_tab.py`, `tests/test_browser_targets.py` |
| **P5** | `supervisor._next_ready` → `format_remaining`, with a ≥1 h regression test | `live/supervisor.py`, `tests/test_live_supervisor.py` |
| **P6** | `HandoverCtx` Protocol + annotations (typing only, no runtime change) | `new_tab.py` |
| **P7** | Optional, structural: `_run` split into `_profile_truth` + the move/close tail; `_world` becomes a dataclass with ≤4 params | `new_tab.py`, `tests/test_new_tab_handover.py` |
| **P8** | Docs: SoR I-79 rows (owner read, pattern home, countdown format), README last-updated, this file's execution log + measured after-values | docs |

P1–P5 are behavior-visible and each carries a RED test **first**; P6 is typing only; P7 is structural (no behavior
change) and can be dropped without affecting the others.

## 6. Behaviour preservation and rollback per step

| Step | Behaviour that must not change | Rollback |
|---|---|---|
| P1 | the probe payload, the retry count (2 × 0.5 s), and `""` for every failure mode | `git revert` — one import + one function body; the private copy stays in history |
| P2 | an empty owner still skips the guard; a real mismatch still rolls back with the same message shape | revert; the old `.lower()` line is one edit |
| P3 | the fallback value is still `arena.ai` when the session is unreadable | revert |
| P4 | the produced string is byte-identical to today's `_page_ws` | revert (call site + helper) |
| P5 | `--:--` when unknown; identical text for every value < 1 h | revert |
| P6 | nothing at runtime (annotations only); `new_tab` must stay importable from `cooldown_service` | revert |
| P7 | same call order, same log lines, same return values; only the internal function boundaries move | revert (pure extraction) |

Every step keeps the file buildable and the gate green on its own; no file-format, slot or public-API change is
involved anywhere in this plan.

## 7. Tests required before and after each step

* **Before P1–P5 (characterization, already present):** the five suites — 92 tests — pin the pipeline end to end
  and each of the five new modules is at **100 % line / 100 % branch** coverage (`coverage run` over the area
  suites; measured 2026-09-30). `new_tab_setting` 100 %, `browser_targets` 100 %, `page_popup` 100 %.
* **New tests (RED first):** P1 — a handover test that patches `tab_owner.read_owner` and asserts it was used
  (fails on the current tree, where `new_tab` never calls it); P2 — `Owner@Example.com` and `aka_1234` labels do
  not roll back, a genuine mismatch still does; P3 — the log line uses `reconcile_rows.DEFAULT_PATTERN`;
  P4 — `page_ws` round-trips through `endpoint_of_ws` (fails: no such name); P5 — `_next_ready` of a 4 500 s wait
  is `1:15:00` (fails: `75:00`).
* **After every step:** the five suites + `tests/test_live_supervisor.py` + `test_firefox_identity.py` +
  full `pytest`, then the quality gate on the touched files (`--allow-legacy`).
* **Not required but useful:** a mutation-style check that deleting any of the five new modules fails a test —
  the 100 % branch coverage already implies it for the v5 modules.

## 8. Documentation changes after the code is reorganised (P8)

1. `SYSTEM_OF_RECORD.md` I-79 row: owner read goes through `tab_owner.read_owner` (one home), the pattern default
   is `reconcile_rows.DEFAULT_PATTERN`, owner labels are normalized with `tab_alias.normalize_owner`.
2. I-80 row (or the countdown part of it): the wait text has one formatter (`core.cooldown.format_remaining`).
3. `docs/README.md` "last updated" entry.
4. This file: execution log, measured after-values, kept/unfixed list.

## 9. Metrics (same commands before and after)

| Metric | Before (measured on `97f4ed37` + audit-#3 branch) | Target after |
|---|---|---|
| files / lines, in-scope production code | 11 / 2 430 (incl. `cooldown_service` 848) | ≤ +0 lines outside P4's helper; `new_tab.py` 298 → ~285 |
| functions > 20 LOC (production) | 1 (`_run`, 23) | 0 |
| functions > 30 LOC (whole area incl. tests) | 1 (`_world`, 47) | 0 |
| params > 4 (whole area incl. tests) | 4 (all test helpers) | 3 (or fewer) |
| max nesting / max CC / radon average | 3 / A (3.63, no block ≥ C) | unchanged |
| rules with two homes (this audit's N1–N6) | 6 | 0 |
| `format_remaining` duplicates | 2 (`supervisor`, legacy `run_state`) | 1 (`supervisor` fixed; legacy listed) |
| per-file coverage, five new modules | 100 % / 100 % | unchanged (no new untested branch) |
| area test count | 132 (8 suites) | +6 … +8 (the RED tests above) |
| gate on the touched files | 0 fail (audits #1–#3 kept them clean) | 0 fail; no recorded maximum grows |

## 10. Execution log

_(appended during implementation — commit per step, gate output, measured after-values.)_
