# New-chat-as-new-tab handover (I-79) — audit & TDD refactor plan (2026-09-30)

Scope: the **I-79 line only** — `8410cb9` ("Start new chat as new tab") and the nine `fix(new_tab)`
commits stacked on it, through `b0b81fc` (profile truth v5) and the guarding tests in `97f4ed3`.
No legacy code is refactored; the text-output/preset feature that shares the same commit range
(`9861e32`, `cdp_arena/text_output.py`, `text_output_probes.py`) is a **different** feature and is
**out of scope** here.

**Headline: this line is in unusually good shape.** 5 modules, 47 functions, max CC 8, max nesting 2,
0 vulture findings, `verify_quality.py` clean, and **100 % line + branch coverage on all five
modules** across the full suite (94 behavioural tests: 36 + 11 + 24 + 8 + 13 Python, 12 jsdom).
The docstrings carry their own provenance (R1–R5, P1–P4, design §4). It is not the mess the
nine-fix-commit count suggests.

So this audit is deliberately short. **One real behavioural defect was found and reproduced**
(N1). The remaining four findings are small and are reported as such rather than inflated into
work. The refactor plan is 6 steps, 4 of which are behaviour-preserving and 1 of which is the N1 fix.

---

## 1. Code map

| File | LOC | Responsibility | Imports |
|---|---:|---|---|
| `app/services/new_tab.py` | 298 | **The handover**: plan → hold the reconciler → dial the job tab's own browser → open → prove → move the worker → close the old tab → roll back on any failure | `browser.cdp.browser_targets`, `browser.new_chat`, `browser.page_pool`, `live.url_policy`, `new_tab_open` |
| `app/services/new_tab_open.py` | 135 | **The two openers and the proof**: (a) `Target.createTarget` in the job tab's context, (b) the job tab's own `window.open`; a tab counts only when the browser's own list puts it in that context | `browser.cdp.browser_targets`, `browser.page_popup` |
| `app/services/new_tab_setting.py` | 48 | **The setting**: keys, URL healing, session read/save. A stdlib-only leaf | stdlib only |
| `app/browser/cdp/browser_targets.py` | 168 | **One endpoint's browser as CDP sees it**: `/json/version` → browser socket, `Target.getTargets` / `createTarget` / `closeTarget`, disconnect | `cdp.client`, `cdp.tabs` |
| `app/browser/page_popup.py` | 75 | **The page opener**: `window.open(url,'_blank')` with `userGesture`, built as a JSON payload | stdlib only |

**Integration seams** (read to understand the feature, not refactored):

| Seam | Line | What it does |
|---|---|---|
| `app/services/cooldown_service.py` | `_best_effort_reset` / `_try_new_tab` | The **only** caller. Both job paths (sequential and live) go through `finish_page_after_job` → `_best_effort_reset`; a failed handover falls through to the in-place `reset_to_new_chat`. Firefox (`lane_reset`) short-circuits first. |
| `app/services/live/reconcile.py` | `reconcile_once` | The **only** other writer of the same `_auto_scan_running` flag — the coupling behind N1. |
| `app/persistence/config_manager.py` | `:33-34` | The persisted defaults `new_chat_new_tab` / `new_chat_new_tab_url` — the second copy of the URL (N3). |
| `app/ui/panels/page_pool.py` | `:299, :308` | The Settings save/load slot, carried by the cooldown slots. |
| `app/ui/web/js/panels/job-cycle-setting.js` | 83 | The two controls (switch + URL field) and their pushes. |

**Tests**: `test_new_tab_handover.py` (36, 633 LOC) · `test_new_tab_open.py` (11) ·
`test_browser_targets.py` (24) · `test_page_popup.py` (8) · `test_new_tab_setting.py` (13) ·
jsdom `test_job_cycle_setting.mjs` (12).

---

## 2. Findings

### N1 — a Reparse queued during a handover is never released by the handover
**Severity: medium. Risk: a user-visible promise the code does not keep. Behaviour change required.**

`new_tab.handover` takes the shared `_auto_scan_running` flag for its whole duration:

```python
# app/services/new_tab.py:127-134
async def _hold_reconciler(bridge) -> bool:
    deadline = time.monotonic() + _RECONCILE_WAIT_SEC
    while getattr(bridge, "_auto_scan_running", False):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)
    bridge._auto_scan_running = True
    return True
```

`reconcile_once` treats that flag as "a pass is running", so a manual Reparse click during a
handover is **queued** and the user is told so:

```python
# app/services/live/reconcile.py:249-268
if getattr(bridge, "_auto_scan_running", False):
    _queue_if_manual(bridge, deps, source)     # sets _reparse_queued + logs
    return Report(error="busy")
...
if getattr(bridge, "_reparse_queued", False):   # the ONLY reader of the flag
    bridge._reparse_queued = False
    return await reconcile_once(bridge, deps, "manual")
```

`_reparse_queued` is read **only** at the end of a `reconcile_once` pass. The handover releases
`_auto_scan_running` in its own `finally` (`new_tab.py:122-123`) and **never looks at
`_reparse_queued`** — so the queued Reparse has no trigger. I-68(a) says a queued pass
"runs it the moment that pass ends"; for the new-tab holder it does not.

**Reproduced** (real `reconcile_once` + real `_hold_reconciler`, only the pass body faked):

```text
reparse during handover -> busy
flag released by handover -> True
_reparse_queued still set -> True
a pass ran by itself -> False        <-- never runs
_reparse_queued now -> True
```

**Mitigation, stated honestly:** the ~15 s `auto_connect_scan` usually starts another pass, which
drains the queue. So the practical symptom is usually a **delay**, not a lost click. But "usually" is
not the contract, the log line the user already read says otherwise, and if the scan is disabled the
click is stranded until the next manual Reparse. No test covers it (`grep reparse tests/test_new_tab_*`
= no hits).

**Not a double-acquire race** — checked and cleared: both `_hold_reconciler` and `reconcile_once`
do their check-then-set with **no `await` in between**, so on one event loop the acquire is atomic.
The docstring's "one loop: no race" claim is correct. The defect is only in the *release*.

### N2 — `_close_old` returns a value nobody reads, and the reason string over-claims
**Severity: low. Risk: misleading contract, no wrong behaviour.**

```python
# app/services/new_tab.py:169 inside _run
    _move_worker(move)
    await _close_old(move, browser)          # -> bool, discarded
    return True, f"new chat ready in the new tab {move.new_id[:12]}"
```

`_close_old` is `-> bool` and documents "still open after two closes", but no caller reads it. So a
handover that **leaves the old tab open** still returns `True, "new chat ready…"` — while
`handover`'s own docstring says "`(False, why) = nothing changed`". Something *did* change. The
error log is correct and tested (`an_old_tab_that_stays_open_is_reported_loudly`), so this is a
contract-wording defect, not a lie told to the user.

### N3 — the default new-chat URL has two owners
**Severity: low. Risk: a silent, order-dependent default.**

```python
app/services/new_tab_setting.py:16   DEFAULT_URL = "https://arena.ai/image/direct?model_a=max"
app/persistence/config_manager.py:34  "new_chat_new_tab_url": "https://arena.ai/image/direct?model_a=max"
```

`config_manager` seeds the config file; `new_tab_setting` heals a bad value. Change one and the
other silently wins depending on whether the key was already written.

### N4 — `_run` is 23 LOC, over the RULE 18.1 prefer band
**Severity: low. Under the RULE 16 fail line (30).**

`new_tab._run` is the 8-step decision path (targets → context → log → open → connect → prove →
move → close) with three early refusals. Every other function in the line is ≤ 18 LOC. It reads as
one decision, so splitting it would scatter the contract; this is recorded, not changed.

### N5 — `_log` swallows, so a log-sink failure is unloggable by construction
**Severity: low. Accepted by design; recorded for the next reader.**

`new_tab._log` is `try: bridge._log(...) except Exception: pass`, and it wraps **every** log line in
the feature. When the sink is broken the failure is invisible by definition. Test 34
(`a_log_sink_that_raises_never_breaks_the_finished_job`) pins the intent: a broken log must not fail
a finished job. Correct, and it is the same trade the workspace audit found missing in the *other*
direction (RULE 2 unsatisfied). The difference is that here the swallow is inside the reporter, so
there is nowhere left to report. Left alone, noted.

### Checked and found clean (not findings)
* **Double acquire on `_auto_scan_running`** — impossible; both check-then-sites are await-free (N1).
* **`_Move` is 15 mutable fields** — a handover record, private, mutated only by the handover; splitting
  it would be a speculative abstraction.
* **Layering** — `services` → `browser` → `cdp`, one direction, no cycles (`import` check clean);
  `new_tab_setting.py` is a stdlib-only leaf so the Settings panel never imports the CDP pipeline.
* **Error handling shape** — every public entry returns `(value, reason)`, never raises; the reason
  strings name the evidence. Exception handling is uniform.
* **Testability** — 100 % line and branch on all five modules; the browser is injected at exactly
  one seam, so the whole pipeline runs without Chrome.

---

## 3. Proposed boundaries

Only one, and it is small. Everything else this line does is already at the right size.

**The `_auto_scan_running` flag becomes an owned, releasable hold.** Today three modules reach into
`bridge._auto_scan_running` and one of them (`new_tab`) releases a flag it does not own. The
proposal is not a new lock class — it is that **`new_tab` releases the flag exactly the way
`reconcile_once` does**, i.e. through the same one function that knows a pass ended. Concretely:
`_hold_reconciler` returns a token, and the release path calls a single `reconcile.pass_ended(bridge)`
that clears the flag *and* drains `_reparse_queued` (re-entering `reconcile_once(…, "manual")`
exactly as `reconcile_once`'s own tail does). One owner for "a pass ended", one place that knows
about the queue.

Rejected as unnecessary: a generic `BusyFlag`/`Lock` class (one flag, two holders — that is a
function, not an interface), extracting `_run`'s steps into a strategy, and giving `_Move` a builder
(15 fields is fine for a private record).

---

## 4. Ordered plan — 6 steps, each buildable, testable, revertable

| # | Kind | Step | Tests before → after | Rollback |
|---|---|---|---|---|
| 1 | S | **Characterization baseline.** Pin the behaviour the later steps must not change: the full 94-test set plus a new test that the handover **does** block a running pass and **does** release the flag afterwards (covers 23/266 today only as separate assertions). | 94 → 96 | `git revert` — no production change |
| 2 | S | **Remove the dead return (N2).** `_close_old` keeps its log; its return becomes the `why` the caller appends to the success line, so the reason string can no longer over-claim. No behaviour change to any log. | +2 (the old tab closing / not closing still say the same) | `git revert` |
| 3 | S | **One default URL (N3).** `config_manager` imports `new_tab_setting.DEFAULT_URL` — the leaf is stdlib-only, so the direction is legal. Value unchanged. | +1 (the seeded default equals the healing default) | `git revert` |
| 4 | B | **N1 — the release drains the queue.** `pass_ended(bridge, deps)` in `reconcile.py` clears the flag and drains `_reparse_queued`; `new_tab`'s `finally` calls it. **RED first:** a test that queues a Reparse during a handover and asserts the pass runs. | 96 → 98 | `git revert` — the queue still self-heals on the next scan, so the revert is a delay, not a loss |
| 5 | S | **RULE 18.4 note for `_run` (N4)** and the N5 note, both as `ideal-size:` / docstring markers so the next reader sees the decision. | 98 (unchanged) | `git revert` |
| 6 | docs | **I-68 amendment + the audit trail** (§6). | — | `git revert` |

Steps 1–3 and 5 are provably behaviour-preserving and land first. Step 4 is the only behaviour
change and is isolated in its own commit. **Ordering rationale:** the N1 fix needs the
characterization of step 1 to prove it changed nothing else; N2/N3 are independent and ride along
as the reversible structure work.

**Frozen by every step:** the five module paths and their public names
(`handover`, `open_in_profile`, `OpenSpec`, `Opened`, `endpoint_of_ws`, `context_of`, `target_of`,
`matching_targets`, `dial`, `open_tab_via_page`, `read_setting`, `save_setting`, `wanted_url`,
`clean_url`); the setting keys; the ≤ 10 s reconciler wait; the two-opener order and its refusal
reasons; the profile-truth rules; the log strings' meaning; the rollback behaviour on every path.

---

## 5. Before/after metrics (measured, same commands)

| Metric | Before | Target after |
|---|---|---|
| Modules / LOC | 5 / 724 | 5 / **≈ 735** (N1's release helper + N2's reason, N3 −1 line) |
| Functions | 47 | 48 |
| Max function LOC | 23 (`_run`) | 23 — unchanged (N4 recorded, not split) |
| Max CC | 8 (`matching_targets`) | 8 |
| Max nesting | 2 | 2 |
| Params > 4 | 0 | 0 |
| `verify_quality` fails in scope | **0** | **0** |
| Vulture (feature + tests) | **0** | **0** |
| Line + branch coverage, the 5 modules | **100 % / 100 %** | **100 % / 100 %** |
| New-tab tests | 94 Python + 12 jsdom | **98 Python** + 12 jsdom |
| Confirmed defects | 1 (N1) | **0** |

---

## 6. Documentation changes

1. **`SYSTEM_OF_RECORD.md` I-68(a)** — amend: the queue is drained by whichever holder ends its pass,
   now including the new-tab handover (today it says "the moment that pass ends" without naming the
   holders).
2. **`SYSTEM_OF_RECORD.md` I-79** — add the two findings that are now decided: the success line
   names a close that did not happen (N2), and one default-URL owner (N3).
3. **`docs/current/QUALITY_RECHECK.md`** — a 2026-09-30 addendum with the table in §5.
4. **This document** stays in the archive (RULE 17); no new top-level doc.
5. No RULE amendment: N1 is a bug against an existing invariant, not a new rule.

---

## 7. RULE 16 §16.7 self-review

```text
[ ] No new function >30 physical LOC                         — the only new fn is 5 LOC
[ ] No new class >150 LOC / >15 methods                       — no new class
[ ] No new function with >4 params                            — pass_ended(bridge, deps) = 2
[ ] radon CC ≤10, cognitive ≤15, nesting ≤4 on every new fn    — measured after the step
[ ] overall line coverage ≥80 % and not below baseline         — the 5 modules stay at 100 %
[ ] every new function has a test that would fail if deleted  — §4 table
[ ] no new vulture findings, no new duplication groups          — N3 *removes* a duplication
[ ] quality-override only with a real constraint                — none added
[ ] no metric gaming                                           — no foo_part1, no lambda dispatch
[ ] RULE 18 ideals: functions 4-20, files 150-300, module 5-15   — all in range; _run recorded
[ ] RULE 19 order respected                                    — N1 is a behaviour fix; N4 records, never splits for the number
[ ] SYSTEM_OF_RECORD.md + docs/README.md updated with the code
```
