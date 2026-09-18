# Captcha session recording — diff-logging system + Recordings window

**Date:** 2026-09-18
**Status:** design complete; implementation follows this document in the same session
**Request:** record page state + DOM changes around captcha events, git-style
diff logging, manual-vs-bot session comparison, and a UI window to browse
recordings and label each as **bot pass** or **manual pass**

## 1. Decision summary

A recording is a **bounded, redacted, append-only session folder** created the
moment a captcha is detected and finalized when the solve edge is known
(success or error). It captures:

1. full sanitized DOM snapshots at significant edges (detect, token inject,
   dialog gone, page error, stop);
2. DOM mutation summaries with timestamps (MutationObserver buffer);
3. page-originated network requests with timestamps (fetch/XHR wrapper);
4. state-transition markers (the captcha lifecycle itself).

Storage is `logs/recordings/<session-id>/` (git-ignored): `session.json`
header + `events.jsonl` + `NNNN.html` snapshots. A new **Recordings** window
(15th window) lists sessions, shows the event timeline + snapshots, renders a
bounded side-by-side diff between any two snapshots, and lets the user set the
label: `bot_pass` / `manual_pass` / cleared. RULE 20 privacy: recaptcha token
fields are redacted IN THE PAGE PROBE before bytes cross CDP; recaptcha-family
URLs keep host/path/param-names only.

## 2. Lifecycle (user-specified contract)

```
captcha detected (handle_captcha choke point, visible=true)
  -> START: create session dir, install observer+netwrap probes, snapshot 0000
  -> EDGES: flush mutation/network buffers + snapshot at token-inject,
     dialog-gone, page-error (each event timestamped)
  -> STOP + finalize outcome when the solve edge is known:
     solved | manual | page_error | token_stale | auto_failed | stopped
```

One recording per captcha encounter per tab; concurrent tabs record
independently (same per-tab isolation as the solver). Recording is fail-open
(RULE 9): any recorder error is logged and swallowed — the captcha flow never
breaks because of telemetry. Toggle `recording_enabled` (default ON) lives in
the Recordings window header — one control, one decision (RULE 10).

## 3. Comparison workflow (the purpose)

1. Solve a captcha **manually** in Chrome while the app watches → recording A
   ends `manual`; the user labels it `manual_pass`.
2. Let **auto-solve** run → recording B ends `solved`; label `bot_pass`
   (or leave unlabeled when the job later failed — labels are human verdicts).
3. In the Recordings window: pick A and B, pick snapshot indices, view the
   bounded unified diff side by side; diff the event timelines (counts by
   kind, request URL families, mutation rates).
4. Findings feed future designs (e.g. requests the human path makes that the
   bot path does not) — this system records evidence, it changes no site
   behaviour (RULE 20).

## 4. Architecture (RULE 18 module split)

### 4.1 `app/services/recording/` — pure + store + facade (no Qt, no browser)

| File | Owns | Ideal size |
|---|---|---:|
| `sanitizer.py` | `redact_dom_html`, `redact_url`, `bound_str` — pure, tested | ~120 |
| `session.py` | `RecordingSession` dataclass + header (de)serialisation with validation | ~110 |
| `store.py` | `RecordingStore`: create/append/snapshot/finalize/list/label/load, atomic writes, corrupt-skip (RULE 4/13) | ~220 |
| `diffview.py` | `snapshot_diff` (difflib, bounded hunks), `timeline_summary` | ~90 |
| `recorder.py` | `RecordingService` facade: per-tab start/edge/stop + UI payloads; delegates probes through `ctrl.cdp.evaluate` | ~200 |

### 4.2 `app/browser/recording_js/` + `recording_probes.py` — page side

| Probe | Behaviour |
|---|---|
| `observer.js` | idempotent install of a MutationObserver into `window.__arenaRecMut`; entries `{ts, kind, sel, added, removed, attr, len}` — summaries, not subtree serialisation (snapshots carry the truth); 500-entry cap, drop-oldest; `flush` returns+clears |
| `netwrap.js` | idempotent wrap of `window.fetch` + `XMLHttpRequest`; entries `{ts, via, method, url, status}` into `window.__arenaRecNet`; 300-entry cap |
| `snapshot.js` | returns `document.documentElement.outerHTML` with every `g-recaptcha-response` field content replaced by `[REDACTED:len]` BEFORE the string leaves the page |
| `recording_probes.py` | builders returning the exact file contents (RULE 8: node tests execute them) |

### 4.3 Wiring — `app/services/captcha/service.py` choke point

* `_recording_start(ctx, signal)` after `_mark_waiting` (visible only);
* `_recording_edge(ctx, note)` — flush + snapshot, called by `_try_auto`
  before/after inject and by `_manual_wait` on clear;
* `_recording_stop(ctx, outcome)` on EVERY return path of `handle_captcha`
  (single helper, one call per exit);
* service object rides the bridge like `_captcha_service()` —
  `_recording_service()` lazy factory (identical pattern).

### 4.4 UI — Recordings window (15th)

* `sash-core.js` WINDOWS + `layout_service.py` WINDOW_IDS/WINDOWS gain
  `recordings` — existing `migrate_grid_tree` appends the missing leaf to old
  14-window layouts (RULE 13 preserved: nothing is substituted, only appended);
* `index.html`: `#winRecordings` panel + script tag;
* `panels/recordings.js`: list (time, tab, url host, outcome, events,
  snapshots, label) + label buttons + detail timeline + snapshot viewer +
  two-picker diff view (bounded hunks rendered as a table);
* bridge slots (thin delegators, captcha-slot pattern):
  `get_recordings_list`, `get_recording_detail`, `get_recording_snapshot`,
  `get_recording_diff`, `set_recording_label`, `delete_recording`,
  `get_recording_settings`, `set_recording_settings`; added to REQUIRED_SLOTS.

## 5. Data contracts

`session.json` (validated on read — corrupt ⇒ skipped with reason, never crash):

```json
{"v": 1, "id": "20260918-152401-154FBF", "tab": "154FBF…", "url": "https://arena.ai/c/…",
 "trigger": "check-security", "kind": "recaptcha_enterprise", "sitekey": "6Le3_cYs…",
 "started": "2026-09-18T13:23:15Z", "stopped": "…", "status": "stopped",
 "outcome": "solved|manual|page_error|token_stale|auto_failed|stopped|none",
 "label": ""|bot_pass|manual_pass", "method": "auto|manual|mixed",
 "counters": {"events": 0, "snapshots": 0, "mutations": 0, "requests": 0}}
```

`events.jsonl` lines: `{"ts":…, "seq":…, "kind": "state|mutation|network|snapshot", …}`.

## 6. Compliance (RULE 20) and non-goals

* **Secrets never recorded:** recaptcha field values redacted in-probe;
  recaptcha/google URLs keep host+path+param NAMES only; no request/response
  bodies; no cookies; no headers; sitekey is public (already in reports).
* Recordings stay on the user's machine in git-ignored `logs/recordings/`.
* The system only OBSERVES: no injected clicks, no request replay, no site
  behaviour change. Label/diff are human-in-the-loop research tools.
* Non-goals: recording outside captcha windows; cross-machine sync; video.

## 7. Test matrix (RULE 8)

1. sanitizer: token fields redacted; recaptcha URL params name-only; other
   URLs untouched; bounds enforced.
2. store: create/append/finalize round-trip; list skips corrupt header with
   reason (empty vs broken); label validates + atomic rewrite; delete.
3. service: start→edge→stop lifecycle with fake ctrl (probes recorded in
   order); fail-open when evaluate raises; one session per tab; outcome map.
4. diffview: bounded hunks; identical snapshots → empty diff; timeline counts.
5. node harness executes the REAL probes: observer buffers+flush clears;
   netwrap records fetch/XHR; snapshot output contains no recaptcha value.
6. window set: Python↔JS 15-window sync (existing parse-and-compare test),
   migration appends `recordings` to a 14-leaf tree; REQUIRED_SLOTS complete.

## 8. RULE 16 / 18 plan (recheck at the end)

* Every new Python function ≤30 LOC (aim 4–20), ≤4 params, CC ≤10, nesting ≤4.
* Files aim 90–250 lines; the recording module = 5 cohesive files (within the
  5–15 band); panel JS ≤300 lines.
* Bridge hotspot: only thin delegating slots (captcha-slot pattern), no logic
  in bridge.py; logic lives in `app/services/recording/` + `app/ui` helper.
* Coverage must not decrease; every new function gets a deletion-failing test.
* Stop honoured (RULE 7): manual-wait edge flush checks nothing new; recorder
  finalizes on the `stopped` outcome too.

## 9. Measured results (filled at implementation, 2026-09-18)

* Final module split = 7 files (RULE 16 size gate forced two more extractions
  than §4.1 planned): `session.py`, `sanitizer.py`, `store.py`, `diffview.py`,
  `recorder.py` (lifecycle only), `proberun.py` (CDP probe I/O + bounding),
  `payloads.py` (WebChannel envelopes). UI payloads are module functions, not
  service methods; bridge slots import them lazily.
* `RecordingService.start(ctrl, tab_id, detect)` — `detect` is the
  url/trigger/kind/sitekey dict gathered at captcha detect (≤3 params).
* Choke point: `handle_captcha` = detect → `_recording_start` → `_handle_visible`
  → `_recording_stop`; edges pinned after auto-solve finish and manual-wait end.
* Window #15 `recordings` in both WINDOWS lists + builtin layouts; the old JS
  `layoutA` preset had 14 leaves vs 13 sizes (threw on apply) — fixed in place.
* Gates: 398 pytest + 114 node pass; verify_quality 0 fails; coverage
  line 39.721% → 41.676% (+1.954pp), branch 27.717% → 29.532% (+1.815pp);
  radon: every new function ≤B(7).
