# Firefox runtime attach — design (2026-09-22)

Owner report: Firefox never connects. The log shows the app hitting
`http://localhost:9224/json/list` (Chrome-only) for the Firefox endpoint,
labelling the failure "Chrome connection error", and asking: does the app
parse ALL browser ports every cycle? It must: 9223 (Chrome) + 9224 (Firefox)
+ 9225 (Edge) — every endpoint defined in Settings. The owner's launch is
manual and minimal — `"...firefox.exe" --start-debugger-server 9224`, no
`-profile`, no `-no-remote` — and the app must attach to that running
instance and automate it.

## 1. What the log maps to (understand first)

| Log line | Code | Verdict |
|---|---|---|
| `📑 Received 16 tab(s)` | `cdp-listeners.js:_logTabsReceived` | Chrome-only fetch worked; Firefox tabs never listed |
| `Browser config saved: firefox on 127.0.0.1:9224` | `cdp_tools.set_cdp_config` | config correct — the runtime ignores it |
| `CDP error: URLError …/json/list: Not Found` | `cdp/tabs._fetch_json_sync` via `bridge.cdp.fetch_tabs()` | the ONLY fetch path; CDP-only, single endpoint |
| `❌ Chrome connection error` | `cdp-listeners.js:onConnectionStatus` | hardcoded label |
| `Reconcile: … 1 stale` | `reconcile.py` | the Firefox tab never joins, so it goes stale |
| `user.js already has the DevTools prefs` | **not in this repo** (searched every branch) | the owner's running build carries extra code from elsewhere; this branch needs no profile prefs to attach (the flag alone opens a local server with no connection prompt) |

Why I-63 did not fix it: I-63 built the protocol seam
(`endpoints.list_targets` / `enabled_targets`) but **nothing at runtime
calls it**. Every fetch goes through `bridge.cdp.fetch_tabs()` (one
CDPClient, one endpoint) and every join through `CDPClient.connect(ws)`
plus a `/devtools/page/` tab-id regex. This round wires the seam through
the runtime — no new architecture, the seam was designed for exactly this.

## 2. Measured constraints (no guessing)

* The automation surface is tiny: `evaluate` (23 call sites), `connect` /
  `disconnect` / `is_connected`, `attach_image_cdp` (1), `send` (only from
  CDP-domain code + `network._body`, which try/excepts). An RDP driver that
  implements `evaluate` + connect + an honest attach refusal runs the whole
  prompt/submit/output/click pipeline.
* `evaluate` returns the DECODED value (`None` + `last_error[_kind]` on
  failure) — the RDP driver must `json.loads` the JSON string `rdp.evaluate`
  returns. Kinds: `""` / `js` / `protocol` / `transport`.
* JS `dedupTabs` keys by `t.id || t.ws_url` — RDP `browserId`s dedup fine,
  but the tab selector uses `ws_url` as the option value, and I-63's shared
  `rdp://host:port` would collapse every Firefox tab into one option.
* The registry holds exactly ONE Firefox row, so `browserId` is pool-unique
  (Chrome/Edge ids are 32-hex; no realistic collision with small ints).
* Frozen surface: 137 bridge slots — payloads and JS only, no new slots.
* Import rules: panels never import browser at top level (lazy), services
  never import ui/browser. The multi-fetch therefore lives in ui land and
  reaches services through the already-injected `fetch_tabs` callables.

## 3. Decisions

**D-1 — One fetch for all browsers.** New `app/ui/panels/browser_fetch.py`:
`fetch_all_tabs(config) -> (tabs, errors)` (sync) + an `async` executor
wrapper. Reads `cdp_tools.browser_settings` + `browsers.resolve_port`,
calls `endpoints.enabled_targets`, converts `TargetRef` → `TabInfo`.
Per-endpoint errors return alongside (manual Scan shows them; the
reconcile pass stays silent — tabs drive rows, an empty fetch is a wait).

**D-2 — The tab handle.** `TargetRef.ws_url` for RDP becomes the per-tab
handle `rdp://host:port#browserId` (was: the shared endpoint). One
representation everywhere: pool keys, `plan.connect`, JS option values,
`connect_tab`. Endpoint = text before `#`. Documented in `endpoints.py`.

**D-3 — RDP driver.** New `app/browser/rdp_driver.py`:
`RdpDriver(CDPTransport)` — async driver over sync `rdp.py` via executor.
`connect(handle)` probes + resolves the tab; `evaluate` decodes to the
CDP value shape with `last_error[_kind]` mapping (`js→js`,
`protocol→protocol`, `transport/no-tab/navigated→transport`);
`attach_image_cdp` refuses honestly (`⛔ not in RDP…`); `send` raises
honestly (all callers guarded); `diagnose_sync` probes + counts with
Firefox-named summary; own `disconnect` (QObject shadow guard, same as
`CDPClient`). No persistent socket — "connected" means the endpoint
answers and the tab resolves, rechecked per op.

**D-4 — Shared tab source.** `CDPClient.fetch_tabs` delegates to an
injected async `tab_source` when set (`main_window` sets
`fetch_all_tabs_async` bound to the live config — always current, no
rewire on save). `RdpDriver.fetch_tabs` uses the same source. Legacy
single-endpoint path stays when no source is set. Zero changes in
`reconcile.py`, `auto_connect.py`, `run_state.py` — they already consume
`fetch_tabs()` callables and `id`-first tab keys.

**D-5 — Driver adoption, no type assumptions.** `bridge.cdp` is "the
current tab's driver", CDP or RDP. `use_tab_driver(bridge, ws_url)` swaps
the pointer (per-scheme cache on the bridge), sets the tab source,
re-runs `wire_cdp` (fresh signals per object — no disconnect surgery),
and best-effort disconnects the idle driver. Nothing assumes the
concrete type (verified: every `bridge.cdp.*` use is covered by D-3).

**D-6 — Join/connect route by scheme, browser by endpoint.**
`tab_id_from_ws` parses `/devtools/page/…` (CDP) or `#fragment` (RDP);
join paths construct the driver by scheme; `PageInfo.browser` comes from
a new override-aware `browser_fetch.endpoint_browsers(config)` lookup
(the registry cannot see per-browser overrides, so the lookup lives in
`browser_fetch.py`, not `browsers.py` — this also fixes pool rows being
stamped with the ACTIVE browser under multi-port);
`do_connect_tab` errors name the browser and the right flag/endpoint
(`tcp://` tip for RDP). `TabInfo` gains `browser`/`protocol` (defaulted —
every existing construction stays green).

**D-7 — Manual-launch Firefox.** Registry: Firefox `extra_args_default=""`,
`dir_flag=""` (`build_command` + JS `compose` skip an empty dir flag), so
the generated command is exactly
`firefox --start-debugger-server=PORT` — no `-profile`, no `-no-remote`.
Notes go manual-first (close other Firefox windows first OR add
`-no-remote`; `--profile=` remains available via extra args for an
isolated profile). The app never needed the profile to attach — attach
is pure TCP — so nothing else changes.

**D-8 — Browser-aware UI.** `tabs_received` payload gains `browser`;
options render `[Browser] title — url`; connection/find/diagnose labels
resolve the browser from the tab list (`selectedWs`), falling back to
neutral wording; static `Chrome:` toolbar prefix → `Browser:`.

## 4. Non-goals (named, not silent)

* **Image attach on Firefox stays unavailable** (`⛔ not in RDP`):
  `DOM.setFileInputFiles` has no RDP equivalent. A JS File-injection
  attach is conceivable but unverifiable from here (no Firefox, no
  live-page check) — shipping it would violate RULE 4. Follow-up needs
  the owner's live verification against arena.ai.
* **No new slots** (137 frozen), no `CDPClient` rename, no baseline
  repair (recorded as integrator work in the I-63 recheck).
* The phantom `user.js` writer: not in this repo — if the owner's build
  has it, it is inert for attach and can be removed.

## 5. File plan

| File | Change |
|---|---|
| `app/ui/panels/browser_fetch.py` | NEW (~60): `fetch_all_tabs` + async wrapper |
| `app/browser/rdp_driver.py` | NEW (~170): `RdpDriver(CDPTransport)` |
| `app/browser/endpoints.py` | RDP `ws_url` → `rdp://host:port#id` handle |
| `app/browser/browsers.py` | `browser_for_endpoint`; Firefox `""` defaults + notes |
| `app/browser/cdp/tabs.py` | `TabInfo.browser`/`protocol` (defaulted) |
| `app/browser/cdp/client.py` | `tab_source` delegation in `fetch_tabs` (~6 lines) |
| `app/ui/panels/browser_tabs.py` | `use_tab_driver`, `tab_id_from_ws`, routed connect + errors |
| `app/ui/panels/page_pool.py` | routed pool join + per-tab browser |
| `app/ui/main_window.py` | set the primary tab source (+3) |
| `app/ui/web/js/panels/cdp/cdp-listeners.js` | browser-aware labels |
| `app/ui/web/js/panels/cdp/cdp-render.js` | `[Browser]` options |
| `app/ui/web/index.html` | `Chrome:` → `Browser:` |
| `app/ui/web/js/panels/browser-connection.js` | skip empty `dir_flag` |
| tests | `test_browser_fetch.py`, `test_rdp_driver.py`, `test_tab_drivers.py` (new); endpoint/profile/slot/JS migrations |

## 6. Test plan (RED-first per file, mutants for the routers)

* Fetch: fake Chrome (HTTP) + fake RDP server side by side → both
  browsers' tabs with identity; dead endpoint → error line, other
  browser unaffected; disabled browser skipped; empty fetch → `([], [])`.
* Driver: connect ok / unknown tab / dead endpoint / garbage handle;
  evaluate decodes dict/str/`null`, error-kind mapping, `last_error`
  set; attach refusal text; `send` raises; disconnect clears;
  diagnose shape.
* Routing: `tab_id_from_ws` ×4 shapes; `browser_for_endpoint` incl.
  overrides; `use_tab_driver` adopts/reuses per scheme; connect/pool
  join construct the right driver (fake bridge); error text names
  Firefox + the flag.
* JS: option values unique per RDP tab, `[Browser]` labels, connection
  labels resolve from the tab list (page-boot test).
* Migrations: endpoint `#id` handles; Firefox command
  `firefox --start-debugger-server=PORT` exactly; no `--profile`,
  no `-no-remote` by default.

## 7. Manual smoke (owner's machine)

1. Close Firefox; launch `"C:\Program Files\Mozilla Firefox\firefox.exe"
   --start-debugger-server 9224`; open an arena.ai page.
2. Settings → base port 9223, Firefox enabled → Save. Scan must list
   Chrome AND Firefox tabs with `[Firefox]` options.
3. Connect a Firefox tab → `✅ Firefox connected`; pool-join it; run a
   prompt-only step (attach on Firefox must refuse with the named
   `⛔ not in RDP` reason, never a traceback).
4. Kill Firefox mid-pool → rows go stale with transport errors, no
   loop-crash; restart → rejoin on the next pass.
