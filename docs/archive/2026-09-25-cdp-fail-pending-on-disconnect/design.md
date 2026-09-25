# Design — CDP commands must fail fast when the connection dies (2026-09-25)

**Status:** implemented 2026-09-25
**Entry:** SYSTEM_OF_RECORD.md → CDP transport (B8 `last_error_kind` contract unchanged)
**Owner report (entry):**

```
evaluate transport error: TimeoutError: CDP command Runtime.evaluate timed out after 30s
CDP receive error ws://127.0.0.1:9223/devtools/page/…: no close frame received or sent (ConnectionClosedError)
CDP disconnected (was connected) ws://127.0.0.1:9223/devtools/page/…
evaluate transport error: TimeoutError: CDP command Runtime.evaluate timed out after 30s
```

## 1. What the log proves

1. First `Runtime.evaluate` burned its full 30 s and reported a misleading
   **TimeoutError** — the socket was dead the whole time (Chrome dropped the
   page without a close frame); a timeout says "slow", the truth was "gone".
2. **After `CDP disconnected` was already logged, the next evaluate burned
   another 30 s** instead of failing at once.
3. Root causes in `app/browser/cdp/transport.py` (all one defect class —
   *the pending-command lifecycle ignores connection death*):
   * `_receive_loop`'s `finally` sets `_connected = False` but leaves
     `_pending` futures unresolved (each waiter still serves its full
     `wait_for` timeout) and leaves `_ws` set (the `if not self._ws` guard in
     `send()` passes → a send on a dying/black-holed socket succeeds into the
     kernel buffer → nobody is reading replies → guaranteed 30 s timeout);
   * `disconnect()` does `self._pending.clear()` — **drops** the futures
     without resolving them (same full-timeout wait for every in-flight
     command);
   * `send()` never pops the pending entry when `ws.send()` itself raises
     (leak until some later teardown).

## 2. Decisions

* **`_fail_pending(reason)`** — the one owner of pending teardown: every
  unresolved future gets `ConnectionError(reason)` (callers are always
  awaiting, so the exception is retrieved), the dict is swapped out. Used by
  `disconnect()` ("CDP disconnected") and by the receive loop's `finally`
  ("CDP connection lost").
* **Receive-loop `finally` also detaches `_ws = None`** → every later
  `send()` fails in milliseconds with `ConnectionError("CDP not connected")`
  — the observed second 30 s timeout disappears. `disconnect()` detaches
  `_ws` *before* cancelling the task so the explicit `ws.close()` still runs.
* **`send()`** guards on `both _ws and _connected`, and pops the pending
  entry if `ws.send()` raises (no leak).
* **Honesty kept:** a genuinely unanswered command on a live socket still
  times out at `timeout` with `TimeoutError` (unchanged, still pinned);
  `evaluate()` keeps returning `None` + `last_error_kind = "transport"`, now
  with `ConnectionError: CDP connection lost` text instead of a fake timeout.
* Receive-loop body extracted: the error-formatting block moves to
  `_receive_error(e)` so `_receive_loop` (file floor `max_func_loc = 28`)
  does not grow when the `finally` gains two lines.

## 3. Tests first (red)

`tests/test_cdp_transport_paths.py` (existing dead-socket fixtures):
1. receive-loop death → an in-flight pending future raises `ConnectionError`
   **within the test's own short wait** (was: full timeout → TimeoutError);
2. after loop death `send()` raises `ConnectionError` fast (was: AttributeError
   / 30 s TimeoutError);
3. `disconnect()` fails pending with `ConnectionError` (was: silent `.clear()`);
4. live socket, unanswered command → still `TimeoutError` (pinned existing).

## 4. Structure (RULE 16/18)

Zero-tolerance ratchets forced the helpers **module-level** (two method
additions blew `max_methods` 9→18; the class body blew `max_class_loc`
120→144) — the file's existing `_note_eval_error` pattern, and
`CDPClient.disconnect` already delegates to `CDPTransport.disconnect`.

| symbol | now → target | limit |
|---|---|---|
| `CDPTransport` class body | 120 → **116** (ratchets clean: class_loc 116 ≤ 120, methods back to baseline) | zero-tolerance growth |
| `_receive_loop` | 28 → **24** (extracted) | file floor was 28 |
| `_fail_pending` (module, new) | — → 11 (docstring lines count) | ≤20 new symbol |
| `_receive_error` (module, new) | — → 7 | ≤20 new symbol |
| `_receive_teardown` (module, new) | — → ~9 | ≤20 new symbol |
| `_send_payload` (module, new) | — → ~6 | ≤20 new symbol |
| `disconnect` | 17 → 17 | breach only >20 |
| `send` | 14 → 16 (walrus guard, one `_send_payload` call) | breach only >20 |

Coverage floor 92.7 % for `transport.py` — every new line is exercised by the
tests above.
