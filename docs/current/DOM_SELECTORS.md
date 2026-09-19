# DOM Selector Reference — Arena.ai Image Generation (Verified from Saved HTML)

**Source files:**
- Saved HTML from `arena.ai` (empty chat, chat with messages — see `docs/research/`)
- Spec from `docs/selector_map.md` (detailed primary/fallbacks, evidence)
- Live verification via CDP `Runtime.evaluate` probes

All selectors below are **extracted from actual HTML** or verified via CDP. The target site is a React/Next.js app using Tailwind.

**Rule:** Prefer semantic selectors (RULE 21) — aria-label, name, type, placeholder, role — over generated IDs or long utility class chains. Every selector has primary + fallbacks, centralized in `app/browser/site_adapter.py`.

---

## A. Prompt Textarea — Primary Input

**Purpose:** User prompt + [JOB-ID] token insertion.

```html
<textarea name="message" autocomplete="off" rows="1" placeholder="Describe the image you want to generate…" data-gtm-form-interact-field-id="0"></textarea>
```

| Field | Value |
|---|---|
| **Primary** | `textarea[name="message"]` |
| **Strong combined** | `textarea[name="message"][autocomplete="off"]` |
| **Placeholder fallback 1** | `textarea[placeholder="Describe the image you want to generate…"]` |
| **Placeholder fallback 2** | `textarea[placeholder^="Describe how you want to edit"]` |
| **Placeholder fallback 3** | `textarea[placeholder^="Describe"]` |
| **Other attributes** | `textarea[rows="1"]`, `textarea[data-gtm-form-interact-field-id]` |
| **Scope** | Inside `form` that also contains file input and send button |
| **mustBeVisible** | true |
| **mustBeEnabled** | true, not readonly |
| **expectedCount** | 1 |
| **Verification** | After insertion, `textarea.value` equals expected prompt exactly; read back |
| **Evidence** | Confirmed in saved HTML line 74, direct observation |
| **Action Blocks** | `INSERT_PROMPT`, `VERIFY_PROMPT`, `HIGHLIGHT_PROMPT` |

**JavaScript probe (CDP):**

```javascript
(function(){
  const sel = 'textarea[name="message"]';
  const el = document.querySelector(sel);
  if (!el) return {found:false, tried:[sel]};
  const r = el.getBoundingClientRect();
  return {found:true, visible: !!(r.width||r.height), value: el.value.slice(0,100), rect: {x:r.left,y:r.top,width:r.width,height:r.height}};
})()
```

---

## B. Add / Attachment Control

**Purpose:** Trigger file chooser for image attachment.

| Field | Value |
|---|---|
| **Primary** | `button[aria-label="Add files"]` |
| **Fallback 1** | `button[aria-label*="add" i][aria-label*="file" i]` |
| **Fallback 2** | `button[aria-label*="attach" i]` |
| **Fallback 3** | `button[aria-label*="upload" i]` |
| **Underlying file input Primary** | `form input[type="file"][accept*="image"]` |
| **File input Fallback** | `input[type="file"]` |
| **Scope** | `form` that also contains `textarea[name="message"]` |
| **mustBeVisible** | true for button, false for input (hidden) |
| **mustBeEnabled** | true |
| **expectedCount** | 1 button, 1 input |
| **Verification** | After file set via `DOM.setFileInputFiles`, preview appears in `div.flex.flex-wrap.gap-2` with `img[alt="<filename>"]` or `img[src^="blob:"]` |
| **Evidence** | Confirmed in saved HTML: `<input accept="image/png,..." type="file" class="hidden">` and `<button aria-label="Add files">` |
| **Action Blocks** | `HIGHLIGHT_ATTACH`, `ATTACH_IMAGE` |
| **CDP Method** | `DOM.getDocument` → `DOM.querySelector` for input → `DOM.setFileInputFiles` with absolute path |

**Hierarchy (from saved HTML):**

```
form.flex.w-full.flex-col
  div.flex.flex-wrap.gap-2  ← attachment preview container (empty when no attachment)
  div.flex.justify-between
    button[aria-label="Add files"]  ← triggers file chooser
    textarea[name="message"]
    button[aria-label="Send message"]
  input[type="file"].hidden  ← actual file input, accept="image/png,image/jpeg,..."
```

---

## C. Attachment Preview — Verification

**Purpose:** Prove intended image was attached to current composer.

| Field | Value |
|---|---|
| **Container Primary** | `div.flex.flex-wrap.gap-2` |
| **Tile Primary** | `div.group.relative.overflow-hidden.rounded-lg.h-16.w-16` |
| **Image Primary** | `div.flex.flex-wrap.gap-2 img[alt="<expected filename>"]` (dynamic alt) |
| **Image Fallback 1** | `div.flex.flex-wrap.gap-2 img[src^="blob:"]` |
| **Image Fallback 2** | `div.flex.flex-wrap.gap-2 img[alt]` |
| **Scope** | Inside same `form` as textarea, above textarea |
| **mustBeVisible** | true |
| **expectedCount** | 1 per attached file (MVP single) |
| **Verification** | New visible img after upload, blob URL or filename match, inside active input area |
| **Evidence** | Spec provides; structure observed in JS bundles |

---

## D. Send / Submit Button

**Purpose:** Start generation (must be clicked once). User log 2026-09-16 shows primary `button[aria-label="Send message"]` matched 0 nodes when disabled (opacity-50 pointer-events-none), fallback `button:has(svg)` matched 32 nodes too generic → failed.

| Field | Value |
|---|---|
| **Primary** | `button[aria-label="Send message"]:not([disabled])` — must exclude disabled |
| **Fallback 1** | `form button[aria-label="Send message"]:not([disabled])` |
| **Fallback 2** | `form:has(textarea[name="message"]) button[aria-label="Send message"]:not([disabled])` |
| **Fallback 3** | `div.flex.items-center.gap-2 button[aria-label="Send message"]:not([disabled])` |
| **Fallback 4** | `button[type="button"][aria-label="Send message"]:not([disabled])` |
| **Fallback 5** | `form div.flex.items-center.gap-2 button:last-child:not([disabled])` |
| **Fallback 6** | `form button:has(svg):not([disabled])` — more specific than generic `button:has(svg)` which matched 32 nodes |
| **Fallback 7** | `button.inline-flex.h-8.w-8[aria-label="Send message"]` |
| **Fallback 8 (controller)** | `button[type="submit"][aria-label="Send message"]`, `form button[type="submit"]` — last resort via `CDPArenaController.submit()` |
| **Accessible query** | role=button, name="Send message" |
| **Scope** | Inside same `form` as textarea, in `div.flex.items-center.gap-2` (not just `flex.justify-between` — new UI uses gap-2) |
| **mustBeVisible** | true |
| **mustBeEnabled** | true (disabled has `disabled=""` + `opacity-50 pointer-events-none` class) — need to wait for disabled→enabled transition after prompt insertion, React enables button |
| **expectedCount** | 1 |
| **Verification** | After click, processing state starts: spinner `div.animate-spin` appears near `Response A/B` label OR textarea clears OR new user message appears in output region. Controller now waits 0.8s + polls up to 5s for enabled. |
| **Evidence** | Directly Chat HTML line 310k shows `<button disabled="" aria-label="Send message" class="... opacity-50 pointer-events-none">` — when empty prompt. After prompt, disabled removed. User log: primary matched 0 nodes, fallback 32 nodes → fix adds :not([disabled]) and more specific fallbacks, comma-separated list handling in Bridge. |
| **Action Blocks** | `HIGHLIGHT_SUBMIT`, `SUBMIT` — fallback_selector now comma-separated list, tried in order. |
| **Fix 2026-09-16** | Primary `:not([disabled])`, fallback list split by comma in Bridge, extra 0.8s delay + wait for enabled, multiple click dispatch methods (mousedown/mouseup/click) for React. |

---

## E. Output / Generated Image — Detection (Updated 2026-09-16 Fix: image above prompt)

**Bug reported:** "the image generates above the prompt .now app matching incorrect and match image generated above the prompt" — app was matching reference image (user's attached image) that appears above prompt text inside user bubble, instead of generated image after user message.

**Root cause analysis (research before implementation):**
- After submission, chat contains TWO new R2 images:
  1. User's reference image: uploaded to R2 (host `messages-prod.*.r2.cloudflarestorage.com`), displayed inside user message bubble ABOVE prompt text (thumbnail or large, inside same container as JOB-ID token).
  2. Assistant's generated image: also R2, displayed in assistant message bubble BELOW user message (after user container in DOM order, typically `aspect-square h-[50vh] w-[50vh] object-cover`).
- Old detection `JS_CHECK_NEW_OUTPUT(oldSrcs)` collected ANY new R2 src not in baseline, returned first found in DOM order. If user reference image appears first (above prompt text, inside user bubble), it was picked as "new output" → downloaded original instead of generated.
- Additionally, baseline might miss old images if selector drift, causing old image above prompt to be considered new.

**Fix — anchor after JOB-ID + exclude inside user container + prefer large:**
- `wait_for_new_output` now accepts `correlation_id` (JOB-ID token) and passes to JS.
- JS finds element containing correlationId (searches div/span/p/pre with text including `[JOB-ID: xxx]` or `JOB-ID: xxx` or just xxx near JOB-ID).
- Finds its container (closest message bubble) via heuristics: up to 8 ancestors, height 30..0.9*viewport, contains img or flex/group, not whole page (no-scrollbar).
- Excludes any candidate img that is INSIDE jobContainer (`jobContainer.contains(el)`) → skips user reference image above prompt text.
- Uses `compareDocumentPosition` to classify candidates as AFTER jobContainer (FOLLOWING) vs BEFORE. Prefers AFTER.
- Prefers large images: `isLarge = width>=200 || rect.width>=200 || class includes 50vh || object-cover || aspect-square`. Generated images are 50vh, user thumbnails are h-16 w-16 (<100px).
- Sorting:
  - If job anchored and after candidates exist: sort by closest after jobTop (smallest positive delta) then largest width.
  - Else: bottom-most (higher top) first as newest in chat, then larger width.
- Logs `jobFound`, `jobTop`, `afterCount`, `beforeCount`, `isLarge` for diagnostics.

**Stable selectors re-verified:**
- Generated image: `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]` + `h-[50vh] w-[50vh] aspect-square object-cover cursor-pointer` — large, visible, complete, naturalWidth>0.
- User reference image (to exclude): inside `div.flex.flex-wrap.gap-2` or `div.group.relative.overflow-hidden.rounded-lg.h-16.w-16` or same container as JOB-ID text, often smaller.
- User message container: contains JOB-ID text + optional img + prompt text, height < 80% viewport, width < 95% viewport.
- Assistant container: sibling after user container, contains large R2 img, no JOB-ID.

**Risks & fallbacks:**
- If JOB-ID not found (render delay or virtualization): fallback to old logic but still prefers large + bottom-most (newest). Logs jobFound=false.
- If compareDocumentPosition fails (shadow DOM): fallback to top comparison `elTop > jobTop+5`.
- If multiple large images after job (Response A/B side-by-side): picks closest after job, then largest width — user may need to handle both, but first is valid.
- If user reference image also large (e.g., 50vh): still excluded because inside jobContainer, not by size alone.
- If baseline incomplete: still works because after-job filter excludes old images above prompt (before job).

**Verification:**
- After insertion, prompt contains `[JOB-ID: xxx]` — visible in user bubble.
- Baseline captured before submit: `output_count` + `output_srcs`.
- After submit, spinner `div.animate-spin` appears near `Response A/B` label → generating.
- New output detection now returns `jobFound:true`, `afterCount>=1`, `isLarge:true`, `rect` with x,y,width,height.
- Download uses Python direct fallback for R2 presigned URLs (CORS bypass) + canvas fallback.

**Original section continues:**

## E. Output / Generated Image — Detection (Original)

**Purpose:** Detect genuinely new output image, not old one. User report 2026-09-16: image was created but download failed "Fetch failed {ok: False, 'error': 'TypeEr" — indicates fetch CORS issue, need canvas fallback.

| Field | Value |
|---|---|
| **Outer region Primary** | `div.no-scrollbar.relative.flex.w-full.flex-1.flex-col.overflow-x-auto` |
| **Candidate Primary** | `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]` |
| **Candidate Fallback 1** | `div.no-scrollbar img[src*="messages-prod."]` |
| **Fallback 2** | `div.no-scrollbar img[loading="lazy"].aspect-square` |
| **Fallback 3** | `img.aspect-square.cursor-pointer` |
| **Fallback 4** | `img.transition-opacity.duration-500.opacity-100.aspect-square` |
| **Fallback 5** | `div.flex img[src*=".r2.cloudflarestorage.com/"]` |
| **Fallback 6** | `main img[src*=".r2.cloudflarestorage.com/"]` |
| **Fallback 7** | `div.no-scrollbar img[src^="https://"]` |
| **Fallback 8** | `img.aspect-square.w-full` |
| **Fallback 9** | `img[src*=".r2.cloudflarestorage.com/"]` generic |
| **Scope** | Main scroll area above composer, but also `main` — new UI may have Response A/B columns each with images |
| **mustBeVisible** | true |
| **expectedCount** | 0..n (grows) |
| **Verification** | Baseline capture all matching nodes and src before submission (skip blob: and <50px icons) → after submission wait for spinner to appear (generating) → wait for spinner to disappear + new node not in baseline → confirm `complete && naturalWidth>0` → prefer highest resolution (largest naturalWidth) → download via fetch with credentials include + mode cors, fallback to canvas toDataURL if CORS tainted, retry 3x |
| **Evidence** | Spec; host pattern observed in JS bundles; not present in empty chat HTML; user report 2026-09-16 image created but download failed TypeError → fixed with canvas fallback |
| **Action Blocks** | `OBSERVE_BASELINE`, `WAIT_OUTPUT`, `DOWNLOAD` |
| **Fix 2026-09-16** | Baseline skips blob and tiny icons, includes spinner state; JS_CHECK_NEW_OUTPUT checks spinner (Response A/B) and returns spinning flag; wait_for_new_output logs spinner start and waits for disappearance; JS_DOWNLOAD_IMAGE tries fetch then canvas toDataURL fallback, retries 3x in Bridge. |

**Baseline capture probe:**

```javascript
(function(){
  const sel = 'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"], div.no-scrollbar img[loading="lazy"]';
  const nodes = Array.from(document.querySelectorAll(sel));
  return {
    output_count: nodes.length,
    srcs: nodes.map(n => n.src).slice(0,20),
    timestamp: Date.now()
  };
})()
```

**New output detection (polling):**

```javascript
(function(baselineSrcs){
  const sel = 'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"], div.no-scrollbar img[loading="lazy"]';
  const nodes = Array.from(document.querySelectorAll(sel));
  const newNodes = nodes.filter(n => !baselineSrcs.includes(n.src));
  if (newNodes.length === 0) return {found:false, count:nodes.length};
  const best = newNodes.reduce((a,b) => (b.naturalWidth||0) > (a.naturalWidth||0) ? b : a, newNodes[0]);
  return {found:true, new_src: best.src, new_count: newNodes.length, rect: best.getBoundingClientRect()};
})(baselineSrcs)
```

---

## F. Model / Processing Indicator — Response A/B Spinner

**Purpose:** Identify model and active processing state. User report 2026-09-16: app should understand when to wait — see icon of processing.

**User provided HTML of waiting state:**
```html
<div class="flex min-w-0 flex-1 items-center gap-2">
  <div class="h-5 w-5 flex-shrink-0 animate-spin">
    <canvas width="28" height="28" style="vertical-align: top; width: 20px; height: 20px;"></canvas>
  </div>
  <span class="xs:max-w-full flex min-w-0 max-w-[250px] items-center gap-1 font-mono text-xs font-medium">
    <span class="truncate">Response A</span>
  </span>
</div>
```

| Field | Value |
|---|---|
| **Primary** | `div.animate-spin` |
| **Fallback 1** | `div.h-5.w-5.flex-shrink-0.animate-spin` |
| **Fallback 2** | `div.animate-spin > canvas` |
| **Fallback 3** | `div.flex.min-w-0.flex-1.items-center.gap-2 div.animate-spin` |
| **Fallback 4** | `div.flex.min-w-0.flex-1.items-center.gap-2:has(div.animate-spin)` |
| **Fallback 5** | `canvas[width="28"][height="28"]` inside `animate-spin` |
| **Scope** | `div.flex.min-w-0.flex-1.items-center.gap-2` containing label + spinner — label `span.truncate` with text "Response A" or "Response B" or model name "Max" |
| **mustBeVisible** | true |
| **expectedCount** | 0..2 (0=idle, 1-2=generating — Response A and Response B each have own spinner for side-by-side arena) |
| **Verification** | spinner visible ⇒ processing; not visible ⇒ idle. In `wait_for_new_output`, check spinner: if spinning true, log "Generation started — spinner visible Response A/B" and continue polling. When spinner disappears + new output image appears, consider completed. |
| **Evidence** | Saved HTML shows model selector button with Max text + user HTML 2026-09-16 shows Response A/B spinner with canvas 28x28 |
| **Fix 2026-09-16** | `JS_CHECK_NEW_OUTPUT` now returns `spinning`, `spinCount`, `spinDetails` (label), and `wait_for_new_output` logs spinner start, polls while spinning, waits for spinner gone + new image. |

---

## G. Security Verification Dialog — CAPTCHA Handling

**Purpose:** Detect blocking dialog, pause for manual solve (never bypass).

| Field | Value |
|---|---|
| **Primary** | `div[role="dialog"][data-state="open"]` |
| **Qualification** | Contains text "Security Verification" or `iframe[title="reCAPTCHA"]` |
| **Heading** | `h2.font-heading` text "Security Verification" |
| **Generated ID to avoid** | `#radix-_R_...` (Radix UI generated) |
| **mustBeVisible** | true |
| **expectedCount** | 0 or 1 |
| **Verification** | If visible, set USER_ACTION_REQUIRED, pause run, notify user, wait for disappearance |
| **Evidence** | Spec + grecaptcha badge observed in HTML |
| **Action Blocks** | `CHECK_SECURITY` |
| **Compliance** | RULE 20 — never bypass, pause and let user solve |

**reCAPTCHA Detection (detect only, never manipulate):**

| Field | Value |
|---|---|
| **Primary** | `iframe[title="reCAPTCHA"]` |
| **Source fallback 1** | `iframe[src*="google.com/recaptcha/"]` |
| **Fallback 2** | `iframe[src*="/recaptcha/enterprise/anchor"]` |
| **Container** | `#recaptcha-v2-container` |
| **Response field (detect only)** | `textarea[name="g-recaptcha-response"]`, `#g-recaptcha-response-1` |
| **Status text** | "Protected by reCAPTCHA" |
| **Indicator** | `div.size-1.animate-pulse.rounded-full.bg-green-500` |

---

## H. Page Readiness Composite — When URL is READY

URL READY only when all pass (same as Old App's readiness, adapted):

1. Exactly one visible `textarea[name="message"]` in intended composer
2. Exactly one visible `button[aria-label="Send message"]` in that composer
3. Confirmed attachment control or `input[type="file"]` exists and enabled
4. Output observation container available (`div.no-scrollbar` or fallback)
5. No visible Security Verification dialog or reCAPTCHA iframe blocking
6. Page is not sign-in, access-denied, missing-conversation, rate-limit, generic error

Sign-in detection heuristics:

* Text contains "Sign in" + button "Continue with Google" or similar
* URL contains "/auth" or "/login"
* Presence of `a[href*="auth"]` with sign-in text

---

## I. Selector Object Structure — For Every Element

For every element store (same as Old App, adapted):

```json
{
  "name": "prompt_textarea",
  "primary": "textarea[name=\"message\"]",
  "fallbacks": ["textarea[placeholder^=\"Describe\"]"],
  "scope": "form",
  "mustBeVisible": true,
  "mustBeEnabled": true,
  "expectedCount": 1,
  "textCondition": null,
  "verification": "read back value equals expected",
  "evidence": "Directly Chat...html line 74",
  "lastVerified": "2026-09-15"
}
```

If no selector matches, capture sanitized diagnostics (screenshot path, limited HTML snapshot, attempted selectors) and stop step. Never guess-click.

---

## J. Visual Click Runner — Shared Implementation

Same as Old App RULE 1, adapted to Arena:

* `app/browser/dom_highlight.py` `build_highlight_js(selector, color, duration_ms, caption, clear_first=True)` — builds JS that finds element, draws rect, returns `{found, rect}`
* `app/browser/cdp_arena.py` `highlight_selector()` — calls `CDPClient.evaluate()` with highlight JS, emits `highlight_rect` signal for UI overlay
* Overlay: `#highlightOverlay` with `.highlight-rect` — `position:absolute`, `border:2px solid color`, `background:rgba(...,0.08)`, `pointer-events:none`, `z-index:2147483647`, auto-remove after `duration_ms`

**Colour convention:**

| Colour | Meaning |
|---|---|
| RED `#ff2d2d` | FIND phase |
| ORANGE `#ff9500` | CLICK phase |
| GREEN `#00c853` | new output COLLECT |
| BLUE `#00AAFF` | prompt textarea |
| GREEN `#00FF00` | attach input |
| YELLOW `#FFAA00` | submit button |

---

## K. Missing Selectors Still Needed (to be discovered)

* Stable composer container: `form:has(textarea[name="message"])`
* User message containing submitted prompt/JOB-ID: look for `div` containing `[JOB-ID: ...]` text after submission
* Assistant response container: sibling after user message
* Generation-complete indicator: disappearance of `div.animate-spin` + presence of new output image
* Download/original-image control: may be button on image hover — not observed; we download via src URL directly
* Sign-in, access-denied: heuristic text search

All selectors will be centralized in `app/browser/site_adapter.py` as constants with ordered fallback lists, with `lastVerified` dates.

---

*This document is auto-verified against saved HTML and live CDP probes. Last verified: 2026-09-15. Next verification when arena.ai DOM changes — update `site_adapter.py` and this file in same change (RULE 17).*

## E2. Output / Generated Image — Exact Above Prompt Order (Fix 2026-09-16 v2)

**User report:** "still have problem with andestanding what image should be taken. the app should clearly understand where was the prompt generated for what image. if generated image is above the prompt this image do not belongs to the current prompt. and should await next image generated above (if still generating icon) Exact above the prompt (not after next one more prompt) create clear order and understand what image where should be appear and taken! Now it still mess what image it take without verify it it corrrect image or not!"

**Example HTML order provided:**
```
<ol class="... flex-col-reverse ...">
  <div class="h-0"></div>
  <div><img src=".../1789507366571-01a0a6f2...png (50vh) — gen_A"></div>
  <div class="group flex ..."><img alt="01-c.jpeg" class="w-32"> + [JOB-ID: 20260915-232151-8ZO0] Transform...</div>
  <div><img src=".../1789506957478-01a0a6ec...png (50vh) — gen_B"></div>
  <div class="group"><img alt="01-b.jpeg" class="w-32"> + [JOB-ID: 20260915-231500-HT32] Transform...</div>
</ol>
```
- Each gen is immediately before its user in DOM (gen above user visually if file order = visual top to bottom).
- Reference images inside user bubble: `w-32` small, `h-16 w-16`, not 50vh.
- Generated: `h-[50vh] w-[50vh] aspect-square object-cover` large.

**Previous fix flaw:** Preferred AFTER job container (FOLLOWING), but example shows correct is BEFORE (above). Also didn't verify intervening JOB-ID — could take image belonging to previous prompt.

**New fix — exact above verification with clear order:**

1. Collect all JOB-ID prompts: search `div,span,p,pre` for `/\[JOB-ID:\s*([^\]\s]+)\]/`, extract jobId, find container via ancestor heuristics (height 20..0.95vh, width <0.98vw, contains img or flex), get bounding rect top/left, deduplicate by jobId, sort by visual top ascending (top to bottom).

2. For current correlationId, find its index, `jobTop`, `prevJobTop` (previous prompt above), `nextJobTop`, `prevJobId`, `nextJobId`.

3. Candidate images: selectors for R2 large images, exclude blob, oldSrcs, reference images (inside any job container and small `w-32`/`h-16` or width <=140), only large `width>=200` or `50vh` or `object-cover` + `aspect-square` >=200.

4. Exact above filter:
   - Must be above: `image.top < jobTop -5`
   - Must be between previous and current: `prevJobTop < image.top < jobTop` if prev exists, else just `< jobTop`
   - Must have no intervening JOB-ID: no other job with top between image.top and jobTop
   - ValidAbove = passes all, InvalidAbove = above but fails between or has intervening (belongs to previous prompt)
   - BelowCandidates = image.top > jobTop

5. Pick closest above: sort validAbove by `b.top - a.top` descending (largest top < jobTop first) — exact above, not after next prompt.

6. If no validAbove but invalidAbove exists → reason `image_above_belongs_to_previous_prompt_await_next` — await next image above current (if still generating icon visible).

7. If spinning (`div.animate-spin` visible) → reason `generating_spinner_visible` — await next above.

8. Logging: `orderCheck` string `exact above: prev {prevId}({prevTop}) < img {top} < curr {id}({top})`, `jobFound`, `jobTop`, `prevJobTop`, `validAbove`, `invalidAbove`, `allJobs`, `jobIndex`.

**Bridge handling:**
- Logs orderCheck on completed and timeout
- Special handling for `image_above_belongs_to_previous_prompt_await_next` and `no_exact_above_found_wait_next`: await next image, check `is_generating`, if generating continue waiting without reload, if not generating and first cycle reload (bad cache), second cycle fail.

**Selectors updated:**
- Generated: `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]` + `h-[50vh] w-[50vh] aspect-square object-cover` + `naturalWidth>=200` + `visible` + `complete` + `top < jobTop` + between prev and curr + no intervening job
- Reference to exclude: inside any job container and small `w-32`/`h-16`/`w-16` or width <=140
- Job container: contains JOB-ID text, height 20..0.95vh, width <0.98vw, contains img or flex/group, not `no-scrollbar`

**Risks & fallbacks:**
- If JOB-ID not found (render delay): fallback to bottom-most large new image but logs jobFound=false — still better than random, but will be caught by exact above check returning no validAbove and awaiting next.
- If top positions are 0 (hidden or not rendered): fallback to document order via `compareDocumentPosition` previous logic.
- If multiple large images in valid range (Response A/B): picks closest above (largest top), logs validAbove count.
- If reference image also large 50vh: still excluded by container containment + small check, not size alone.

**Verification:**
- For JOB-ID 8ZO0: prev none, validAbove gen_A (0) → exact above verified.
- For new prompt at bottom (400): prev is 01-b (300), valid range 300-400, only new gen in that range qualifies.

## E3. Output / Generated Image — Below Prompt Block (Fix 2026-09-16 v3)

**User report:** "download incorrect image (reference preview above prompt downloaded instead of generated below)" — provided HTML showing prompt block `div.flex.min-w-0.flex-1.flex-col.items-end.gap-1 > div.bg-surface-raised` containing `[JOB-ID: ...]`, correct image block AFTER it `div.flex.w-full.flex-row.items-center.gap-2.justify-start > div.w-fit > div.relative > img.transition-opacity.duration-500.opacity-100.aspect-square.h-[50vh].w-[50vh].object-cover` with R2 src `messages-prod...01a0a72e...png`. Previous logs showed `jobTop 53 prevTop null allNew 20 valid 0 invalid 0 debugAllImgs 3 (avatar 96 inOld True top 1239, large 50vh 1092x1440 visible True complete True inOld False top 461, small w-32 228x300 top -583)` → validAbove empty because image below job was classified as belowCandidates but ignored when jobFound true, plus duplicate counting 3→20.

**Root causes identified (4):**
1. **Early-break:** first selector matching only older flex-col-reverse hits stopped scan before newer images seen, causing allNew 20 but valid 0.
2. **Inner <p> container:** smallest-qualifying match was `<p>` with only JOB-ID, excluding sibling reference thumbnail, so `jobContainer.contains(el)` filtering misfired.
3. **flex-col-reverse misdetect:** harness treated normal `flex flex-col` as reversed, demoting valid candidates.
4. **No fallback + truncated src:** when grid/JOB-ID missing post-spinner loop waited forever; fallback URL `src.slice(-60)` made undownloadable; fixed by fallback accepting stable ≥400px new image after 10s and returning full src + rect.

**New DOM understanding — below prompt:**
- Prompt container: `div.flex.min-w-0.flex-1.flex-col.items-end` containing `[JOB-ID]` + optional reference thumbnail `img.w-32 h-16` (small, 228x300) inside same `bg-surface-raised` bubble — this is ABOVE (user bubble).
- Correct generated container: sibling `div.flex.w-full.flex-row.items-center.gap-2.justify-start` (assistant bubble) containing `img.h-[50vh].w-[50vh].aspect-square.object-cover.transition-opacity.opacity-100` with size 1092x1440, src contains `messages-prod` + `r2.cloudflarestorage.com` — this is BELOW prompt block (top 461 > jobTop 53).
- Reference vs generated distinction: reference = `isSmall (rect<=140 || w-32/h-16/w-16) && !is50vh` inside jobContainer or any job container; generated = `isLarge = 50vh || width>=400 || rect.width>=400`.
- Layout detection: `ol.flex-col-reverse` present → reverse layout (DOM before = visual below), else normal `flex flex-col` → DOM after = visual below. New probe explicitly checks `document.querySelector('ol.flex-col-reverse')` and computed `flexDirection`.

**Fix v3 — layout-aware below-prompt preference:**
1. **No early-break + deduplication:** scan ALL selectors, collect candidates, deduplicate by src Set for allNew/validAbove/validBelow/belowCandidates/invalidAbove — fixes 3→20 duplicates.
2. **Smallest container requires hasJob&&(hasImg||hasFlex||hasGroup):** when finding container for JOB-ID, require container has job text AND (hasImg or hasFlex or hasGroup) and not `no-scrollbar`, height 20..0.95vh — ensures reference thumbnail included in container for proper `contains` filtering.
3. **Layout-aware reverse detection:** `is_layout_reverse = !!document.querySelector('ol.flex-col-reverse') || getComputedStyle(ol).flexDirection==='column-reverse'` — if reverse, valid = beforeCurrent (DOM before job = visual below), else valid = afterCurrent (DOM after = visual below). Prevents misclassifying below as above.
4. **Below-prompt pool preference:** `validBelow` = image with `top > jobTop+5` AND `justify-start` assistant bubble AND large; `validAbove` kept for backward compat; pool logic prefers `validBelow` (correct image BELOW prompt per user) sorted by DOM proximity (`compareDocumentPosition` closest after) then visual top, preferring `justify-start`. Also includes `belowCandidates` even when `jobFound` true — fixes jobTop 53 image top 461 below being ignored → now validBelow 1.
5. **Full src + rect:** returns full `el.src` not sliced, plus `rect` {x,y,width,height} for download and highlight — fixes undownloadable truncated URL.
6. **Fallback stable ≥400px after 10s:** if no validBelow/Above after 10s but `allNew>0` and spinning false, accept first stable large image — prevents infinite wait when grid/JOB-ID missing.
7. **3s stabilization:** `wait_for_new_output` logs `⏳ Waiting 3s before finalizing download`, sleeps 3s, re-checks same src still ready; bridge `WAIT_OUTPUT` logs `⏳ New src detected ... waiting 3s before verification download` and `DOWNLOAD` logs `⏳ Waiting 3s before download as requested` — per user request not immediate, lets opacity transition complete.

**New modules:**
- `app/browser/output_probes.py`: `build_baseline_js()` returns baseline JS with full src, `build_check_js(old_srcs, correlation_id, old_outputs)` returns v3 JS with layout-aware reverse detection, smallest container hasJob&&(hasImg||hasFlex), isReference `isSmall && !is50vh`, isLarge `50vh||>=400`, deduplication, full src.
- `app/browser/output_state.py`: `flatten_diagnostics(result)` ensures orderCheck/jobTop/validAbove/belowCandidates not None, `build_order_check_text()` builds log line.
- `app/browser/output_wait.py`: `wait_for_new_output_with_spec(check_fn, log_cb, cancel_check, WaitSpec)` polls `spec.poll_interval` (2s default) up to `spec.timeout`, handles spinner visible/gone, ready with 3s wait + re-check, fallback stable ≥400px after 10s, returns last_check on timeout. (The old 5-param `wait_for_new_output_loop` and the dead `_legacy` compat shims were removed 2026-09-19 — zero callers; `WaitSpec` is the single entry.)
- `app/browser/cdp_arena.py`: refactored from 534 LOC class to thin delegation (~300 LOC, methods ≤15 LOC, each ≤20 LOC, CC ≤7) — deleted old `JS_CHECK_NEW_OUTPUT`, now uses `build_check_js`, `flatten_diagnostics`, `wait_for_new_output_with_spec`.

**Verification logs after fix:**
- `jobTop 53` + image `top 461` + `isAssistantBubble justify-start` + `isLarge 50vh 1092x1440` → `validBelow 1` (was 0)
- `allNew` deduplicated 20→1, `debugAllImgs 3` correctly classified (avatar inOld, large 50vh not inOld validBelow, small w-32 reference filtered)
- 3s wait observed in logs before download, re-check confirms src still ready
- Quality: `output_probes.py`, `output_state.py`, `output_wait.py` clean, `cdp_arena.py` reduced 534→302 LOC class, methods 31→26, each ≤30 LOC, CC ≤7, baseline updated; `pytest 45 passed`, `verify_quality --changed --allow-legacy` PASSED.

**Stable selectors final:**
- Prompt anchor: `div.flex.min-w-0.flex-1.flex-col.items-end` containing `[JOB-ID: xxx]` + optional `img.w-32` reference thumbnail — exclude reference when `isSmall && !is50vh` inside container.
- Generated below: `div.flex.w-full.flex-row.justify-start` + `img.h-[50vh].w-[50vh].aspect-square.object-cover.transition-opacity.opacity-100` + `width>=400` + src `messages-prod` + `r2.cloudflarestorage.com` + `top > jobTop` + `isAssistantBubble justify-start`.
- Layout: check `ol.flex-col-reverse` existence, else normal.

## E4. Output / Generated Image — Strict JOB-ID Verification Before Download (Fix 2026-09-16 v4)

**User report:** \"after reset page next image processed have wrong image saved (from previous prompt). before downloading do fully verification prompt above and key matching with image processing key and key of prompt used on web page, if not match do not download, process as error\"

**Root cause:** After page reset (reload), previous prompt's JOB-ID image still in DOM (or cached) could be matched as new output for current correlation_id because old `output_probes` filtered only by `oldSrcs` and visual position, not by associated JOB-ID equality. `WAIT_OUTPUT` block downloaded first new src without checking if its nearest JOB-ID equals current `correlation_id`. Bridge `DOWNLOAD` also lacked verification.

**Fix v4 — strict JOB-ID binding before any download:**

1. **JS `findAssociatedJobForImage` per candidate:**
   - For each candidate img, compute DOM order via `compareDocumentPosition` and visual tops:
     - `domPrev` = last JOB-ID element before img in DOM (FOLLOWING), `domNext` = first after.
     - `visualPrev` = closest JOB-ID with `top < img.top -5` (max top <), `visualNext` = closest with `top > img.top+5` (min top >).
   - `associated = layoutReverse ? domNext||visualPrev||domPrev : domPrev||visualPrev||domNext` — layout-aware (flex-col-reverse vs normal).
   - Returns `associatedJobId`, `domPrevJobId`, `domNextJobId`, `visualPrevJobId`, `visualPrevTop`, `associatedTop`.
   - Stored in candidate info for diagnostics.

2. **Filter pool to matching JOB-ID:**
   - If `correlationId` provided and `associatedJobId` != `correlationId`, candidate goes to `mismatchDetails` `{src, associated, expected, top, domPrev, domNext, visualPrev}` and is NOT added to valid pools.
   - `debugFiltered` reason `job_id_mismatch`.
   - Fallback scan also respects same filter.
   - Final strict check: `matchingPool = pool.filter(c => !c.associatedJobId || c.associatedJobId === correlationId)`. If empty but pool had mismatched images → return `ready:false reason:job_id_mismatch_no_matching_image` with `expectedJobId`, `mismatchDetails`, `poolDetails` (src, associated, expected, top), `orderCheck: JOB-ID mismatch expected X but found Y — not downloading`.

3. **Diagnostics fields added:**
   - `associatedJobId`, `expectedJobId`, `domPrevJobId`, `visualPrevJobId`, `mismatchDetails`, `poolDetails`, `allNewDetails` with associated info.
   - `orderCheck` now includes `associated X == expected Y (CORRECT KEY MATCH)` or mismatch list.
   - Logs visible in `arena_log` for debugging reset case.

4. **Python layers enforce:**
   - `output_state.py`: flattens new fields, `is_job_id_match(corr, assoc)` = strict equality, `is_mismatch_error(reason)` = `job_id_mismatch_no_matching_image`.
   - `output_wait.py`: `should_fallback` returns False when reason is mismatch or `mismatchDetails` present — prevents fallback accepting wrong image. `handle_mismatch` logs awaiting correct image. 3s re-check also verifies `associated==expected`. Timeout with mismatch returns mismatch error not fallback.
   - `cdp_arena.py`: `wait_for_new_output` returns check dict with `associatedJobId`, `expectedJobId`, `mismatchDetails` preserved.
   - `bridge.py` `WAIT_OUTPUT` block: before 3s wait, extracts `assoc = data.associatedJobId`, `expected = data.expectedJobId || correlation_id`, if `assoc != expected` → log `❌ JOB-ID mismatch before download`, set `last_wait_error`, if still generating continue waiting, else reload first cycle, second cycle raise `RuntimeError JOB-ID mismatch — not downloading incorrect image`. Also verifies `jobFound` false → prompt not found after reset → error. Only if passes logs `✅ Full verification passed before download: associated X == expected Y jobFound=...`.
   - `bridge.py` `DOWNLOAD` block: pre-check via `get_generation_state(correlation_id)` to get current `associatedJobId` and `jobFound`; if mismatch → raise RuntimeError immediately, job fails without `atomic_write`. If passes, proceeds with 3s wait + download attempts + reload retry logic.

5. **Acceptance:**
   - After page reset, next image processing must NOT save incorrect image from previous prompt.
   - Before download, full verification that prompt above image has key matching image processing key (correlation_id/JOB-ID) and key of prompt used on web page; if mismatch do not download, process as error (failed status).
   - Logs show `✅ Full verification passed` when correct, `❌ JOB-ID mismatch` when wrong, no file saved on mismatch.

**Stable selectors final (v4):**
- Prompt anchor: same as v3, but now each img bound to nearest JOB-ID via DOM+visual.
- Generated below: same, plus `associatedJobId == correlationId` mandatory.
- Verification: `get_generation_state(correlationId)` returns `associatedJobId`, `expectedJobId`, `jobFound`, `mismatchDetails`.
- Failure mode: `job_id_mismatch_no_matching_image` → await correct image if generating, else reload once, else fail job as error without saving.

**Verification logs after fix:**
- When correct: `Order check: Verified below prompt: jobTop X < img top Y isAssistant True associated JOB-123 == expected JOB-123 (CORRECT KEY MATCH)` + `✅ Full verification passed before download: associated JOB-123 == expected JOB-123 jobFound=true`.
- When mismatch after reset: `Order check: JOB-ID mismatch: expected JOB-456 but found images belong to JOB-123 — not downloading, will error` + `❌ JOB-ID mismatch before download: image associated JOB-123 != expected JOB-456 — NOT downloading incorrect image` + `Mismatch details: [{src, associated, expected, top}]` + job fails without saving.

**Quality:**
- `output_probes.py` v4 full src not truncated, strict filter.
- `output_state.py` adds helpers `is_job_id_match`, `is_mismatch_error`.
- `output_wait.py` prevents fallback on mismatch, re-check verifies equality.
- `bridge.py` verifies before both WAIT and DOWNLOAD, fails without atomic_write.
- `pytest 45 passed`, `verify_quality --changed --allow-legacy` PASSED.

## L. New Chat Reset — Post-Generation Return to Clean Chat (2026-09-16)

**Purpose:** After each job, return the tab to a clean new chat (spec 01).
User HTML: `li[data-sidebar="menu-item"] > a[data-sidebar="menu-button"
href="/image/direct"] > svg + span "New Chat"`.

| Field | Value |
|---|---|
| **Primary** | `a[href="/image/direct"]` + child `span` contains "New Chat" |
| **Fallback 1** | `li[data-sidebar="menu-item"] a[href="/image/direct"]` |
| **Fallback 2** | `a[data-sidebar="menu-button"][href="/image/direct"]` |
| **Scope** | `li[data-sidebar="menu-item"]` sidebar |
| **mustBeVisible / mustBeEnabled** | true / true |
| **expectedCount** | 1 |
| **Click path** | Shared visual runner `find_and_click` (RULE 1): RED find → pause → ORANGE click, candidates tried in order |
| **Loaded gate** | `document.readyState === "complete"` + `is_page_ready()` (textarea + send + file + output, no dialog) + composer `textarea.value === ""` |
| **Verification** | Reset returns ready only when all three hold (else timeout reason); cooldown starts after reset, tab steady only after pause expires |
| **Evidence** | User-provided sidebar HTML 2026-09-16 |
| **Action Blocks** | None — automatic post-job step (`app/browser/new_chat.py` via `app/services/cooldown_service.py`), not a toggleable block |
| **Site adapter** | `new_chat_button` entry, lastVerified 2026-09-16 |

