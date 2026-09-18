# Captcha Session Records — implementation fix and clean re-recording

**Date:** 2026-09-18
**Status:** research + design complete; implementation follows this document in the same session
**Request (verbatim scope):** fix all identified problems in the Captcha Session
Records implementation, redesign the recording system so it produces clean and
comparable sessions, then re-record sessions that make manual-vs-bot comparison
possible. Root-cause hypotheses to test: token late / after challenge-identity
change; token in the wrong response field or scope; wrong or stale callback
client; dialog disappearance treated as server acceptance; missing or premature
Continue/Verify transition; wrong captcha task classification or sitekey
context; page operation failed before captcha completion; CDP/recording
concurrency produced incomplete evidence.
**Predecessors:**
`docs/archive/2026-09-18-captcha-session-recording/design.md`,
`docs/archive/2026-09-18-captcha-solve-comparison-diagnostic/verification-and-problem-diagnostic.md`
(P1–P10), `docs/archive/2026-09-18-recaptcha-verification-architecture/design.md`
(acceptance-candidate vocabulary), `docs/archive/2026-09-18-recording-history-removal/`
and `.../recording-deletion-undo/` (window contract).
**Compliance:** RULE 20 — observe only; no injected clicks, no request replay, no
token/header/cookie/body persistence, no fingerprint or biometric collection.

## 1. Evidence available for this audit

There is **no recording on this machine**: `config/captcha_recordings/` does not
exist in the checkout (git-ignored) and `logs/` holds a single 3.5 KB log from
2026-09-16. The audit below is therefore **source-level**, which is sufficient
for every claim it makes, because each defect is a code path that cannot reach
the intended behaviour. Anything that needs a live browser is marked
*re-record required* and is verified by the deterministic replay harness added
with this fix (§8.3), not by inspection of a missing folder.

## 2. Findings — the implementation defects (confirmed from source)

### D1 — two competing recording systems; the newer one is dead code (critical)

`app/services/captcha/service.py::_recorder()` returns the legacy recorder
*only when* `bridge._captcha_service()` is absent:

```python
def _recorder(ctx):
    if _service(ctx) is not None:
        return None
    ...
```

`Bridge._captcha_service` always exists in production, so
`_recording_start/_recording_edge/_recording_stop` can never start
`app/services/recording/recorder.py`. That second system therefore writes
nothing, while its panel (`app/ui/web/js/panels/recordings.js`) is not even
loaded by `app/ui/web/index.html` (only `captcha-recordings.js` and
`captcha-recording-comparison.js` are). Its eight bridge slots
(`get_recordings_list`, `get_recording_detail`, `get_recording_snapshot`,
`get_recording_diff`, `set_recording_label`, `delete_recording`,
`set_recording_settings`, `get_recording_settings`) target `logs/recordings/`
— a **different store** from the canonical `config/captcha_recordings/` that the
`recordings` window documents and reads.

Signature: recordings exist in the UI and grow, but the `Recordings` window id
maps to two different stores; a reviewer diffing the two implementations finds
opposite results; `logs/recordings/` never appears while its slots exist.
Consequence: evidence split-brain, two schemas, two READMEs, double maintenance,
and a misleading fallback path that would silently switch stores if the captcha
service ever failed to construct.

### D2 — terminal evidence can be dropped (critical for comparison)

`CaptchaRecorder._checkpoint()` refuses **every** checkpoint once
`snapshot_count >= max_snapshots`, and `force=True` is not exempt:

```python
if self._counts["snapshot"] >= self.limits.max_snapshots:
    self._truncated.add("snapshots")
    return
```

With `max_snapshots = 25` and a 2 s mutation cadence, any captcha that lives
longer than ~50 s of DOM activity (the normal case: 2Captcha queue 61–101 s per
`too-late-to-solve`) fills the budget before the solve edge. The recording then
has **no `resolved` checkpoint** — the single most important DOM evidence — and
is flagged truncated. The same shape exists in `_event()`: after `max_events`
the terminal `state`/`solve_report` lines are dropped.

Signature: last checkpoint timestamp far below the manifest `elapsed_ms`;
`truncated: ["snapshots"]` on long sessions; comparison panes show "No DOM
checkpoint" for one side.

### D3 — no milestone vocabulary, so manual and bot timelines cannot be aligned (critical for the purpose)

The persisted events are `state`, `mutation`, `network_*`, `snapshot`,
`response_body`, `solve_report` and one `state: auto_attempt_finished` note.
Offsets exist, but there is no shared, named timeline of *semantic* edges. The
comparison protocol requires exactly that (`.../captcha-solve-comparison-
diagnostic` §5 step 3): align `detected → challenge_current → task_created →
token_ready → pre_injection → response_field_delivery → callback_or_manual_clear
→ dialog_cleared → page_acceptance_candidate → generation_resumed →
output_verified | page_error | timeout`.

Today the information exists only *inside one JSON blob* (`solve_report`) and
only for the auto path; the manual path records neither field-fill nor
dialog-clear evidence. A manual session and a bot session therefore share only
`detected` and `recording_finished`, and `_first_divergence` degenerates to a
raw event-sequence diff (noisy mutation/network rows).

Signature: A/B report's "First divergence" points at a mutation or network row,
never at a named edge; manual panes have no `token_ready`/`field_delivery` rows
to compare with.

### D4 — dialog disappearance is the only acceptance evidence (critical, hypothesis H4)

* auto path: `_verify_gone()` returning `True` (dialog no longer visible) is
  turned into `status = "solved"`, `reason = "token accepted"` — even when the
  page then fails the job (`too-late-to-solve` documents exactly this: "solved
  … vacuous: there was nothing left to accept it").
* manual path: `cooldown_service.wait_captcha_cleared()` returns `True` when the
  dialog is not visible **and also when the visibility probe raises**
  (`except Exception: return True`). A CDP hiccup during the wait is recorded as
  a human solve.
* nothing writes the later truth: `single_job_runner._emit_captcha_job_lines`
  produces the `🧾 CAPTCHA_JOB` join line with `job: completed|failed`, but the
  recording has already been finalized and never learns it.

The project vocabulary already separates these layers
(`.../recaptcha-verification-architecture` §3.1: `AcceptanceGate` →
`accepted_candidate`, `JobRunner` → `CAPTCHA_JOB`; "a callback is an attempt,
not proof of server acceptance"). The recording does not.

Signature: manifest `outcome: solved` with a later `job: failed` in the log
join; no way to tell a candidate from a verified pass in the UI.

### D5 — six semantic facts are computed but never persisted

Present in the solve path but absent from the recorded evidence:

| Fact | Produced where | Recorded today |
|---|---|---|
| response-field count/scope **before** injection | `build_detect_js` (`responseFields`, `responseScope`) | ✗ (detect snapshot only) |
| challenge/page identity **at token receipt** | `_current_signal()` inside `_stale_reason()` | ✗ |
| Continue/Verify click result | `build_continue_js` `{ok, used}` | ✗ (return value discarded) |
| post-injection field count in the served scope | `inject.js` `{scope, fields, len}` | only inside `solve_report.inject` string |
| manual-path field fill (count + non-empty) | not observed at all | ✗ |
| page-error offset relative to token arrival | `plan.page_error_at` | ✗ (`SolveOutcome` carries only `page_error_at_s`) |

These are precisely the hypotheses H1 (late token), H5 (Continue/Verify), H6
(sitekey/field scope), H7 (page error before completion).

### D6 — evidence collection is not observation-neutral (hypothesis H8)

* `install.js` `scrub()` does `node.cloneNode(true)` **and**
  `copy.outerHTML` (up to 4096 chars) for every added and every removed node,
  inside the page's own `MutationObserver` microtask, and `pathOf()` rebuilds a
  CSS path per record (up to 8 ancestors, each scanning siblings).
* `snapshot.js` serializes the whole document every 2 s during a captcha
  (the page is exactly the busiest place: the security dialog plus a streaming
  app), bounded at 2 000 000 chars.
* `NetworkCollector` fetches and stores redacted **response bodies** for every
  textual response of the page (up to 64 KB each), not only for captcha traffic
  — the largest noise source in a diff and the least justified by RULE 20.
* `self.responses` grows without bound (entries are popped only when a
  `loadingFinished` arrives for a textual MIME).
* the recorder polls the same CDP connection as the solve path (0.5 s) — the
  design intent, but combined with the three points above it can delay the page
  enough to distort the very timings being measured.

Signature for H8: `truncated`/`warning` events, missing final checkpoint,
durations that do not reproduce with recording disabled.

### D7 — network evidence is uncorrelated and unbounded (diagnostic P8)

`Network.requestWillBeSent/responseReceived/loadingFailed` are persisted with
`safe_url` + `category`, which is good, but there is no drop counter for
responses whose body fetch failed, no per-category summary, and no pairing
guarantee (`loadingFinished` may arrive after the session is finalized).

### D8 — a recording is skipped silently when one is already active (RULE 4)

`RecordingManager.start()` returns `None` for `tab_id in self._active` with no
log and no record of the skip. The UI cannot distinguish "no captcha happened"
from "this encounter was not recorded".

### D9 — comparison reads the latest checkpoint only and ignores alignment (P3/P4 residual)

`EvidenceReader` returns the checkpoint list, but `RecordingComparison._dom_diff`
diffs `latest_snapshot` only; the UI report has no milestone alignment, no
per-category network summary and no "cohort validity" verdict (unknown/mixed
labels still produce a comparison without a warning that it is not
interpretable as manual-vs-bot).

## 3. Hypothesis → signature map (what the fixed recorder can prove)

| # | Hypothesis | Recording signature after this fix | Status before fix |
|---|---|---|---|
| H1 | token arrives too late / after challenge identity change | `token_ready` offset vs `detected`; `pre_injection` identity match; `token_stale` milestone with reason (`token_age`, `page_identity_changed`, `challenge_identity_changed`) | partially — `solve_report` only, no named edge |
| H2 | token in wrong response field or scope | `field_delivery.scope` + `fields_set` + `value_len` next to `pre_injection.response_fields/scope`; manual counterpart `manual_field_filled` | ✗ (string only, no manual counterpart) |
| H3 | wrong or stale callback client | `field_delivery.cb_source/cb_called/cb_error` as a first-class field | ✗ (string only) |
| H4 | dialog disappearance treated as acceptance | `acceptance.state = accepted_candidate` + `job_result` updating the manifest to `verified`/`refuted`; comparison warns when a side is only a candidate | ✗ |
| H5 | Continue/Verify missing or premature | `continue_clicked {found, used}` milestone plus `dialog_cleared` offset | ✗ |
| H6 | wrong task classification / sitekey context | `task_created {task_type, is_invisible, sitekey_source, website_host}` + detect `sitekey_source`/`challenge_identity` | ✗ |
| H7 | page operation failed before captcha completion | `page_error` milestone with offset relative to `token_ready` (order is the proof) | partial |
| H8 | CDP/recording concurrency dropped evidence | neutrality bounds (§5.4) + `truncated`/`dropped` counters + terminal-evidence reservation (D2) | ✗ (silent loss possible) |

Out of scope by design (documented, not a defect): cross-origin challenge-frame
internals (diagnostic P5) cannot be observed without breaking iframe isolation;
a manual solve's *site* callback cannot be observed, so `callback_invoked` stays
bot-only and the alignment marks it "bot-only, expected".

## 4. Design decision — one system, three layers

1. **Capture** (`app/services/captcha_recording/*` + `recording_js/*`):
   one canonical, fail-open recorder per visible captcha encounter, one store
   (`config/captcha_recordings/<session-id>/`), one lifecycle owned by
   `handle_captcha`. The parallel `app/services/recording/*` implementation,
   its page probes, its panel and its bridge slots are **deleted** (D1).
2. **Semantics** (`milestones.py`, new pure module): a closed milestone
   vocabulary derived from the existing `SolveOutcome`/report evidence plus live
   stamps, so both paths produce the same named timeline (§5.1).
3. **Verdicts** (`store.apply_job` + `manager.join_job` + comparison): the
   recording keeps its observed runtime outcome untouched and adds an explicit
   `acceptance` state that the `CAPTCHA_JOB` join resolves into
   `verified`/`refuted` (§5.2).

RULE 18 target sizes: no new file above ~150 lines; `recorder.py` loses code to
`milestones.py`; deleted code (≈1 000 Python + ≈250 JS lines of the duplicate)
exceeds everything added.

## 5. Redesign detail

### 5.1 Milestone vocabulary (closed set, shared by both paths)

A milestone is one bounded event `{kind: "milestone", phase, at, offset_ms, base_ms?, …}`.
Milestones derived from the outcome use `offset_ms = base + at_s*1000`, where
`base` is the `detected` milestone's own offset, so bot and manual timelines are
directly comparable. Live stamps win; derivation fills the gaps (never both).

| Phase | Path | Bounded payload |
|---|---|---|
| `detected` | both | kind, integration, invisible, sitekey_source, anchor/challenge evidence, response_fields/scope, page_identity, challenge_identity |
| `task_created` | bot | task_type, is_invisible, website_host, sitekey_source |
| `token_ready` | bot | polls, token_sec, token_len, identity (page/challenge) |
| `pre_injection` | bot | dialog_visible, response_fields, response_scope, identity_match, challenge_identity |
| `field_delivery` | bot | scope, fields_set, value_len, cb_source, cb_called, cb_error |
| `manual_field_filled` | manual | fields_total, fields_filled, scope (counts and lengths only — never content) |
| `continue_clicked` | bot | found, used |
| `dialog_cleared` | both | evidence: `probe` \| `probe_error` \| `timeout` \| `stop` |
| `acceptance_candidate` | both | state, verifier (`callback+closure` \| `closure`) |
| `page_error` | both | text (bounded, redacted), after_token (bool) |
| `token_stale` / `not_accepted` / `auto_failed` / `stopped` / `interrupted` | bot/both | reason (bounded) |
| `job_result` | both (join) | job (`completed`/`failed`), error, page_error |

### 5.2 Two-stage acceptance and the job join

* `manifest.acceptance` = `accepted_candidate` | `not_accepted` | `page_error` |
  `stale` | `none` (the *observed* verdict at the solve edge; `outcome`/`status`
  still carry the runtime values, unchanged).
* `manifest.verified` = `null` until the image job ends, then `true`/`false`;
  `manifest.job` = `completed`/`failed`, `job_error` bounded.
* `single_job_runner._emit_captcha_job_lines` calls the recording join for each
  stashed `eid` (fail-open, small helper). `RecordingManager.join_job(eid, line)`
  resolves the session through an in-memory `eid → session_id` map with a
  bounded store lookup fallback and appends one `job_result` milestone.
* Comparison treats `verified` as the pass/fail truth and warns when a side has
  `acceptance = accepted_candidate, verified = null` ("not yet verified").

### 5.3 Evidence bounds that can never drop the terminal edge

* `max_snapshots` is split: regular (throttled) checkpoints stop at
  `max_snapshots − 2`; forced/terminal checkpoints (`detected`, `resolved`,
  milestone edges) are always allowed up to the hard cap.
* `max_events` reserves the last 50 slots for `state`/`milestone`/`solve_report`;
  regular `mutation`/`network_*`/`response_body` events stop earlier and set
  `truncated: ["events"]`.
* every drop is counted and surfaced (`truncated`, `dropped`, `warning` events).

### 5.4 Observation neutrality (no behaviour change — RULE 20 / H8)

* mutation records carry a **skeleton** `{tag, attrs (secret names redacted),
  kids, text_len}` instead of cloned `outerHTML` (mutation summaries were always
  meant to be summaries; snapshots carry the content);
* `pathOf` uses a bounded same-tag walk (≤100 siblings) instead of array
  filtering;
* document checkpoints stay (they are the DOM-diff substrate) but the view cap
  drops from 2 000 000 to 512 000 chars and the payload keeps its sha256;
* response bodies are captured **only** for `captcha`/`verification` category
  requests (bounded 16 KB); everything else keeps method/status/category/mime/
  cache/duration metadata. `self.responses` is capped at 200 entries with a
  drop counter.

### 5.5 Read model, comparison report, UI

* reader: checkpoint index with `reason`/`offset_ms`/sha256, milestone list,
  acceptance + verification, per-category network counts, dropped counters;
* comparison: **milestone alignment** (both / A-only / B-only / offset delta),
  `first_divergence` by milestone, bounded sequence diff kept as
  `sequence_divergence`, DOM diff of the *aligned* checkpoints (same `reason`,
  else nearest offset within 1 s), network class diff, and cohort warnings
  (`unknown`/`mixed` labels, unverified candidate, truncation, missing initial
  or final checkpoint);
* window: rows gain acceptance/verified and milestone count; the detail pane
  renders the milestone timeline above the raw events; the report pane renders
  the alignment table first.

## 6. Remediation plan (file level)

| File | Change | Gate intent |
|---|---|---|
| `app/services/recording/**`, `app/browser/recording_js/**`, `app/browser/recording_probes.py`, `app/ui/web/js/panels/recordings.js` | delete | removes the duplicate system (D1) |
| `app/ui/bridge.py` | delete `_recording_service` + 8 slots, `import json` stays used | RULE 16 (bridge stays thin) |
| `app/services/captcha/service.py` | delete `_recorder/_recording_start/_recording_edge/_recording_stop`; call `recordings.milestone()` on the manual clear edge and `recordings.finish()` on every exit | ≤4 params, ≤30 LOC each |
| `app/services/captcha_recording/milestones.py` (new) | pure derivation + live-stamp merge + acceptance | ~130 lines, pure, tested |
| `app/services/captcha_recording/recorder.py` | terminal reservation, milestone persistence, counters, reduced snapshots | stays ≤200 lines |
| `app/services/captcha_recording/{store,manager,reader,comparison,network,models,retention}.py` | job join, bounds, alignment, cohort validity | per-file ≤200 |
| `app/browser/captcha_js/fields.js` (new) + `captcha_probes.py` | manual field-fill observation probe | ~25 lines JS |
| `app/browser/captcha_js/continue_click.js` | unchanged (result now persisted by the solver) | — |
| `app/services/captcha/solver.py` | stamp `dialog_cleared`, continue result, pre-inject evidence into `SolveOutcome` | ≤30 LOC functions |
| `app/services/single_job_runner.py` | join hook (≈10 lines) | small helper |
| `app/ui/web/js/panels/captcha-recordings.js`, `captcha-recording-comparison.js` | acceptance/verified column, milestone rendering, alignment report | ≤300 lines each |
| tests | recorder boundaries + milestones + join + alignment + replay (real service, fake CDP) + probe execution under node | every function has a deletion-failing test |

## 7. Verification plan

1. focused: recorder/milestones/store/manager/comparison/service/replay tests;
2. full: `python -m pytest tests -q`, `npm run test:js`;
3. RULE 16: `python tools/verify_quality.py --changed --allow-legacy`, then the
   full gate, then coverage (no decrease);
4. replay harness (§8.3) produces a clean manual + bot pair from the REAL
   service/recorder path and asserts the comparison report names the expected
   milestones and first divergence;
5. live re-record (user machine) per §8.4 — the harness proves the pipeline, the
   live run supplies the empirical evidence.

## 8. Re-recording

### 8.3 Deterministic replay (runs in CI, no browser)

`tests/test_captcha_recording_replay.py` drives `handle_captcha` twice through a
scripted fake controller/CDP — once to a human clear, once through a provider
token — into a temp store, then runs the reader + comparison and asserts that
`detected`, `dialog_cleared`, `acceptance_candidate` and `job_result` align
across both sessions, that the bot-only milestones are exactly the provider ones
and that no recorded byte contains token material.

### 8.4 Live re-record procedure (user machine, after this fix)

1. `config/captcha_recordings/` may be kept or cleared; new sessions get fresh
   ids and the schema is unchanged (v2 + additive keys), so old and new coexist.
2. manual session: with the 2Captcha switch OFF, let one captcha appear and
   solve it in Chrome; label the row `manual` + `passed` (or `failed`).
3. bot session: enable 2Captcha, let one captcha auto-solve; label it `bot` +
   the true result. If a human finishes an auto attempt, label `mixed`.
4. compare A/B in the Recordings window; the report lists the milestone
   alignment first, then the first divergence and the bounded DOM diff.

## 9. Measured results

*(filled at implementation — see §10)*

## 10. Implementation record

*(filled at implementation)*
