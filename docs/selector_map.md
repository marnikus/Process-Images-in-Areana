# Selector Map — Arena.ai Image Generation

For every element we store: primary, fallbacks, scope, visibility, enabled, expected count, text condition, success verification, source evidence.

## A. Model / Processing Indicator

**Purpose:** Identify model/status row and active processing state.

- **Primary:** `span.truncate` with normalized text equals "Max" (or other model names) — locate via `//span[contains(@class,'truncate') and normalize-space()='Max']`
- **Spinner Primary:** `div.animate-spin` containing `canvas`
- **Spinner Fallback:** `div.h-5.w-5.flex-shrink-0.animate-spin`
- **Scope:** `div.flex.min-w-0.flex-1.items-center.gap-2` containing both label and spinner
- **mustBeVisible:** true
- **mustBeEnabled:** false
- **expectedCount:** 1 for label, 0-1 for spinner (0 = idle, 1 = generating)
- **Text condition:** label text equals model name (configurable)
- **Verification:** spinner visible => processing; spinner not visible => idle
- **Evidence:** saved HTML shows model selector button with Max text, spinner not present in idle state; spec shows spinner structure.

## B. Add / Attachment Control

**Purpose:** Trigger file chooser for image attachment.

- **Primary:** `button[aria-label="Add files"]`
- **Fallback 1:** `button[aria-label*="add" i][aria-label*="file" i]`
- **Fallback 2:** `button[aria-label*="attach" i]`
- **Fallback 3:** `button[aria-label*="upload" i]`
- **Underlying file input Primary:** `form input[type="file"][accept*="image"]`
- **File input Fallback:** `input[type="file"]`
- **Scope:** `form` that also contains `textarea[name="message"]`
- **mustBeVisible:** true for button, false for input (hidden)
- **mustBeEnabled:** true
- **expectedCount:** 1 button, 1 input
- **Verification:** After click, file chooser dialog appears (Playwright) OR after file set, preview appears in `div.flex.flex-wrap.gap-2`
- **Evidence:** Confirmed in saved HTML line: `<input accept="image/png,..." type="file" class="hidden">` and `<button aria-label="Add files">`

## C. Attachment Preview

**Purpose:** Prove intended image was attached to current composer.

- **Container Primary:** `div.flex.flex-wrap.gap-2`
- **Tile Primary:** `div.group.relative.overflow-hidden.rounded-lg.h-16.w-16`
- **Image Primary:** `div.flex.flex-wrap.gap-2 img[alt="<expected filename>"]` (dynamic alt)
- **Image Fallback 1:** `div.flex.flex-wrap.gap-2 img[src^="blob:"]`
- **Image Fallback 2:** `div.flex.flex-wrap.gap-2 img[alt]`
- **Scope:** Inside same `form` as textarea, above textarea
- **mustBeVisible:** true
- **expectedCount:** 1 per attached file (multiple allowed but MVP single)
- **Text condition:** alt equals source filename when available
- **Verification:** New visible img after upload, blob URL or filename match, inside active input area
- **Evidence:** Spec provides; not observed in empty chat HTML but structure plausible.

## D. Remove Attached File

- **Primary:** `button[aria-label="Remove file"]`
- **Scoped:** `div.flex.flex-wrap.gap-2 button[aria-label="Remove file"]`
- **Fallback:** `button[type="button"][aria-label="Remove file"]`
- **mustBeVisible:** true
- **mustBeEnabled:** true
- **expectedCount:** 1 per preview
- **Verification:** After click, preview container becomes empty
- **Evidence:** Spec

## E. Prompt Textarea

- **Primary:** `textarea[name="message"]`
- **Strong combined:** `textarea[name="message"][autocomplete="off"]`
- **Placeholder fallback 1:** `textarea[placeholder="Describe the image you want to generate…"]`
- **Placeholder fallback 2:** `textarea[placeholder^="Describe how you want to edit"]`
- **Placeholder fallback 3:** `textarea[placeholder^="Describe"]`
- **Other attributes observed:** `textarea[rows="1"]`, `textarea[data-gtm-form-interact-field-id]`
- **Scope:** Inside `form`
- **mustBeVisible:** true
- **mustBeEnabled:** true, not readonly (unless blocked by credits)
- **expectedCount:** 1
- **Verification:** After insertion, `textarea.value` equals expected prompt exactly; read back
- **Evidence:** Confirmed in saved HTML.

## F. Send / Submit Button

- **Primary:** `button[aria-label="Send message"]`
- **Fallback 1:** `button[type="submit"][aria-label="Send message"]`
- **Fallback 2:** `form button:has(svg)` near textarea, last button in form footer
- **Accessible query:** role=button, name="Send message"
- **Scope:** Inside same `form` as textarea, in `div.flex.justify-between`
- **mustBeVisible:** true
- **mustBeEnabled:** true (disabled during generation)
- **expectedCount:** 1
- **Verification:** After click, processing state starts (spinner appears or textarea clears or new user message appears)
- **Evidence:** Partial — aria-label present in HTML but full button truncated; spec confirms.

## G. Output / Generated Image

- **Outer region Primary:** `div.no-scrollbar.relative.flex.w-full.flex-1.flex-col.overflow-x-auto`
- **Candidate Primary:** `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]`
- **Candidate Fallback 1:** `div.no-scrollbar img[src*="messages-prod."]`
- **Fallback 2:** `div.no-scrollbar img[loading="lazy"].aspect-square`
- **Fallback 3:** `img.aspect-square.cursor-pointer`
- **Fallback 4:** `img.transition-opacity.duration-500.opacity-100.aspect-square`
- **Scope:** Main scroll area above composer
- **mustBeVisible:** true
- **expectedCount:** 0..n (grows)
- **Verification:**
  - Capture all matching nodes and src before submission (baseline)
  - After submission, wait for new node not in baseline
  - Confirm appears after current prompt in DOM order
  - Wait for image loading complete (`complete` && `naturalWidth>0`)
  - Prefer highest resolution (largest naturalWidth or src without thumbnail params)
- **Evidence:** Spec; not present in empty chat HTML; host pattern observed in JS bundles.

## H. Security Verification Dialog

- **Primary:** `div[role="dialog"][data-state="open"]`
- **Qualification:** Contains text "Security Verification" or `iframe[title="reCAPTCHA"]`
- **Heading:** `h2.font-heading` text "Security Verification"
- **Generated ID to avoid:** `#radix-_R_...`
- **mustBeVisible:** true
- **expectedCount:** 0 or 1
- **Verification:** If visible, set USER_ACTION_REQUIRED, pause, notify user
- **Evidence:** Spec + grecaptcha badge observed in HTML

## I. reCAPTCHA Detection — Manual Only

- **Primary:** `iframe[title="reCAPTCHA"]`
- **Source fallback 1:** `iframe[src*="google.com/recaptcha/"]`
- **Fallback 2:** `iframe[src*="/recaptcha/enterprise/anchor"]`
- **Container:** `#recaptcha-v2-container`
- **Response field (detect only, never manipulate):** `textarea[name="g-recaptcha-response"]`, `#g-recaptcha-response-1`
- **Status text:** "Protected by reCAPTCHA"
- **Indicator:** `div.size-1.animate-pulse.rounded-full.bg-green-500`
- **Behavior:** Pause, show page to user, wait for disappearance
- **Evidence:** HTML contains grecaptcha badge + anchor.html + bframe.html

## J. Page Readiness Composite

URL READY only when all pass:
1. Exactly one visible `textarea[name="message"]` in intended composer
2. Exactly one visible `button[aria-label="Send message"]` in that composer
3. Confirmed attachment control or `input[type="file"]` exists and enabled
4. Output observation container/strategy available (`div.no-scrollbar` or fallback)
5. No visible Security Verification dialog or reCAPTCHA iframe blocking
6. Page is not sign-in, access-denied, missing-conversation, rate-limit, generic error

Sign-in detection heuristics (need to implement):
- Text contains "Sign in" + button "Continue with Google" or similar
- URL contains "/auth" or "/login"
- Presence of `a[href*="auth"]` with sign-in text

## K. Selector Object Structure

For every element store:
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

## L. Missing Selectors Still Needed (to be discovered with attached-file and post-generation HTML)

- Stable composer container: `form.flex.w-full.flex-col...` — use `form:has(textarea[name="message"])`
- Conversation/message container: need `div[data-message-id]` or similar — not observed; fallback use output region
- User message containing submitted prompt/JOB-ID: need to locate after submission — look for `div` containing JOB-ID text
- Assistant response container: sibling after user message
- Generation-complete indicator: disappearance of `div.animate-spin` + presence of new output image
- Download/original-image control: may be button on image hover — not observed; we will download via src URL directly
- Sign-in, access-denied, etc.: heuristic text search

All selectors will be centralized in `app/browser/site_adapter.py` as constants with ordered fallback lists.
