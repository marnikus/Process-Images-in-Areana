# Design — register searched Firefox tabs in the URL list and worker pool

**Date:** 2026-09-25
**Status:** design only; no production code or tests are implemented by this document.
**Request:** the Ui.Vision search now finds the correct Firefox tabs. The next change must make those
matched tabs become URL-list rows and pool workers without corrupting the existing Chrome/CDP path.

This is deliberately an archive design, not current behaviour. The current truth must not claim that
Firefox tabs are already pooled until the design below has been implemented and verified.

## 1. The user-visible contract

After an explicit **Sync matched Firefox tabs** action:

1. only running Firefox profiles are considered; profile names are labels, never identity;
2. the configured title and URL patterns are applied together to every readable tab of every selected
   profile;
3. every safe, addressable match is represented by exactly one Firefox URL row and exactly one Firefox
   worker record;
4. two tabs with the same URL are allowed when their tab references differ;
5. a new row is enabled because the user explicitly asked to sync the search result; an existing row
   keeps its checkbox, cooldown, assignment and URL-row id;
6. the URL row owns membership. Unchecking it removes the worker from the active worker set; deleting
   it removes the worker after the busy-job guard. A later sync must not resurrect an unchecked row;
7. the pool does **not** pretend that a normal Firefox tab has a CDP websocket. A discovered Ui.Vision
   tab is shown as `detected`/`extension` until a Ui.Vision execution adapter proves it can receive a
   job. It is not counted as a free CDP worker and is not sent to the current CDP job runner;
8. a failed, stale, or unavailable Firefox read never clears existing Firefox rows. A single healthy
   empty read also preserves them; only repeated healthy misses may remove a missing Firefox row under
   the source-scoped stale-row policy in D6 and §6.3;
9. Chrome rows, Chrome pool pages, Chrome primary connection, cooldown state and the existing
   framework smoke test keep their current semantics.

The distinction between **found**, **registered**, and **job-capable** is intentional. A tab may be
correctly found and visible in the pool while still being ineligible for image processing until the
Ui.Vision image-job executor exists. Calling that tab `steady`, `connected`, or `free` before then
would make the UI lie and would cause a CDP-only runner failure.

## 2. What was researched before designing

### 2.1 Current repository facts

| Area | Current implementation | Consequence |
|---|---|---|
| Firefox search | `app/browser/uivision/tabs.py` reads Firefox session-store files; `app/browser/uivision/plan.py` applies the title + URL predicate; `app/browser/uivision/runner.py` reports matches and executes the current framework test | The result is an ephemeral `Target` list owned by one test run. No bridge/service hands it to `AppState.urls` or a pool. |
| Firefox identity | A session-store row currently contains `url` and `title`; `profile_sessions()` adds profile directory, name, windows, source and timestamp, but no browser target id | A Firefox row cannot be identified by a CDP target id. `profiles.ini Name=` is not a safe identity because the existing delivery design already found name-keyed routing unreliable. |
| Firefox liveness | `profile_in_use()` uses the profile lock; session files can be old or can represent the previous session | “Profile directory exists” and “a session file parsed” are not sufficient evidence that a current tab is open. A sync must distinguish a live recovery answer from a stale/history fallback. |
| URL list | `app/core/models.py:UrlRow` stores `tab_id`, but not a backend or Firefox locator. `app/ui/panels/url_queue.py` and `app/services/live/url_policy.py` assume one generic id and currently use the Chrome pool for membership. | A Firefox reference would collide with Chrome assumptions or be silently treated as a CDP target. |
| Chrome reconciler | `app/services/live/reconcile.py` receives `browser_tabs.live_tab_rows()` and `app/services/auto_connect.py:plan_auto_connect()`, both shaped around CDP `id`/`ws_url` values | Passing Firefox dictionaries into this path would either produce no usable id/socket or make the Chrome pass remove Firefox rows after misses. |
| Current pool | `app/browser/page_pool.py:PagePool` stores `PageInfo`, CDP clients and `CDPArenaController` instances. `app/ui/panels/page_pool.py:do_connect_page_pool()` parses a websocket URL and registers a client/controller. | A fake `ws://` value would create a page that looks ready but has no client, controller, DOM, screenshot, input, output or recovery path. |
| Image runner | `app/services/single_job_runner.py`, `app/services/batch_orchestrator.py` and `app/services/live/supervisor.py` use the CDP client/controller and current pool keys | Registering Firefox as a normal `PageInfo` would make the next image fail at the first CDP operation. |
| Framework smoke test | `plan.one_per_profile()` intentionally reduces matching targets to one run per profile after the 2026-09-24 first-run fix | Registration must not silently change the smoke-test policy. Discovery can retain all matches while the smoke test continues to execute one target per profile. |

The key finding is architectural: **the searched Firefox tabs and the current CDP worker pool are not the
same kind of object**. The correct integration is a backend-aware worker registry with a Ui.Vision
adapter, not a cast from a session-store row to `PageInfo`.

### 2.2 External facts checked this round

* Ui.Vision's official `selectWindow` documentation says that tabs can be selected by a title pattern
  (wildcards are supported) or by a tab index. It also documents that tab indexes are relative to the
  macro's starting tab. That makes a title/URL verification step and duplicate-title refusal necessary;
  a stored position must not be treated as a permanent browser id.
  Source: https://ui.vision/rpa/docs/selenium-ide/selectwindow
* Ui.Vision's current API documentation separates native desktop input from browser/debugger input and
  says that native desktop input requires the XModule and a visible/foreground browser. This supports
  a Ui.Vision backend adapter, but it does not provide a Python CDP websocket for Firefox.
  Source: https://ui.vision/rpa/docs/uiv
* Mozilla's profile documentation says that running profiles are protected by OS file locks and that
  a profile has a root directory managed through the profile service. The directory is therefore the
  right routing identity; the display name is not.
  Source: https://firefox-source-docs.mozilla.org/toolkit/profile/index.html
* Firefox session backups are snapshots rather than a live target protocol. The repository's own
  `tabs.py` already prefers `recovery.jsonlz4`/`recovery.json` and falls back to older files. The
  registration path must not treat `previous.jsonlz4` or a shutdown snapshot as proof of a current tab.
  The file-order behaviour is covered by `tests/test_uivision_tabs.py` and the session-store fact is
  consistent with Firefox's documented profile/session model.

### 2.3 Reproduced failure classes to prevent

These are design-level reproductions from the current interfaces, not implementation claims:

* the search logs `match 1` but no `UrlRow` is created because `run_test()` has no state-write seam;
* a Firefox row with only `url`/`title` has no `tab_id`, so the existing run gate cannot authorize it;
* a fake Firefox `PageInfo` can appear in `PagePool.status_snapshot()` but `get_clients(tab_id)` is
  empty, so `single_job_runner` cannot execute it;
* the Chrome reconciler's `live_keys` do not contain a Firefox key, so its two-miss removal rule can
  delete a Firefox row that it does not own;
* two Firefox tabs with the same title can make `selectWindow title=*…*` select the wrong tab;
* a profile name change can route a later macro to the wrong Firefox instance if it is used as the
  persisted identity;
* a broken or stale session file can be mistaken for “zero open tabs” and cause destructive cleanup.

## 3. Design decisions

### D1 — Discovery is a read model; registration is an explicit state change

The existing search remains read-only. It produces a `FirefoxDiscoverySnapshot` held in memory with a
snapshot id, source status, profile metadata and all candidates. A separate **Sync matched Firefox tabs**
action consumes that snapshot (or performs one fresh read) and writes URL rows and worker records.
Running the framework smoke test must not unexpectedly mutate the URL list.

This gives the user one clear authorization action and keeps RULE 10's “one control per decision”
meaningful: the search answers *what is open and matches*; Sync answers *which matches become managed
workers*. A passive background read may refresh the preview, but it must not add or remove rows.

### D2 — Use profile directory identity, not profile name

The persisted Firefox source identity is the normalized absolute profile directory. The `profiles.ini`
name is display-only. Each candidate carries:

```text
backend       = firefox_uivision
profile_id    = normalized profile directory
profile_name  = display label only
window_index  = 1-based session-window index
tab_index     = 0-based usable-tab index in that window
url           = observed current URL
title         = observed current title
content_hash  = bounded hash of normalized URL + title
source        = recovery.jsonlz4 or recovery.json
source_stamp  = observation metadata, not identity
```

The canonical worker reference is a structured value, not a naked URL:

```text
worker_key = firefox_uivision:<profile-id-hash>:w<window_index>:t<tab_index>
```

`content_hash` is stored beside it so a position cannot silently become a different tab. The key is
called a **positional reference**, not a stable Firefox target id: normal Firefox exposes no stable
remote target id through the allowed read-only session-store channel.

Refresh matching rules, in order:

1. exact existing `profile_id + window_index + tab_index + content_hash` keeps the row and worker;
2. an unambiguous same-profile URL + title match may preserve a row when the session store reorders
   tabs without changing content;
3. a changed-content position is a new candidate, not an automatic rebind;
4. a duplicate URL/title match is ambiguous and is not auto-bound;
5. the old row becomes stale only through the source-scoped removal policy, never through a failed read.

This is deliberately conservative. A wrong tab is worse than a candidate that needs one explicit
re-registration.

### D3 — Add a backend-neutral worker reference, not Firefox fields hidden in CDP code

Introduce a small pure `WorkerRef`/`WorkerKind` value in a core module. Chrome keeps its existing target
id as its native reference; Firefox uses the positional reference above. All ownership and membership
comparisons use the composite `(backend, worker_key)`, never `tab_id` alone.

The wire/data shape may retain `tab_id` for Chrome compatibility, but new rows also carry:

```text
backend: "chrome_cdp" | "firefox_uivision" | "unassigned"
tab_ref: { profile_id, profile_name, window_index, tab_index, content_hash, ... }
worker_status: discovered | ready | busy | cooldown | offline | stale | ambiguous | unsupported
```

`UrlRow.from_dict()` remains tolerant. Old rows with a non-empty `tab_id` and no `backend` are migrated
as `chrome_cdp`; old rows with no tab remain unassigned. `tab_ref` is read back exactly as persisted,
so RULE 13 is satisfied. A URL string alone never becomes a Firefox worker binding.

### D4 — Keep the existing CDP PagePool as a Chrome adapter

Do not add Firefox branches to `PagePool.add_page()`, `do_connect_page_pool()`,
`worker_badges.connected_clients()`, or `single_job_runner`. That would grow a legacy hotspot and hide
a transport mismatch.

Add a backend-neutral registry/facade above the two transports:

```text
WorkerRegistry
  ├─ ChromeWorkerAdapter → existing PagePool + CDP client/controller
  └─ UiVisionWorkerAdapter → Firefox worker records + profile lock + macro executor seam
```

The registry owns identity, URL-row ownership, membership, lifecycle status and the normalized snapshot
shown by the pool UI. Each adapter owns its transport-specific join/leave/execute operation.

The first registration slice can create a UiVision worker record with `status=detected` and
`capabilities=["tab-discovery", "uivision"]`. It must not set `is_connected=true`, `free=true`, or
`receiver=true` merely because a session file was readable. `ready` is reserved for the later adapter
that has verified the extension/XModule execution path.

### D5 — The URL list remains the single ownership authority

Firefox registration goes through the same state funnel as other explicit URL changes:

```text
DiscoverySnapshot
  → pure RegistrationPlan
  → backend-scoped WorkerRegistry admission
  → UrlRow add/update/remove under the bridge state lock
  → one commit_urls() call (persist + emit + undo)
  → pool snapshot + live-bus wake
```

System refreshes use the existing no-undo system funnel. A user-triggered Sync is undoable. There is no
second JavaScript writer and no direct mutation of `App.state.urls`.

The plan must:

* preserve an existing row's `id`, `enabled`, cooldown and image assignment;
* add one row per safe worker reference, even when URLs are equal;
* default a genuinely new row to `enabled=true` because Sync is explicit user authorization;
* leave ambiguous/titleless candidates out of the active pool and report the reason;
* never claim a checked Chrome row for a Firefox candidate or vice versa;
* remove only Firefox rows owned by the Firefox sync source, never rows owned by Chrome reconciliation
  or manually entered rows;
* use `(backend, worker_key)` for deduplication and orphan detection;
* wake the live loop only after the committed state is visible.

The existing checkbox rule remains: checked means eligible for that backend, unchecked means excluded.
An enabled but `unsupported` Firefox worker still has `receiver=false`; the row explains that the
Ui.Vision image executor is not enabled rather than claiming the tab is ready.

### D6 — Reconciliation is source-scoped and fetch-first

The Chrome pass must not own Firefox rows. The future source model is:

```text
Chrome source      → /json/list → Chrome rows/workers only
Firefox Ui.Vision  → live recovery snapshot → Firefox rows/workers only
Manual URL entry   → no source until an explicit backend binding exists
```

For Firefox, a source is healthy only when the selected profile is open and a current recovery file is
successfully read. `previous.jsonlz4`, `sessionstore.jsonlz4`, a missing profile lock, a parse error,
and an empty answer are reported separately:

| Observation | State change |
|---|---|
| open profile + current recovery file + parsed tabs | authoritative source snapshot; add/update candidates |
| open profile + current file missing/unreadable | `unavailable`; preserve existing rows |
| profile not running | `offline/waiting`; preserve existing rows; no automatic deletion |
| current file answers with zero matching tabs | healthy empty result; stale matching rows may advance a miss counter |
| old/history file only | `stale observation`; preview may show it, registration does not admit it |

A healthy empty result may remove an unbusy Firefox row after two consecutive healthy misses, matching the
existing hysteresis idea. A live job defers removal. A profile that simply stopped answering is not an
empty tab list. A manual “Rebuild from open profiles” may offer an explicit destructive cleanup, but it
must still fetch first and preserve busy rows.

### D7 — Pool counts must distinguish registered, ready and receiver workers

The normalized pool snapshot should expose at least:

```text
total             = registered worker records (Chrome + Firefox)
ready              = workers with a usable execution adapter
free               = ready, checked, connected, non-busy, non-cooling workers
detected           = Firefox records found but not execution-ready
unsupported        = records whose backend cannot run the current job type
pages/workers[]    = backend, worker_key, label, profile, title, URL, status, receiver, reason
```

The existing Chrome-compatible `pages` field may remain during migration. The UI must not render
“parallel ready” from `total >= 2`; it must use `ready/free`. A Firefox discovery record can appear in
the table without inflating the free-worker count.

Pool actions route by backend:

* Chrome Connect/Disconnect continue to use websocket and client/controller operations;
* Firefox Sync/Register creates or removes the Ui.Vision record;
* cooldown reset/edit uses the common worker state only when that state exists;
* a Firefox row cannot invoke a Chrome `evaluate`, badge, CAPTCHA or page-recovery operation.

### D8 — Do not promise image processing before the Ui.Vision executor exists

The current Ui.Vision macro is a framework smoke test: it launches an autorun page, brings Firefox to the
foreground, performs an XClick and polls a savelog. It is not yet the equivalent of the Arena CDP image
pipeline (attach, prompt, submit, output verification, atomic save).

The integration therefore has two explicit capability levels:

* **Registration level:** searched tabs can be listed, owned by URL rows, displayed in the worker pool,
  checked/unchecked and removed safely.
* **Execution level:** a future `UiVisionJobExecutor` implements the image-job contract and changes the
  record from `detected/unsupported` to `ready` only after it can perform the full workflow.

The future executor must hold a per-profile async lock because native input cannot safely drive two tabs
in one Firefox profile at once. Before selecting a tab it must re-read/verify its profile and locator,
refuse duplicate-title ambiguity, foreground the correct profile directory, and use the Ui.Vision
savelog/result contract. Stop must be checked between macro phases and inside polling. The CDP path is
not copied into the Ui.Vision path.

The current `plan.one_per_profile()` smoke-test rule remains unchanged. Worker registration retains all
safe matches; execution policy is a separate decision and must not be inferred from the smoke-test
planner.

## 4. Proposed data flow

```text
Firefox Auto: title + URL patterns + selected profile dirs
                    │
                    ▼
        FirefoxDiscoverySnapshot (read-only)
        - open/closed/answer status per profile
        - all matching candidates
        - positional ref + content hash
        - addressability / ambiguity reason
                    │ explicit Sync
                    ▼
              RegistrationPlan
        - preserve / add / stale / defer
        - backend = firefox_uivision
        - one row per safe worker ref
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
     WorkerRegistry       AppState.urls
   (UiVision records)   (one commit funnel)
          │                   │
          └─────────┬─────────┘
                    ▼
          normalized pool + URL snapshots
                    │
                    ▼
          live run eligibility / UI
```

A later execution-enabled flow adds only the backend operation:

```text
live supervisor → eligible WorkerRef → UiVisionWorkerAdapter
               → profile lock → foreground → macro/select/verify
               → savelog verdict → common job/cooldown result
```

The two branches share ownership and status vocabulary, not transport code.

## 5. Boundary and file design

The names below are proposed boundaries, not files changed in this design-only turn.
They are intentionally split before touching the existing hotspots.

| Boundary | Responsibility | Size/quality budget |
|---|---|---|
| `app/core/worker_ref.py` | Pure backend enum, structured ref, composite-key formatting, legacy migration helpers | New module 150–220 lines; functions 4–20 lines; ≤4 parameters; no Qt/IO |
| `app/browser/uivision/discovery.py` | Convert open profile/session-store answers into typed candidates and a snapshot; live-source classification; duplicate/titleless decisions | New module 180–280 lines; no state writes; do not grow `tabs.py` or `runner.py` |
| `app/services/live/firefox_registration.py` | Pure registration plan plus injected apply seam; preserve enabled/assignment; source-scoped misses and busy deferral | New module 180–280 lines; no browser/UI imports; no function over 20 ideal / 30 hard |
| `app/services/live/worker_registry.py` | Backend-neutral records, membership, normalized snapshot and dispatchability counts | New module 200–300 lines; collaborating small types rather than a >10-method class |
| `app/services/live/uivision_workers.py` | Ui.Vision record lifecycle and profile-lock seam; no CDP client/controller | New module 120–220 lines; execution method remains an injected adapter until full image support |
| `app/ui/panels/firefox_registration.py` | One bridge slot/mixin for explicit Sync and status/receipt conversion; keeps the already full `firefox_auto.py` at its 250-line ratchet | New UI module ≤180 lines; slot body ≤20 ideal / 30 hard |
| `app/ui/web/js/panels/firefox-auto-tabs.js` | Sync button, candidate/result table and backend/reason rendering; do not inflate the existing panel script without measuring | New JS module with its own line/complexity budget and Node coverage |
| `app/ui/web/js/panels/worker-backend-cells.js` | Pool/URL backend labels and capability reasons, called through measured facades | New JS module; keep frozen URL/pool files within their current ratchets |
| existing `app/core/models.py` | Add tolerant `backend`/`tab_ref`/worker-status fields only after baseline measurement | Current baseline is 283 lines, max function 28, max class 74; do not add a second large model class |
| existing `app/services/live/url_policy.py` | Small backend-key and source-partition helpers only | Stored baseline: 294 lines, max function 18, CC 7; extract policy tables instead of growing `pool_exits` |
| existing `app/ui/panels/url_queue.py` | Keep the one commit funnel; delegate registration/membership | Stored baseline: 275 lines, max function 14, class 115; do not put Firefox discovery here |
| existing `app/browser/page_pool.py` | Chrome adapter only | Stored baseline: 275 lines, class 144, 15 methods; no Firefox branches and no new method unless a net reduction is designed |
| existing `app/services/live/reconcile.py` | Chrome reconciler remains source-specific until a measured generic source abstraction exists | Stored baseline: 375 lines, max function 18, CC 10; do not append a second large reconciler |

`Bridge` remains a hotspot. The new slot should live in a separate mixin and be added to the frozen
surface deliberately, with the slot-contract test and WebChannel packing test updated for the new
public API. No existing slot is repurposed to hide a new decision.

## 6. State and lifecycle rules

### 6.1 Candidate admission

A candidate is admitted to the active Firefox worker set only when all are true:

* the profile lock says Firefox is running;
* a current recovery file answered and parsed;
* title and URL satisfy both configured patterns;
* title is non-empty and the Ui.Vision locator is unambiguous within that profile;
* the candidate has a complete positional reference and content hash;
* no existing row owns the same `(backend, worker_key)`.

A titleless or duplicate-title match may still appear in the preview with a named reason, but it does not
become an enabled receiver. This is RULE 4's “empty versus broken” distinction applied to discovery.

### 6.2 Existing row preservation

When a candidate matches an existing worker reference, update only observation fields (`title`, `url`,
source metadata and last-seen time). Never reset `enabled`, `receiver`, cooldown, current job,
`assigned_url_id` or the stable URL-row id during a refresh. A changed content hash requires an explicit
rebind rather than silently moving a job to a new tab.

### 6.3 Removal and pool membership

The URL row is the owner. A row removed by sync, user delete or undo sends its worker reference through
the same membership decision. A busy worker is deferred and logged; it is not detached mid-job. An
orphan worker with no URL row is removed once it is not busy. An unchecked row remains visible but is not
an active receiver.

### 6.4 Browser separation

Every operation takes a `WorkerRef`/backend, not a bare string. The Chrome reconciler never evaluates
Firefox refs; the Firefox source never prunes Chrome rows; primary CDP selection never considers a
Ui.Vision record. This is the required protection against cross-backend accidental removal and wrong
transport calls.

## 7. Error/log contract

Every sync emits a bounded, actionable sequence through `bridge._log()` and the existing status signal:

```text
🦊 Tab sync started — search title “…” + URL “…”
🦊 Profile <label> — open / unavailable / stale observation
🦊 Match <n> — profile …, window …, tab …, URL …, title …
🦊 Registered Firefox worker … — URL row …
⏸ Firefox worker … — removal/rebind deferred because a job is running
⚠ Firefox match skipped … — title is empty / duplicate locator / stale source
🤖 Firefox sync: +N added, M updated, −R removed, D deferred, S skipped
```

The log must never say “connected”, “steady” or “ready” for a session-store-only record. It must name
whether the answer was empty, unavailable, stale, ambiguous or unsupported. Per-tab output is capped in
the same spirit as the current search log, with a summary for the remainder.

## 8. Rejected alternatives

* **Pass Firefox rows directly to `auto_connect.plan_auto_connect`.** That planner requires CDP ids and
  websocket joins; it would mix source-specific identity and removal rules.
* **Create a fake `ws_url` or `CDPClient` for every Firefox tab.** This would make the UI report a free
  worker whose first real operation fails and would violate the normal-Firefox/no-debugger decision.
* **Add Firefox branches to `PagePool` and `single_job_runner`.** This grows two hotspots, duplicates
  transport decisions and makes every CDP caller branch on browser type. Adapters keep the blast radius
  local.
* **Use the URL as the worker id.** Two tabs can show the same URL; URL-only matching is exactly how a
  job can be sent to the wrong account/tab.
* **Use `profiles.ini Name=` as the persisted profile id.** Names are display labels and can drift; the
  directory is the routing identity already established by the delivery-by-directory design.
* **Use the session-store tab index as an eternal id.** Firefox's read-only snapshot gives no stable
  target id; position is a locator with a content hash, and changed content must not be silently rebound.
* **Auto-register during every framework smoke-test search.** A test run is not a user authorization to
  mutate the URL list. Sync is an explicit action and is undoable.
* **Let JavaScript append rows or call pool membership directly.** That creates a second writer and
  bypasses persistence, undo, busy deferral and the live-bus wake path.
* **Remove Firefox rows whenever the profile lock is absent.** A closed profile and an unreadable/stale
  session file are not proof that the user wants persisted authorization deleted; preserve and report
  until a healthy source sync or explicit cleanup.
* **Count detected Firefox tabs as free workers.** Detection is not execution capability. The pool must
  show separate detected/ready/free counts.

## 9. Test contract for the future implementation

Tests must be written against real production logic with fakes only at the filesystem, Qt/WebChannel and
transport seams (RULE 8). The important RED-first contracts are:

### Pure discovery and identity

* profile directory remains the identity when `profiles.ini Name=` changes;
* current recovery source is admitted; previous/root-only source is preview-only and never registered;
* title + URL matching matrix is identical to the existing search;
* every profile and every matching position is retained in the discovery snapshot;
* same URL in two tabs yields two refs; same title in two tabs is marked ambiguous;
* empty title, malformed session data, closed profile and failed read have distinct outcomes;
* the same candidate refresh preserves its content hash/row mapping; changed content does not silently rebind.

### Registration and ownership

* a successful explicit sync adds one row and one registry record per safe candidate;
* duplicate URL rows are allowed when worker refs differ;
* existing checkbox, row id, assignment and cooldown survive refresh;
* unchecked rows do not auto-rejoin; checking a supported row joins through the registry seam;
* Chrome reconciliation cannot remove a Firefox row;
* failed/empty/stale Firefox reads leave rows untouched;
* missing rows are removed only after the healthy miss threshold and busy rows defer;
* deleting/undoing a row removes or restores the matching worker without an orphan;
* a failed persistence attempt does not leave a visible registry/URL mismatch.

### Pool and UI boundaries

* a Firefox detected worker has no CDP client/controller, is not `free`, and cannot reach
  `evaluate_on_tab`/CAPTCHA/page recovery;
* worker snapshot reports backend, profile label, position, reason and receiver flag consistently in
  Page Pool and URL List;
* counts use `ready/free`, not raw `total`;
* the new bridge slot is present in the deliberate frozen surface and returns a JSON string on every path;
* JS tests cover the Sync action, candidate rendering, skipped reasons, backend labels and callback failure.

### Regression

The existing Chrome pool, URL reconciler, run gate, `test_uivision_runner.py` smoke-test semantics and
all current WebChannel/slot tests must remain green. The future executor gets a separate test family for
profile serialization, stop polling, duplicate-title refusal, macro/savelog result parsing and full
image-job verification; it must not be hidden inside registration tests.

## 10. RULE 16 / RULE 18 quality budget and final recheck

No production code is part of this turn. The following is the merge gate for the later implementation.
The numbers below are the stored baseline in `tools/quality_baseline.json` (a fresh radon run was not
claimed here because `radon` is not installed in this checkout).

### Existing ratchets that must not worsen

| File | Stored size/complexity fact | Design consequence |
|---|---|---|
| `app/browser/uivision/runner.py` | 497 lines; max function 25; max CC 9 | Do not add registration orchestration; extract discovery/registration. |
| `app/browser/uivision/tabs.py` | 362-line baseline; max function 18; max CC 9 | Do not add identity/registration logic here. |
| `app/browser/page_pool.py` | 275 lines; class 144 lines / 15 methods; max CC 8 | Chrome-only; no new backend methods without net reduction. |
| `app/services/live/reconcile.py` | 375 lines; max function 18; max CC 10 | Keep the Chrome source pass bounded; use a new source adapter. |
| `app/services/live/url_policy.py` | 294 lines; max function 18; max CC 7 | Extract backend-key decisions instead of growing a decision function. |
| `app/ui/panels/browser_tabs.py` | 644 lines; max function 20; max CC 7 | No Firefox discovery code in the Chrome panel. |
| `app/ui/panels/firefox_auto.py` | 250-line baseline; max class 70; max function 23 | Put registration slot/helpers in a sibling mixin/module. |
| `app/ui/panels/url_queue.py` | 275 lines; max function 14; class 115 | Keep it as the commit funnel, not a discovery service. |

### New-code targets

* function ideal 4–20 physical lines; hard fail over 30;
* class ideal ≤120 lines, hard fail over 150; design a collaborator before method 11;
* ≤4 parameters excluding `self`/`cls`;
* cyclomatic complexity ≤10, cognitive complexity ≤15, nesting ≤4;
* each new function has a behavioural test that fails if the function is deleted or its decision inverted;
* overall line coverage remains ≥80% and branch coverage ≥75%, without lowering the stored baseline;
* no new duplication, dead imports or untested zero-hit production functions;
* no metric-gaming helpers, flag-dispatch lambdas or `**kwargs` parameter hiding;
* new JS is measured separately and does not grow frozen URL/pool files without an explicit budget;
* new modules stay near 150–300 lines and the live package remains within the 5–15-module reader
  context ideal.

### End-of-change recheck checklist

Before any future implementation is called complete:

```text
[ ] Discovery, registration and execution are separate responsibilities.
[ ] Firefox identity is profile-directory + guarded positional/content reference; names/URLs are not ids.
[ ] A broken/stale/empty source is distinct from a healthy empty source.
[ ] URL rows are the only ownership authority; all mutations use the correct commit funnel.
[ ] Chrome and Firefox reconciliations are source-scoped.
[ ] No Firefox record is sent to a CDP client/controller or counted as a free worker without an adapter.
[ ] Busy workers defer removal; Stop/cancel checks exist in every future Ui.Vision poll/loop.
[ ] Page Pool and URL List render the same composite worker identity and backend reason.
[ ] Every new production function/class meets RULE 16 hard gates and aims at RULE 18 ideals.
[ ] Stored per-file ratchets did not worsen; no hotspot grew for convenience.
[ ] Python coverage ≥80% line / ≥75% branch; new functions are behaviour-tested.
[ ] JS tests, WebChannel slot surface, persistence round-trips and Chrome regressions pass.
[ ] `docs/current/SYSTEM_OF_RECORD.md` is updated only after behaviour is actually landed.
[ ] This design remains archived unchanged; implementation evidence gets a dated companion record.
```

## 11. Current-doc and delivery boundary

Per RULE 17, this design lives at:

`docs/archive/2026-09-25-uivision-tab-registration/design.md`

This design-only change may update the archive map in `docs/README.md`. It must not rewrite
`docs/current/SYSTEM_OF_RECORD.md`, `docs/current/QUALITY_RECHECK.md` or the rules to describe a feature
that is not implemented. When the implementation lands, its verification record should link back to
this design and then update the current truth, invariants, module table and UI contract in the same
change.
