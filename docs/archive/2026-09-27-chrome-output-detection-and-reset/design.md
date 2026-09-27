# Chrome job: finished image not detected, no page restart after a failure, log window (2026-09-27)

Owner report (with log and screenshot, 09:04–09:09):

1. **Log window.** Add a "Copy all" button that copies the whole log. Stop
   jumping to the bottom while the user has scrolled up, and follow again once
   they scroll back down.
2. **"Can not save generated image still."** The screenshot shows the image
   finished on the page: Direct mode, model "Max", the image with Edit / 👍 /
   👎 / ↻ / ⬇ under it. The log shows `✔ sent` at 09:04:32, then nothing from
   the wait for 4 minutes, then
   `✖ output_detected — Wait failed: Timeout after 120000ms`.
3. **"After failed page the restart of page and return to new chat was never
   happened."** The log ends at `🔍 FIND phase: searching New Chat`. In the
   screenshot (9:09:10) the old chat and our wait overlay are still on the page,
   28 s after the reset began.

## 1. Evidence

### E-1 The wait was blind, and the log could not say why

`output_wait` logs only these states: spinner visible or gone, no exact image
below the prompt, JOB-ID mismatch, and ready. These reasons log nothing:
`no_new`, `no_result`, `not_complete`, `zero_width`, `hidden`, `loading`, and a
thrown probe. The timeout error drops the last reason. So a 4-minute silence
means only "never saw a usable image". We cannot tell which case it was.

### E-2 Real arena DOM, run in real Chromium (153, headless)

`docs/research/Directly Chat…html` is a saved Direct-mode page from arena.ai.
It was saved mid-generation, with a user attachment `01-c.jpeg` and the model
"Max". I made fixtures from it:

* the `Generating image...` block replaced by a finished `<img>`, with an
  `https:`, `data:` or `blob:` src;
* the prompt replaced by `[JOB-ID: …]` plus 2 000 characters or more in one
  paragraph (the owner's prompt is that long);
* three sidebar chat titles set to `[JOB-ID: …]` (arena names chats after the
  prompt).

I then ran the production `JS_CHECK_NEW_OUTPUT_V3` against each fixture:

| Fixture (spinners removed = finished) | Result |
|---|---|
| https output | ready, correct image |
| data: output | ready, correct image |
| **blob: output** | **ready with `thumb.png` — the user's own attachment thumbnail**, logged "CORRECT KEY MATCH" |
| generating (saved page as-is) | spinner, but the candidate is `thumb.png` |

Root causes, each visible in the returned diagnostics:

* **R1 — `blob:` images are skipped outright.** This happens in both the
  selector pass and the all-images fallback. A blob output is invisible to the
  wait.
* **R2 — the user's attachment can become the "output".** The thumbnail sent
  with the prompt (`img.w-32`, 128 px shown, 1024 px natural) passes the size
  gate on its natural size. `isReferenceImage` protects only thumbnails inside
  a found job container. See R3.
* **R3 — JOB-ID anchoring is wrong on a real page.**
  * An element whose text is longer than 2 000 characters is skipped, so the
    owner's prompt bubble is never found.
  * The three JOB-IDs that *are* found are sidebar chat titles (`allJobs=3`,
    `jobTop=0`).
  * Sidebar spinners (`[data-sidebar]`) count as "generating", so another
    tab's running job would keep this tab waiting.

If arena now renders outputs as `blob:` (or the thumbnail is `blob:` too), the
owner gets exactly what the report shows: a silent timeout, or worse, the input
image saved as `_AI`.

### E-3 No restart path after a failed reset

`reset_to_new_chat` clicks New Chat through the visual runner and then waits
for a clean composer. If the click or the wait fails, `_finish_normal` logs
"cooling anyway", and the next job starts on the same dirty page. There,
`confirm_clean_start` tries New Chat again, fails again ("nothing sent, safe to
retry"), and the loop repeats with no page restart.

A page call that does not answer (`Runtime.evaluate` waits up to 30 s,
`_probe_json` retries 3×) stalls the reset with no log line. That matches the
28-second silence after `FIND phase`. The same stall pattern explains a
120-second wait that lasted 249 s.

### E-4 Not provable here

The live DOM of a *finished* Direct-mode image: the actual src scheme and
markup. Also why page calls stalled. Candidates:
* the Google Drive project folder (`config/cooldowns.json` threw WinError 5 at
  09:08:13), with synchronous writes on the app's event loop;
* a busy page.

The design therefore (a) fixes every root cause proven on the real saved DOM,
and (b) makes the next failure name its cause in the log.

## 2. Design

### D-1 Turn detector (`app/browser/turn_probe.py`, new)

One JS payload that finds *this job's* answer by the page's visual order.
Structure (reverse DOM order, class names) does not matter:

1. **Anchor.** The text node carrying `JOB-ID: <id>]`, visually lowest (the
   latest send), outside the chat chrome. Chat chrome = sidebar, nav, aside,
   header, form (site_adapter `chat_chrome`). A text node is used, not an
   element, so the 2 000-character prompt is found (fixes R3).
2. **Region.** From the anchor down to the next `[JOB-ID:` prompt below it,
   else the end of the page.
3. **Generating.** A visible spinner or a `Generating image` status inside the
   region only. Sidebar spinners never count (fixes R3).
4. **Output.** An `<img>` in the region shown at least 200×200 px on screen.
   Any src scheme counts: `https:`, `blob:` or `data:` (fixes R1).
   * Thumbnails shown under 200 px are never outputs. They are reported as
     `refs` (fixes R2).
   * Ready = `complete`, `naturalWidth > 0`, and opacity ≥ 0.5. When there are
     several, the largest wins.

It returns the same keys the wait already reads:
`ready / src / rect / width / height / spinning / associatedJobId /
expectedJobId`. Not-ready reasons:
* `turn_not_found`
* `turn_generating`
* `turn_no_image`
* `turn_image_loading`

### D-2 Poll order (`cdp_arena/output._poll_output_diag`)

* **Turn detector first.** If it answers `ready` or `generating`, that answer
  stands.
* **Otherwise the legacy v4 check.** Battle mode, layouts without a readable
  anchor, and the unit/golden fakes behave as today.
* **Thumbnail guard.** A legacy `ready` whose src is one of the turn's `refs`
  is refused (`thumbnail_rejected`). The input image can never be saved as the
  output.
* **`no_result` carries the page's reason** (`evaluate_failure`), e.g.
  "CDP command Runtime.evaluate timed out after 30s".

### D-3 Wait status line + timeout detail (`app/browser/output_wait_status.py`, new)

* **Status line.** One line when the check's plain-words status changes, and
  at most every 20 s while it doesn't:
  `⏳ Output check 34s/120s: no finished image in this job's answer yet (1 image loading) · poll 1.2s`.
  Slow polls (≥ 5 s) are always named.
* **Timeout detail.** The error becomes
  `Timeout after 120000ms — last check: <same words>`.

### D-4 New Chat → restart the page (`app/browser/page_restart.py`, new; `new_chat.py`)

`reset_to_new_chat` has two stages. Each is bounded, so a silent page can no
longer hang it:

1. **Click New Chat** through the visual runner (RULE 1) and wait for a clean
   composer. The whole stage is capped at `timeout_sec + 20 s`.
2. **Otherwise restart the page.**
   * `Page.navigate` goes to `<origin of the tab>` + `NEW_CHAT_PATH`. The
     origin comes from `Target.getTargetInfo`, which is answered by the browser
     even when the page is stuck. `NEW_CHAT_PATH` is the New Chat link's own
     href, `/image/direct`, from site_adapter. This is the same page the click
     opens, on the same user-authorized origin (RULE 20).
   * If the navigate fails, one `Page.handleJavaScriptDialog` accept clears a
     leave-page dialog, and the navigate is tried once more.
   * Then the same clean-composer wait.
   * Log: `🔄 New Chat did not open (<why>) — restarting the page: <url>`.

Every caller gets the restart: the post-job reset, the job-start clean check,
and tab Stop/Cancel.

### D-5 Log window (`log-console.js`, `index.html`, `main_window.py`)

* **Follow mode.** A new line scrolls to the bottom only while the view is at
  the bottom (8 px slack). Scrolling up pauses following, and a "⬇ N new" chip
  appears. Scrolling back down, or clicking the chip, resumes. Lines trimmed
  from the top while paused keep the view still.
* **Copy all.** Copies the whole session history, up to 5 000 lines, including
  lines already trimmed from the 500-line view. It tries
  `navigator.clipboard`, then falls back to `execCommand('copy')`. Qt:
  `JavascriptCanAccessClipboard` is on. No new bridge slot (the 135-slot
  contract stays).

### D-6 Save retry

`SAVE_TRIES` goes from 3 to 5 (0.5 / 1 / 1.5 / 2 s). Google Drive denies a
replace for about a second (WinError 5 at 09:08:13, recovered at 09:08:14).

## 3. Sizes (RULE 16/18/19)

| module | role | target |
|---|---|---|
| `browser/turn_probe.py` | D-1 payload (one JS literal, RULE 16.1.5) + builder + guard | ~170 lines |
| `browser/output_wait_status.py` | D-3 words + throttle | ~120 lines |
| `browser/page_restart.py` | D-4 tab url, navigate, dialog | ~90 lines |
| `browser/new_chat.py` | two-stage reset | +35 lines |
| `browser/cdp_arena/output.py` | poll order + timeout words | +15 lines |
| `ui/web/js/log-console.js` | follow + copy | ~150 lines, functions ≤ 13 lines (ratchet) |

Every new function: ≤ 20 lines, CC ≤ 10, nesting ≤ 4, ≤ 4 params. Rejected:
* patching the 739-line v4 payload in place — its stub tests lock the shape,
  and a second anchor model inside it would double the heuristics;
* a Qt clipboard slot — it would break the frozen slot contract.

## 4. Tests first

* `tests/js/test_turn_probe.mjs` — the real payload on a geometry stub:
  * anchor is the lowest transcript token; sidebar titles are ignored;
  * a 2 000+ character prompt is found;
  * `blob:` / `data:` / `https:` outputs are accepted;
  * a thumbnail is never an output;
  * an answer-region spinner or "Generating image" status means generating; a
    sidebar spinner does not;
  * the next prompt bounds the region;
  * loading and opacity 0 mean not ready.
* `tests/test_turn_poll.py` — poll order, thumbnail guard, `no_result` reason.
* `tests/test_output_wait_status.py` — words, throttle, slow poll, timeout
  detail.
* `tests/test_page_restart.py` + new-chat tests:
  * click fails → restart → clean;
  * restart fails → both reasons;
  * a stalled click stage is cut at its budget.
* `tests/js/test_log_console.mjs` — follow / pause / resume / chip / trim
  anchoring / copy text and fallback.
* **Real Chromium** (manual, recorded in §5): the D-1 payload on the saved-page
  fixtures above.

## 5. As built — real-Chromium record (2026-09-27)

Setup:
* Headless Chromium 153 (`@sparticuz/chromium` from the npm registry; kept outside the repo).
* Fixtures made from `docs/research/Directly Chat…html`, with the changes listed in §E-2. Scripts removed, relative `/image/direct`.
* The app's own `CDPClient` / `CDPArenaController`.
* The fixtures and scripts are not committed; they were built by hand as described here.

**Turn probe on the fixtures (`build_turn_js`):**

| Fixture | Result |
|---|---|
| saved page as-is (generating) | `turn_generating`; the thumbnail is in `refs` |
| https / data / blob output, spinners gone | ready: the 1024×1024 output, `refs` = the thumbnail |
| older job (its image above ours), ours generating | `turn_generating`, 0 candidates |
| same-id revival (old image above the latest prompt) | `turn_generating` on the latest prompt |
| sidebar spinner of another chat, ours done | ready (sidebar ignored) |
| output at opacity 0 | `turn_image_loading` |

**End to end.** `capture_baseline` → the send (prompt + thumbnail appear) → "Generating image…" → 6 s later a `blob:` output → `wait_for_new_output` → `download_image`:

| Code | What happened |
|---|---|
| before (60b20b4) | `completed` with **`thumb.png`, the user's attachment** (4 025 bytes), while the image was still generating. With the baseline taken after the send: "Spinner gone, scanning…" then `Timeout after 20000ms` (the owner's pattern). |
| after | `⏳ Output check 0s/20s: the image is still being generated (job prompt found, no large image under it)`, then at the blob's arrival `✅ New output verified … Turn probe: blob image 1024x1024`, then a page download of 5 337 bytes (PNG). |

**Page restart (`restart_to_new_chat`):**

| Page | Result |
|---|---|
| normal | at `/image/direct` in 1.0 s |
| leave-page dialog armed | 2.5 s (dialog accepted after the 1.5 s grace) |
| renderer in a 40 s busy loop | 17.5 s (navigate timed out, `Runtime.terminateExecution`, navigate) |

On the frozen page, `Runtime.evaluate` itself took the full 30 s. That is the silent-stall pattern.

**`reset_to_new_chat` with the real controller:**

| Case | Result |
|---|---|
| New Chat link missing | restart → `✔ New chat open — clean composer confirmed (after page restart: new chat ready)` in 1.0 s |
| link not clickable | 3 clicks refused, then restart → ✔ in 3.1 s |
| frozen page | click stage cut at 30 s (`timeout_sec` 10 + 20), then restart → ✔ in 52.6 s |

**Log window.** `log-console.js` + `layout.css` in Chromium:
* follow while at the end;
* scroll up: the view stays on the line being read while 400 lines arrive ("⬇ 400 new"); nothing on screen is trimmed while paused;
* back at the end: follows and trims to 500;
* chip click: jumps and follows;
* a real mouse click on **Copy all** put all 722 lines (from line 0, including lines trimmed from the screen) on the clipboard; the button shows "Copied ✓".

**Gates:**
* pytest: 2 677 passed / 6 skipped (xdist);
* JS: 454 pass (26 new);
* `verify_quality.py`: only the 5 fails that are identical on a clean HEAD worktree (uivision `desktop` / `mozlz4` / `runner`, `captcha.js`, `firefox-auto.js` — untouched); coverage ratchet green, cognitive checked.
* New modules: `turn_probe.py` 150 lines, `output_wait_status.py` 98, `page_restart.py` 95. Every new function is ≤ 20 LOC, CC ≤ 7, nesting ≤ 3, ≤ 4 params. `wait_for_new_output_with_spec` went from 23 to 19 LOC.

**Found on the way and fixed.** `CDPTransport.send` popped `self._cmd_id` (the newest command) on a timeout. A concurrent command then lost its entry, its reply was dropped, and it hung to its own timeout. `send` now pops its own id in `finally` (timeout or cancel).

**Still not provable here:** the live markup of a finished Direct image on arena.ai. The turn probe does not depend on it: it only needs our `[JOB-ID]` text, visual order, and an `<img>` shown large. If the live page still defeats it, the new status line and the timeout text name the exact state (prompt found or not, image count / scheme / size / loading, or the page's own error).
