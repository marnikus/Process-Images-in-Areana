# Captcha — stop false "on screen" triggers + visual CAPTCHA_WAITING flag

Date: 2026-09-18 · Branch: `arena/01a0b1a7-process-images-in-areana` · Status: research → implemented
User requests: (1) "does not start solving captcha as it was on screen now. fix";
(2) "detect exact moment the captcha is on screen and show the msg it await to be
solved flag. Let it visual confirmation."

## 1. Research — re-analyzed the saved page state (the exact problem location)

Saved normal state (`arena webpages/state/Arena _ Benchmark & Compare the Best AI
Models.html`) — the always-present badge widget:

```html
<div class="grecaptcha-badge" data-style="bottomright"
     style="width:256px; height:60px; position:fixed; visibility:hidden;
            display:block; transition:right 0.3s; bottom:14px; right:-186px; ...">
  <div class="grecaptcha-logo">
    <iframe title="reCAPTCHA" src="…/enterprise/anchor?…&size=invisible&k=6LeTGMcs…">
  </div>
  <textarea id="g-recaptcha-response-100000" name="g-recaptcha-response" style="…display:none;">
```

**The trap:** `display: block` + `position: fixed` ⇒ `iframe.offsetParent !== null`
in Chrome — even though the badge is `visibility: hidden` AND off-screen
(`right: -186px`, slides in via `transition: right`). The legacy predicate measured
**layout presence** (`offsetParent`), not **on-screen visibility** — so a page in its
NORMAL state (badge on screen in layout, hidden to the eye) read as "captcha on
screen" → captcha flow started (and 2Captcha solving too, when enabled).

Fix history: 2026-09-18 commit `2dd057d` added the identity exclusion
(`.closest('.grecaptcha-badge')`) to both predicates. That is necessary but not
sufficient as a general rule — ANY recaptcha widget that is laid out but hidden
(visibility/clip/off-screen) would still pass `offsetParent`. This change upgrades
the gate to measure **actual on-screen visibility** (the user's words: "on screen").

## 2. Design

### 2.1 "On screen" predicate (visible.js v2)

Challenge = open `role=dialog[data-state=open]` with "Security Verification" /
"Protected by reCAPTCHA" / reCAPTCHA widget (dialog branch — unchanged) **OR** a
reCAPTCHA iframe that is:
1. not inside `.grecaptcha-badge` (identity, kept — defense in depth), AND
2. **actually visible on screen**: `offsetParent !== null`, no `display:none` /
   `visibility:hidden|collapse` on the iframe OR any ancestor, non-zero rect, and
   rect intersects the viewport.

The saved-state badge fails checks 1, 2a (visibility:hidden) and 2c (off-screen) —
triple-covered. A real challenge widget (dialog, `size=normal`, centered) passes.

`BrowserController` (URL validation) keeps its minimal edit: badge exclusion +
`visibility !== 'hidden'` (no rect walk — legacy diff kept small).

### 2.2 Visual confirmation at the exact moment (request 2)

At detection (the choke point `handle_captcha`, the moment the probe first reports
visible):
- Log flag line (manual path): `🛡️ FLAG CAPTCHA_WAITING — captcha on screen (tab …) —
  awaiting your solve in Chrome`
- Log flag line (auto path, only when enabled+key): `🤖 FLAG CAPTCHA_AUTO — 2Captcha
  auto-solve started (tab …)` — auto-solve is never silent
- On-page overlay: existing red `wait for user. Captcha` overlay (kind=captcha)
- Fleet: pool row already flips to `waiting_captcha` (red) via `mark_waiting`
- Captcha window status line now shows the ACTIVE POLICY explicitly:
  `auto-solve: ON (2Captcha) / OFF (manual wait)` — so the user sees exactly why
  the app would (or would not) solve on its own

### 2.3 "Do not start solving" (request 1)

Auto-solve stays strictly opt-in: it runs ONLY when **Enable auto-solve** is
checked AND a key is saved (default OFF). The policy is now visible in the window
status line + a loud CAPTCHA_AUTO log line at start, so the state can never be
surprising. With the policy OFF, the flow is exactly: detect → CAPTCHA_WAITING
flag → manual wait → penalty.

## 3. Verification (2026-09-18)

- pytest: **287 passed** (5.1 s).
- node `npm run test:js`: **85/85 passed** (was 82; +3 new geometry tests in
  `test_captcha.mjs`: off-screen rect, `visibility:hidden` ancestor, `display:none`
  ancestor — none badge-class, so the geometry walk is proven independently of the
  identity exclusion).
- `tools/pre_push_check.sh` stage 2 (RULE 16, changed files vs main, legacy allowed):
  **PASS** — "✅ Quality gate passed (changed files)".
- `tools/pre_push_check.sh` stage 4 (whole-app coverage threshold 80/75): **FAIL at
  29.3% line / 22.6% branch — PRE-EXISTING, not caused by this diff.** Proven by
  re-running the identical coverage step on the tree WITHOUT this diff:
  29.306%/22.643% vs 29.317%/22.643% with it (this diff adds 2 covered Python log
  lines, +0.011%). The app-wide UI layer is largely untested; RULE 16's changed-files
  mechanism (stage 2) is the per-change gate and it passes.
- RULE 18 (ideal sizes) on changed code: `visible.js` 38 lines; `service.py` 221
  lines, every function ≤21 LOC (hard gate ≤30); `captcha.js` 96 lines; no new
  modules, no signature changes. `controller.py` size is legacy-grandfathered
  (stage 2 passes with `--allow-legacy`).

## 4. RULE 18 recheck (changed code)

- `visible.js` probe file (~35 lines, self-contained)
- `service.py`: +2 log lines total (each 1 LOC, in existing functions — no size
  growth beyond 1–2 lines per function)
- `captcha.js` (UI): +1 line in `renderStatus` (policy prefix)
- No new modules; no signature changes.
