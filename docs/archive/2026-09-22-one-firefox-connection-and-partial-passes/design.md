# One Firefox connection, and a Firefox that is detectable like Chrome (round 11, 2026-09-22)

Owner report, verbatim:

> still generating — Firefox shows "An incoming request to permit remote debugging connection was detected"
> popup — App sends never-ending permission request messages — Popup keeps reappearing — user must click
> Allow repeatedly. remove it completely. should stop sending it
>
> 2 fireFox is not detactable URL as Crome does. But also shoulbe be able detect URL with pattern and add it
> to url list! fix both

Round 10 (I-62 clause (k)) reduced a listing pass from two Firefox connections to one. That was the wrong
number: the count that matters is **connections per operation**, and it was never one.

## 1. Facts, measured before anything changed

`tests/fakes/rdp_stub_server.py` is a real TCP DevTools server, so the connection count is a fact, not an
opinion. Instrumenting `RdpConnection.connect()` and running **one** reconcile pass against a Firefox with two
open tabs (Chrome switched off, so every socket in the count is Firefox's):

| What opened the socket | Sockets per pass |
|---|---|
| `endpoints._rdp_refs` (the listing) | 3 |
| `attached._attach_rdp` (the pool join, per tab) | 2 |
| `attached.evaluate` (badges, owners, scan lines) | 10 |
| **total** | **15** |

`rdp.attach()` is a context manager — *"A connected client for one operation, closed again whatever happens"* —
so every listing, every evaluate and every click in `app/browser/` ends with `close()`, and the next one dials
again. `GREETING_TIMEOUT` is **0.6 s** (`wire.py`): when Firefox is showing the Allow dialog the socket connects,
no greeting arrives within six tenths of a second, the client gives up, closes, and the pass opens another one.
Firefox asks about **each incoming connection** (`devtools/shared/security/auth.js:169` —
`if (!Services.prefs.getBoolPref("devtools.debugger.prompt-connection"))`, read per connection), so the owner's
browser was being asked fifteen times per pass, every pass. That is the "never-ending permission request
messages"; no pref we write into a profile could stop it, because the requests kept coming.

Sources (Mozilla, checked this round):

* `devtools/shared/security/auth.js:169` — the prompt is decided from
  `devtools.debugger.prompt-connection`, **per incoming connection** (not once at startup).
* `devtools/startup/DevToolsStartup.sys.mjs:1316` — `--start-debugger-server` sets
  `devToolsServer.allowChromeProcess = true`, so the root actor exposes the **parent process**
  (`devtools/server/actors/root.js:506`), and a process descriptor answers `getTarget`
  (`devtools/shared/specs/descriptors/process.js:16`) exactly like a tab descriptor does.
* `devtools/server/actors/descriptors/process.js:205` — the process form carries `isParent`.
* `devtools/server/actors/targets/window-global.js:477` — a target form carries `consoleActor`, and the parent
  process target's console evaluates in **chrome scope**, where `Services` exists.

## 2. Design decision

**D-1 — one socket per Firefox endpoint, for the life of the app run.** `app/browser/rdp/session.py` keeps one
live `RdpClient` per `(host, port)`; listing, evaluate, click, info and the pool join all take it from there, and
a lock serialises the request/response exchanges on that one socket. Fifteen connections become **one**.

**D-2 — the dialog is waited for, not raced.** The first attach of an endpoint waits `ALLOW_WAIT` (25 s) for the
greeting instead of 0.6 s, and says so in the log first: the dialog is on screen and the user can answer it.
Once the greeting arrives the session is live and **never re-attaches**, so the dialog cannot reappear.

**D-3 — after the first allowed attach, Firefox is asked to stop asking.** Because `--start-debugger-server`
allows the chrome process, the same socket can run one expression in the browser's own scope:
`Services.prefs.setBoolPref("devtools.debugger.prompt-connection", false)`. The pref is read per connection
(D-…, auth.js:169), so it takes effect immediately, and it is sticky, so it is written to `prefs.js` and the
next Firefox start does not ask either. `Prepare Profile` (round 10) stays the way to have it true **before**
Firefox ever starts. What cannot be done is suppressing a dialog that is already on screen; the first run of the
app on a fresh profile shows it once, and that is stated in the panel text rather than hidden.

**D-4 — a browser that did not answer is not evidence that its tabs closed (partial pass).** `enabled_targets`
already reports a missing browser as a note; the reconciler now uses that: `UrlRow.browser` records where each
row's tab came from, and a pass where Firefox did not answer skips miss-advance, removal and the manual sweep for
those rows, and does not mark its pool pages stale. This is the second half of the owner's report — "fireFox is
not detectable URL as Chrome does": a parked or non-answering Firefox used to have its URL rows and workers
deleted by the next Chrome-answered pass.

**D-5 — detection parity is proven, not asserted.** A pattern-matched Firefox tab becomes a URL row linked to
its `ctx-N` handle exactly like a Chrome tab becomes a row linked to its target id, and the row remembers
`browser="firefox"`.

**D-6 — parked, never looping.** An endpoint whose greeting never arrives is parked with one message naming the
exact next step; automatic passes do not touch it (no sockets → no dialogs). Any explicit user action — Reparse,
Refresh, Diagnose, Connect — clears the park and waits again.

## 3. Files

| File | Change |
|---|---|
| `app/browser/rdp/session.py` | **new** — the one-socket registry, the wait, the park, `retry_all()` |
| `app/browser/rdp/prefs.py` | **new** — `suppress_prompt(client, timeout)`: chrome-scope `setBoolPref`, `(ok, reason)` |
| `app/browser/rdp/connection.py` | `connect(greeting_wait=…)`, `greeted` flag |
| `app/browser/rdp/client.py` | module functions take the session; `chrome_eval()`, `greeting` |
| `app/browser/endpoints.py` | a parked endpoint answers with its reason and opens nothing; one suppression attempt per session |
| `app/browser/attached.py` | `_evaluate_rdp` through the session |
| `app/core/models.py` | `UrlRow.browser` |
| `app/services/auto_connect.py` | the plan carries the tab's browser |
| `app/services/live/url_policy.py` | `RemovalSpec.unconfirmed` — no misses, no removal, no sweep for those rows |
| `app/services/live/reconcile.py` | the pass reads `bridge._scan_missing`; `sync_pool_presence` unconfirmed-aware |
| `app/ui/panels/browser_tabs.py` | explicit actions call `retry_all()`; the one log line names the action |
| `tests/fakes/rdp_stub_server.py` | a prompt mode + a parent process with a chrome console |
| `tests/test_rdp_session.py`, `tests/test_partial_pass.py` | **new** RED-first contracts |

## 4. Rejected alternatives

* **Raise the timeout everywhere / retry slower.** The dialog would still come back; only the rate would change.
  "Should stop sending it" means no second socket.
* **Only write the profile pref (round 10's answer).** It cannot reach a Firefox that is already running, and it
  does nothing about fifteen connections per pass asking again.
* **Patch Firefox's UI or disable the prompt by killing DevToolsServer.** The server is the channel; hiding its
  chrome is the fingerprint this app exists to avoid (round 10, D-4).
* **Keep per-operation sockets and add a cooldown.** Fifteen sockets per pass on a cooldown is still a browser
  being asked to allow a debugger over and over.
* **Treat a missing browser as "no tabs" (the old behaviour).** It is what deleted real Firefox rows and made
  Firefox look undetectable next to Chrome.

## 5. RED first

`tests/test_rdp_session.py` (session reuse, one dialog, the wait, park/retry, suppression, degradation) and
`tests/test_partial_pass.py` (Firefox rows and workers survive a pass Firefox did not answer) are written
against the current code before the implementation, and `tests/fakes/rdp_stub_server.py` grows the two servers
they need: a Firefox that asks for permission until it is told not to, and a parent process whose console has
`Services` in scope.

## 6. Outcome (2026-09-22)

Measured with the same instrument as §1 — `RdpConnection.connect()` counted during one
reconcile pass over a stub Firefox with two tabs: **15 sockets before, 1 after**. The
permission dialog follows the socket count, so the stream of "incoming request to permit
remote debugging connection" dialogs is gone; what is left is one dialog at most on the
very first encounter (plus, in the worst case, the one identity question that keeps a
BiDi Firefox from being mistaken for a dialog), then none — and none at all once the pref
is written.

Delivered as designed: `rdp/session.py` (one socket per endpoint, the wait, the park,
`retry_all`), `rdp/prefs.py` + `rdp/chrome.py` (the running browser is told to stop asking,
through its own process console), `attached`/`client` routed through the session, `UrlRow
.browser` + `RemovalSpec.unconfirmed` (a browser that did not answer is a wait, not a
removal), and Reparse/Refresh/Diagnose/Connect as the only places a new dialog may be
asked for.

Numbers: pytest **2,200 passed / 4 skipped**, JS **76 suites / 375 pass / 0 fail**, coverage
**89.22 % line / 84.61 % branch** (baseline 86.36 / 82.33), `verify_quality --changed-files`
**0 fails**; the whole-repo lane keeps only the pre-existing untouched `captcha.js max_cc`.
Two round-8 pins were re-pointed on purpose (a listing no longer dials per call), and RULE
16 forced two splits during the round rather than baselines: `ChromeMixin` (the class was
172 LOC / 20 methods) and `_presence` (CC 11 in `sync_pool_presence`).

Honest limits: the dialog that is already on screen cannot be retracted — the first run of
the app with a profile whose pref is still true shows it once, and answering it is what lets
the app write the pref; the identity question costs one extra connection the first time an
endpoint that never greets is met; and the pref switch relies on Firefox exposing its own
process, which a hardened build may refuse — that case is named in the panel, not hidden.
