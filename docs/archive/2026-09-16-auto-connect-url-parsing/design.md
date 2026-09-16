# Auto-Connect & URL Parsing — design (2026-09-16)

Spec: **01 GOAL / 02 PAGE DETECTION / 03 AUTO-CONNECTION / 04 CDP SETTINGS REFERENCE**

Goal: no manual URL connection. The app parses every page Chrome exposes on the
configured debug port and links each page whose URL matches a storable pattern —
on start, on a timer, and when Chrome reports a new tab.

---

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Scan **only** `cdp_host:cdp_port` from Settings (`strict_host=True`); no `localhost` fallback during scans | Spec 02. Fallback hosts made "which Chrome am I talking to?" ambiguous and could link a page from another profile. `diagnose_sync()` keeps the multi-host probe because its job is explaining *why* nothing was found. |
| D2 | A page is identified by its **CDP page id** (`/json/list` `id`, else the id inside `webSocketDebuggerUrl`), never by URL | Spec 02: the same URL open twice is two pages. Repeated *ids* (same target listed via two host spellings) are collapsed and counted as `duplicates`. |
| D3 | Filter = **substring match on normalized URL** (scheme/fragment/trailing slash removed, case-insensitive), optional `*`/`?` wildcards, comma / semicolon / newline / space / `|` separated list, title used as a secondary haystack | Spec 02 asks for a "URL string pattern (e.g. only pages containing arena.ai)". Substring is what the user described; wildcards are free via `fnmatch`. |
| D4 | `devtools://`, `chrome://`, `chrome-extension://`, `about:`, `edge://` and bundled-inspector pages are **never** linked | They cannot run a job; linking them would put a dead page in the pool. Counted separately as `skipped_internal` so "0 matched" stays distinguishable from "everything filtered" (RULE 4). |
| D5 | Auto-connect writes into the **existing PagePool** (one dedicated `CDPClient` per page) and only takes over the **primary** session when that session owns no tab | The pool is what the batch dispatcher consumes, so auto-linked pages are immediately usable for parallel jobs. Stealing an already-connected primary session would break a running job. |
| D6 | Re-scan = **reconcile**, not re-dial: pooled pages are *adopted*; only unknown ids are dialled; auto-added pages that vanished or stopped matching are removed unless BUSY/WAITING | Spec 03 ("confirm the connection not lost"). Churning websockets every 5 s would disconnect live jobs; dropping a busy page would kill a job. Manually added pages are never removed — auto-connect only reaps what it linked itself. |
| D7 | Two triggers: a timer (`autoconnect_interval_ms`, clamped 1 000–600 000 ms) **and** browser-level CDP events (`Target.targetCreated` / `targetDestroyed` / `targetInfoChanged`) | Spec 03 asks for periodic *or* new-tab events; events give sub-second linking of a freshly opened arena tab, the timer is the safety net when the browser endpoint is unreachable or the stream drops. |
| D8 | Every knob is storable in `config/session.json` **and** in arena preset JSON | RULE 10 (one control per decision) + the product rule "all UI params storable". |

## 2. Modules (new)

| File | Responsibility | Qt? | I/O? |
|---|---|---|---|
| `app/browser/autoconnect_match.py` | Pure detection: `normalize_url`, `compile_patterns`, `url_matches`, `page_id`, `select_pages` → `Selection` | no | no |
| `app/browser/autoconnect_config.py` | `AutoConnectConfig` (defaults + clamping) and `config_from_getter()` | no | no |
| `app/browser/autoconnect_linker.py` | `PageLinker` — one reconcile pass: link / adopt / fail / reap, keyed by page id | no | via callbacks |
| `app/browser/autoconnect_service.py` | `AutoConnectService` (one pass: fetch → select → link → publish) and `ScanScheduler` (timer + events, `run`/`halt`/`stop`, RULE 7) | no | via callbacks |
| `app/browser/autoconnect_report.py` | Message wording: `summarize_scan`, `startup_message` | no | no |
| `app/browser/tab_events.py` | `TabEventWatcher` — browser-endpoint websocket on its own daemon thread | no | yes |
| `app/ui/autoconnect_pages.py` | `PageConnector` — the only code that knows Bridge ↔ Chrome ↔ pool | no | yes |
| `app/ui/autoconnect_settings.py` | Payload → `session.json` keys, preset doc, clamp helpers | no | no |
| `app/ui/bridge_autoconnect.py` | `AutoConnectMixin` — Qt slots + boot/shutdown wiring | yes | no |
| `app/ui/web/js/panels/auto-connect.js` | Settings block + toolbar: pattern, interval, max pages, primary, Scan Now, On/Off, live status | — | — |

Changed: `cdp_client.py` (`candidate_hosts`, `strict_host`, `fetch_tabs(host, port)`),
`bridge.py` (mixin base, `autoconnect_status` signal, boot call, preset block,
`_do_connect_page_pool` reuses a live client), `config_manager.py` (defaults),
`main_window.py` (`shutdown_autoconnect()` on close), `index.html` / `arena-app.js`.

Layering stays `ui → browser → core` with no cycles: the browser modules receive
callbacks and never import the Bridge.

## 3. Stored settings

| Key (`config/session.json`) | Default | Meaning |
|---|---|---|
| `autoconnect_enabled` | `true` | Link matching pages without a manual Add |
| `autoconnect_url_pattern` | `arena.ai` | URL string filter (list + wildcards allowed) |
| `autoconnect_interval_ms` | `5000` | Re-scan period, also the connection watchdog |
| `autoconnect_max_pages` | `0` | `0` = every match |
| `autoconnect_primary` | `true` | Also point the primary CDP session at the first match |
| `cdp_host` / `cdp_port` | `127.0.0.1` / `9222` | The only endpoint scanned (arena users set `9223`) |

Arena presets carry `autoconnect: {enabled, url_pattern, interval_ms, max_pages,
connect_primary}` next to the existing `cdp` block, so a preset restores the whole
connection behaviour.

## 4. One pass

```
fetch_tabs(host, port, strict)            ← only the configured endpoint
  → select_pages(tabs, patterns, max)     ← filter + dedupe by page id
      → PageLinker.reconcile(selection)
          adopt  ids already in pool      (no re-dial)
          link   new matching ids         (pool always, primary if free)
          reap   auto-added ids that are gone / no longer match (skip BUSY)
          report scanned/matched/duplicates/skipped/linked/failed/removed/pool_total
  → publish autoconnect_status + log one line (empty ≠ broken ≠ error)
```

## 5. Failure modes and the answer

| Situation | Behaviour |
|---|---|
| Chrome not running / port closed | Report `ok:false` + the fetcher error, log `warn` with the endpoint, retry next tick. Never "success with 0 pages". |
| Port open, no page matches | `warn`: scanned N, 0 matched pattern X — nothing to connect (RULE 4). |
| Websocket refuses one page | That page is `failed`, the others still link; next pass retries it. |
| Browser endpoint (`/json/version`) unreachable | Watcher backs off silently; the timer keeps confirming links. |
| Event stream drops | Watcher logs once, reconnects after `retry_sec`. |
| Page closed / navigated away | Removed from the pool on the next pass, unless a job is running on it. |
| App closing | `MainWindow.closeEvent` → `shutdown_autoconnect()` → `halt()` cancels the loop and stops the watcher thread. |

## 6. Tests

`tests/unit/test_autoconnect_match.py`, `test_autoconnect_config.py`,
`test_autoconnect_linker.py`, `test_autoconnect_service.py`, `test_tab_events.py`,
`test_bridge_autoconnect.py` — real `PagePool`, real `ConfigManager` (tmp dir),
real service/loop; only Chrome and the Qt signal are faked (RULE 8). Covers:
duplicate URLs → two pages, repeated id → one page, devtools filtered, empty vs
broken, adopt-not-redial, reap on close/pattern change, busy never dropped,
manual pages never dropped, event wake, thread-safe wake, prompt stop, boot run.

## 7. Quality gate

`python tools/verify_quality.py --changed --allow-legacy` → 0 fails; `pytest tests -q` → 272 passed.
New-code coverage (line+branch, `coverage report` on the nine new files) ≈ 92 %.
Classes were split to fit the limits instead of carrying overrides:
detection / linking / one pass / scheduling / glue / slots are separate units
(RULE 19: responsibility first, size follows).
### 6.1 `tests/integration/test_autoconnect_endpoint.py` — real HTTP endpoint

Three integration tests drive the shipping chain (real `CDPClient` over HTTP, real
`select_pages`, real `PageLinker`, real `PagePool`, real `ScanScheduler`) against a
local `ThreadingHTTPServer` that serves `/json/list` and `/json/version` — no Chrome
required, so they run in CI. Only the Bridge is a stub (it registers pages in the
real pool instead of opening websockets). They cover: only matching pages linked,
same URL twice → two pool pages, devtools page skipped, new tab linked by the next
periodic pass, closed tab reaped, and a closed port reported as broken.

## 8. Three production bugs this integration test caught

Unit tests with a fake CDP client passed while the real path was broken. Running
one pass against a real HTTP endpoint found:

1. **`CDPClient.fetch_tabs` had no `strict_host` parameter** — `PageConnector`
   passed it, so *every* production scan raised `TypeError`. Fixed: the signature is
   now `fetch_tabs(host=None, port=None, strict_host=None)`, where `None` keeps the
   client default (`True`), and the sync fallback forwards the same flag.
2. **The websocket handshake blocked the event loop.** `TabConnection` runs a
   synchronous `websockets.connect` with a ~2 s timeout per attempt; awaiting it
   inside a pass stalled the scan timer *and* the Qt loop — one dead tab could make
   a pass outlast the interval. Fixed by offloading: `PageLinker._dial` →
   `_handshake` → `asyncio.to_thread(_handshake_sync)` → `asyncio.run(connect_page)`.
   `offload=False` keeps the in-loop path for tests (I-33).
3. **An unreachable port looked like "0 pages open".** `CDPClient.fetch_tabs`
   swallows errors into a Qt signal and returns `[]`, so a closed Chrome produced
   `ok=True, scanned=0` — an empty report for a broken endpoint, against RULE 4.
   Fixed with `autoconnect_pages.confirm_empty`: when the async client returns
   nothing, the configured endpoint is read again through `fetch_tabs_sync`; an
   error raises `ConnectionError` (broken, pages kept, next pass retries) while a
   real "no tabs" answer still returns `[]` (empty) (I-34).

Lesson recorded: a fake that mirrors the *assumed* interface cannot catch a missing
keyword argument or a blocking call — one integration test against the real
transport is worth more than three more fakes (RULE 8).
