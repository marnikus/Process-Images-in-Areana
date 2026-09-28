# Fix: CDP disconnect spam and grid_layout_changed noise

## Logs observed
```
js: grid_layout_changed {"v":9,"tree":... (listeners.js:70)   # spam every drag
CDP receive error ws://127.0.0.1:9223/...: no close frame received or sent
CDP disconnected (was connected) ...
evaluate transport error: ConnectionError: CDP not connected (x3)
Task was destroyed but it is pending! coro=CDPClient.disconnect() running at client.py:88
```

## Root causes
1. **grid_layout_changed** – `arena-app/listeners.js:_handleGridLayout` does `console.log('grid_layout_changed', payload.slice(0,100))`. JS console.log is forwarded to Python as `js: grid_layout_changed` INFO, spamming on every layout change (drag, resize). Should be quiet/debug only.

2. **CDP receive error spam** – `transport.py:_receive_loop` catches any exception and calls `_receive_error` which logs ERROR with traceback for every `ConnectionClosedError: no close frame`. When old tab closes (new_tab handover) or browser closes tab abruptly, this is expected. 3 clients on same tab → 3 errors. Should be INFO when it's a normal close (ConnectionClosedError, no close frame) and only ERROR for unexpected.

3. **evaluate transport error spam** – `_note_eval_error` logs WARNING for every evaluate returning None due to transport. After old tab closed, some background evaluations may still be attempted on disconnected client, logging 3 warnings. Should be DEBUG for transport ConnectionError during handover/close, or at least not spam.

4. **Task destroyed pending** – `main_window.py:_drop_browser_sockets` does `asyncio.ensure_future(cdp_client.disconnect())` at closeEvent without awaiting. `CDPTransport._disconnect` does `await receive_task` which may block, leaving disconnect() task pending when loop closes → "Task was destroyed but it is pending". Fix: make disconnect not await forever, use timeout, and make main_window try to await or shield.

## Decisions
- D1: `listeners.js` – change `console.log` to `console.debug` or remove; keep payload handling but no INFO log. This makes grid changes quiet, only visible in devtools debug, not forwarded as INFO.

- D2: `transport.py:_receive_error` – detect expected close errors: if exception is `ConnectionClosedError` or message contains "no close frame" or "ConnectionClosed", log at INFO level "CDP receive closed <url>" not ERROR, no traceback. Keep ERROR for unexpected.

- D3: `_note_eval_error` – if kind=="transport" and text contains "not connected" or "ConnectionError", log at DEBUG not WARNING, to avoid spam during tab close.

- D4: `_disconnect` – cancel receive_task then await with timeout 0.5s, not forever. If timeout, abandon task. This ensures disconnect() finishes quickly, no pending at exit.

- D5: `main_window.py:_drop_browser_sockets` – try to get running loop, if running create task and add done callback that suppresses exception; if not running, try run_until_complete with timeout. Or simply call `client._ws = None` synchronously to avoid pending task warning. Keep simple: try `asyncio.create_task` and if loop not running, ignore.

## Code shape (RULE 16/18)
- `listeners.js`: 1 line change, CC unchanged
- `transport.py`: 
  - `_is_expected_close(e)` helper ≤10 LOC, CC ≤3
  - `_receive_error` split to check expected → INFO else ERROR, ≤20 LOC, CC ≤5
  - `_disconnect` – add timeout handling, ≤20 LOC, CC ≤4
  - `_note_eval_error` – add quiet check for transport not connected → DEBUG, ≤15 LOC
- `main_window.py`: _drop_browser_sockets – add loop handling, ≤15 LOC

All functions ≤20 LOC ideal, file ≤300.

## Tests
- Existing `test_new_tab_handover` still green
- New test: `test_cdp_transport_expected_close_is_info_not_error` – mock ConnectionClosedError and assert log level INFO not ERROR (can check via caplog)
- Manual: run app, trigger new-tab handover, verify no ERROR spam, only INFO "CDP receive closed" and no evaluate warnings.

## Ideal sizes justification
- transport.py currently 287 lines, adding helpers keeps <300
- Helpers named by domain (expected close), not foo_part1
