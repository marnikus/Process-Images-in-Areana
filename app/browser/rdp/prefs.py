"""Ask the running Firefox to stop showing the "Allow connection?" dialog (round 11, D-3).

`devtools.debugger.prompt-connection` is what makes Firefox ask
(`devtools/shared/security/auth.js`: read per incoming connection, so a change takes effect
at once and persists in `prefs.js`). Writing it is only possible from Firefox's own scope —
a page console cannot touch `Services` — but `--start-debugger-server` sets
`DevToolsServer.allowChromeProcess = true` (`devtools/startup/DevToolsStartup.sys.mjs`), so
the root actor exposes the parent process, its descriptor answers `getTarget`, and that
target form carries a **chrome** console actor (`window-global.js`). That is the actor this
module evaluates in — one expression, on the socket the app already has.

Two honest limits, both said out loud rather than hidden:

* a dialog that is already on screen can never be retracted — the first run on a fresh
  profile shows it once, and the user answers it once;
* a build that refuses the parent process (or a hardened configuration) simply cannot be
  told, and the answer names the manual fallback instead.

`Prepare Profile` (round 10) remains the way to have the pref true *before* Firefox starts.
"""

from __future__ import annotations

from typing import Tuple

from .wire import RdpError

PROMPT_PREF = "devtools.debugger.prompt-connection"
SUPPRESS_JS = f'Services.prefs.setBoolPref("{PROMPT_PREF}", false); "{PROMPT_PREF}=false"'
DONE = (f"told the running Firefox to stop asking for permission ({PROMPT_PREF}=false) — the "
        f"dialog will not come back")
NO_CHROME = ("could not reach Firefox's own process to switch the permission dialog off — click "
             "“Allow” once in the dialog (the app will not ask again while it stays connected), or "
             "run Prepare Profile while Firefox is closed and restart it")


def _reason(error: object) -> str:
    return f"{NO_CHROME} [{error}]"


def ask_to_stop(client, timeout: float) -> Tuple[bool, str]:
    """One chrome-scope evaluation: `(True, what happened)` or `(False, why not)`."""
    try:
        reply = client.chrome_eval(SUPPRESS_JS, timeout)
        value, err = client.value_of(reply, timeout)
    except RdpError as e:
        return False, _reason(e)
    except Exception as e:                      # a broken actor tree must not break the pass
        return False, _reason(e)
    if err:
        return False, _reason(err)
    if isinstance(value, str) and "=false" not in value:
        return False, _reason(value)
    return True, DONE
