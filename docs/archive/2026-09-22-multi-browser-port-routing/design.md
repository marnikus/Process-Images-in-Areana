# One app, several browsers, one protocol each (2026-09-22, I-63)

Bug report: Firefox would not connect. The log said

```
CDP error: URLError [http://localhost:9224/json/list]: Not Found
❌ Chrome connection error
🤖 Reconcile: +0 added, 0 linked, −0 removed, 0 joined, 0 revived, 1 stale
```

## Root cause

Two independent defects, both from the same assumption — *there is exactly one
browser and it is Chrome*.

1. **The protocol was hard-wired.** Every tab fetch went through
   `bridge.cdp.fetch_tabs()` → `/json/list`. That endpoint is Chrome-only.
   Firefox started with `--start-debugger-server 9224` serves **no HTTP and no
   WebSocket** on that port — it speaks the length-prefixed DevTools RDP over a
   raw TCP socket. So the app asked a question Firefox cannot answer, got
   `Not Found`, and retried forever.

2. **The endpoint was single.** `cdp_host`/`cdp_port` is one host and one port.
   There was nowhere to say "9223 is Chrome and 9224 is Firefox", so even a
   correct Firefox client would never have been pointed at 9224.

The misleading label was a third, smaller defect: `onConnectionStatus` logged
the literal word "Chrome" regardless of which browser the status came from.

Worth stating plainly: the RDP client shipped in I-62 was **correct but never
called**. Nothing in the app referenced `app/browser/rdp/`. This change is the
wiring that makes it reachable.

## The fix

### 1. Endpoints are declared, not sniffed

`app/browser/endpoints.py` — a `BrowserEndpoint` is `(host, port, kind)` where
`kind` is `chrome` or `firefox`. Ports derive from one base so the user sets
`9223` and gets `9223, 9224, 9225…`, but an explicit port always wins.

```json
{
  "browser_base_port": 9223,
  "browser_endpoints": [{ "kind": "chrome" }, { "kind": "firefox" }]
}
```

The kind is **declared** (the choice made in this task) rather than probed,
because the two protocols are not interchangeable and guessing wrong is exactly
what caused the retry loop. An unknown kind is dropped and reported — never
defaulted to Chrome.

### 2. One scan, one protocol per endpoint

`app/browser/browser_scan.py` maps kind → scanner:

| Kind | Scanner | Transport |
|---|---|---|
| `chrome` | `cdp.tabs.fetch_tabs_sync` | HTTP `/json/list` + WebSocket |
| `firefox` | `rdp.discovery.list_firefox_tabs` | raw TCP, length-prefixed JSON |

All endpoints are scanned **concurrently**, and one failing browser never
cancels the others — a dead Firefox must not hide a working Chrome. Each
failure is attributed to the endpoint that produced it, which is what makes the
log readable:

```
🔎 Browser scan — Chrome 127.0.0.1:9223 4 tab(s) · Firefox 127.0.0.1:9224 ✗
❌ Firefox 127.0.0.1:9224: connection refused — start it with:
   firefox.exe --start-debugger-server 9224
```

### 3. Firefox tabs carry an `rdp://` locator

Firefox has no WebSocket URL, but the pool is keyed by one. Discovery emits
`rdp://host:port/<actor>` in `ws_url`. It is deliberately **not** dialable — it
is an opaque key meaning "reach this tab by RDP", and `is_rdp_locator` is the
single predicate that routes protocol at every downstream fork:

* `connect_pool_client` → `FirefoxPoolClient` instead of `CDPClient`
* `pool_tab_id` → the whole locator (Chrome's page id lives inside its URL;
  Firefox actor ids renumber per connection, so the locator is the stable handle)
* `do_connect_page_pool` → joins **without** a `CDPArenaController`, because a
  Firefox tab is click-only and a CDP controller would fail on its first call

### 4. `FirefoxPoolClient` — the pool's vocabulary over RDP

`connect` / `disconnect` / `evaluate` / `click` / `probe`, backed by
`RDPSession`. It remembers the tab's **URL**, not its actor, and re-resolves
after every attach — which is what makes reconnect-without-restart work instead
of silently addressing an actor that no longer exists.

## Backward compatibility

With `browser_endpoints` empty — every existing install — `fetch_all_tabs`
calls the original `bridge.cdp.fetch_tabs()` and nothing changes. The
multi-browser path activates only once endpoints are declared.
`test_with_no_declared_endpoints_the_legacy_chrome_path_is_used` pins this.

## Operator setup

```
"C:\Program Files\Mozilla Firefox\firefox.exe" --start-debugger-server 9224
```

Exactly as requested: no `-profile`, no `-no-remote`, no geckodriver. Firefox
uses its normal profile, so extensions and history are the real ones, and
`navigator.webdriver` stays `false` (I-62). The profile still needs the three
DevTools prefs from `rdp/stealth.required_prefs()` — without
`devtools.debugger.remote-enabled` the port never opens.

Settings: `browser_base_port: 9223`, endpoints `[{kind: chrome}, {kind: firefox}]`
→ Chrome on 9223, Firefox on 9224.

## Files

| File | LOC | Owns |
|---|---:|---|
| `browser/endpoints.py` | 129 | declared endpoints, port derivation |
| `browser/browser_scan.py` | 139 | per-kind scan, named failures |
| `browser/rdp/discovery.py` | 83 | RDP tabs as `TabInfo`, the `rdp://` locator |
| `browser/rdp/pool_client.py` | 128 | pool client vocabulary over RDP |
| `services/browser_connect.py` | 60 | settings → endpoints → scan → log |

Touched: `page_pool.py` (routing), `browser_tabs.py` (fetch seam),
`config_manager.py` (2 defaults), 3 JS files (browser-named status).

## Verification

* **73 new tests** (63 Python + 5 JS + 5 covering the real scanner adapters),
  the Firefox ones against a real socket speaking the real protocol.
* **Mutation-checked** (RULE 8): forcing `is_rdp_locator` to `False` (i.e.
  reintroducing the original bug) and pinning the scanner to Chrome each fail
  the suite — 16 failures.
* pytest **2,143 passed** / 4 skipped · JS **291 pass** · gate **0 fails**
* Coverage **88.67 → 88.77** line, **85.23 → 85.34** branch; every new module
  **100 %** except the pre-existing `rdp/transport.py` (91.2 %).

Pre-existing and unrelated (verified by stashing this work and re-running):
`test_quality_gate.py::test_40loc_js_function_fails`, the 9 JS failures, the 4
coverage-ratchet fails, and `browser_tabs.py`'s `max_func_loc 20→21`.

## Not built

Protocol **auto-detection** (declared kinds were chosen instead), and running
full arena jobs on a Firefox tab — Firefox joins the pool click-only, since
`CDPArenaController`'s image-attach and output-scrape paths are CDP-specific.
