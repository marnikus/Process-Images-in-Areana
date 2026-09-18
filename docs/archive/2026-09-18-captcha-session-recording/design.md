# CAPTCHA session recording and review window

**Date:** 2026-09-18  
**Status:** design complete; implementation follows in this work session  
**Scope:** record the user-authorized page state from CAPTCHA appearance until CAPTCHA/job terminal state, then manually label the recording as `manual_pass`, `bot_pass`, `manual_fail`, `bot_fail`, or `unknown`.

## 1. Purpose and safety boundary

The recorder is an observability and research tool. It compares a human-resolved session with an API-attempted session; it is not an evasion or fingerprint-spoofing system.

Allowed:

- DOM structure and bounded text/attribute evidence;
- mutation diffs;
- safe request/response metadata and bounded status/body classification;
- timestamps and existing correlation IDs;
- user-entered labels and notes.

Never record:

- CAPTCHA tokens or response textarea values;
- cookies, authorization headers, API keys, passwords, IP addresses;
- full request/response bodies by default;
- prompt text, uploaded image bytes, generated image bytes, or private conversation content;
- raw browser fingerprint or telemetry values.

The recorder must redact sensitive fields before persistence, use size limits, and make recording explicitly user-controlled. This is required by RULE 20 and protects the user’s own page/session data.

## 2. Recording lifecycle

A recording starts only when the existing CAPTCHA choke point detects a visible challenge:

```text
captcha detected
  -> create recording manifest + initial snapshot
  -> install MutationObserver + safe network event capture
  -> append periodic/significant snapshots and diffs
  -> stop on one of:
       manual/API CAPTCHA terminal outcome
       page error
       job completed
       job failed/stopped
       explicit user stop
  -> flush atomically and make review entry available
```

The recorder must not start on the always-present hidden badge. It must not continue forever after a terminal outcome. A bounded emergency timeout prevents leaks when a callback path is lost.

One recording has:

- `rid`: short unique recording ID;
- `eid`: CAPTCHA encounter ID;
- `corr`: job correlation ID;
- tab/page identity;
- start/end timestamps;
- initial/final page evidence;
- ordered event stream;
- current manual label and note;
- schema version.

## 3. Architecture

```text
Captcha service
  -> SessionRecorder.start(ctx, signal, encounter)
Page probe / CDP
  -> snapshot + mutation events + safe network events
Captcha solver/service/runner
  -> recorder event(status, outcome, page_error, job terminal)
SessionRecorder.stop()
  -> atomic manifest/events/snapshot files
Review store
  -> list/get/label/delete
Bridge API
  -> open/list/load/label/delete recording
Review window
  -> timeline, diff, evidence, manual label controls
```

### 3.1 Storage

Use a dedicated user config directory:

```text
config/captcha_sessions/<rid>/manifest.json
config/captcha_sessions/<rid>/events.jsonl
config/captcha_sessions/<rid>/snapshots/<seq>.json
config/captcha_sessions/index.json
```

Write event/snapshot files through temporary files and `os.replace`. Index updates are atomic. Enforce configurable caps:

- maximum session duration: 10 minutes;
- maximum events: 5,000;
- maximum snapshot size: 512 KiB;
- maximum total recording size: 20 MiB;
- text values truncated to 500 characters;
- request/response metadata capped at 1,000 entries.

The recorder drops old high-frequency mutation noise after the cap and records a `dropped_events` summary rather than growing without bound.

## 4. Snapshot contract

Snapshots must be useful for comparison without persisting private content:

```json
{
  "seq": 0,
  "at_s": 0.0,
  "url": "https://arena.ai/c/<id>",
  "page_identity": "url|timeOrigin",
  "title": "...",
  "dom": {
    "node_count": 123,
    "structure": "redacted structural tree",
    "security": {
      "dialog": true,
      "anchor": {"present": true, "visible": true},
      "challenge": {"present": true, "visible": true, "src": "host/path"},
      "response_fields": 2
    },
    "spinners": 1,
    "outputs": 0,
    "errors": []
  }
}
```

DOM structure is a semantic/structural summary, not `outerHTML` by default. Text is reduced to known state labels and bounded error messages. Attributes are allow-listed (`role`, `data-state`, `title`, `aria-*`, safe class fragments, tag names); values from `value`, `src` query strings, `href` query strings, `name`, `id`, and response fields are redacted or normalized.

## 5. Mutation diff contract

The page-side observer reports normalized mutations:

```json
{
  "kind": "mutation",
  "at_s": 1.24,
  "changes": [
    {"op": "attributes", "target": "dialog", "name": "data-state", "from": "closed", "to": "open"},
    {"op": "added", "target": "iframe", "semantic": "recaptcha-challenge"},
    {"op": "removed", "target": "spinner", "semantic": "generation-spinner"}
  ]
}
```

Coalesce mutations within a 100 ms window. Record semantic target paths and bounded attributes, never raw HTML or token values. The observer is disconnected at stop.

## 6. Network event contract

Use CDP network events already available through the browser controller where possible. Capture metadata only:

- request method;
- safe host/path classification;
- resource type;
- request start/end relative time;
- status/status text;
- response content type and bounded size;
- failure class (`network`, `timeout`, `4xx`, `5xx`, `parse`);
- correlation if already available.

Redact query strings and sensitive headers. Do not persist bodies by default. For explicitly allow-listed JSON error responses, store only a bounded classified message after redaction. Google/2Captcha tokens and Arena prompt/image data are never stored.

## 7. Event contract

All events share:

```json
{"v":1,"rid":"...","eid":"...","at_s":12.3,"kind":"..."}
```

Kinds:

- `recording_started`;
- `snapshot`;
- `mutation`;
- `network`;
- `captcha_outcome`;
- `page_error`;
- `job_outcome`;
- `recording_stopped`;
- `label_changed`.

`captcha_outcome` references the existing structured `CAPTCHA_SOLVE` fields but excludes token data. `job_outcome` references `CAPTCHA_JOB` status and page error. This makes manual/API comparison joinable by `rid/eid/corr`.

## 8. Manual labels

Labels are intentionally manual and editable:

- `manual_pass`: user solved and the job/page proceeded;
- `bot_pass`: API/provider path solved and the job/page proceeded without manual intervention;
- `manual_fail`: user attempted/was present but page/job failed;
- `bot_fail`: API path failed or was rejected;
- `unknown`: not enough evidence.

The review window must display the evidence before allowing a label. Labels do not alter solver behavior or statistics. Every label change is appended to the event stream and atomically updates the manifest.

Recommended evidence banner:

```text
Observed path: manual | auto | mixed | unknown
CAPTCHA outcome: ...
Job outcome: completed | failed | stopped
Manual intervention: not observed | observed | unknown
Confidence: high | medium | low
```

Because the current system cannot prove Google’s private risk decision from DOM alone, `bot_pass` requires either explicit operator confirmation or a completed job with no manual intervention and a matching automatic solve window. `mixed` observations must default to `unknown` rather than being mislabelled.

## 9. Review window

Add a dedicated `captcha_records` window to the existing window/preset system. It must provide:

1. recording list with date, tab, URL host/path, duration, CAPTCHA result, job result, label;
2. filters for label, outcome, date, tab, and host;
3. timeline view with event timestamps;
4. before/after snapshot selector;
5. side-by-side structural diff view;
6. safe mutation and network metadata tables;
7. CAPTCHA/job report links by `eid/corr`;
8. label dropdown, note field, Save button;
9. delete recording and delete-all controls with confirmation;
10. refresh/export of redacted JSON only.

Window state/preset integration must use the existing single-writer/preset validation path. The new window must be added to the canonical window set and remain portable in presets.

## 10. Implementation steps

### Step 1 — Pure contracts/store

Create `app/services/captcha/recording.py` with dataclasses/normalizers, atomic store, redaction, caps, event append, list/load/label/delete. No browser or UI imports.

### Step 2 — Page probes

Create `captcha_js/record.js` (or split leaf probes) for redacted snapshot and coalesced MutationObserver. Execute through the existing JS harness. Add tests for token/value/URL/header redaction and mutation normalization.

### Step 3 — CDP lifecycle adapter

Add a small controller adapter for installing/removing the observer and receiving safe network metadata. Keep the recorder independent of Qt and provider APIs.

### Step 4 — Service/runner integration

Start at `handle_captcha` after the encounter/report exists. Stop on solver/manual terminal outcome, page error, job terminal result, cancellation, or emergency timeout. Ensure one recorder per `eid` and reused controllers do not leak sessions.

### Step 5 — Bridge/window

Expose bridge methods for list/load/label/delete/clear/export. Add the new window to the window registry and UI navigation. Follow RULE 1 for controls that locate/click page elements; review-window controls are app controls and use the existing UI event pattern.

### Step 6 — Tests and live comparison

Create manual and API recordings on separate controlled runs. Label them manually. Compare timeline/snapshot/network metadata. Do not make behavioral changes to CAPTCHA solving from a single recording; use repeated evidence and explicit approval.

## 11. RULE 16 and RULE 18 recheck

### RULE 18 — ideal sizes

Keep responsibilities split:

- `recording.py`: store, schema, caps, redaction;
- `recording_probe.js`: snapshot/mutation only;
- controller adapter: CDP event plumbing only;
- captcha service/runner: lifecycle start/stop only;
- bridge/UI: review operations only.

Use a `RecordingSession` object instead of growing service signatures. Do not put DOM serialization, redaction, file I/O, and UI formatting in one function.

### RULE 16 — quality gates

Every production batch must run:

```text
pytest tests/ -q -p no:cacheprovider --ignore=tests/integration
npm run test:js
python tools/verify_quality.py --changed --allow-legacy
python -m radon cc <changed-production-files> -s
```

Required: zero quality-gate fails, new code at B or better, real JS harness tests, store round-trip tests, no secret leakage tests, UI bridge tests, and no pre-existing regressions.

## 12. Acceptance criteria

- Recording begins only after a real challenge is detected.
- Recording stops on CAPTCHA/job success, failure, page error, stop, or emergency timeout.
- Every persisted event has a timestamp and recording/correlation IDs.
- DOM mutations are diffed and coalesced.
- Network metadata is safe/redacted and bodies are not persisted by default.
- Manual and API runs can be compared side-by-side.
- User can manually label and relabel recordings.
- Labels survive restart and are included in export.
- No token, credential, cookie, prompt, or image bytes appear in recording files.
- New window survives preset save/load validation.
- All RULE 16 gates pass; final diff reviewed against RULES 8, 13, 15, 16, 18, 20, 21, and 22.
