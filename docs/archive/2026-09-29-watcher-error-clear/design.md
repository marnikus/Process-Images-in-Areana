# Fix: Watcher overlay not cleared consistently on page error "Something went wrong"

## Bug
Screenshot shows blue overlay "WAIT FOR FINISH GENERATION" with 54s elapsed, timeout 188s, 126s left, and below error banner "Something went wrong while generating the response. Please try again. Trace ID: ..."

User reports: When error detected, one page closed the watcher warning another dont. Expecting same behaviour on both pages.

Logs: both tabs have same error, but watcher cleared for one, not for other.

## Root cause
Watcher loop checks:
1. captcha -> if captcha, pause
2. generation (is_generating checks spinner) -> if generating, show overlay
3. clear -> if not captcha and not generating, clear overlay and resume

When page error "Something went wrong" appears:
- Spinner may disappear in one tab (generation false) -> watcher clears overlay
- Spinner may still be visible in another tab (generation true) -> watcher keeps overlay, even though job has failed with page error

Page error detection is done in job runner (output.py) which fails job and hides its own overlay, but watcher overlay is separate and remains if spinner still visible.

Expected: When page error detected, watcher should clear overlay and resume jobs consistently, regardless of spinner state.

## Desired behavior
- When page error "Something went wrong" or "Trace ID" detected, watcher should treat generation as finished, clear overlay, resume jobs
- Same behaviour on both tabs

## Design
- Add `check_page_error` to `WatcherCDP`: calls `cdp.scan_page_errors()` and checks for "something went wrong" or "trace id" (case-insensitive)
- In `WatcherLoop.check_once()`, check page error after captcha check, before generation check:
  - If page error detected, log "Watcher: page error detected, clearing generation wait", hide overlay, resume jobs, clear waiting state
  - Return early, similar to clear handling
- Keep generation handling unchanged for normal case
- Add `handle_page_error` to `WatcherHandlers` that clears overlay

Code shape:
- `watcher_pkg/cdp.py`: new method `check_page_error` ≤10 LOC, CC ≤3
- `watcher_pkg/handlers.py`: new method `handle_page_error` ≤15 LOC
- `watcher_pkg/loop.py`: call check_page_error and handle, ≤20 LOC

Quality:
- File sizes ideal 150-300, functions ≤20
- Tests: watcher tests should still pass

## Risks
- Page error scan may be expensive, but it's already used in job runner, and watcher interval is 500ms-2000ms, so okay
- Must not clear captcha wait when page error, only generation wait

## Acceptance
- Both tabs clear watcher overlay when "Something went wrong" appears
- Jobs resume consistently
