# Firefox stealth attach via the DevTools RDP (2026-09-22)

Reimplementation of the Firefox connection. The previous attempt did not work;
this one is built on the one remoting channel that provably does not announce
itself to websites.

## The requirement

| Constraint | How this design meets it |
|---|---|
| Firefox launched **manually** by the user | the app never spawns a browser; `stealth.launch_command` only *renders* the command for a human to run |
| App **attaches** to the running browser | `RDPTransport.connect()` opens a TCP socket to the DevTools server |
| **Click-only** actions | `click_js` builds exactly three payloads: click, probe, signal-read |
| Detach/reattach, browser stays up | `close()` drops our socket; the process, profile and tabs are untouched |
| `navigator.webdriver` stays **false** | see below — verified in Firefox source |
| No geckodriver / Selenium / Playwright / Puppeteer | zero new dependencies; stdlib `asyncio` + `json` only |
| Real profile, extensions, history | `-P <profile>` names the user's own profile |
| No headless | `--headless` is in `FORBIDDEN_FLAGS` and fails preflight |

## Why the DevTools RDP, and not the obvious flag

`navigator.webdriver` is not a heuristic — it has one implementation, and it
reads exactly two sources (`dom/base/Navigator.cpp`, `Navigator::Webdriver`):

```cpp
bool Navigator::Webdriver() {
#ifdef ENABLE_WEBDRIVER
  nsCOMPtr<nsIMarionette> marionette = do_GetService(NS_MARIONETTE_CONTRACTID);
  if (marionette) { marionette->GetIsBrowserAutomationRunning(&isAutomation); ... }
  nsCOMPtr<nsIRemoteAgent> agent = do_GetService(NS_REMOTEAGENT_CONTRACTID);
  if (agent) { agent->GetIsBrowserAutomationRunning(&isAutomation); ... }
#endif
  return false;
}
```

So the property is true iff **Marionette** or the **Remote Agent** is running:

| Channel | Flag | `navigator.webdriver` | Verdict |
|---|---|---|---|
| Marionette / geckodriver / Selenium | `--marionette` | **true** | excluded |
| WebDriver BiDi / CDP | `--remote-debugging-port` | **true** | excluded (Bugzilla 1719505 bound the flag here deliberately) |
| **DevTools server** | **`--start-debugger-server`** | **false** | **used** |

The DevTools server is a third mechanism the property never consults. That is
the entire basis of this design, and `test_the_devtools_flag_is_not_treated_as_an_automation_signal`
pins it so nobody "simplifies" the launch command into a detectable one.

### Known gap, stated honestly

RDP still trips Firefox's **local** "under remote control" chrome hint — the
robot icon and striped URL bar, tooltip `(reason: DevTools)`. It is browser UI
only, **not** web-observable: no DOM, JS or network surface exposes it. Cosmetic
suppression if the operator wants it:

```css
/* chrome/userChrome.css, with toolkit.legacyUserProfileCustomizations.stylesheets=true */
#remote-control-box { display: none !important; }
#urlbar-background  { background-image: unset !important; }
```

Residential IP and profile age remain **environment** concerns. No client-side
protocol choice affects them; RDP neither helps nor harms there.

## Operator setup

```bash
firefox -P "daily" --start-debugger-server 6000      # Linux/macOS
firefox.exe -P "daily" -start-debugger-server 6000   # Windows: single dash
```

Profile prefs (`about:config` or `user.js`) — `stealth.required_prefs()`:

| Pref | Value | Why |
|---|---|---|
| `devtools.debugger.remote-enabled` | `true` | enables the server at all |
| `devtools.chrome.enabled` | `true` | lets the console actor evaluate |
| `devtools.debugger.prompt-connection` | `false` | no modal on every reattach |

Leave `devtools.debugger.force-local` at its default `true`: the port then binds
`127.0.0.1` only. With the prompt disabled, anything that can reach the port can
drive the browser — keep it off the network.

## Protocol facts that shaped the code

Three properties of this protocol cause silent, expensive bugs. Each is encoded
as a named function and pinned by a test.

1. **Frames are `<byte-length>:<json>`.** The prefix counts *bytes*. Firefox
   sends raw UTF-8 (a page title with an accent), so a character count
   truncates the frame and desyncs everything after it.
   → `framing.decode_packets`, `test_a_prefix_that_counted_characters_leaves_the_stream_desynced`.

2. **There are no request ids.** A reply carries only `from`. Correlating on
   `from` alone is wrong, because the same actor also pushes events — a
   `consoleAPICall` landing between request and reply gets read as the answer.
   The discriminator is *shape*: a direct response has **no** `type` key, an
   event always does.
   → `framing.is_reply_from`, `test_an_event_arriving_first_does_not_become_the_reply`.

3. **A timeout poisons the connection.** The server was never told we stopped
   listening, so the abandoned reply is still coming and would be returned as
   the *next* call's answer — a wrong result with no symptom. A timed-out call
   therefore closes the socket. Reconnecting is a cheap localhost connect.
   → `transport._fill`, `test_a_timeout_poisons_the_connection_instead_of_desyncing_it`.

Related: `evaluateJSAsync` answers **twice** — an immediate ack carrying
`resultID`, then a separate `evaluationResult` event with the value. Returning
the ack is the classic bug; `session.evaluate` waits for the matching event.

## Reconnect: actor ids are per-connection

Firefox hands out `server1.conn21.tabDescriptor7`. The `conn21` segment changes
on **every** attach, so a cached actor id is not merely stale — it addresses a
connection that no longer exists. Therefore:

* `attach()` clears the actor cache; every reconnect re-enumerates from `root`.
* `FirefoxTab` is a frozen value object (actor, title, url), not a live handle,
  so a pool may hold one across a detach without holding a dead reference.
* Memoisation of console actors is scoped to a single connection, never beyond.

→ `test_actor_ids_are_never_reused_across_a_reconnect` drives a full
detach/reattach and asserts the renumbered actor is picked up.

## Module layout (RULE 18)

| File | LOC | Owns |
|---|---:|---|
| `framing.py` | 88 | wire codec, reply-vs-event shape rules |
| `transport.py` | 128 | one socket, one in-flight request, attach/detach |
| `session.py` | 155 | actor tree, click / probe / signal verbs |
| `click_js.py` | 88 | in-page payloads (click-only scope) |
| `stealth.py` | 93 | launch constraints as data + preflight |
| `__init__.py` | 37 | public surface |

Six cohesive files, all leaves: no Qt, no services, no UI imports, zero new
third-party dependencies. `geckordp` was evaluated as a dependency and rejected
— it pulls a full actor framework for what is, at click-only scope, three
packet types.

## Verification

* 65 new tests, all against a **real socket** speaking the real protocol
  (`tests/rdp_fake_firefox.py`), not a mock of our own assumptions.
* Mutation-checked (RULE 8): matching replies by sender alone, and returning the
  ack instead of the `evaluationResult`, each fail the suite (8 failures).
* Quality gate: **0 fails**. Max CC 6 (preference ≤7). Vulture clean.
* Coverage: line 88.43 → **88.54**, branch 85.02 → **85.06**.

## Not built (out of the stated scope)

Typing, navigation, file upload, and pool/UI wiring. The scope given was
click-only attach; `RDPSession` is the seam those would extend.
