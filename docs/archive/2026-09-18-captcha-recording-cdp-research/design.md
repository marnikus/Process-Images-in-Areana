# Captcha session recording — research and implementation design

Date: 2026-09-18
Status: implementation blueprint written before code (RULE 17)

## 1. Problem and boundary

A single `CAPTCHA_SOLVE` report describes the solver decision but does not preserve the page transition that led to it. We need a bounded recording that starts after a visible captcha is detected and ends when the encounter resolves (`solved`, `manual`, `page_error`, `token_stale`, `stopped`, or auto failure followed by manual resolution). A Records window must list sessions and let the user assign the ground-truth actor label `bot`, `manual`, or `unknown`.

This is diagnostic observability, not a fingerprint-evasion subsystem. RULE 20 remains unchanged: recordings may explain lifecycle, callback, timing, and server outcomes; the app will not derive or apply browser-fingerprint spoofing, conceal automation, replay credentials, or defeat a site's controls.

## 2. Research findings

Chrome DevTools Protocol (CDP) already exposes the needed primitives:

* `Runtime.evaluate` can install a `MutationObserver`; this is the low-cost source for chronological added/removed/attribute/text diffs.
* `DOMSnapshot.captureSnapshot` returns a flattened DOM including iframe/template/shadow content, but its string table may contain sensitive page data and can be very large. The first release therefore stores a sanitized parent-document HTML checkpoint plus structured mutation diffs. CDP DOMSnapshot remains a future opt-in artifact.
* `Network.requestWillBeSent`, `Network.responseReceived`, `Network.loadingFinished`, and `Network.loadingFailed` reconstruct request lifecycles by request id. `Network.getResponseBody` is only valid for some completed resources and can fail for downloads/cached resources, so body capture must be best-effort.
* The current `CDPClient._receive_loop` consumes command replies but drops events. A small event-listener seam is required; callbacks must not await a new CDP command inside the receive loop or they would deadlock. The recorder listener queues events and its own worker retrieves eligible response bodies later.

References consulted:

* Chrome DevTools Protocol DOMSnapshot domain: https://chromedevtools.github.io/devtools-protocol/tot/DOMSnapshot/
* Chrome DevTools Protocol Network domain: https://chromedevtools.github.io/devtools-protocol/1-3/Network/
* MDN MutationObserver: https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver

## 3. Recording contract

### Lifecycle

1. `handle_captcha` confirms a visible signal and creates the encounter report/eid.
2. Recorder starts before automatic solving or manual waiting.
3. Initial sanitized snapshot is written as checkpoint 0.
4. Every 500 ms, a worker drains MutationObserver batches. Each batch is an immutable diff event. A debounced checkpoint is added when the sanitized DOM hash changes.
5. CDP network events are queued concurrently. Metadata is always recorded; eligible textual response bodies are captured after `loadingFinished`.
6. Resolution is recorded in a terminal event and final checkpoint. The manifest is atomically changed from `recording` to its final outcome.
7. Startup recovery marks orphaned `recording` manifests as `interrupted`.

Recorder failure is fail-open: it logs a warning but never changes captcha handling.

### Session directory

`config/captcha_recordings/<session-id>/`

* `manifest.json` — schema, ids, UTC start/end, elapsed ms, URL origin/path, source, captcha kind, method/outcome/reason, actor label, counters, truncation flags.
* `events.jsonl` — append-only ordered events (`state`, `mutation`, `network_request`, `network_response`, `network_failure`, `response_body`, `warning`). Each has sequence, wall-clock UTC, and monotonic offset.
* `snapshots/000000.json.gz` — sanitized HTML checkpoint with hash, reason, URL, title, viewport, and timestamp.

The index is reconstructed from manifests instead of maintaining a second mutable database. JSON only; no DB.

### Labels

`actor_label` is independent of observed `method`:

* `unknown` — default; no ground truth asserted.
* `bot` — user confirms automatic/provider path passed.
* `manual` — user confirms a person passed it.

The UI never silently infers the user label. It displays method and outcome as evidence beside the editable label.

## 4. Diff and snapshot schema

Mutation event payload is bounded and semantic:

```json
{
  "kind": "mutation",
  "changes": [
    {"op":"add","path":"main>div:nth-of-type(2)","html":"<div role=...>..."},
    {"op":"remove","path":"body>div[role=dialog]","html":"<div role=...>..."},
    {"op":"attr","path":"...","name":"data-state","old":"open","new":"closed"},
    {"op":"text","path":"...","old":"Verify","new":"Success"}
  ],
  "dropped": 0
}
```

Limits protect the browser and disk: 200 changes per drain, 4 KiB per fragment, 2 MiB sanitized snapshot, 64 KiB textual response body, 2,000 events/session, and 25 snapshots/session. Exceeding a limit sets manifest truncation flags and emits one warning. Store retention is also bounded: prune oldest completed/interrupted session folders above 200 sessions or 512 MiB total, on startup and finalization.

Checkpoints are content-addressed by SHA-256. Identical checkpoints are skipped. The viewer can reconstruct a timeline from initial snapshot + diffs; later side-by-side comparison should align sessions by semantic milestones (`detected`, `token_received`, `injected`, `dialog_closed`, `page_error`) rather than raw sequence number.

## 5. Privacy and security model

A literal full-page/network dump would collect credentials, cookies, prompts, generated content, and anti-abuse tokens. The safe recording contract is therefore:

* never persist request/response headers, cookies, POST data, authorization, raw captcha token, API key, or local file paths;
* strip URL query and fragment; retain scheme/host/path;
* sanitize DOM: remove script/style content; clear input/textarea/select values; redact token-like long strings and attributes named value/token/authorization/cookie;
* only retrieve response bodies for textual MIME types and relevant hosts observed during the encounter; redact token-like strings and cap size;
* binary/image/font/media bodies are metadata-only;
* recordings directory is git-ignored and local; UI clearly says artifacts may still contain page text and should be reviewed before sharing.

## 6. Components and dependency direction

`app/services/captcha_recording/`

* `models.py` — limits and immutable session metadata helpers; stdlib only.
* `sanitize.py` — URL/text/event redaction; pure and directly tested.
* `store.py` — atomic manifests, JSONL append, gzip snapshots, list/label API; stdlib only.
* `probes.py` + `recording_js/*.js` — install/drain/snapshot probe builders; exact JS executed by Node tests.
* `recorder.py` — per-tab async lifecycle, event queue, polling worker; imports store/probes, no Qt.
* `manager.py` — active session map and fail-open start/finish facade used by captcha service.

Dependency direction: browser CDP event seam → recording service → store. UI Bridge imports manager/store lazily. Recording modules never import Qt or Bridge.

## 7. UI window

New sash-grid id `captcha_records`, title `Captcha Session Records`:

* Refresh button and compact summary.
* Table: started, tab, host/path, method, outcome, duration, mutations/network/snapshots, editable actor label.
* Label change calls one Bridge slot and updates only the manifest atomically.
* “Folder” action is deferred because cross-platform reveal already has a separate service and is not required to establish the recording contract.
* UI receives summaries only, never full DOM or response body. Raw artifacts remain files for offline diff tooling.

Adding a window changes the frozen Python/JS window set and grid version. All default layouts, preset validation, migration, panel map, and grid tests must move together (RULE 13).

## 8. Integration details

### CDP events

`CDPClient` gains `add_event_listener`/`remove_event_listener`. `_receive_loop` dispatches method messages to a copied listener tuple. Sync callbacks execute immediately; coroutine results are scheduled, never awaited. Listener exceptions are isolated and logged.

### Captcha choke point

`CaptchaService` owns one lazy `RecordingManager`. `handle_captcha` starts it immediately after `_new_encounter`. One resolution helper wraps every post-detection return so the manager always finishes. A `try/finally` guard marks unexpected exceptions `interrupted` without masking the original exception.

To keep service.py under quality limits, lifecycle orchestration lives in `captcha_recording.manager`, not in solver or UI code.

## 9. Comparison roadmap

This change creates trustworthy inputs. Follow-up offline comparison should:

1. choose one `manual` and one `bot` session with the same sitekey/kind and similar page route;
2. align milestone timestamps;
3. compare sanitized snapshots by DOM path and normalized attributes;
4. compare network endpoint/status/timing sequences, not secret payloads;
5. report hypotheses with confidence and reproducibility;
6. permit reliability fixes (correct callback, race, stale-page handling) but reject fingerprint spoofing or control evasion under RULE 20.

No automatic strategy change is part of this recording release.

## 10. Test plan

* Store: atomic create/finish, orphan recovery, newest-first listing, valid/invalid label, corrupt manifest ignored, limits.
* Sanitizer: URL query removal and secret/token redaction.
* CDP client: event delivered once, listener removal, exception isolation, command response unchanged.
* Recorder: real probe-builder strings through fake CDP, initial/final snapshots, mutation drain, network metadata/body eligibility, stop cancellation, truncation.
* Service: session starts only for visible captcha and finishes for solved/manual/page-error/stopped; recorder failure does not affect outcome.
* UI/Grid: Python and JS window sets identical; panel exists; label callback renders safely.
* Full Python + Node suites and `tools/verify_quality.py --changed --allow-legacy`.

## 11. RULE 16/18 design recheck

* New Python files target 150–300 lines, one responsibility each.
* New functions target 4–20 lines; hard max 30 LOC, 4 params, CC 10, nesting 4.
* Recorder configuration is one dataclass instead of parameter growth.
* No production logic is hidden in Bridge; slots delegate to store/manager.
* JavaScript probes are standalone wire payloads and may carry an `ideal-size` constraint comment if they exceed the preference.
* Complexity remediation order is nesting → CC → cognitive → size (RULE 19).
* Tests execute actual store/probe/listener code (RULE 8).
