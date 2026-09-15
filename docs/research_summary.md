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

