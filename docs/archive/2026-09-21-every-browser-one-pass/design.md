# Every browser, one pass — protocol-routed endpoints, and Firefox that actually connects

**Date:** 2026-09-21 (round 9) · **Owner report:** "i can not connect the Firefox browser. does the app parse
now all channels for the browsers? now every browser like chrome - firefox and others has its individual port.
if it starts from 9223 then app should parse all page on ws: 9223, ws: 9224 and ws: 9225 for example (all that
defined in win settings)" — with this log:

```
[15:04:25] Browser config saved: firefox on 127.0.0.1:9224 (base 9223) dir=C:\arena-images-firefox
[15:04:29] CDP error: URLError http://localhost:9224/json/list: Not Found
[15:04:29] ❌ Chrome connection error
[15:04:32] CDP error: URLError http://localhost:9224/json/list: Not Found
... every reconcile pass, forever
```

## 1. What is actually wrong (measured in the code, not guessed)

| # | Finding | Where |
|---|---|---|
| F1 | The **execution path never learned about protocols.** `CDPClient` (the object the pool, the reconciler and every job action use) still lists tabs over HTTP `GET /json/list` and evaluates over a WebSocket, whatever the endpoint is. Round 8 taught the *panel* about RDP; it did not teach the client. | `app/browser/cdp/client.py` (`_fetch_tabs_aiohttp`, `fetch_tabs`, `connect`), `app/browser/cdp/tabs.py`, `app/browser/cdp/probe.py` |
| F2 | **That is the log.** The active browser is Firefox on 9224, so the reconciler asks `http://…:9224/json/list` every pass; a Firefox DevTools socket does not answer HTTP, so `fetch_tabs` fails → `client.error` → "CDP error … Not Found" → "❌ Chrome connection error" → `+0 added … 1 stale`, on a loop. | `bridge_context.on_cdp_error`, `browser_tabs.live_deps.fetch_tabs` |
| F3 | **A saved config pushes a port but not a protocol.** `apply_cdp_config` calls `bridge.cdp.set_host_port(host, resolved_port)`; the client has no idea whether that endpoint is CDP, RDP or BiDi. | `app/ui/panels/cdp_tools.py` → `app/browser/cdp/transport.py:set_host_port` |
| F4 | **Only one endpoint is ever looked at in a pass.** The reconciler/pool read `bridge.cdp.fetch_tabs()` = the ACTIVE browser's port. Chrome's tabs on 9223 simply vanish from the app the moment Firefox is selected — and the multi-browser seam built in round 7 (`endpoints.enabled_targets`) is **not called by anything**. | `app/services/live/reconcile.py:_fetch` → `browser_tabs.live_deps`, `app/ui/panels/page_pool.py:_live_sockets` |
| F5 | `enabled_targets` has a **port bug** that would make it useless the moment it *were* called: `entry.get("port") or profile.port_offset` passes the registry **offset** (0/1/2) as a port. The shared base port + the per-browser offset is the real endpoint (`browsers.resolve_port`). | `app/browser/endpoints.py:enabled_targets` |
| F6 | `connect_tab` **refuses** an `rdp://` handle by name (round 8 decision D-8), so a Firefox tab can never be connected from the tab list. With the client now able to attach over RDP, that refusal is obsolete — and it is exactly "i can not connect the Firefox browser". | `app/ui/panels/browser_tabs.py:connect_tab` → `browser_tabs.connect_refusal` → `app/browser/protocols.py` |
| F7 | A Firefox started with the round-7 command (`--remote-debugging-port=9224`) answers **HTTP 404** on `/json/list` and nothing on RDP. Nothing in the app tells the owner that this is the disqualified channel — the log just says "Not Found". | log above; needs an honest classification |
| F8 | A BiDi tab handle is `ws://host:port/session` — **the same URL for every context**, so two BiDi tabs would pool as one. It also looks exactly like a Chrome socket. | `app/browser/endpoints.py:_bidi_refs` |

## 2. Decisions

| # | Decision |
|---|---|
| **D-1** | **One handle grammar.** A tab handle names its own endpoint and protocol: `ws://host:port/devtools/page/<id>` (CDP), `rdp://host:port/ctx-N` (Firefox DevTools), `ws://host:port/session#<context>` (BiDi — a session socket **plus** its context id, fixing F8). `app/browser/attached.py:parse_handle` is the one parser; the browser id is resolved from the port (`browsers.browser_for_port`), so a pooled row knows which browser it belongs to without extra plumbing. |
| **D-2** | **`CDPClient` routes by protocol.** It carries a *declared* protocol (pushed from the registry by `apply_cdp_config`) and otherwise **detects** it once per endpoint (`endpoints.detect_protocol`, cached, invalidated by `set_host_port`). `fetch_tabs`/`fetch_tabs_sync`/`diagnose_sync` dispatch: RDP → the RDP socket (never HTTP), BiDi → the session, else CDP exactly as before. **No HTTP request is ever made to an RDP endpoint** (test-pinned: the fake DevTools server records every byte and must see no `GET `). |
| **D-3** | **`evaluate` is the one execution seam that matters.** Attached (RDP/BiDi) mode runs `client.evaluate(expr)` in the RDP/BiDi client. Every job action in this app already goes through it — prompt insert, submit, verify, download, highlight, worker badge, owner probe, FIND/CLICK probes in `visual_click` — so Firefox gets the whole click-only path, and `last_error`/`last_error_kind` keep B8's contract. |
| **D-4** | **Capability refusals, named per operation.** The only CDP-domain operations (`get_document`, `query_selector`, `query_selector_all`, `set_file_input_files`, `attach_image_cdp`) refuse on an attached handle with a reason that names the operation and the channel ("RDP cannot set a file input — Firefox's DevTools protocol has no DOM.setFileInputFiles; use a CDP browser for image attach"). Never a silent `None`. |
| **D-5** | **One pass covers every enabled browser.** `browser_tabs.live_tab_rows(bridge)` becomes the app's only listing seam: `endpoints.enabled_targets(rows, base_port, host)` lists Chrome 9223 + Firefox 9224 + Edge 9225 (each at `base + offset`, `F5` fixed), skipping browsers switched off in Settings, tagging every row with browser/protocol/port. It feeds the Refresh list, the reconciler (`LiveDeps.fetch_tabs`), tab matching and the pool's rejoin — so **all** endpoints defined in the settings window are parsed, at every cadence, in one pass. |
| **D-6** | **One warn line per distinct failure.** Each browser that fails contributes one reason; the same text is logged once per session until it clears (`_reconcile_last_error` precedent). A dead Edge on 9225 must not produce three log lines a second. |
| **D-7** | **Honest classification of a wrong-channel Firefox.** When an RDP endpoint does not greet, `endpoints.explain_failure` probes once and classifies: nothing listening → "start it with `--start-debugger-server <port>` (+ Prepare Profile)"; HTTP answers but not CDP (404 on `/json/version`) → "this is Firefox's **Remote Agent** (`--remote-debugging-port`): it sets `navigator.webdriver` for the session (bug 1719505) and its CDP is gone — close Firefox and start it with `--start-debugger-server <port>`". This turns the owner's log into one actionable line. |
| **D-8** | **Connect works for every handle the app lists.** `connect_tab` no longer refuses `rdp://`; it attaches (`CDPClient.connect(handle)`), and `do_connect_page_pool` joins by handle (host/port/protocol/tab id/browser from the handle, not from the pool's active endpoint). `protocols.connect_refusal`/`refuses_tab_socket` are **deleted** — with RDP attachable they would be dead code (RULE 16.6), and the panel feature they guarded (a browser dialled for a tool) is now covered by the real endpoint rules. |
| **D-9** | **The UI says which endpoints are scanned.** The Settings browser block gets one line: `Scanning: chrome 127.0.0.1:9223 (CDP) · firefox 127.0.0.1:9224 (RDP) · edge — off`, and the tab list tags Firefox rows with the channel, so the owner can see both the scope and the port each browser uses. |

## 3. Files

| Area | File | Change |
|---|---|---|
| new | `app/browser/attached.py` | handle grammar + RDP/BiDi attach, evaluate, list, diagnose, capability refusal |
| edit | `app/browser/protocols.py` | drop the obsolete `rdp://`-refusal rule (D-8); keep the names/ports/`port_in` |
| edit | `app/browser/browsers.py` | `browser_for_port(port, base_port, overrides)` |
| edit | `app/browser/endpoints.py` | `enabled_targets` port fix (F5, D-5), `explain_failure` (D-7), BiDi handle carries its context (F8) |
| edit | `app/browser/cdp/client.py` | protocol routing (D-2/D-3/D-4); `set_protocol`; DOM ops refuse on an attached handle |
| edit | `app/ui/panels/browser_tabs.py` | `live_tab_rows` = every enabled browser; `connect_tab` attaches; protocol-aware tips |
| edit | `app/ui/panels/cdp_tools.py` | push protocol to the client; `scan_targets` in the payload |
| edit | `app/ui/panels/page_pool.py` | join by handle; `_live_sockets` via the one listing seam |
| edit | `app/services/run_state.py` | `resolve_tab_info(…, client=None)` so a joined tab's title/url come from its own endpoint |
| edit | `app/ui/web/index.html`, `js/panels/browser-connection.js`, `js/panels/cdp/cdp-listeners.js`, `js/panels/cdp/cdp-render.js` | scan line, browser/protocol chip, per-browser tab summary |
| new | `tests/test_attached.py`, `tests/test_browser_scan.py`, `tests/test_pool_rdp_join.py` | RED-first suites |
| edit | `tests/test_rdp_actors.py`, `tests/test_browser_endpoints.py`, `tests/js/test_browser_selector.mjs`, `tests/test_browser_config_slots.py` | re-point to the new truth (RDP handles are connectable; scan payload key) |
| edit | `docs/current/SYSTEM_OF_RECORD.md` (I-62 extended), `docs/current/QUALITY_RECHECK.md` (addendum f), `README.md`, this doc | the living truth |

## 4. Rejected alternatives

* **Make `CDPClient.fetch_tabs` always aggregate all browsers.** The pool join and `resolve_tab_info` need
  "this endpoint's tabs" (and tests pin that); the aggregation belongs at the UI seam that owns the settings.
* **Encode the browser id in the handle** (`rdp://firefox@…`). Ports are already `base + offset` and
  `browser_for_port` derives the id from the endpoint — one rule, and it fixes CDP rows too.
* **Route `join_tab` through a ref object instead of a string.** `plan.connect` is a list of sockets (pinned by
  existing tests, and the plan is pure); the handle string already carries everything the join needs.
* **Keep the `rdp://` connect refusal.** It was a round-8 consequence of the client not being protocol-aware.
  With attach implemented it would block exactly what the owner asked for.
* **Silence the failing pass entirely.** A browser that is down is information; the rule is one line per
  distinct reason, not zero.
* **Pool BiDi tabs.** A BiDi session is one socket for every context and that channel flags the browser; the
  handle now carries its context (F8) but joining it is refused by name (D-4) until a round needs it.

## 5. Tests first (RED at `741b771`)

* `tests/test_attached.py` — handle parsing for all three grammars; attach verifies the tab exists (unknown
  `ctx-N` → named reason); evaluate over RDP through the real fake server; a JS exception → `last_error_kind ==
  "js"`; capability refusals name the operation; **the RDP endpoint receives no HTTP** (the stub counts every
  byte: no `GET `, `/json/list` never appears); a Remote-Agent-shaped endpoint (HTTP 404 on `/json/version`) →
  the honest classification naming `--start-debugger-server`; a `ws://…/session` handle → named BiDi refusal.
* `tests/test_browser_scan.py` — `enabled_targets` lists Chrome **and** Firefox at `base + offset` (not at the
  offsets), skips browsers switched off, and reports one reason per down browser (a live second browser still
  listed); `live_tab_rows` (panel seam) needs no `bridge.cdp` for Firefox and tags rows; `ScanTargets` – one
  line per enabled browser with its protocol.
* `tests/test_pool_rdp_join.py` — `do_connect_page_pool` with an `rdp://` handle: page registered with
  `tab_id=ctx-3`, `browser="firefox"`, title/url from the tab's own endpoint; the pooled client evaluates over
  RDP (worker-badge JS reaches the fake Firefox); the CDP refusals carry into the pool; a BiDi session handle
  is refused by name.
* Re-pointed: `tests/test_rdp_actors.py` (the handle rules), `tests/test_browser_endpoints.py`
  (`enabled_targets` signature + ports), `tests/js/test_browser_selector.mjs` (scan line).

## 6. Outcome (2026-09-21f)

Delivered as designed — full measurements, gates and honest limits in [`docs/current/QUALITY_RECHECK.md`](../../current/QUALITY_RECHECK.md)
addendum **2026-09-21f**; the living truth is SoR **I-62** clauses (a)–(j).

* **One grammar, three channels**: `app/browser/attached.py` parses `ws://…/devtools/page/<id>`, `rdp://host:port/ctx-N`
  and `ws://host:port/session#<ctx>`, and `list_rows` / `attach` / `evaluate` / `diagnose` / `refusal` route by channel;
  a byte-counting fake Firefox proves no listing on an RDP endpoint is ever an HTTP request.
* **One pass**: `endpoints.enabled_targets` lists every enabled browser at `base + offset` over its own protocol;
  `browser_tabs.live_tab_rows` is the single seam for the reconciler, the pool join, the rejoin gate and the tab panel,
  with one `ScanNote` per down browser printed once per distinct reason.
* **Firefox connects**: `connect_tab` accepts `rdp://…/ctx-N`, `RemoteMixin` attaches one socket and `client.evaluate(...)`
  drives the tab (badge, owner probe, job actions); pooled rows name their browser; the round-8 `rdp://` refusal is deleted
  and BiDi is the one handle refused by name.
* **Honest failures**: an unusable pass raises `endpoints.ScanUnavailable` to the reconciler ("Reconcile skipped") instead
  of looking like a closed tab list, and every wrong-channel case is classified with the one flag that fixes it.

Numbers: pytest **2,147 passed / 11 skipped**, JS **377 tests (373 pass, 0 fail)**, coverage **89.14 % line / 84.57 %
branch** (baseline 86.36 / 82.33), `verify_quality.py --changed-files` **0 fails**, `js_metrics` worst levels on the
touched JS files loc 17 / cc 10 / depth 2.
