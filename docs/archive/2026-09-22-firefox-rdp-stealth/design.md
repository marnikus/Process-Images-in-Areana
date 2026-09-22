# Firefox over DevTools RDP (stealth) — replacing the BiDi approach (2026-09-22)

Owner report: the I-62 Firefox approach (WebDriver BiDi via `--remote-debugging-port`)
is *not working as expected*. Hard requirements for the replacement:

* launch a regular GUI Firefox manually (real profile, no framework);
* the app attaches to the already-running instance for click-only actions,
  detaches and re-attaches without a browser restart (persistent session);
* **no automation signals**: no geckodriver/Selenium/Playwright/Puppeteer
  footprint, `navigator.webdriver` stays `false`, residential connection —
  sites (incl. Google/Gmail) must see a normal human session.

## Research (measured, not guessed)

**Why BiDi fails the hard constraint.** `navigator.webdriver` is `true` in
Firefox whenever Marionette is enabled or `--remote-debugging-port` (the Remote
Agent) serves an active WebDriver session — the flag is bound to the session
state, and the old pref to suppress it is gone. Probing `POST /session` alone
*creates* such a session, so even detection taints the browser. A second,
mechanical failure: the pool joins tabs over a CDP WebSocket, which a BiDi
socket cannot answer — I-62 listed Firefox tabs but could not drive them.

**The one channel that keeps `navigator.webdriver === false`.** Firefox's
legacy DevTools Remote Debugging Protocol (RDP), enabled by the *different*
flag `--start-debugger-server` (TCP `length:JSON` on 127.0.0.1, e.g.
`--start-debugger-server 6000`; the `ws:` form speaks the same packets over a
socket). It loads no Marionette, creates no WebDriver session, and
`about:debugging` uses it — attach/detach is its native mode (actors die with
the connection, the browser keeps running). One-time profile prefs:
`devtools.debugger.remote-enabled=true`, `devtools.chrome.enabled=true`,
`devtools.debugger.prompt-connection=false` (loopback only).

**Wire shapes** (two independent implementations agree; geckordp 1.0.3 verified
against Firefox 136, ff-rdp typed specs live-tested against Firefox 156):

| Step | Request | Reply |
|---|---|---|
| greeting | (TCP connect) | `{"from":"root","applicationType":"browser",…}` |
| tabs | `{"to":"root","type":"listTabs"}` | `{"from":"root","tabs":[{"actor":…,"browserId":…,"browsingContextID":…,"title":…,"url":…}]}` |
| target | `{"to":<descriptor>,"type":"getTarget"}` | `{"from":…,"frame":{"actor":<target>,"consoleActor":…}}` |
| eval | `{"to":<console>,"type":"evaluateJSAsync","text":…,"mapped":{"await":true}}` | ack `{"from":…,"resultID":…}`, then event `{"from":…,"type":"evaluationResult","resultID":…,"result":…,"hasException":…}` |
| navigate | `{"to":<target>,"type":"navigateTo","url":…}` | empty ack `{"from":…}` |
| long string | `{"to":<actor>,"type":"substring","start":0,"end":N}` | `{"from":…,"substring":…}` |

Invariants used: replies carry **no** `type` field, push events always do
(ff-rdp `console.rs`); actor ids change per connection, so every operation
re-enumerates (`root → listTabs → getTarget`) and tab identity is the stable
`browserId` (`browsingContextID`/`outerWindowID` fallback). Errors are
`{"from":…,"error":…,"message":…}` (`noSuchActor`, …).

## Decisions

**D-1 — New `app/browser/rdp.py`, sync, stdlib-only, same shape as `bidi.py`.**
`Endpoint` / typed `RdpError(code, message)` / `RdpConnection` (connect →
requests → close) plus `probe` / `list_tabs` / `evaluate` / `navigate` that
return `(result, error_text)` and never raise. One TCP connection per
operation: attach/detach per call, browser untouched.

**D-2 — Registry: Firefox speaks `rdp`.** New `PROTOCOL_RDP` with the same
honest capability set (`tabs`, `evaluate`, `navigate`); new `debug_arg`
template field (`--remote-debugging-port={port}` vs
`--start-debugger-server {port}`) so `build_command` stays branch-free and a
future browser is still one row. Notes carry the stealth prefs.

**D-3 — Delete `bidi.py`.** BiDi violates the non-negotiable flag *by design*
and offered the same three ops RDP now covers; keeping it would keep a
tainting code path and a `websockets` dependency Firefox no longer needs.
`detect_protocol` probes CDP (`GET /json/version`, ESR path intact) then RDP
(greeting only — creates no session, taints nothing).

**D-4 — Tab identity is the stable `browserId`** (never the per-connection
actor); `TargetRef.ws_url` for RDP is `rdp://host:port` (names the endpoint;
the pool's CDP-only join stays untouched — see non-goals).

**D-5 — Panel rides the frozen slots (137).** Payload rows gain `debug_arg`
(the JS live preview composes the right flag, line-neutral in
`browser-connection.js`); RDP `test_url` is `tcp://host:port` (raw TCP, no HTTP
page to open); the static help line says so.

**D-6 — `evaluate` wraps expressions** in a JSON-stringifying async IIFE with
`mapped.await`, so results match the CDP `returnByValue` contract (JSON text)
and clicks ride it (`querySelector(…).click()` needs no return value);
`longString` grips are dereferenced via `substring`.

**Non-goals.** Driving the full arena run pipeline through RDP (the visual
runner is CDP-bound — a transport seam is the next round); RDP-native
screenshot/file-input/DOM actors (future capabilities, named as gaps meanwhile).

## Rejected alternatives (RULE 16.6)

* Keeping BiDi beside RDP — a second protocol for the same three ops, and the
  BiDi probe itself flips the flag the round exists to protect.
* WatcherActor flow instead of legacy `getTarget` — needed only for shared
  connections (ff-rdp daemon); our one-connection-per-op never shares, and the
  legacy path is live-tested through Firefox 156.
* `startListeners` before every eval — one more packet for console/page-error
  subscriptions no click/eval needs; `evaluateJSAsync` is self-contained.
* A `click` op beside `evaluate` — clicks are eval payloads; a second op would
  promise a runner that stays CDP-bound (non-goal above).

## Files

| File | Change |
|---|---|
| `app/browser/rdp.py` (new) | framing + `RdpConnection` + `probe`/`list_tabs`/`evaluate`/`navigate` |
| `app/browser/bidi.py` (deleted) | replaced — see D-3 |
| `app/browser/browsers.py` | `PROTOCOL_RDP`, `debug_arg`, Firefox row → RDP + stealth notes |
| `app/browser/endpoints.py` | detect CDP→RDP, `_rdp_refs`, `rdp://` ids, per-browser hint flag |
| `app/ui/panels/cdp_tools.py` | `tcp://` test URL + `debug_arg` in the row payload |
| `app/ui/web/js/panels/browser-connection.js` | `compose` uses the row's `debug_arg` (net-zero lines) |
| `app/ui/web/index.html` | help line: Firefox is raw TCP, not an HTTP URL |
| tests | new `tests/test_rdp.py` (real-TCP fake server); `test_bidi.py` deleted; endpoints/profiles/slots/JS re-pointed to RDP |

## Tests first (RED)

* `tests/test_rdp.py` fails to collect (`app.browser.rdp` missing); then the
  fake RDP server (length-prefixed TCP: greeting, two tabs, `getTarget`,
  two-packet eval with an interleaved event, longString, `navigateTo`, error
  packets) pins: probe, listing rows, eval value + `mapped.await`, event
  skipping, exception → `js` error, unknown tab → `no-tab`, dead/garbage
  endpoints never raise.
* profiles/endpoints/slots/JS suites fail on `bidi`/`/session` expectations
  and are re-pointed to `rdp`/`--start-debugger-server`/`tcp://` (same count).

## Outcome

Delivered as designed; gate record in `docs/current/QUALITY_RECHECK.md`
(addendum 2026-09-22), living rules `docs/current/SYSTEM_OF_RECORD.md` I-62
(amended) + I-63. Manual smoke on a real Firefox (owner machine, GUI,
residential IP): set the three prefs once, launch
`firefox --profile <real> --start-debugger-server 6001 -no-remote`, attach via
the app's Firefox endpoint — `navigator.webdriver` reads `false` in the page.
