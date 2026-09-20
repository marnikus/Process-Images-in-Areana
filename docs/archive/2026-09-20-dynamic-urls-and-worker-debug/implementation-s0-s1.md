# S0 + S1L-1 implementation — 2026-09-20

Scope: **only S0 (prerequisite) and S1L-1** from the staged plan.
Base: `528af87e8092e1066c6c8ed5f7c82e34546313e6`.
Branch: `arena/01a0bf1f-process-images-in-areana`.

**Status:** bootstrap/baseline captured; scheduler fix implemented and regression-tested.
**Release acceptance is blocked**, not green: the checkout already fails hygiene and
quality gates. No S2–S10 work, baseline reset, gate suppression, commit or push was performed.

## 1. S0 — bootstrap before any test or production edit

Installed `.venv` with Python 3.11.2, requirements, radon, vulture, coverage,
`cognitive-complexity==1.3.0`, and pyflakes. Ran `npm ci` (Node 22.22.3,
npm 10.9.8): 152 packages installed, zero audit vulnerabilities. Dependency files
were not changed. Environment artifacts remain ignored.

Captured the full Python suite with branch coverage, JS suite, quality gates,
vulture, duplication and hashes of all 12 golden traces before S1. These are
measurements of this checkout, not the older `6bbaf8b` plan numbers.

Machine-readable baseline and after-results:
`docs/archive/2026-09-20-dynamic-urls-and-worker-debug/s0-s1-measurements.json`

| Measurement | S0 before | S1 after |
|---|---:|---:|
| Full pytest | 1,612 passed / 1 failed / 11 skipped | 1,616 passed / 1 failed / 11 skipped |
| Listed JavaScript suite | 240 passed | 240 passed |
| Golden scenarios | 12 passed | 12 passed; hashes unchanged |
| Actual statement coverage | 87.7408% | 87.7483% |
| Branch coverage | 83.2136% | 83.2462% |
| Gate's combined coverage (`percent_covered`) | 86.8930% | 86.9052% |
| Pool panel combined coverage | 82.2430% | 83.1776% |
| jscpd (`--min-tokens 60`) | 1.119277% / 23 groups | unchanged |
| Vulture @90 with whitelist | zero findings | zero findings |
| All-files quality gate | 121 failures | same 121 findings, identical digest |
| Explicit pool-file gate, including coverage checks | 3 failures | same 3 failures |
| Combined pre-push | exits 1 at hygiene | same blocker |

Only `app/ui/panels/page_pool.py` changed coverage; no other file's summary decreased.
The gate labels combined statement/branch coverage as its line metric; actual line
coverage is listed separately above to avoid conflating them.

### Pre-existing blockers (preserved, not hidden)

1. `tests/test_repo_hygiene.py::test_no_runtime_data_is_tracked` finds six tracked
   runtime artifacts: two Python 3.10 `.pyc` files and `config/app_state.json`,
   `config/captcha_stats.json`, `config/cooldowns.json`, `config/undo.json`.
   `pre_push_check.sh` stops there before running later lanes. Those lanes were
   run independently. No runtime contents were copied into this report.
2. With cognitive-complexity 1.3.0 installed, 119 files exceed recorded
   `max_cog: 0` values. The pool panel measures **6 before and after**, not zero.
   This is baseline drift, not a complexity increase introduced by the fix.
3. Two unchanged per-file combined coverage checks fail:
   `app/browser/cdp/transport.py` 84.2697% against 90.45%, and
   `app/ui/qt_compat.py` 39.2857% against 60.71%.
4. PySide6 is installed, but QtWidgets cannot import without system `libGL.so.1`.
   Tests use the existing headless fallback. The real QObject metaobject test
   skips; its source/contract checks pass unchanged. No live Chrome/Qt UI claim
   is made. L-5 (pool window visibility) is explicitly still deferred to S8.

The ordinary `--changed --base 528af87e...` invocation reports no gated files
for these uncommitted edits and loudly falls back to all files. We also ran
`--changed-files app/ui/panels/page_pool.py` to explicitly gate the edited module.
Neither invocation is reported as green. The historical green-start prerequisite
cannot be satisfied on this checkout without separate hygiene/baseline remediation;
S1 is measured against the captured failing baseline, not accepted for release.

## 2. S1L-1 — interface → RED → GREEN → test refactor

**Interface plan (before tests):** keep `PagePoolMixin.connect_page_pool(self,
ws_url: str)` and its JSON vocabulary unchanged. Import the existing
`app.services.run_state.schedule_coro` and call it with `(self, coroutine)`.
Do not add a Bridge method, slot, signal, scheduler wrapper or package.
The existing join coroutine still owns CDP attachment and pool registration.

**RED:** added `tests/test_page_pool_join.py` and ran it before production edits:
**2 failed / 2 passed**. The scheduling test returned
`{"ok": false, "error": "'Host' object has no attribute '_schedule_coro'"}`;
the source guard also found the private scheduler call. The guard/error-vocabulary
and direct-join equivalence paths were already green.

**GREEN:** exactly two production lines changed: extend the existing import and
replace `self._schedule_coro(...)` with `schedule_coro(self, ...)`.
All four new tests then passed.

**L-6 test refactor:** removed all five fake `_schedule_coro` attributes from
`tests/test_panel_browser_tabs.py`. Its connect/cooldown test now spies on the real
module helper, waits for its returned future and asserts the registered page.
All existing cooldown expectations remain. This is a delegating spy, not a
scheduler replacement. The new regression test also executes the real scheduler
and join, using a running test event loop and the existing fake websocket transport.
Clients disconnect during cleanup; no sleeps or detached test threads are needed.

New test coverage:
- Host without `_schedule_coro` → one real scheduling call → steady pooled page
  → one pool-status notification.
- Source guard prevents reintroducing the private scheduler seam.
- Empty URL / absent pool retain exact error replies and schedule nothing.
- Direct join preserves page identity, connected client/controller registration,
  websocket URL and notification (positive control).

Focused equivalence command passed **70 tests, 1 skipped**, including all goldens:
`tests/test_page_pool_join.py`, `tests/test_panel_browser_tabs.py`,
`tests/test_page_pool.py`, `tests/test_run_state.py`, `tests/test_bridge_slots.py`,
`tests/test_bridge_metaobject.py`, `tests/characterization/`.
Frozen slot surface is **135**, not the old plan's 134; contract tests and goldens
were not edited. The existing unrelated unawaited-coroutine warnings remain;
the pool test's formerly unawaited join is now consumed.

## 3. RULE 16 / RULE 18 final review

- Edited slot: **11 physical LOC, CC 4, cognitive 3, nesting 1, one parameter
  excluding self**; within both hard limits and the 4–20-line ideal.
- Production file: **234 lines**, 14 functions; all measured maxima unchanged:
  function LOC 16, class LOC 139, methods 9, CC 7, cognitive 6, nesting 1, params 4.
- No new production symbol, abstraction, dependency, override or decision removed.
  No RULE 19 remediation needed: neither complexity nor size increased.
- The existing class exceeds the 120-line preference, not the 150-line hard cap;
  its existing `ideal-size` explanation preserves the nine frozen slot/helper pairs.
- New test file is a small focused leaf. Tests/docs are exempt from RULE 16
  production size gates. Existing oversized context docs receive targeted row/link
  edits only; restructuring them would expand beyond S0/S1.
- Syntax compilation and undefined-name check passed. Vulture and duplication
  did not regress. All baseline files and golden contents remain untouched.
- RULE 17: current row 19 and the docs map now distinguish the repaired slot from
  deferred UI visibility/later stages. Original archived designs/evidence remain
  immutable; this record closes **L-1 and L-6**, not L-5/L-7/L-8.
- **RULE 16 release gate is NOT passed** because of the captured existing blockers.
  No bypass, metric gaming or automatic re-baselining was used.

## 4. Reproduction commands

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt radon vulture coverage cognitive-complexity==1.3.0 pyflakes
npm ci
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_page_pool_join.py -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m coverage run --branch --source=app -m pytest tests -q -p no:cacheprovider
.venv/bin/python -m coverage json -o coverage.json
npm run test:js
.venv/bin/python tools/verify_quality.py --allow-legacy --coverage-ratchet
.venv/bin/python tools/verify_quality.py --changed-files app/ui/panels/page_pool.py --allow-legacy --coverage-ratchet
.venv/bin/radon cc -s app/ui/panels/page_pool.py
.venv/bin/python -m vulture app tools/vulture_whitelist.py --min-confidence 90
npx --no-install jscpd app --min-tokens 60 --reporters json --output /tmp/s0-s1-jscpd --silent
bash tools/pre_push_check.sh
git diff --check
```

Raw local execution logs and the complete pip freeze were kept outside Git under
`/home/user/s0-s1-evidence/`; the compact measurements above are the durable record.
