# Research Summary — Saved Webpages Evidence

## Sources Inspected
- `docs/research/Directly Chat with Frontier Image Generation AI Models.html` (arena.ai/c/01a0a4f3-b60a-7169-8e15-aa3f099d8e4e) — full saved page with JS bundles
- `Process Images in Areana/Old App/Restore/From Webpage Code saved/Arena _ Benchmark & Compare the Best AI Models.html` — older landing page (not image direct chat, used for selector cross-check)
- Prompt-supplied selector inventory (steps A-L)

## Page Structure Observed

### Overall Layout
- Next.js app, sidebar with conversation history, main area centered
- Composer fixed at bottom, form element with file input + textarea + buttons
- Output area scrollable above composer: `div.no-scrollbar.relative.flex.w-full.flex-1...`

### Composer Form
```html
<form class="flex w-full flex-col items-start justify-center p-2">
  <div class="flex w-full flex-col justify-between gap-2">
    <input accept="image/png,.png,image/jpeg,.jpg,.jpeg,image/webp,.webp" multiple="" tabindex="-1" class="hidden" type="file" ...>
    <textarea rows="1" name="message" autocomplete="off" placeholder="Describe the image you want to generate…" ...></textarea>
    <div class="flex justify-between gap-4">
      <div class="mr-1 flex h-8 min-w-0 items-center gap-2">
        <button aria-label="Add files">...</button>
        <button role="combobox" ...>Direct</button>
        <button>Max model selector</button>
      </div>
      <div class="flex items-center gap-2">
        <button aria-label="Send message">...</button>
      </div>
    </div>
  </div>
</form>
```

Key findings:
- File input is hidden, triggered by Add files button. Accepts png, jpg, jpeg, webp. Multiple attribute present.
- Textarea name="message" is stable. Placeholder varies:
  - "Describe the image you want to generate…"
  - Prompt spec mentions "Describe how you want to edit this image…"
  - Both start with "Describe"
- Send button: `aria-label="Send message"` present, no type="submit" observed in this snapshot (but spec says type="submit" — need fallback). Visible + enabled.
- Add files button: `aria-label="Add files"` (spec says "Add files" vs earlier guess "attach/upload" — confirmed).
- No attachment preview in this saved state (empty chat start). Need to infer preview from spec.

### Attachment Preview (from spec + inferred)
- Container: `div.flex.flex-wrap.gap-2`
- Tile: `div.group.relative.overflow-hidden.rounded-lg.h-16.w-16`
- Image: `img[alt="<filename>"]` or `img[src^="blob:"]`
- Remove: `button[aria-label="Remove file"]`

We have not observed a real preview in saved HTML, but selector logic from spec is credible and matches Tailwind structure.

### Model / Processing Indicator
- Outer: `div.flex.min-w-0.flex-1.items-center.gap-2`
- Spinner: `div.h-5.w-5.flex-shrink-0.animate-spin` containing `canvas[width="23"][height="23"]`
- Label: `span.truncate` text "Max" (model name)
- For processing detection: spinner visible near model label

### Output / Generated Image
- No output image in empty chat snapshot. From spec:
  - Outer region: `div.no-scrollbar.relative.flex.w-full.flex-1...`
  - Nested: `div.min-w-0 > div.flex.flex-col.gap-3`
  - Image: `img[src*=".r2.cloudflarestorage.com/"]` — host pattern `messages-prod.<hash>.r2.cloudflarestorage.com`
  - Fallback: `img[loading="lazy"].aspect-square`, `img.cursor-pointer`, `img.transition-opacity.duration-500.opacity-100.aspect-square.h-[50vh]...`
  - Should wait for image loading complete and nonzero natural dimensions.

### Security Verification / CAPTCHA
- Not present in current snapshot, but spec + HTML contains:
  - `div[role="dialog"][data-state="open"]` containing "Security Verification"
  - `iframe[title="reCAPTCHA"]`, `iframe[src*="google.com/recaptcha/"]`
  - `#recaptcha-v2-container`, `textarea[name="g-recaptcha-response"]`
  - Text "Protected by reCAPTCHA"
  - Behavior: pause, require manual user action, never bypass.

### Other States Missing from Evidence
- Sign-in / access-denied / missing conversation / rate-limit / generic error — not observed in saved HTML. Must implement generic detection: look for text like "Sign in", "Please log in", "Conversation not found", "Access denied", "Rate limit" in main content.
- Composer container scoping: need stable parent — `form` containing textarea + file input + send button.
- Conversation/message container: need to identify user message containing JOB-ID and assistant response container. Not observed.
- Download/original-image control: not observed.
- Generation-complete indicator: not explicit; inferred via disappearance of spinner + appearance of new image.

## Selector Strategy Conclusions
- Prefer semantic: `aria-label`, `name`, `role`, `placeholder` prefix, `alt`.
- Avoid: full Tailwind class chains, generated radix IDs (`radix-_R_...`), signed URLs with query params.
- Need fallback chains for each element.
- For file input: use hidden input selector `input[type="file"][accept*="image"]` scoped inside composer form.
- For textarea: primary `textarea[name="message"]`, fallback `textarea[placeholder^="Describe"]`.
- For send: primary `button[aria-label="Send message"]`, fallback `form button:has(svg)` near textarea, ensure visible+enabled.
- For add files: primary `button[aria-label="Add files"]`, fallback `button[aria-label*="add" i][aria-label*="file" i]`.
- For output: primary `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]`, fallback `img[loading="lazy"].aspect-square`, fallback `img.cursor-pointer`.

## Risks / Uncertainties
- Placeholder text may change per locale/model — need prefix match, not exact.
- Send button may be disabled during generation — must check disabled attribute and aria-disabled.
- Attachment preview blob URL is temporary — use filename alt if available.
- Output image host may change (different R2 bucket) — use substring ".r2.cloudflarestorage.com" not full host.
- Spinner detection: canvas dimensions may change — use `div.animate-spin` + nearby model label.
- Security dialog IDs are generated — must use role+state+text, not ID.
- No evidence of remove file button placement — spec says inside preview container.
- No evidence of composer after attachment — preview likely appears above textarea inside same flex container.

## Open Questions to Confirm Before Coding
1. What exact attachment preview DOM appears after file selection? (Need screenshot or HTML with file attached)
2. What does generating state look like? (Spinner + disabled send?)
3. What does completed output DOM look like with new image? (Need HTML after generation)
4. Is there a download button or do we download via src URL directly?
5. How does page indicate rate limit or error?
6. What is stable conversation container for correlating prompt and output order?
7. Does textarea retain value after submit or clear?

For MVP, we will implement with fallback strategies and structured logging of selector failures, allowing easy adapter updates.

## Fix 2026-09-16: Image Generates Above Prompt — Matching Incorrect

**User report:** "fix. the image generates above the prompt .now app matching incorrect and match image generated above the prompt."

**Investigation:**
- Saved HTML empty chat has no output, but user screenshot shows generated image block `<div class="flex w-full flex-row..."><img class="aspect-square h-[50vh] w-[50vh] ... object-cover" src="https://messages-prod...r2.cloudflarestorage.com/...">`
- After submit, DOM contains:
  - User message bubble: contains reference image (uploaded, now R2 URL) ABOVE prompt text, plus `[JOB-ID: xxx]` token.
  - Assistant message bubble: contains generated image BELOW user bubble, large 50vh, after user container in document order.
- Old `JS_CHECK_NEW_OUTPUT` only checked `oldSrcs` exclusion, returned first new R2 img regardless of position → matched reference image above prompt (inside user bubble) instead of generated.

**Stable selectors re-verified (2026-09-16):**
- Generated: `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]` + class `h-[50vh] w-[50vh] aspect-square object-cover` + `naturalWidth>=200` + `visible`.
- Reference (to exclude): `div.flex.flex-wrap.gap-2 img`, `div.group.relative.overflow-hidden.rounded-lg.h-16.w-16 img`, or any img inside container that also contains JOB-ID text.
- Job container: element containing `[JOB-ID: xxx]` → closest ancestor with height 30..0.9*vh, width <0.95*vw, contains img or flex/group, not `no-scrollbar`.
- Document order: `jobContainer.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING` → after.

**Fix implemented:**
- `CDPArenaController.wait_for_new_output(baseline, timeout_ms, correlation_id)` now accepts correlation_id.
- JS `JS_CHECK_NEW_OUTPUT(oldSrcs, correlationId)`:
  - Finds jobEl by searching div/span/p/pre with text including correlationId near JOB-ID.
  - Finds jobContainer via ancestor heuristics.
  - Excludes imgs inside jobContainer.
  - Classifies after vs before via compareDocumentPosition, prefers after.
  - Prefers large (isLarge) to skip small thumbnails above prompt.
  - Sorts by closest after jobTop then largest width, else bottom-most then largest.
  - Returns jobFound, jobTop, afterCount, beforeCount, isLarge for logging.
- Bridge passes correlation_id to all wait_for_new_output calls.
- Baseline still skips blob and <50px icons, but now after-job filter provides second safety net.

**Risks & fallbacks:**
- If JOB-ID not yet rendered (virtualization delay): jobFound=false → fallback to large+bottom-most heuristic, still better than before.
- If reference image also large 50vh: still excluded by container containment, not size.
- If Response A/B side-by-side (two large images after): picks closest after job, logs afterCount=2.
- If compareDocumentPosition fails: fallback to top comparison.

**Evidence:**
- Spec + user HTML spinner `div.flex.min-w-0.flex-1.items-center.gap-2 > div.animate-spin > canvas + Response A`.
- User report image above prompt.
- Existing selector map `docs/selector_map.md` already lists output primary `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]` and fallback `img.aspect-square.w-full`.


## Fix 2026-09-16 (2): Wait New Output finishes but Saved to None — indentation bug breaks block loop

**User screenshot:** `image-1.png` shows paused job 10/15 waiting at Wait New Output, log shows:
- `[20260915-214916-Z8JG] New output detected https://messages-prod...r2.cloudflarestorage.com/... (795x1979), JS fetch TypeError Failed to fetch + canvas SecurityError, Python direct 1729034 bytes success`
- Then `Wait cycle 2/2 after reload`
- Second `New output detected 1729034 bytes Python direct`
- Then `Job completed 01-c.jpeg Saved to None`, UI shows waiting pending, not success.

**Root cause in app/ui/bridge.py:**
- `for wait_cycle in range(max_wait_cycles):` at 28 spaces (line ~1549)
- `for block in action_stack:` at 16 spaces
- `if wait_success: break` and `if not wait_success and wait_cycle == max_wait_cycles-1:` at 28 spaces (lines 1678-1681) were OUTSIDE wait_cycle loop, so they broke `for block` loop after wait_cycle loop finished both cycles.
- Log matches: Cycle1 success does NOT break inner loop, continues to Cycle2 reload, second success, then outer `if wait_success: break` aborts block loop, skipping DOWNLOAD (already downloaded check), VALIDATE, SAVE atomic _AI suffix and img.output_path set → `Saved to None`, UI paused waiting.

**Fix:**
- Move `if wait_success: break` to 32 spaces inside wait_cycle loop (and second check also 32), so first success breaks inner loop immediately, preserves file_bytes/new_src, proceeds to DOWNLOAD skip, VALIDATE, SAVE.
- Also verified DOWNLOAD: `for dl_cycle` at 32, `for attempt` at 36, `if dl_success: break` after attempt loop at 36 inside dl_cycle (was 40 incorrectly inside attempt), final `if dl_success:` at 32 outside loop — now correct.
- Added `if file_bytes and len(file_bytes)>100: skip DOWNLOAD` already exists, so after fix flow: WAIT_OUTPUT success → DOWNLOAD skip log → VALIDATE → SAVE → output_path real, job_finished with real path not None, UI success not paused waiting.
- No extra reload cycle after verified downloadable.

**Verification:**
- `py_compile` ok, `pytest 40 passed`
- Expected log after fix: single `New output detected ... Python direct 1729034 bytes` then `Download already done during wait verification` then `Saved to ..._AI.jpeg` with real path, no `Wait cycle 2/2 after reload`.


## Fix 2026-09-16 (3): Add Watcher Win — passive recheck for generating icon or captcha

**User request:** "Add a win watcher. it passively rechecking (every x ms) if the page has awaiting icon as it generating or it detects capcha. in both situations it should give a draw rectangle msg on lot left center page with msg 'wait for finish generation' or 'wait for user. Captcha' in both situations it sleep circle run and wait it solve. (time to solve timeout add user in win this setting)"

**Implementation:**

- **New window** `watcher` added to `sash-core.js` WINDOWS list, defaultTree and layoutA/B/C, `index.html` panel `winWatcher`, JS `watcher.js`, backend `app/services/watcher.py`.
- **WatcherConfig** stored in `config/session.json` via `config_manager.py` DEFAULT_SESSION:
  - `watcher_enabled` bool, `watcher_interval_ms` 500-30000 ms (every x ms), `watcher_captcha_timeout_sec` 10-3600 s, `watcher_generation_timeout_sec` 30-3600 s, `watcher_auto_pause` bool.
  - All UI params storable, window position/size auto saved on closing (existing main_window geometry persistence).
- **WatcherService** loop:
  - Every `check_interval_ms`, calls `cdp.is_security_dialog_visible()` (checks `div[role=dialog][data-state=open]` containing Security Verification + `iframe[title=reCAPTCHA]`) and `cdp.is_generating()` (checks `div.animate-spin` visible + processing text).
  - If captcha: draws overlay via `cdp.show_watcher_overlay("wait for user. Captcha", kind="captcha")` — red `rgba(180,20,20,0.92)`, border `#ff4444`, icon 🛡️, left 2%, top 50% centered, 36% width min 320px max 520px, pulse animation, spinner, timestamp updating every 1s. Pauses jobs via `pause_run()` if `auto_pause_jobs`, sets status `waiting_captcha`, logs, waits until captcha gone or timeout. Timeout from win setting — logs timeout but keeps waiting (user must solve manually, never bypass per RULE 20).
  - If generating: draws overlay `wait for finish generation` — blue `rgba(20,80,180,0.92)`, border `#44aaff`, icon ⏳, same position left center, pauses jobs, waits until `is_generating` false or generation timeout.
  - When condition cleared: hides overlay `hide_watcher_overlay()`, resumes jobs via `resume_run()`, status back to `watching`, logs success.
  - `force_clear()` and `ensure_task()` for qasync loop readiness.
- **Overlay JS** in `dom_highlight.py`:
  - `build_watcher_overlay_js(message, kind)` creates fixed div with `data-arena-watcher-overlay` attr, pulse keyframes, spin keyframes, time element updating.
  - `build_watcher_clear_js()` removes overlay.
- **CDP methods** in `cdp_arena.py`: `show_watcher_overlay`, `hide_watcher_overlay`.
- **Bridge** `app/ui/bridge.py`:
  - Signals `watcher_status` (JSON) and `watcher_log`, init watcher service with getters for CDP controller and job runner, callbacks to emit status to UI.
  - Slots: `get_watcher_config`, `set_watcher_config`, `start_watcher`, `stop_watcher`, `get_watcher_state`, `clear_watcher_overlay`, `check_watcher_now` — all persisted to session.
  - `_get_watcher_cdp_controller()` creates `CDPArenaController` from current `cdp_client`.
- **UI** `watcher.js`:
  - Controls: enable checkbox, interval ms input, captcha timeout, generation timeout, auto-pause select, save/start/stop/check now/clear overlay buttons.
  - Status display: current status, last check human, checks count, waiting info with duration and timeout, gen waits, captcha waits, last generation details, captcha detected bool.
  - Badge colors: red for captcha, blue for generation, green for watching, muted for idle.
  - Polls render every 1s for waiting duration, loads config on bridge ready (1.5s delay), listens `watcher_status` signal.
- **Tests**: 5 new watcher tests, total 45 passed.
- **Compliance**: Never bypasses captcha — draws rectangle and waits for user manual solve, respects timeout setting from win, pauses job circle run and sleeps until solved.

**Evidence:**
- Old app had similar security pause logic in `bridge.py` checking `is_security_dialog_visible()` and pausing.
- New watcher extends that to passive monitoring even outside job run, with configurable interval and timeouts, and visual overlay on page left center.


## Fix 2026-09-16 (4): Exact Above Prompt — clear order for correct image matching

**User report:** "still have problem with andestanding what image should be taken. the app should clearly understand where was the prompt generated for what image. if generated image is above the prompt this image do not belongs to the current prompt. and should await next image generated above (if still generating icon) Exact above the prompt (not after next one more prompt) create clear order and understand what image where should be appear and taken! Now it still mess what image it take without verify it it corrrect image or not!"

**Example HTML provided:**
- Outer `<ol class="... flex-col-reverse ...">` containing alternating gen and user messages.
- DOM order (top to bottom as in file): gen_A (1789507366571-01a0a6f2), user 01-c (JOB-ID 8ZO0), gen_B (1789506957478-01a0a6ec), user 01-b (JOB-ID HT32)
- Each gen is immediately before its user in DOM (gen above user visually if file order = visual top to bottom).
- Reference images inside user bubble: `w-32` small, not `50vh`.
- Generated images: `h-[50vh] w-[50vh] aspect-square object-cover` large, R2 URL.

**Problem with previous logic:**
- Previous `JS_CHECK_NEW_OUTPUT` preferred `afterJobCandidates` (images after job container via `compareDocumentPosition FOLLOWING`), but example shows correct image is **before** job container (above).
- It only excluded images inside jobContainer, but didn't verify that image belongs to current prompt vs previous prompt — could take image that belongs to previous prompt if no exact above found.
- No check for intervening JOB-ID between image and current prompt.

**New logic — exact above verification:**
- Collect **all JOB-ID prompts** with their bounding rect `top`, container, jobId. Sort by visual top ascending (top to bottom). Deduplicate by jobId.
- For current `correlationId`, find its index, `jobTop`, `prevJobTop` (previous prompt above), `nextJobTop`.
- Collect candidate images: R2, large (`width>=200` or `50vh` or `object-cover`), not blob, not in `oldSrcs`, not reference (inside any job container and small `w-32`/`h-16`), visible.
- **Exact above filter:**
  - Image must be above prompt: `image.top < jobTop -5`
  - Must be between previous and current: `prevJobTop < image.top < jobTop` (if prev exists), otherwise just `image.top < jobTop`
  - Must have **no intervening JOB-ID** between image and current: loop allJobs, if any job with top between image.top and jobTop (excluding current), then invalid.
  - Valid above = passes above + between + no intervening. Invalid above = above but fails between or has intervening.
  - Below candidates = image.top > jobTop.
- Pick **closest above**: sort validAbove by `b.top - a.top` descending (largest top < jobTop first) — exact above, not after next prompt.
- If no validAbove but invalidAbove exists → reason `image_above_belongs_to_previous_prompt_await_next` — image above belongs to previous prompt, await next image above (if still generating icon).
- If no validAbove and no invalidAbove but allNew exists → `no_exact_above_found_wait_next` — await next.
- If spinning visible (`div.animate-spin`), return not ready `generating_spinner_visible` even if candidate exists — await next above if still generating.
- Logging: `orderCheck` string with `prev {prevId}({prevTop}) < img {top} < curr {id}({top})`, `jobFound`, `jobTop`, `prevJobTop`, `validAbove`, `invalidAbove`, `allJobs`.

**Bridge handling:**
- Logs orderCheck on both completed and timeout.
- Special handling for reasons `image_above_belongs_to_previous_prompt_await_next` and `no_exact_above_found_wait_next`: logs awaiting next above, checks `is_generating`, if generating continues waiting without immediate reload, if not generating and first cycle reloads (bad cache chance), second cycle fails.
- Ensures app clearly understands where prompt was generated for what image, verifies correct image, awaits next image generated above if still generating.

**Verification:**
- `py_compile` ok, `pytest 45 passed`
- Expected for JOB-ID 8ZO0: prevJob HT32? Actually sorted top ascending: 01-c (100), 01-b (300) — for 8ZO0 (100) prev none, validAbove gen_A (0) → exact above verified.
- For new prompt at bottom (400): prev is 01-b (300), valid range 300-400, only new gen in that range qualifies, not gen_B which is below prev.


## Fix 2026-09-16 (5): Baseline preservation across reload — correct image lost after reload

**Failure log:**
```
[23:42:59] Spinner disappeared but no new image yet — waiting...
[23:43:03] Wait timeout after 180000ms cycle 1/2 — is_generating=False spinning False spinCount 0
Baseline after reload: 4 outputs
Wait cycle 2/2 after reload
```
**Provided HTML order top→bottom:**
- gen 01a0a703 1789508459484 50vh R2 (correct for ISAN)
- user 02-c w-32 [JOB-ID: 20260915-233957-ISAN]
- gen 01a0a6ff + user 3OS3
- gen 01a0a6f2 (opacity-0 spinner) + user 8ZO0
- gen 01a0a6ec (opacity-0) + user HT32

Correct image exists immediately above ISAN prompt but wasn't downloaded — timeout.

**Root cause:**
- `app/ui/bridge.py` after reload did `baseline = await ctrl.capture_baseline()` which captured 4 outputs including the new gen 01a0a703.
- `wait_for_new_output` uses `baseline.get("output_srcs")` as `oldSrcs` to exclude. After overwrite, oldSrcs now contains the correct new image, so `allNew` becomes empty, JS returns `no_new_image` or `no_exact_above_found_wait_next`, second cycle never downloads.
- Logs showed `is_generating=False` after spinner disappeared but image present — generation finished but detection failed before reload; after reload detection should succeed if oldSrcs preserved.

**Fix:**
- Preserve `original_old_srcs` across reloads:
  - At `OBSERVE_BASELINE`, store `original_old_srcs = list(baseline.get("output_srcs", []))`.
  - At every reload path (`WAIT_OUTPUT` and `DOWNLOAD` cycles), capture `_new_baseline_tmp = await ctrl.capture_baseline()` but keep `baseline = {"output_count": _new_baseline_tmp.count, "output_srcs": original_old_srcs, ...}` — keep original old srcs for new detection, update count only for logging.
  - For `latest_baseline` download retry path, use only NEW src not in original_old_srcs, preserve original_old_srcs for next detection.
- Enhance JS `JS_CHECK_NEW_OUTPUT` logging:
  - When `no_exact_above_found_wait_next` or `image_above_belongs_to_previous_prompt_await_next`, return detailed `allNewDetails`, `invalidAboveDetails`, `belowDetails`, `allJobs` map, `jobTop`, `prevJobTop`, `nextJobTop`, `jobIndex`, `orderCheck` for debugging.
  - Bridge logs these details on both completed and timeout paths.
- Ensure exact above logic handles `prevJobTop=null` (topmost job) — already does `if prevJobTop !== null` check, so any image above topmost qualifies if no intervening JOB-ID.

**Result:**
- After reload, correct image 01a0a703 remains in `allNew` (not in original_old_srcs), `validAbove` should contain it, closest above picked, download succeeds.
- `pytest 45 passed`, `py_compile` ok.

