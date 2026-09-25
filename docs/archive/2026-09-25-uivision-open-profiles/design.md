# Design — only open Firefox profiles run (lockfile liveness) + JS boot guards

Date: 2026-09-25 · Owner reports: *"app find all profiles: fix — find only open
profiles right now, not all existing and saved in Firefox"* + a screen error
`Uncaught TypeError: fn is not a function`.

## Only open profiles (the fix)

A closed profile's sessionstore keeps its LAST session's tabs, so reading
every profile invented runs for windows that don't exist (stale matches, aimed
deliveries to nowhere). New `locks.py` (~80 lines) asks the lockfile Firefox
itself holds in each RUNNING profile's dir:

* Windows: `parent.lock` exists AND is held open — a crash leaves it
  stale-but-openable, so the check opens it for write: `PermissionError`
  (sharing violation) ⟺ live, anything else ⟺ closed.
* POSIX: the `lock`/`parent.lock` symlink to `IP:+PID` — live ⟺ the PID
  answers `os.kill(pid, 0)` (`PermissionError` = alive, another user's;
  `ProcessLookupError`/malformed = stale ⟺ closed).

`is_running` never raises (every refusal answers "closed", the tabs.py RULE 8
pattern); the Windows opener is injectable and both OS branches are unit-tested
on Linux (real symlinks, a fake sharing violation, a dispatched platform).

Wiring: `tabs.profile_sessions()` and `tabs.addon_seen()` filter the DEFAULT
enumeration through `locks.running()`; EXPLICIT dir lists read as given (the
caller's responsibility — the test seam, documented on the new `_session_dirs`
single source). Every prod caller uses the default (runner detect + rescan,
`profiles.list_profiles` — the on-screen list the owner quoted, the global
addon check), so closed profiles vanish from matches, deliveries, and the UI
at once. The skip stays visible (RULE 4): detect prints one info line,
`closed profile(s) skipped (only open profiles run): …`, via `locks.closed()`.
Side effect, verified by the gate: the `_session_dirs` split shrank tabs.py's
maxima back under the stale baseline (two pre-existing size ratchets cleared).

## `fn is not a function` (audit + hardening)

Exhaustive audit of all 107 app JS files: every bare `fn(...)` call site is
guarded (`typeof`/`!fn` checks), fed only function literals by all known
callers, or try/caught — no unguarded site exists in our code, and the injected
page scripts call nothing named `fn`. The screen error therefore most plausibly
comes from a driven page's own script (or a trimmed stack) — forensics pending
from the owner (which screen, repeatable, full stack).

Done regardless: the last two unguarded `fn` entry points now refuse loudly
instead of throwing — `BridgeReady.ready()` and `Boot.onBridgeReady()` warn
(`[BridgeReady]/[Boot] … needs a function`) and return on a non-function, so
no current-or-future misuse can surface as `Uncaught TypeError: fn is not a
function` again. Pinned by node tests (a new `test_bridge_ready.mjs` harness +
a `test_boot.mjs` case; neither file is on the frozen list). If the owner's
stack points elsewhere, that becomes a follow-up with evidence.

## Follow-up (same day) — ErrorTrail forensics

The owner placed the startup `fn is not a function` in the app's own Live
Debug feed, with no stack. The widened audit (every bare-identifier call in
every panel `init`, every Qt-signal `connect`, every QWebChannel slot call on
the startup path) confirmed guarded call sites only — so the page now carries
**ErrorTrail**: `error`/`unhandledrejection` hooks installed at the top of
`bridge-ready.js` (the first app script) that print the full stack plus
file:line:col into the console AND the LogConsole feed. Next occurrence
self-explains; if none appears, the error came from a driven page's own
(minified) script, which the trap also rules out by absence. Published as
`BridgeReady.errorTrail` (no new window.X — the UI wiring contracts require
bare `typeof LogConsole` reads for lexical globals and IIFE-scoped consts to
stay private). `JobHistoryLimit.load` got a `typeof` guard one-liner on the
same sweep.

* RULE 18 note: `uivision/` is 18 modules (one cohesive feature — same reason);
  all new/edited code within absolute limits; the suite + gate numbers are in
  the commit message.
