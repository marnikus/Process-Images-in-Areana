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

## E. Output / Generated Image — Detection

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
