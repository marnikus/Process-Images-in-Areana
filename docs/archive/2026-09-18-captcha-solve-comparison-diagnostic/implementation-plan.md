# CAPTCHA Solve Comparison — Implementation Plan

**Date:** 2026-09-18
**Status:** actionable plan derived from `verification-and-problem-diagnostic.md`
**Prerequisite:** read `verification-and-problem-diagnostic.md` first (P1–P10, H1–H8)

---

## 1. Executive summary

The A/B comparison system **cannot diagnose bot failures today** because:

| Blocker | What works | What is broken |
|---------|-----------|----------------|
| Event timeline | events are recorded | viewer reads wrong field names → shows nothing |
| Snapshot alignment | up to 25 checkpoints stored | reader returns only the latest |
| Labels | `actor_label` exists | no `result_label`, no `mixed` option |
| Record management | sessions stored on disk | no delete, no "view all" with count |
| Solver milestones | `SolveOutcome` carries rich data | recording does not persist it |

Three code changes unlock the entire diagnostic workflow:

1. **Fix the read model** (P1 + P2): align `EvidenceReader` field names with `CaptchaRecorder`
2. **Add delete + view-all** (feature request): `RecordingStore.delete_session()` + bridge + UI
3. **Enrich recording milestones** (P6): emit solver lifecycle into `events.jsonl`

---

## 2. Prioritized fix list

### Priority 1 — Fix A/B viewer field names (P1 + P2)

**Problem:** Comparison JS reads `event.at_ms` and `event.payload` but recorder writes
flat `event.offset_ms` and inline keys. Snapshot reads `at_ms` but stores `at`.

**Fix in `reader.py`:**
- Map `offset_ms` → expose as `at_ms` for backward compat
- Collect non-envelope keys into a `payload` dict for the viewer
- Snapshot: expose `at` as both `at` and `at_ms` (parsed from ISO string)

**Fix in `captcha-recording-comparison.js`:**
- Use `event.at_ms` (now mapped) and render all non-envelope fields as payload text

### Priority 2 — Add delete session (feature request)

**Files touched:**
- `store.py`: add `delete_session(session_id)` using `shutil.rmtree`
- `manager.py`: delegate to store
- `captcha_recordings_bridge.py`: add `delete_session` Slot
- `captcha-recordings.js`: add delete button per row with confirmation
- `SYSTEM_OF_RECORD.md`: update row 22

### Priority 3 — Add view-all with count (feature request)

**Files touched:**
- `captcha_recordings_bridge.py`: `list_sessions` already returns all (limit=200)
- `captcha-recordings.js`: show total count prominently, add "Show all" if pruned

### Priority 4 — Add `result_label` and `mixed` actor (P7)

**Files touched:**
- `models.py`: add `result_label` to `VALID_LABELS`-like set, add `mixed` to actor
- `store.py`: update `_new_manifest` and `set_label` to accept both fields
- `captcha_recordings_bridge.py`: add `set_result_label` Slot
- `captcha-recordings.js`: add result dropdown + `mixed` option in actor dropdown

### Priority 5 — Persist solver milestones in recording (P6)

**Files touched:**
- `recorder.py`: add `note_solve_milestone(phase, data)` that writes an event
- `service.py`: after `_try_auto` / `_manual_wait`, call `note_solve_milestone`
- Keep token material out (RULE 20): only `token_fp`, `dialog_at_token`, `inject`,
  `polls`, `callback_called`, `page_error`, `stale_reason`

### Priority 6 — Thread-safe network handoff (P9)

**Files touched:**
- `network.py`: replace `asyncio.Queue` with `collections.deque` + `threading.Lock`

---

## 3. Verification matrix

| Change | Unit test | Integration | Manual check |
|--------|-----------|-------------|-------------|
| P1+P2 field fix | `test_captcha_recordings_bridge.py` round-trip | A/B viewer shows event timeline | Load two sessions, verify events visible |
| Delete session | `test_captcha_recording_store.py` delete+list | list count decreases | Click delete, confirm removal |
| View all | count in bridge response | UI shows total | Open records window |
| P7 labels | `set_label` + `set_result_label` round-trip | bridge response correct | Label a session, reload |
| P6 milestones | recorder event count after solve | events contain milestone kinds | Record a session, inspect events |
| P9 thread safety | worker-thread event injection test | no dropped events under load | Concurrent network events |

---

## 4. Implementation order

```
Phase 1: P1+P2  (fix viewer)          — unlocks all comparison work
Phase 2: delete + view-all            — user-requested features
Phase 3: P7 result_label + mixed      — valid cohorts for research
Phase 4: P6 solver milestones         — root-cause attribution
Phase 5: P9 thread safety             — evidence completeness
```

Each phase is independently testable and shippable.