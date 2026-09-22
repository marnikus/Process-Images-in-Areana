# Firefox support — one browser registry, shared host/port, per-browser profile (2026-09-21)

Owner request (verbatim): *"Add Firefox as a supported browser alongside Chrome … same automation operations must work in
both browsers … CDP Host same for both, CDP Port same for both … Both browsers run on the same host and port
simultaneously … URL Pattern same pattern for all browsers … separate launch command and separate user data dir per
browser … Rename 'Chrome Debug Connection' to support both browsers, add browser selector or dual-section layout (Chrome /
Firefox) — think there could be support of other browsers later … Each browser gets its own launch command, data dir …
Use Firefox DevTools Protocol framework for full dev mode support … Ensure feature parity with Chrome CDP operations …
Both browsers should be connectable and poolable at the same time."*

## Research (measured, not guessed)

**The code today.** One hard-coded browser: `cdp_tools.read_cdp_config` reads `cdp_host` / `cdp_port` /
`cdp_user_data_dir` / `cdp_extra_args` / `url_pattern`; `build_chrome_commands` prints one Windows + one Linux Chrome
command; `app/browser/cdp/tabs.fetch_tabs_sync(host, port)` lists tabs from `GET /json/list`; the pool and the debug
client hold ONE `host:port` (`PagePool._host/_port`, `CDPTransport._host/_port`); the panel title is "Chrome Debug
Connection".

**What Firefox actually offers (2026).**
* Firefox's Remote Agent is started with `--remote-debugging-port <port>` (same idea as Chrome). It speaks **WebDriver
  BiDi**, always enabled since 129.
* **CDP was deprecated in Firefox 129 and fully removed in Firefox 141** — the Mozilla post `cdp-retirement-in-firefox`
  says ESR 140 was the last channel with `remote.active-protocols=2` (CDP) still available; ESR 128 had it too. So a
  current release Firefox cannot be driven by CDP at all: `/json/list` is not served and CDP commands are gone.
* BiDi's HTTP entry point is `POST /session` → `{"value": {"capabilities": {"webSocketUrl": "ws://host:port/session"}}}`;
  the tab list is `browsingContext.getTree` over that session socket, JS is `script.evaluate`, navigation is
  `browsingContext.navigate`. Firefox exposes one session socket per browser, not one socket per tab.

Consequence for "feature parity": everything the app does through JS probes works over BiDi, but the CDP-only
operations (screenshot capture `Page.captureScreenshot`, file attach `DOM.setFileInputFiles`, input events
`Input.dispatchMouseEvent`, `DOM.querySelector`) have no BiDi equivalent in Firefox yet. The design therefore keeps
**one protocol-autodetect seam** and states the matrix per browser instead of pretending.

## Decisions

**D-1 — One browser registry, data-driven (`app/browser/browsers.py`).** A `BrowserProfile` row per browser
(`chrome`, `firefox`, `edge` as the third, proving "other browsers later"): id, label, protocol, port offset, default
data dir, default extra args, the dir flag (`--user-data-dir` vs `--profile`), executable candidates per OS, and notes
shown in the panel. Adding a browser later is one row — no new code path.

**D-2 — Host and base port are shared; each browser gets a derived endpoint.** `cdp_host` and `cdp_port` stay the single
shared settings (the panel shows them once), `url_pattern` stays one pattern for every browser. Two TCP servers cannot
listen on the same port, so each profile resolves its own endpoint port as **base + offset** (Chrome 0, Firefox 1, Edge
2), with a per-browser override field for the rare case the user needs a specific one. The panel shows the resolved
port next to each browser, so "same port setting" stays true as a *setting* while simultaneity is physically possible.

**D-3 — Protocol autodetect, then an honest capability matrix.** `endpoints.detect_protocol(host, port)` probes
`GET /json/version` (CDP answers) and falls back to `POST /session` (BiDi answers). So: Firefox ESR 128/140 launched
with CDP enabled works exactly like Chrome with zero special-casing, and a modern Firefox is driven over BiDi.
`browsers.capabilities(protocol)` lists what each protocol can do today — CDP: tabs/evaluate/navigate/screenshot/
set_files/input/dom; BiDi: tabs/evaluate/navigate — and `browsers.supports(profile, op)` is the one gate a CDP-only
operation asks before running, so a Firefox tab refuses with a named reason instead of an obscure timeout.

**D-4 — One listing seam, so both browsers are poolable at once.** `endpoints.list_targets(browser_id, host, port)`
returns `TargetRef(id, title, url, ws_url, browser, port, protocol)` — CDP via the existing `fetch_tabs_sync`, BiDi via
`bidi.list_contexts` (`POST /session` + `getTree`, sync client, called from an executor like the CDP path). The pool
keeps one page set, each page carrying its browser id, so Chrome and Firefox tabs sit in the same pool table and in the
same Live Debug view.

**D-5 — No new bridge slots.** The 119-slot surface stays frozen (contract §1 item 1): `get_cdp_config`,
`set_cdp_config` and `get_chrome_launch_command` grow a `browsers` map + `active_browser` in their payloads, and the
panel renders per-browser sections from it. `get_chrome_launch_command` keeps its name (frozen) but now returns every
browser's commands.

**D-6 — Screen = "Browser Debug Connection" with a selector.** Shared row (host, base port, URL pattern) + a browser
selector that swaps the per-browser block: data dir, extra args, resolved endpoint port, the generated launch command
(Windows/Linux/macOS + "with URL"), the `/json/list` (CDP) or `/session` (BiDi) test URL, and the capability line. The
Firefox block carries the two facts a user needs: `-no-remote`/`--new-instance` (else the port never opens when Firefox
is already running) and, for CDP on ESR, the `user.js` line `user_pref("remote.active-protocols", 2);`.

## Rejected alternatives (dishonest reductions, RULE 16.6)

* **"Just add a second port field"** — leaves the browser concept in the user's head, not in the code; a Firefox command
  built by a Chrome template is exactly the "did not produce a working solution" outcome.
* **Pretending BiDi is CDP** (sending CDP commands to a Firefox session socket) — every call times out with no reason;
  the capability matrix names the limit instead.
* **One shared data dir** — the browsers refuse each other's profile format; per-browser dirs are what the owner asked
  for and what Firefox's `--profile` requires.
* **Hiding the second browser behind a mode switch** — the owner wants both pooled simultaneously.
* **A new slot per browser** — would break the frozen slot contract for no gain; the payload is the extension point.

## Files

| File | Change |
|---|---|
| `app/browser/browsers.py` (new) | `BrowserProfile` registry (chrome/firefox/edge), `resolve_port`, `launch_commands`, `capabilities` / `supports`, `default_data_dir`, `profile_ids` |
| `app/browser/bidi.py` (new) | WebDriver BiDi leaf: `open_session` (HTTP `POST /session`), `list_contexts` (`getTree`), `evaluate`, `navigate`, typed `BidiError` — sync, never raises |
| `app/browser/endpoints.py` (new) | `TargetRef`, `detect_protocol`, `list_targets(browser_id, host, port)` dispatching CDP↔BiDi |
| `app/persistence/config_manager.py` | `active_browser` + `cdp_browsers` defaults |
| `app/ui/panels/cdp_tools.py` | config read/parse/apply carry the per-browser map; payloads gain `browsers` / `active_browser`; launch payload per browser |
| `app/browser/page_status.py` + `app/ui/panels/page_pool.py` | `PageInfo.browser` (default `chrome`), carried into the snapshot and set at join |
| `app/ui/web/index.html` | "Browser Debug Connection" + browser selector + per-browser block (dir, args, endpoint port, commands, test URL, notes) |
| `js/panels/cdp/*` + `js/panels/settings.js` | selector state, per-browser rendering, browser-aware preview/launch payload |
| tests | `tests/test_browser_profiles.py`, `tests/test_bidi.py` (real fake Remote Agent: one port serving `POST /session` + the session socket), `tests/test_browser_endpoints.py`, `tests/js/test_browser_selector.mjs` |

## Tests first (RED at `bce5a01`)

* registry: three profiles with the right protocol/offset/dir flag; `resolve_port(9223, chrome/firefox/edge)` =
  9223/9224/9225 and an explicit override wins; launch commands per OS carry the right binary, the right dir flag, the
  port and the extra args; Firefox's default extra args contain `-no-remote`; `supports` is true for CDP-only ops on
  chrome and false on firefox/bidi.
* BiDi: against a fake Remote Agent on one port, `open_session` returns the socket URL, `list_contexts` flattens two
  contexts into targets with URL and id, `evaluate` returns the JS value, a JSON error becomes a typed `BidiError`, and
  a dead port returns `""`/`[]` without raising.
* endpoints: `detect_protocol` says `cdp` for a `/json/version`-answering fake and `bidi` for the Remote Agent fake;
  `list_targets('chrome', …)` and `list_targets('firefox', …)` both return `TargetRef`s carrying their browser id — the
  "both poolable at the same time" acceptance, tested by listing both and asserting two distinct browsers in one set.
* JS: the panel has the selector, the shared host/port row, and per-browser blocks rendered from the payload; the
  preview and launch-command text follow the selected browser; the Firefox block shows the `-no-remote` note.

## Outcome (2026-09-21)

> **Superseded for Firefox (round 8, same day).** The BiDi/Remote Agent connection described here is a
> `--remote-debugging-port` session, and the Remote Agent sets `navigator.webdriver = true` for the whole
> browser (Firefox bug 1719505). Firefox now connects over the legacy DevTools RDP socket instead — see
> [`2026-09-21-firefox-rdp-stealth-connection`](../2026-09-21-firefox-rdp-stealth-connection/design.md) and
> I-62 (rewritten). The registry, panel and pool-row structure delivered here stand unchanged; BiDi remains a
> **detected** fallback (with its flag consequence named in the panel).


Delivered as designed; gate record in `docs/current/QUALITY_RECHECK.md` addendum 2026-09-21d, the living rule in
`docs/current/SYSTEM_OF_RECORD.md` I-62.

* **D-1 registry** — `app/browser/browsers.py` (Chrome / Firefox / Edge rows, `resolve_port`, per-OS binaries,
  `endpoint()` + `build_command` / `launch_commands`, `capabilities` / `supports`). 9 tests.
* **D-2 shared host + base port** — `cdp_port` is the base, each browser resolves `base + offset`; the panel shows
  the resolved number, and `set_cdp_config` never stores the panel's derived port (a hand-edited per-browser `port`
  in `session.json` remains the only override).
* **D-3 protocol detection + capability gate** — `endpoints.detect_protocol` probes `/json/version` then `POST
  /session` (CDP wins when both answer, i.e. an ESR Firefox with `remote.active-protocols=2`); every panel row
  carries `capabilities` + `unavailable`, so BiDi's missing CDP-only ops are named in the UI.
* **D-4 one listing seam** — `list_targets` returns `TargetRef` rows for both protocols, and `enabled_targets`
  lists every enabled browser in one pass (both connectable/poolable at the same time, tested against two live fake
  endpoints). `PageInfo.browser` carries the browser into the `page_pool_updated` snapshot.
* **D-5 no new slots** — frozen at 137; `get_cdp_config` / `get_chrome_launch_command` gained `browsers`,
  `active_browser`/`browser`, `resolved_port`, `protocol`, `capabilities`/`unavailable` and per-browser `commands`,
  and `set_cdp_config` persists `active_browser` + full `cdp_browsers` rows while pushing the ACTIVE browser's
  endpoint to `CDPClient` and the pool. The legacy flat `cdp_user_data_dir`/`cdp_extra_args` pair keeps tracking
  the DEFAULT browser so pre-multi-browser readers (presets, older panels) still see Chrome's values.
* **D-6 panel** — `index.html` "Browser Debug Connection (Chrome / Firefox)" + `js/panels/browser-connection.js`
  (selector, shared row, per-browser block, launch preview, capability/notes line; the registry stays in Python and
  the payload wins, JS keeps only an id/label fallback for the first paint). `settings.js` 251 → 227 lines by
  delegating; `cdp-render.updateChromeToolbar` accepts a pre-composed command.

Deviations from the plan, all RULE-16 driven:

* `build_command` / `launch_commands` collapsed their four launch arguments into one `endpoint()` dict (6/5 params
  → 1) and `bidi.evaluate` / `navigate` take an `Endpoint` NamedTuple (5 → 4 params).
* `PagePool` was at its 15-method cap, so the pool's browser is assigned through the same `_host` / `_port`
  attribute push `apply_cdp_config` already performs — no new method.
* A per-browser `extra_args` of `""` means "use the registry default" (so Firefox keeps its required
  `-no-remote`); clearing it entirely stays possible by hand-editing `config/session.json`.

Honest scope boundary: the **panel, the registry and the listing seam** handle both browsers at once, and either
browser can be the active endpoint the automation drives. Making the dispatcher drive two browsers in one run
(two pools / routing per URL row) is a separate round — `endpoints.enabled_targets` and `PageInfo.browser` are the
prepared seams, and no count-based or browser-based routing was invented here.
