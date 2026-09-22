# One connection per Firefox, not one per scan (2026-09-22, I-64)

Bug report: Firefox popped up

> **Incoming Connection** — An incoming request to permit remote debugging
> connection was detected. A remote client can take complete control over your
> browser! Client Endpoint: 127.0.0.1:59892 · Server Endpoint: 127.0.0.1:9224

…every second, forever.

## Root cause

Firefox prompts for **every incoming debugger connection it accepts**. So the
number of dialogs equals the number of connections the app opens.

`list_firefox_tabs` opened one and closed it on every call:

```python
session = RDPSession(RDPTransport(host=host, port=port, timeout=timeout))
await session.attach()          # ← a dialog, every time
try:
    return [...]
finally:
    await session.detach()
```

The URL reconciler calls that on a timer (`url_reconcile_interval_ms`, default
5 s, clamped as low as 500 ms). Connect → prompt → detach → connect → prompt,
indefinitely. The detach in the `finally` was well-intentioned — "leave the
browser as we found it" — but against a protocol that authorises per
*connection*, politeness became a popup storm.

## The fix, in two layers

### 1. Stop reconnecting (`rdp/session_cache.py`)

One attached `RDPSession` per `host:port`, held for the life of the process and
reused by every scan. A connection is opened only when there is none or the
previous one died.

Measured against the fake Firefox — 20 reconciler passes:

| | connections opened | dialogs shown |
|---|---:|---:|
| before | 20 | 20 |
| after | **1** | **1** |

`acquire` is serialised behind a lock, so two concurrent scans of one browser
cannot each open a link and show *two* dialogs. This is also more correct
protocol-wise: actor ids stay valid for the lifetime of the connection that
issued them, and it is precisely *new* connections that renumber them (I-62).

A cached link that dies between scans is retried exactly once — the case where
the browser genuinely went away — and if that retry also fails the caller hears
about it rather than seeing a silently empty tab list (RULE 4).

### 2. Tell the user how to remove it entirely (`rdp/prefs_help.py`)

Reuse reduces the dialog to **one per Firefox start**. Only the pref removes it:

```
about:config → devtools.debugger.prompt-connection = false → restart Firefox
```

`REQUIRED_PREFS` already listed it (I-62) but nothing ever *said* so at runtime.
The app now prints the instructions the first time it scans a Firefox endpoint —
once per endpoint per run, not per scan, because the fix for log spam must not
itself be log spam. `user_js_snippet()` renders a paste-ready `user.js`.

Nothing writes to the profile. Firefox rewrites `prefs.js` on exit and can
clobber external edits, so the app produces instructions and the human applies
them — consistent with "the user launches the browser, the app only attaches".

## Security note

That dialog is a real safeguard: anything reaching the port can drive the
browser. Turning it off is safe only because `devtools.debugger.force-local`
defaults to `true`, binding the port to `127.0.0.1`. Keep it that way.

## Files

| File | LOC | Owns |
|---|---:|---|
| `browser/rdp/session_cache.py` | 92 | one live session per endpoint, reconnect-on-death |
| `browser/rdp/prefs_help.py` | 48 | the prompt explanation + `user.js` snippet |
| `browser/rdp/discovery.py` | 92 | now scans over the shared session (+ one retry) |
| `services/browser_connect.py` | 77 | `log_firefox_hint`, once per endpoint |

## Verification

* **22 tests** for this change; the Firefox ones run against a real socket
  speaking the real protocol, and count *connections* because that is what the
  user experiences as dialogs.
* **Mutation-checked** (RULE 8): deleting the reuse branch — i.e. restoring the
  popup storm — fails 3 tests, including
  `test_repeated_scans_reuse_one_connection`.
* One test was **inverted on purpose**:
  `test_discovery_detaches_and_leaves_the_browser_running` asserted a fresh
  connection per scan, which is the defect itself. It is now
  `test_repeated_scans_reuse_one_connection`.
* pytest **2,152 passed** · JS **291** · gate **0 fails** · coverage
  **88.83 line / 85.39 branch** (up from 88.77/85.34); all three new/changed
  modules **100 %**.
* Also cleared pre-existing debt in the touched file: `browser_tabs.py`
  `max_func_loc` 21 → 19, so its long-standing ratchet fail is gone.

Pre-existing and unrelated: `test_quality_gate.py::test_40loc_js_function_fails`,
the 9 JS failures, and the 4 coverage-ratchet fails (all verified on a clean tree).
