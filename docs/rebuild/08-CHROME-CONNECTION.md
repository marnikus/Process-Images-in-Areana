# 08 — Reuse existing debug-Chrome connection and rectangle/click systems

> Target-design record. Current progress and executed tests are maintained in [implementation status](../IMPLEMENTATION-STATUS.md); the roadmap now authorizes Steps 1–6; current implementation and outstanding manual gates are listed there.

**Owner requirement:** reuse and adjust the previous working connection and visual-click systems, not replacements. Keep all prior requirements for global undo, dark drag/drop workspace, saved layouts, full presets and variable saving. This is a documentation-only revision; no code restored/deleted, Chrome launched, live connection attempted or old tests rerun in this phase.

## User-owned Chrome session

The user opens Chrome manually, for example from Windows Command Prompt:

```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\arena-images-chrome"
```

The `C:\Users\marni>` shell prompt and HTML-escaped `&gt;` are not part of the command. The user then opens the desired exact image conversation pages and signs in there. The desktop app connects to this existing debug-enabled browser; it does not launch another Chrome, replace its profile, import cookies, or close the user's browser on app shutdown.

Default endpoint: `http://127.0.0.1:9222`, local to the **desktop app and Chrome on the same computer**. Host/port and connection preferences are editable and preset-storable, with loopback-only MVP validation. Do not expose remote debugging to the LAN/Internet, disable browser security, or suggest broad origin-allowance flags. A local debug port has powerful access to browser state; use the dedicated user-selected profile and keep it private. Normal Chrome without remote debugging is not attachable; show a clear instruction rather than silently relaunching it.

Windows is an explicit required connection scenario from the supplied command. Packaging/version support and whether other OSs are also required remain to be confirmed. A remote web preview cannot reach Chrome on the user's computer via its own localhost; this feature belongs to the local desktop app.

## Existing source inspected and to retain

Paths relative to `Process Images in Areana/Old App/`:

| Existing component | Observed responsibility | Planned adaptation |
|---|---|---|
| `backend/cdp_client.py`, `cdp_client_transport.py`, `cdp_client_commands.py`, `cdp_client_events.py` | CDP QObject facade, websocket lifecycle/requests, tab discovery, commands, event fan-out, reconnection and lease | Retain transport/contracts; remove chat-specific consumers; bound requests and revalidate target/context after reconnect |
| `services/cdp_service.py` | Fetch tabs, connect, emit `TabsReceived`, `ConnectionChanged`, `TabMatchResult` via event bus | Retain service pattern and connection UI; add per-URL row/target identity and independent connection/readiness statuses |
| `backend/tab_matcher.py` | Ranked URL/path/host/keyword matching with URL normalization | Change authorization policy for exact image URLs; old fuzzy scoring can never silently choose processing destination |
| CDP bridge, `ui/js/url-toolbar.js` and shared connection controls | Existing connection/bookmark interaction surface | Keep useful interaction/status mechanisms; adapt to multiple exact URL rows rather than chat/language-only assumptions |
| `backend/visual_click.py`, `dom_highlight.py`, `dom_probe.py`, `probe_requests.py` | Shared FIND/red, staged CLICK/orange, saved target and configurable visual request | Reuse actual implementation; adapt scoped image selectors, typed outcomes and persistence boundary; do not fork a second click path |

Observed caveats: the old `CdpService.find_tab_by_url` strips query whitespace and can log unrelated available tabs. The old matcher lowercases full URLs, ignores scheme/fragment/trailing slashes, decodes URLs and offers path-prefix/host/keyword matches. These old behaviors are **not safe proof of exact destination** for this app. Preserve the working transport/UI, not these permissive matching/logging policies. Do not log unrelated tab titles/URLs or websocket debugger endpoints. Discovery metadata stays local and minimal.

The existing client/lease centers on a single CDP socket. MVP retains sequential operation: check/connect rows one at a time, protect an active job's target, and clearly separate a live connection from a cached successful check. Do not claim concurrent per-tab sessions that the retained implementation does not provide.

## Per-link connection workflow

1. User enters/enables exact URL rows and presses Discover Chrome / Refresh tabs.
2. Check local endpoint reachability and valid Chrome discovery metadata using the existing transport. Distinguish connection refused, timeout, wrong service and no page targets. Do not upload or evaluate on every unrelated tab.
3. Match each requested exact URL to actual page targets, not extensions/devtools/workers. Preserve raw input. First prefer literal URL agreement; any browser-serialization difference or redirect is shown for explicit approval, never a silent path/host/title fallback.
4. If no matching page is open, show **Page not open** and ask the user to open it in that debug Chrome. Do not create/navigate a new tab automatically.
5. If multiple tabs match, show title, actual URL and short target ID; require choosing the target. Never select the first duplicate silently. Rows remain independent even if deliberately mapped to the same tab; a shared target can only execute one job at a time.
6. Connect through the retained client to the selected target. A websocket handshake alone is insufficient: perform a harmless page-context round-trip, verify actual location and returned target/context identity, then report connected. Do not insert a prompt or attach a file during testing.
7. Run adapter readiness separately in this same session: image composer, attach, prompt, Send presence and output observation strategy, no blocking challenge/sign-in/error. A working CDP connection can coexist with **Authentication required**, **User action required**, **Unsupported page**, or **Still loading**.
8. Show the outcome for every row. Test enabled rows serially only when no active job can be disrupted. A row checked earlier displays **Verified at <time>; not currently attached** once the single socket moves away.
9. Before each scheduled job, refresh target discovery as needed, attach to the row's chosen existing target and repeat identity/liveness/readiness checks. Cached readiness never authorizes a fresh upload by itself.

Suggested displayed fields: exact requested URL, enabled, tab open/missing/ambiguous, chosen title/target ID, actual URL, connection state, page readiness, last check, error/recovery action, active-job assignment. Persist preferences and historical check summaries, not live sockets or supposedly durable target IDs. Rediscover after browser restart; require confirmation when mapping is ambiguous or changed.

Connection state sequence: `unchecked → checking endpoint → discovering → missing/ambiguous/connecting → connected/error/disconnected`. Site readiness is a separate field with the product statuses. “Ready for scheduling” still requires a fresh attachment/check before action.

## Navigation, reconnect and shutdown

- A closed tab, changed URL, destroyed execution context or broken socket invalidates current readiness. User navigation to another conversation does not authorize continued uploading.
- Automatic transport reconnect may restore communication; it never grants permission to replay commands. Do not retry non-idempotent upload/Send just because a websocket reconnected.
- If send may have occurred, preserve submission-intent/attempt evidence and pause for review. Recover only by observing the marked message/result; no blind re-submit.
- Testing another URL while a job owns the single client is queued or disabled, visibly. Retain the lease's exclusion semantics even if collector priority becomes unnecessary.
- App Stop/Exit releases CDP resources only; it must not close browser, tabs or delete the profile. Local cancel after submit is not a claim of remote cancellation.
- Retest all after Chrome restart/session expiry; stored previous “connected” status is historical only. Login/CAPTCHA remains manual in the existing browser, which the app may bring to the foreground.

## Reuse the old rectangle runner

Retain `find_and_click` / `find_and_click_exact`, `ClickRequest` and their FIND → staged CLICK → click contract. The source request already exposes:

- `highlight_enabled` (default true);
- `confirm_pause_ms` (default 700 ms);
- `highlight_ms` (default 1200 ms);
- semantic selector/text/target fields and readable action label.

Existing staged CLICK pause is 250 ms. Preserve compatible saved fields; expose human-friendly seconds in UI if desired without lossy JSON round-trip. Keep red FIND / orange CLICK outlines, transparent non-intercepting overlay, same-target behavior and cancellation. Retain the existing probe tests; add image-composer scoping, target detachment, duplicate/multiple matching and duration/cleanup cases. Verify actual timing and any speed-scaling interaction before claiming an exact on-screen duration. User-requested duration must not be silently changed by an inherited speed multiplier.

Pass only researched image selectors into the runner. No hand-written alternate `.click()` path in new image actions. Bind single Send to durable submission intent and verified upload/prompt prerequisites. Success from the old runner means the action executed, **not that the job completed**: all attachment/submission/output verification remains mandatory. Never automate interaction inside a CAPTCHA challenge. Optional highlight-only inspection uses the existing no-click helper.

## Existing regression suites to protect

Found in the old repository; presence inspected, execution not claimed:

- `tests/test_cdp_events.py`
- `tests/unit/backend/test_cdp_client_transport.py`
- `tests/unit/bridge_safety/test_cdp_wire.py`
- `tests/integration/services/test_services_cdp.py`
- `tests/test_tab_matcher.py` (update expectations only for documented exact-match policy)
- `tests/test_find_click_visual.py`
- `tests/test_visual_click_contract.py`
- `tests/unit/backend/test_dom_highlight_contract.py`
- `tests/unit/backend/test_dom_highlight_probes.py`

Additional automated gates: two configured links/two existing targets; absent/ambiguous tab; case-sensitive path/query/fragment differences; discovery success but failed page round-trip; target navigation/disconnect; stale cached status; serialized retest during active job; reconnect with possibly submitted request; no command replay; no closing user Chrome; all endpoint/highlight fields preset round-trip; redacted unrelated tab metadata.

Manual gate: user launches the exact command above, opens two authorized image pages, connects and verifies both row statuses, runs sequentially while target assignment stays visible, changes highlight duration, closes/reopens one tab, restarts Chrome and observes safe rediscovery. Confirm UI settings/undo/layout/presets survive, and no second browser or new automatic tab appears.

## Plan consequences

- CDP, connection controls, rectangle implementation and their tests join the **KEEP/adapt** list.
- Keep required aiohttp/websockets dependencies; no Playwright replacement, auto-launcher or app-owned profile lifecycle in MVP.
- Retain dark workspace, global undo, layouts, all preset/template/variable systems unchanged in scope.
- Remove database and unrelated chat features only after retained dependencies are extracted safely.
- Research gaps for current Arena attachment/results/downloads still block adapter implementation. Proven old connection/click infrastructure does not establish new-site output correlation.
