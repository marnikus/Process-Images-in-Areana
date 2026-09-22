"""The browser's own process over the same DevTools socket (round 11, D-3).

`--start-debugger-server` sets `DevToolsServer.allowChromeProcess = true`
(`devtools/startup/DevToolsStartup.sys.mjs`), so the root actor exposes the **parent
process**, its descriptor answers `getTarget` exactly like a tab descriptor, and the
target form carries a console actor that runs in **chrome scope** — the only place
`Services` exists. That is what lets the app switch off its own permission dialog while
Firefox is running (`rdp.prefs.ask_to_stop`), and it is why this lives beside the tab
machinery instead of inside the tab path: same two requests, different actor.

A mixin (the `cdp.remote.RemoteMixin` pattern) because it is a capability layered on one
connection, not a second client: `RdpClient` owns the socket, the actor cache and the
request/response machinery this borrows.
"""

from __future__ import annotations

from typing import Any, Dict

from . import actors
from .wire import RdpError

CHROME_KEY = "chrome"        # actor-cache key for the browser's own process console
ASYNC_COMMAND = "evaluateJSAsync"
LEGACY_COMMAND = "evaluateJS"


class ChromeMixin:
    """Chrome-scope evaluation on a connection that is already open."""

    def chrome_eval(self, expression: str, timeout=None) -> dict:
        """Run JS in Firefox's own scope — `Services`, and therefore preferences."""
        console = self._actor_cache.get(CHROME_KEY) or self._resolve_chrome(timeout)
        return self._eval_on(console, expression, timeout)

    def _resolve_chrome(self, timeout) -> str:
        """`listProcesses` → the parent descriptor → its console actor (cached)."""
        descriptor = actors.parent_process(self._connection.request(
            {"to": "root", "type": "listProcesses"}, timeout))
        if not descriptor:
            raise RdpError("this Firefox does not expose its own process (no chrome scope)",
                           "protocol")
        return self._resolve_actor(descriptor, CHROME_KEY, timeout)

    def _resolve_actor(self, descriptor: str, key: str, timeout) -> str:
        """`getTarget` on a descriptor; `attach` when the form hides the console actor."""
        form = actors.target_form(self._connection.request(
            {"to": descriptor, "type": "getTarget"}, timeout))
        console = actors.console_actor_of(form)
        if not console:
            attached = self._connection.request({"to": descriptor, "type": "attach"}, timeout)
            console = actors.console_actor_of(actors.target_form(attached))
        self._actor_cache[key] = actors.require_actor(console)
        return self._actor_cache[key]

    def _eval_on(self, console: str, expression: str, timeout) -> dict:
        """One evaluation — the async command when this server knows it, else legacy.

        `requestTypes` answers which packet types the actor implements, is asked once per
        attach, and keeps this working on servers that predate `evaluateJSAsync`.
        """
        if self._async_known is None:
            names = actors.actor_types(self._connection.request(
                {"to": console, "type": "requestTypes"}, timeout))
            self._async_known = ASYNC_COMMAND in names
        command = ASYNC_COMMAND if self._async_known else LEGACY_COMMAND
        reply = self._connection.request({"to": console, "type": command,
                                          "text": str(expression)}, timeout)
        if not self._async_known:
            return reply
        return self._await_result(console, actors.result_id(reply), timeout)

    def _await_result(self, console: str, result_id: str, timeout) -> dict:
        """The `evaluationResult` event that answers an async evaluation."""
        if not result_id:
            raise RdpError(f"{console} answered without a resultID", "protocol")
        return self._connection.wait_for(lambda p: actors.result_matches(p, result_id), timeout)
