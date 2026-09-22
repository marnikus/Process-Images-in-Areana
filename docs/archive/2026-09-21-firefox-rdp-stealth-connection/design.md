# Firefox integration — the DevTools RDP channel (stealth connect, click-only) — design

**Date:** 2026-09-21 · **Owner request:** the round-7 Firefox connection "is not working as expecting";
replace it with the DevTools Remote Debugging Protocol (RDP) approach, under the hard constraints below.

## 1. What the owner requires (verbatim intent)

| # | Requirement |
|---|---|
| R1 | Launch a **regular Firefox manually** (not via an automation framework) and connect the app to that **already-running** instance |
| R2 | **Click-only** actions on websites; **disconnect / reconnect** at will **without restarting** Firefox; the browser session stays persistent |
| R3 | **No automation signals**: no geckodriver / Selenium / Playwright / Puppeteer footprint, `navigator.webdriver === false`, **real user profile** with the user's extensions and history, **no headless**, no datacenter/VPN fingerprinting |

## 2. Research — why the round-7 Firefox path had to go

| Fact | Source |
|---|---|
| `navigator.webdriver` is `true` **for the whole Firefox session** once the browser is started with `--remote-debugging-port` (the Remote Agent that serves WebDriver BiDi). The flag is *not* yet bound to an active session — that follow-up (bug 1696425) is still **NEW** | [Bugzilla 1719505](https://bugzilla.mozilla.org/show_bug.cgi?id=1719505) — *RESOLVED FIXED, Firefox 101*; blocks [1696425](https://bugzilla.mozilla.org/show_bug.cgi?id=1696425) (NEW) |
| The DevTools server (`--start-debugger-server`) does **not** set the flag — the request to make it do so is still **open** | [Bugzilla 1720838](https://bugzilla.mozilla.org/show_bug.cgi?id=1720838) — *NEW* ("[devtools-rfc] DevTools remote-debugging should enable navigator.webdriver") |
| Firefox's CDP was deprecated (129) and removed (141); the Remote Agent is the only channel left there — and it is the flagged one | round-7 research (fxdx.dev) |
| The DevTools server speaks the **Remote Debugging Protocol**: packets are `<length>:<json>`, client packets `{"to":actor,"type":…}`, server packets `{"from":actor,…}`; a packet to a dead actor answers `{"from":actor,"error":"noSuchActor"}`; **actors live only as long as the client connection** (the root actor dies with it) | [Remote Debugging Protocol](https://firefox-source-docs.mozilla.org/devtools/backend/protocol.html) |
| On connect the server sends the root form (`{"from":"root","applicationType":"browser","testConnectionPrefix":"server1.connN.","traits":{…}}`); `{"to":"root","type":"listTabs"}` answers tab **descriptors** carrying `actor`, `title`, `url`, **`browsingContextID`**, `outerWindowID`, `isZombieTab`, `traits.watcher` | live Firefox transcript ([SO 78601004](https://stackoverflow.com/questions/78601004/how-do-i-speak-the-firefox-remote-debugging-protocol)) |
| A descriptor's `{"type":"getTarget"}` answers a **target form whose `consoleActor`** is what evaluates JS; the same form carries `screenshotActor`, `inspectorActor`, … Modern clients also `attach` the target | [SO 58628493](https://stackoverflow.com/questions/58628493/firefox-70-remote-debugging-unable-to-get-consoleactor), [SO 73692117](https://stackoverflow.com/questions/73692117/how-to-send-messages-to-firefox-through-devtools-protocol) |
| `evaluateJSAsync` answers `{resultID}` immediately and the value arrives as an **`evaluationResult` event**; large results come back as a **long string** needing `substring` | [cookiemonster](https://embracethered.com/blog/posts/2020/firefox-cookie-debug-client/), [geckordp](https://github.com/jpramosi/geckordp) |
| Actor initials must be re-resolved every session: "actors have limited lifetimes … always re-enumerate rather than cache actor IDs"; **`browsingContextID` is the tab's stable identity**, the actor id is not | [protocol doc](https://firefox-source-docs.mozilla.org/devtools/backend/protocol.html), geckordp README |
| `--start-debugger-server <port|ws:port|host:port>` + prefs `devtools.debugger.remote-enabled` (**required** — the CLI flag is ignored without it), `devtools.chrome.enabled`, `devtools.debugger.prompt-connection=false` (otherwise every connection pops a prompt), `devtools.debugger.force-local` (default true → loopback only) | [VS Code Firefox debugger docs](https://marketplace.visualstudio.com/items?itemName=firefox-devtools.vscode-firefox-debug), [Bugzilla 1286281](https://bugzilla.mozilla.org/show_bug.cgi?id=1286281), [balena thread](https://stackoverflow.com/questions/79342737/firefox-remote-debugger-does-not-connect-over-balena-tunnel) |
| A JS-dispatched click (`el.click()`) carries `isTrusted === false`; RDP has **no input-synthesis actor**, so only the OS can produce a trusted click | RDP actor set (no input actor); documented as a limitation, see §5 R3 |

**Conclusion:** RDP is the one Firefox channel that satisfies R3, and it satisfies R1/R2 by construction — the
browser is an ordinary GUI Firefox the owner starts; the app's socket is just a client that can come and go.
BiDi stays in the tree only as a **detected fallback**, with the flag consequence named in the panel.

## 3. Decisions

| # | Decision |
|---|---|
| **D-1** | `app/browser/rdp/` package, mirroring `app/browser/cdp/`: `wire.py` (the `length:JSON` codec), `connection.py` (socket, greeting, serialized request/response, event queue), `actors.py` (pure packet parsers + the click expression), `client.py` (`RDPClient` facade + one-shot helpers), `profile.py` (the Firefox prefs and the `user.js` writer) |
| **D-2** | **Identity is `browsingContextID`**, never an actor id: a tab is `RdpTab(id="ctx-<browsingContextID>", …)`; the descriptor/target/console actors are resolved **per operation** (cached only inside one connection, invalidated on `noSuchActor`), which is exactly what makes detach/re-attach work (R2) |
| **D-3** | The Firefox row's protocol becomes `rdp`: `CAPABILITIES["rdp"] = {tabs, evaluate, click, navigate}`; `unavailable` = the CDP matrix minus that = `dom, input, screenshot, set_files` — named per browser, never a silent timeout (round-7 D-3 rule kept) |
| **D-4** | `build_command` gains a per-profile `debug_flag` (`--remote-debugging-port={port}` for Chrome/Edge, `--start-debugger-server {port}` for Firefox) and Firefox's dir flag becomes the documented `-profile`; the generated command **never** contains `--remote-debugging-port` (locked by a test — that is the stealth regression guard) |
| **D-5** | Prefs live in the registry (`BrowserProfile.prefs`) and reach the panel + a **`prepare_profile`** action on the existing `set_cdp_config` slot (no new slots, 137 frozen): the app merges the four `devtools.debugger.*` prefs into `<profile dir>/user.js`, **preserving every unrelated line** of an existing `user.js`, and says "restart Firefox" — writing into the owner's real profile is explicit, opt-in and idempotent |
| **D-6** | `detect_protocol` order becomes **CDP → RDP → BiDi**: `/json/version` (Chrome/Edge/ESR), then the RDP probe (greeting or a `listTabs` answer on the raw socket — an HTTP server cannot fake that), then `POST /session`. Each result names the stealth consequence in the panel |
| **D-7** | `endpoints` keeps one listing/acting seam: `list_targets` returns `TargetRef`s for all three protocols (`ws_url = rdp://host:port/<tab id>` — a stable *handle*, there is no per-tab socket in RDP), plus `endpoints.evaluate` / `endpoints.click` dispatch with a **named reason** for a protocol that cannot do the op |
| **D-8** | Panel honesty: the Firefox block shows the RDP launch command, the prefs (`user.js` text + Prepare button), the resolved socket (`tcp 127.0.0.1:<port>`), the capability line, and a stealth note that says *why* this channel keeps `navigator.webdriver` false — and what the BiDi/CDP alternative would cost |

## 4. Files

| Area | File | Change |
|---|---|---|
| new | `app/browser/rdp/{__init__,wire,connection,actors,client,profile}.py` | the RDP client + the prefs writer |
| new | `tests/fakes/rdp_stub_server.py` | a fake Firefox DevTools server: greeting, `listTabs` descriptors, `getTarget`/`attach`, `requestTypes`, `evaluateJSAsync` + event, legacy `evaluateJS`, long-string `substring`, actor expiry, byte-counted-prefix and non-ASCII modes |
| new | `tests/test_rdp_wire.py`, `tests/test_rdp_connection.py`, `tests/test_rdp_client.py`, `tests/test_rdp_profile.py` | RED-first suites |
| edit | `app/browser/browsers.py` | `PROTOCOL_RDP` + capabilities, `debug_flag`, Firefox row (RDP, `-profile`, prefs, stealth note), `prefs`/`stealth`/`debug_flag` fields |
| edit | `app/browser/endpoints.py` | RDP detection, RDP listing, `evaluate`/`click` dispatch with named reasons |
| edit | `app/ui/panels/cdp_tools.py` | row facts (`prefs`, `prefs_file`, `stealth`, RDP test hint), `prepare_profile` handling in `set_cdp_config` |
| edit | `app/ui/panels/browser_tabs.py` | `do_fetch_tabs`/`do_diagnose_chrome` gain the RDP branch; `connect_tab` refuses an `rdp://` handle by name |
| edit | `app/ui/web/index.html`, `app/ui/web/js/panels/browser-connection.js` | prefs block + Prepare Profile button + stealth line |
| edit | `tests/test_browser_profiles.py`, `tests/test_browser_endpoints.py`, `tests/test_browser_config_slots.py`, `tests/js/test_browser_selector.mjs` | re-point Firefox expectations to RDP, keep the BiDi path as the detected fallback |
| edit | `docs/current/SYSTEM_OF_RECORD.md` (I-62 rewritten), `docs/current/QUALITY_RECHECK.md` (addendum e), `README.md`, round-7 design (superseded note) | the living truth |

## 5. Rejected alternatives

* **Keep BiDi as the Firefox default** — rejected: bug 1719505 (FIXED, FF 101) sets `navigator.webdriver = true`
  for the whole session; that is precisely the signal R3 forbids. Kept only as a *detected* fallback.
* **Marionette / geckodriver / Selenium** — rejected: same flag, plus an external driver binary (R3).
* **Playwright/Puppeteer `connect_over_cdp`** — rejected: launches/attaches through the flagged Remote Agent,
  and R1 forbids launching through a framework.
* **Bundle the RDP client of a third-party project** — rejected: a new runtime dependency and a second
  protocol implementation inside the app; the wire format is 60 lines (`wire.py`) and must be ours to test.
* **Fake `navigator.webdriver = false` with a page-level patch** — rejected: dishonest, detectable (a
  `toString`-checkable override), and it would not fix the trait-level signals the flag stands for.
* **Synthesize trusted clicks by driving the OS input queue (xdotool / SendInput)** — out of scope for this
  round; documented as the only way to get `isTrusted: true`, and the reason `click` is a named RDP capability
  rather than a promise of full parity.
* **Write the prefs into `prefs.js` / silently on save** — rejected: `prefs.js` is Firefox's own file, and a
  silent write into a real profile is not acceptable; `user.js` (the documented override file) merged, opt-in,
  and reported.

## 6. Tests first (RED at `464185a`)

* **wire**: round trip; the UTF-16 prefix rule (Cyrillic + emoji both ways); a packet split across TCP reads;
  a server that counts bytes instead of UTF-16 units (tolerant read); a bogus prefix / garbage body → `RdpError`
  (never a hang).
* **connection**: greeting read and greeting-absent tolerance; request/response pairing; unsolicited events
  queued while a request is pending; a *typed* response (`tabAttached`) still treated as the response;
  `noSuchActor` → `RdpError("noSuchActor")`; timeout; `close()` idempotent.
* **client**: `list_targets` identity is `ctx-<browsingContextID>` and is **identical across two connections
  whose actor ids differ** (the R2 acceptance); `evaluate` over `evaluateJSAsync` (event correlation) and over
  the legacy `evaluateJS` (chosen from `requestTypes`); long-string `substring`; an expired console actor →
  one re-resolve → success; two expiries → a named error (no infinite retry loop); `click` sends the
  click-only expression; a dead port returns an error text and never raises.
* **profile**: `user_js_text` carries the four prefs; `prepare_profile` writes into a temp profile dir; an
  existing `user.js` keeps its unrelated lines; a missing dir is an error; a second run reports "already".
* **endpoints/profiles**: `detect_protocol` says `rdp` for the fake server and `bidi` for the round-7 fake
  Remote Agent; `list_targets('firefox', …)` rows carry `protocol="rdp"`; the Firefox launch command contains
  `--start-debugger-server <resolved port>`, `-no-remote`, `-profile` and **never** `--remote-debugging-port`;
  `supports('firefox', 'click')` is `True` and `'set_files'` is `False`.
* **slots/panel**: the payload carries `prefs`/`prefs_file`/`stealth`/the RDP test hint; `prepare_profile`
  writes and reports; `prepare_profile` on Chrome is refused by name; the JS block renders the prefs, names
  the missing CDP operations, and the Prepare button calls `set_cdp_config` exactly once with
  `prepare_profile: true`.

## 7. Outcome

Delivered as designed, with these decisions confirmed by the code and the tests:

| Decision | Where it landed | Evidence |
|---|---|---|
| D-1 own Python client, no new dependency | `app/browser/rdp/{wire,connection,actors,client,profile}.py` (177/148/227/244/104 lines) | `tests/test_rdp_{wire,connection,actors,client,profile}.py` (67 tests) |
| D-2 identity is `browsingContextID`, actors re-resolved per operation | `actors.tab_of_descriptor` → `ctx-N`; `RdpClient._console_actor` cache is per attach; one `noSuchActor` retry | `test_the_tab_identity_survives_a_reconnect`, `test_a_stale_actor_is_resolved_again_and_the_call_still_succeeds`, `test_an_actor_that_never_comes_back_is_named_after_one_retry` |
| D-3 RDP capability row | `CAPABILITIES[rdp] = {tabs, evaluate, click}`; `unavailable` = CDP matrix minus that | `test_capabilities_state_what_each_protocol_can_do_today`, `test_each_browser_row_carries_its_own_port_dir_command_and_capabilities` |
| D-4 per-profile debug flag, Firefox never gets `--remote-debugging-port` | `browsers.debug_arg` + `launch_commands` | `test_firefox_command_starts_the_devtools_server_instead_of_the_remote_agent`, `test_no_firefox_command_ever_enables_the_flagged_remote_agent` |
| D-5 prefs in the registry + opt-in `prepare_profile` on `set_cdp_config` | `rdp/profile.py`, `cdp_tools.prepare_active_profile` | `tests/test_rdp_profile.py` (7), `test_a_plain_save_never_touches_the_real_firefox_profile`, `test_prepare_profile_writes_the_devtools_prefs_when_asked`, `test_prepare_profile_is_refused_by_name_for_a_browser_without_devtools_prefs` |
| D-6 detection order CDP → RDP → BiDi | `endpoints.detect_protocol` + `rdp.probe` | `test_detect_protocol_reads_the_endpoint`, `test_detect_prefers_cdp_then_rdp_then_bidi` |
| D-7 one listing seam, named refusals | `endpoints._rdp_refs`, `evaluate(ref, …)`, `click(ref, …)` | `test_firefox_targets_come_from_the_rdp_tab_list`, `test_evaluate_and_click_are_dispatched_by_protocol`, `test_an_rdp_firefox_is_not_poolable_through_a_tab_socket` |
| D-8 panel honesty | `index.html` prefs/stealth/Prepare Profile block + `browser-connection.js`; `browser_tabs` RDP listing/diagnose | `tests/js/test_browser_selector.mjs` (11) |

Deviations from the plan, all recorded on purpose:

* **No `ws:` transport.** `--start-debugger-server ws:<port>` is documented, but its framing drops the length prefix and
  the round only needs one channel; TCP is the default Firefox offers and the one the prefs assume.
* **No launcher process.** The design first considered spawning Firefox for the user; the requirement is an ordinary,
  manually started browser, so the app only *prints* the command (`debug_arg`) and attaches. Nothing in `app/` spawns a
  browser for this path.
* **`evaluate`/`click` take a `TargetRef`**, not six loose parameters — RULE 16's ≤4-param limit decided that, and it
  reads better at the call sites.
* **`connect_refusal` lives in the panel layer** (`browser_tabs`) over the pure rule in `app/browser/protocols.py`,
  because the message is UI text while the rule is structural — and the panel must not import the browser layer at
  module level.
* **`decode_packet` was added** to the codec as the public "body → dict" helper (the incremental reader keeps its own
  decode loop for leftovers).
* **One real bug found by the boundary tests**: a socket that timed out once could not be read again through a
  `socket.makefile` handle ("cannot read from timed out object"), and a partial read was possible on a timeout-mode
  socket. Both are why the reader now reads off the socket with `select` deadlines and exact-length loops.

Gates for the round: pytest **2,108 passed / 11 skipped**, JS **369 tests / 365 pass / 0 fail / 4 skipped**, coverage
**88.31 % line / 84.76 % branch**, `verify_quality.py --changed-files` 0 fails (whole-repo lane: only the pre-existing
`captcha.js max_cc`), `js_metrics` 0 new violations. Honest limits (named in the panel, not hidden): no input
synthesis, no screenshot, no file chooser, no `Network.*`; residential-IP and profile-history requirements are
properties of the machine and the profile the user brings, not of this code path.
