# Workflow / State Diagram

## Text Visualization (from prompt, refined)

```
[00 START APPLICATION]
  |
  v
[01 LOAD SAVED CONFIGURATION + JOB HISTORY] — JSON file
  |
  v
[02 RESEARCH ALL SAVED WEBPAGES] — already done, selector map built
  |
  v
[03 USER ADDS EXACT WEBPAGE URL ROWS]
  |
  v
[04 VALIDATE + OPEN EACH ENABLED URL]
  |-- Invalid/unreachable/sign-in: mark unavailable
  |-- CAPTCHA/security: pause for manual
  v
[05 VERIFY PAGE IS READY] — attachment, textarea, send, output, no security dialog
  |-- Any NO: URL not ready, no jobs assigned
  v
[06 USER SELECTS ROOT FOLDER]
  |
  v
[07 RECURSIVELY DISCOVER SUPPORTED IMAGES]
  |-- Ignore *_AI outputs
  |-- Reconcile persisted completed/pending state
  v
[08 USER REVIEWS QUEUE + SELECTS/DESELECTS IMAGES]
  |
  v
[09 SELECT NEXT PENDING IMAGE] — if none, go to 21
  |
  v
[10 CREATE JOB + UNIQUE CORRELATION ID]
  |
  v
[11 ASSIGN READY URL + CAPTURE PRE-SUBMISSION BASELINE]
  |-- Record attachments, outputs, message order, URLs, timestamp
  v
[12 FIND ATTACHMENT CONTROL + ATTACH SOURCE IMAGE]
  |
  v
[13 VERIFY CORRECT ATTACHMENT PREVIEW]
  |-- Verified: continue
  |-- Not verified: retry safely, then fail/pause; never submit
  v
[14 BUILD FINAL PROMPT]
  |-- Prepend [JOB-ID: unique-id]
  v
[15 FIND TEXTAREA, INSERT PROMPT + READ IT BACK]
  |-- Exact match: continue
  |-- Mismatch: correct or fail
  v
[16 FIND SEND BUTTON + SUBMIT ONCE]
  |-- Confirm processing/loading state
  |-- Prevent duplicate submission
  v
[17 WAIT FOR RESULT OR REQUIRED USER ACTION]
  |-- CAPTCHA: pause, notify user, wait manual
  |-- Website error/timeout: bounded recovery
  v
[18 DETECT A NEW OUTPUT IMAGE]
  |-- Compare with Step 11 baseline
  |-- Confirm result follows current job
  |-- Uncertain: mark NEEDS REVIEW
  v
[19 DOWNLOAD + VALIDATE OUTPUT]
  |-- Confirm valid image bytes, format, dimensions, non-HTML
  v
[20 SAVE BESIDE SOURCE AS *_AI.ext]
  |-- Never overwrite source
  |-- Unique suffix if target exists
  |-- Persist output metadata + completed state
  |
  +--------------------------> Return to Step 09

[21 BATCH COMPLETE]
  |-- Show totals
  |-- Keep logs, allow retries
  v
[22 END]
```

## State Machine — Formal

### URL Row States
- UNCHECKED -> CHECKING -> READY
- CHECKING -> UNAVAILABLE, AUTH_REQUIRED, CAPTCHA_REQUIRED, UNSUPPORTED, ERROR
- Any -> UNCHECKED on retest
- DISABLED is manual flag, not a check status

### Image Item States
- PENDING (discovered, not yet selected? Actually selected pending)
- SELECTED (user included)
- DESELECTED (user excluded)
- PROCESSING (currently being processed)
- COMPLETED (output saved and verified)
- FAILED (error, retryable)
- SKIPPED (user skipped or filtered)
- NEEDS_REVIEW (output correlation uncertain)

Transitions:
- DISCOVERED -> PENDING (default)
- PENDING -> SELECTED / DESELECTED via user
- SELECTED -> PROCESSING when job starts
- PROCESSING -> COMPLETED, FAILED, NEEDS_REVIEW, SKIPPED (if source disappears)
- FAILED -> SELECTED on retry
- COMPLETED -> stays, but can be reset to SELECTED
- Any -> DESELECTED via user action (except PROCESSING which requires cancel)

### Job States
- CREATED
- BASELINE_CAPTURED
- ATTACHING
- ATTACHMENT_VERIFIED
- PROMPT_INSERTED
- PROMPT_VERIFIED
- SUBMITTED
- WAITING_GENERATION
- OUTPUT_DETECTED
- DOWNLOADING
- VALIDATING
- SAVING
- COMPLETED
- FAILED
- NEEDS_REVIEW
- PAUSED_USER_ACTION_REQUIRED
- INTERRUPTED (crash during active)

Transitions are linear forward with failure branches to FAILED or PAUSED. No backward jumps except retry creates new attempt.

### App Run States
- IDLE
- RUNNING (processing queue)
- PAUSED (user paused)
- STOPPING_AFTER_CURRENT (will go IDLE after current job)
- CANCELLING_CURRENT (abort current job, mark failed/interrupted)
- BATCH_COMPLETE
- ERROR (fatal)

## Step Contracts Detail

### 00 START
Init UI, persistence, browser controller, site adapter, scanner, logs. UI responsive, errors visible.

### 01 RESTORE STATE
Load URL rows, folder, prompt, image decisions, completed fingerprints, interrupted jobs. Never auto-resubmit interrupted.

- File: `config/presets.json` or `app_state.json`
- Contains: urls, folder path, prompt, settings, image states, job history
- On load, reconcile with filesystem: check if source files still exist, if output files exist, etc.
- Interrupted jobs: mark as INTERRUPTED, require user confirmation before retry.

### 02 RESEARCH
Already documented. If required control evidence missing, STOP and request saved page states. For MVP we have enough for primary flow, but missing preview and output HTML — we proceed with fallback strategies and logging.

### 03 CONFIGURE URLS
Preserve exact URL per row. Validate syntax (URL parse). Persist enabled state. Stable internal row ID.

### 04 OPEN AND CHECK URLS
Navigate via approved browser session (Playwright persistent context). Detect redirects (final URL != initial), auth, security dialogs, unavailable pages. On failure show exact status + required action.

Timeouts: configurable, default 30s for page load, 10s for selector checks.

### 05 PAGE READINESS GATE
Confirm attachment entry point, prompt input, send control, output observation. Failing URL gets no jobs.

Implementation: `site_adapter.is_ready(page)` returns (ready: bool, reasons: list)

### 06-08 BUILD QUEUE
Recursively scan, filter supported files (png, jpg, jpeg, webp — configurable), ignore generated outputs (default *_AI.*), reconcile history, display manual controls.

- Use `pathlib.rglob`
- Ignore: files ending with `_AI` before extension, case-insensitive
- Durable identifier: path + mtime + size, optionally hash (if enabled, slower)
- Detect added/removed/renamed/changed after initial scan via re-scan button
- Keep manual status across restarts

### 09-11 PREPARE ONE JOB
Choose one selected pending image, allocate one ready URL (round-robin), create unique job ID (timestamp + random hex), record page baseline before changing anything.

- Correlation ID format: `20260915-142530-A7F3` — date-time + 4 hex chars, unique per attempt
- Baseline: list of output img srcs, count, last message position, timestamp, current attachments count

### 12-13 ATTACH AND VERIFY
Activate researched attachment control/file input and supply image. New preview must appear in current input area and match intended file via filename and/or trusted upload metadata. On failure, remove incorrect attachment if safe and stop before submission.

- Playwright: `set_input_files` on hidden input
- Then wait for preview selector with timeout
- Verify alt or filename
- If fails, attempt to click remove and retry once, then fail

### 14-15 INSERT AND VERIFY PROMPT
Final format:
```
[JOB-ID: <unique correlation ID>]
<user's exact prompt>
```
Fill textarea, dispatch input/change events, read back value. Continue only when complete expected string appears exactly once.

- Use `fill` or `type` with verification
- Read back via `input_value()`
- If mismatch, clear and retry once

### 16 SUBMIT ONCE
Confirm prerequisites (attachment verified, prompt verified), click Send once, record time. Verify processing or new message state starts. Never click repeatedly without proving first click failed.

- Check send button enabled before click
- Click once
- Wait for: textarea cleared OR spinner appears OR new user message with JOB-ID appears
- If none within timeout, consider failed

### 17 WAIT SAFELY
Monitor processing, page errors, session expiry, security verification. Never bypass CAPTCHA. Pause for manual user completion, then confirm dialog gone and normal controls ready.

- Polling loop with timeout (default 180s for generation)
- Check every 1-2s for:
  - Security dialog -> pause
  - Error text
  - New output
  - Spinner disappearance
- On timeout: mark failed, log

### 18 CORRELATE NEW OUTPUT
Compare output elements with baseline using insertion, response order, timestamps, changed src, completion state. If ownership uncertain, mark Needs review.

- Must be new src not in baseline OR new DOM node
- Must appear after submission timestamp
- Must have loaded (naturalWidth >0)
- If multiple new images, pick latest or mark needs review

### 19-20 DOWNLOAD, VALIDATE, SAVE
Obtain highest-quality permitted image. Validate, write temp file, atomically rename to <source-base>_AI.<actual-extension>.

- Download via Playwright `request` or `fetch` in page context to preserve auth, or via `page.goto`? Better use `requests` with same cookies? Simplest: get src URL and download via browser's fetch (to include auth headers) or via Playwright's APIRequestContext with storage state.
- Validate: not HTML (check content-type and magic bytes), is supported image (png/jpg/webp), size >0, dimensions if possible
- Naming: same folder as source, base + "_AI" + ext (preserve downloaded format if practical, else source ext)
- Never overwrite source (different name ensures)
- If target exists and overwrite disabled, create unique name: `name_AI_2.png`, `name_AI_3.png`, etc.
- Write to temp file `*.partial` first, validate, then rename atomic

### 21-22 FINISH
Summarize outcomes, keep failed/needs-review actionable.

## Core Execution Rule
Always: observe baseline -> execute one action -> verify effect -> persist state -> advance. A successful click is never sufficient.

## Visual Highlight Requirement
- When clicking element, draw rect overlay above element for several seconds (user-configurable, default 2s)
- Implementation: inject JS that creates absolute positioned div with border, highlight color, animation, auto-remove after timeout
- Should not interfere with page layout or clicks
- Configurable: enable/disable, duration, color

## Persistence & Resume
- On startup, reconcile saved state with filesystem
- Active job during crash must not be blindly resubmitted: mark interrupted, inspect output folder, ask confirmation or safe recovery check
- All state changes persisted immediately after verification

## Error Handling
Explicit errors for each failure mode, with recovery actions. Retries bounded, logged, backoff. Never retry submission automatically when duplicate paid/rate-limited work risk.

## Observability
Structured logs with timestamp, job ID, URL row ID, image path, workflow state, attempt, result. User-friendly summaries without secrets. Optional sanitized screenshot on failure.
