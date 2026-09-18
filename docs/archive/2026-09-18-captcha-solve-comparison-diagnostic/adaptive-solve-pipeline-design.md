# CAPTCHA Solve Reliability — Adaptive Pipeline Design

**Date:** 2026-09-18
**Status:** design; evidence-backed from rounds 5–11 live data
**Supersedes:** complements `2026-09-18-recaptcha-verification-architecture/design.md`
**Scope:** user-authorized Arena pages; 2Captcha opt-in path; existing baseline/output runner
**Safety boundary:** no fingerprint spoofing, no proxy impersonation, no ToS violation

---

## 1. Root-cause analysis from live evidence

### 1.1 The timing mismatch (PROVEN — Round 9, 13:14 run)

```
13:14:25  submit line — generation request sent
13:14:29  captcha detected (+4s)
13:14:29  2Captcha task submitted
13:15:30  token received (+65s from detect, +69s from submit)
13:15:30  dialog already gone — page error at ~+60s
13:15:30  injected anyway → "solved" locally
13:15:30  page error: "Something went wrong" → job FAILED
```

**Key insight:** page patience starts at SUBMIT time (+0s), not at detect time (+4s).
The effective solve window is **~56 seconds** (60s page patience − 4s detect delay).
Enterprise worker queue is **61–101 seconds** observed. The token **never arrives in time**.

### 1.2 The false-solved problem

Dialog disappearance is treated as `solved` → penalty applied → job continues.
But the server may have rejected the token (expired, wrong challenge, rate-limited).
The job then fails at the output stage with a misleading "captcha accepted" intermediate status.

### 1.3 The sequential blocking problem

The solve runs inside `_security_gate` → blocks the generation wait loop.
While solving, the page error scan is **blocked**. A page error that appears at +30s
is not seen until the token arrives at +65s. The error could have been detected earlier.

### 1.4 The missed pre-submit window

Between generation submit (+0s) and captcha detection (+4s), the page is loading.
If we could predict or detect the captcha challenge during this window, we could
start the provider task 4 seconds earlier — potentially the difference between
success and timeout.

### 1.5 No site-specific adaptation

All sites use the same `solve_timeout_sec` (default 180s). A fast v2 site (5–15s solve)
gets the same policy as a slow enterprise site (60–100s). There is no feedback loop:
success/failure timing data is not used to adjust future behavior.

---

## 2. Failure taxonomy

| ID | Failure mode | Evidence | Frequency | Impact |
|----|-------------|----------|-----------|--------|
| F1 | Token arrives after page patience | Round 9: 69s > 60s | Every enterprise solve | Job always fails |
| F2 | Token injected into dead page | Round 9: dialog already gone | Every F1 occurrence | Wasted credit + false status |
| F3 | Wrong callback/client | Round 5: anchor cb≠window cb | Intermittent | Dialog persists, manual fallback |
| F4 | Dialog gone ≠ server accepted | Architecture doc §3 | After every "solved" | Penalty on rejected solves |
| F5 | Page error hidden during solve | Round 8: sequential blocking | Every solve with concurrent error | Delayed error detection |
| F6 | No pre-emptive task submission | Current: detect→submit sequential | Every solve | 4s wasted |
| F7 | No adaptive timeout | Fixed 180s for all sites | Every slow site | Credit waste on impossible solves |
| F8 | No feedback from recordings | Data collected but unused | Continuous | No learning loop |

---

## 3. Design: adaptive solve pipeline

### 3.1 Architecture overview

```
┌─────────────────────────────────────────────────────┐
│                 handle_captcha (choke point)          │
│                                                       │
│  ┌──────────┐    ┌───────────┐    ┌────────────────┐ │
│  │ DETECT   │───▶│ DECIDE    │───▶│ RESOLVE        │ │
│  │ (probe)  │    │ (policy)  │    │ (auto/manual)  │ │
│  └──────────┘    └───────────┘    └────────────────┘ │
│                       │                               │
│                       ▼                               │
│              ┌─────────────────┐                      │
│              │ TimingDatabase  │                      │
│              │ (per-site stats)│                      │
│              └─────────────────┘                      │
└─────────────────────────────────────────────────────┘

DECIDE policy:
  IF site known-impossible (avg solve > page patience)
     → skip auto, instant manual
  IF site marginal (avg solve ~ page patience)
     → auto with concurrent error race
  IF site fast (avg solve << page patience)
     → auto with generous timeout
  IF no data (first encounter)
     → auto with default timeout + record timing
```

### 3.2 Timing database — site-specific solve intelligence

**File:** `config/captcha_timing.json` (git-ignored, auto-managed)

```json
{
  "arena.ai": {
    "attempts": 12,
    "successes": 2,
    "failures": 10,
    "avg_solve_sec": 72.3,
    "avg_token_sec": 68.1,
    "p95_solve_sec": 95.0,
    "page_patience_sec": 60,
    "kind": "recaptcha_enterprise",
    "last_updated": "2026-09-18T13:15:00Z",
    "verdict": "impossible"
  },
  "fast-site.example": {
    "attempts": 5,
    "successes": 4,
    "failures": 1,
    "avg_solve_sec": 8.2,
    "avg_token_sec": 6.1,
    "p95_solve_sec": 14.0,
    "page_patience_sec": 120,
    "kind": "recaptcha_v2",
    "last_updated": "2026-09-18T12:00:00Z",
    "verdict": "fast"
  }
}
```

**Verdict classification:**

| Verdict | Condition | Action |
|---------|-----------|--------|
| `impossible` | `p95_solve_sec > page_patience_sec` or `success_rate < 10%` after ≥3 attempts | Skip auto → instant manual |
| `marginal` | `avg_solve_sec > page_patience_sec * 0.7` | Auto with concurrent error race |
| `fast` | `avg_solve_sec < page_patience_sec * 0.5` | Auto with generous timeout |
| `unknown` | <3 attempts | Auto with default timeout + record |

### 3.3 Pre-emptive challenge detection

**Current flow:** generation submit → wait for output → captcha detected → create task
**Proposed flow:** generation submit → **immediate lightweight probe** → if challenge visible, create task immediately

The existing `wait_for_new_output` polls every ~2s. The first poll that detects a captcha
enters `_security_gate`. If we start the provider task AT DETECTION TIME (not after the
full `handle_captcha` flow), we save the overhead of the signal extraction + stats recording.

**Implementation:** In the `_security_gate` callback, start the provider task as a
background `asyncio.Task` BEFORE entering the synchronous `handle_captcha` flow.
The flow reuses the already-running task instead of creating a new one.

```python
# In _security_gate (simplified):
if detected and auto_enabled:
    # Pre-start: task runs in background while handle_captcha extracts signal
    solver.warm_up(ctrl, tab_id, preliminary_signal)
outcome = await handle_captcha(ctx)
# handle_captcha's solver.solve() dedupes via _inflight map
```

### 3.4 Concurrent error race

**Current:** sequential — solve completes, THEN check for page errors.
**Proposed:** race — solve task vs error watcher task.

```
async def _solve_with_error_race(plan, timeout_sec):
    solve_task = create_task(_poll_and_inject(plan, timeout_sec))
    error_task = create_task(_watch_for_page_error(plan))
    done, pending = await wait(
        {solve_task, error_task}, return_when=FIRST_COMPLETED)
    for t in pending: t.cancel()
    if error_task in done and solve_task not in done:
        return _failed("page_error", error_task.result())
    return solve_task.result()
```

**Benefit:** If the page dies at +30s, we cancel the poll at +30s instead of waiting
until +65s. Saves 35 seconds per failed solve and frees the tab for retry sooner.

**Risk mitigation:** The error watcher uses the SAME CDP client with the SAME lock.
Since `_note_page_error` already runs sequentially in the poll loop (proven safe),
the concurrent version adds only one additional CDP evaluation per ~5s poll cycle.

### 3.5 Page-patience estimation

We don't know the exact page patience, but we can estimate it from recordings:

```
page_patience ≈ min(time_to_first_error_across_sessions)
```

For arena.ai: the error appeared at ~60s from submit (Round 9 data).
The timing database stores this per-host and updates it from each session.

### 3.6 Adaptive timeout

**Current:** fixed `solve_timeout_sec` (default 180s, range 30–600s).
**Proposed:** `effective_timeout = min(user_timeout, page_patience_estimate * 0.8)`

If the site's page patience is 60s, the effective timeout is 48s.
If the provider hasn't returned a token in 48s, abort and free the credit.
This saves ~132s of waiting + the credit cost of a useless token.

### 3.7 Instant-manual for known-impossible sites

When the timing database verdict is `impossible`:
- Skip the 2Captcha attempt entirely
- Log: `🤖 Auto-solve skipped — arena.ai is known-impossible (avg 72s > 60s patience)`
- Go straight to manual wait with the WHY line
- No credit spent, no time wasted

This is the single highest-impact change for the user's current problem.

---

## 4. Solve outcome honesty

### 4.1 Rename `solved` to `accepted_candidate`

The current `status=solved` is misleading. A dialog disappearance is a candidate,
not proof of server acceptance. Rename internally:

```python
# Current
SolveOutcome(status="solved", reason="token accepted")

# Proposed
SolveOutcome(status="accepted_candidate", reason="dialog cleared, no page error")
```

The `accepted_candidate` status means:
- Token was injected
- Callback was called
- Dialog disappeared
- No page error observed within the grace period

The JOB is only `completed` when the output image is verified.

### 4.2 Penalty only on job completion

**Current:** penalty applied when `status == "solved"` or `status == "manual"`.
**Proposed:** penalty applied only when the JOB completes successfully after a captcha solve.

This prevents penalizing tabs for solves that looked successful locally but
the server rejected (job fails at output stage).

### 4.3 Timing feedback loop

After each solve attempt (success or failure), record timing to the database:

```python
def _record_timing(signal: CaptchaSignal, outcome: SolveOutcome):
    host = host_of(signal.page_url)
    entry = timing_db.get(host, blank_entry(host))
    entry["attempts"] += 1
    entry["avg_solve_sec"] = rolling_average(entry, outcome.elapsed_sec)
    entry["avg_token_sec"] = rolling_average(entry, outcome.token_sec)
    if outcome.status == "accepted_candidate":
        entry["successes"] += 1
    else:
        entry["failures"] += 1
    entry["verdict"] = classify_verdict(entry)
    timing_db.save()
```

---

## 5. Implementation plan

### Phase 1 — Timing database + instant-manual (highest impact)

**Files:** `app/services/captcha/timing_db.py` (new, ~120 lines)
**Changes:** `service.py` — check verdict before `_try_auto`

**Effect:** Arena.ai (known-impossible) → instant manual, no credit waste.

### Phase 2 — Adaptive timeout

**Files:** `solver.py` — compute effective timeout from timing DB
**Changes:** `_solve_once` reads timing DB, clamps timeout

**Effect:** Fast sites get full timeout; slow sites get truncated timeout.

### Phase 3 — Concurrent error race

**Files:** `solver.py` — `_solve_with_error_race` replaces sequential flow
**Changes:** `_poll_task` + `_inject_and_verify` run as a raced task

**Effect:** Saves ~35s per failed solve on arena.ai.

### Phase 4 — Pre-emptive task start

**Files:** `service.py` — `warm_up` method on `CaptchaSolver`
**Changes:** `_security_gate` calls `warm_up` before `handle_captcha`

**Effect:** Saves ~4s per solve attempt.

### Phase 5 — Outcome honesty + penalty reform

**Files:** `signals.py`, `service.py`, `cooldown_service.py`
**Changes:** rename `solved` → `accepted_candidate`, defer penalty to job completion

**Effect:** Accurate status reporting, no false penalties.

---

## 6. Test matrix

| Scenario | Expected behavior | Timing DB | Penalty |
|----------|------------------|-----------|---------|
| Arena.ai (known-impossible) | Instant manual, log WHY | verdict=impossible | Only on job complete |
| Fast v2 site (first visit) | Auto with default timeout | verdict=unknown, records timing | Only on job complete |
| Fast v2 site (known-fast) | Auto with generous timeout | verdict=fast | Only on job complete |
| Slow site (marginal) | Auto with error race | verdict=marginal | Only on job complete |
| Page error during solve | Abort solve, cancel poll | Records timing | None |
| Token arrives late | Abort before injection | Records timing | None |
| Token arrives on time, dialog clears | accepted_candidate | Records timing | Only on job complete |
| User solves manually | manual | Records timing | Only on job complete |
| Stop during solve | stopped | No timing record | None |

---

## 7. Data-driven decision framework

After Phase 1–3 are live, collect one batch of data:

```
For each host:
  - attempts, successes, failures
  - avg/p95 solve time vs page patience
  - verdict distribution
```

If the data shows that enterprise sites are ALWAYS impossible (>95% failure rate),
the auto-solve path becomes a research-only feature for v2 sites.
If the data shows the concurrent race + adaptive timeout makes enterprise viable,
keep both paths active.

**Decision gate:** After 10 captcha encounters across 3+ sessions, review the timing
database. If `impossible` sites have 0% auto-solve success, document the finding
and default to instant-manual for enterprise integration sites.

---

## 8. Quality gates

- New file `timing_db.py` ≤150 lines, CC ≤10
- No new Bridge methods (timing DB is services-layer only)
- `SolvePlan` grows by ≤3 defaulted fields
- All existing tests pass unchanged
- New tests: timing DB CRUD, verdict classification, adaptive timeout, concurrent race,
  instant-manual path, timing feedback recording
- RULE 20: timing DB contains no tokens, keys, or credentials — only durations and counts
- RULE 13: corrupt timing DB → blank defaults
- Docs: update SYSTEM_OF_RECORD.md row 12, docs/README.md archive entry
---

## 9. Implementation status (2026-09-18, same day)

Shipped on branch `arena/01a0b59d-process-images-in-areana`, 432 tests green,
RULE 16 gates pass on every changed file.

| Phase | Status | Evidence |
|---|---|---|
| 1 — Timing database + instant-manual | **SHIPPED** | `app/services/captcha/timing_db.py` (183 lines); `service.py` checks `get_verdict()` before auto-solve; `_record_timing` feeds every auto attempt back |
| 2 — Adaptive timeout | **SHIPPED** | `timing_db.get_effective_timeout()` = `min(user, patience*0.8)`; `_try_auto` passes it via `SolveRequest.timeout`; `solver._run_client` clamps the poll |
| 3 — Concurrent error race | **DROPPED — design corrected** | see §3.4 correction below |
| 4 — Pre-emptive task start | **SHIPPED** | `app/services/captcha/warm.py` (`WarmTaskPool`, 126 lines); `handle_captcha` warms right after detection, consumes on solve, `finally: discard_warm()` deletes stragglers |
| 5 — Outcome honesty | **PARTIAL — scoped** | rename `solved`→`accepted_candidate` rejected: round-8/9 verify-grace already gates `solved` on dialog-closed evidence, and the rename would break `CAPTCHA_SOLVE` line consumers (comparison viewer labels). Penalty stays at the accepted edge (best acceptance signal); the `CAPTCHA_JOB` join line already records the true job outcome for offline analysis |

### §3.4 correction — why the concurrent race was dropped

The design claimed error checking was "sequential — solve completes, THEN check
for page errors". That premise was stale when re-measured against the code:
`_provider_result` (now `polling.provider_result`) calls `note_page_error` on
**every poll round** (~5 s cadence), so a page that dies mid-solve is already
caught within one interval — the 35 s saving this section promised was
delivered by the round-8/9 code, not missing. A concurrent watcher would
duplicate an existing check on the same CDP lock for ~2.5 s of average earlier
detection. Per the anti-gaming clause (RULE 16.2) and "actionable findings
over general observations", the complexity was not paid. The verifiable split
that remained was done instead: the poll family moved verbatim to
`app/services/captcha/polling.py` (96% line coverage, behavior locked by the
existing solver suite).

### RULE 16 hard-fail remediation (measured with `tools/verify_quality.py`)

| Violation found by the gate | Fix (RULE 19 order) |
|---|---|
| `solver.solve` / `_solve_once` params 5 > 4 | `SolveRequest` parameter object (extends the existing `SolvePlan` bundle pattern) |
| `timing_db.record_attempt` params 6 > 4 | `TimingSample` frozen dataclass |
| `RecordingStore` methods 16 > 15 | `set_label(field, label)` merges the two label setters; manager keeps both public names |

Result: `python tools/verify_quality.py --changed --allow-legacy` → **PASSED, no fails**.
New-code coverage: `warm.py` 92%, `polling.py` 96%, `timing_db.py` 96%,
`solver.py` 84%, `service.py` 89% line. Repo-overall 41% is the pre-existing
headless-Qt gap, untouched by this change (`coverage.json` is gitignored).

### Module map after the split (RULE 18.2/18.3)

`captcha/` now 12 files: `api_client`, `key_store`, `plan` (data), `polling`
(provider wait), `recovery`, `service` (choke point), `signals`, `solver`
(token application), `stats`, `timing_db`, `warm` (pre-started tasks) —
each ≤420 lines, one responsibility each.
