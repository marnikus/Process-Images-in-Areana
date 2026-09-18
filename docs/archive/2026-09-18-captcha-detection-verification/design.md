# CAPTCHA DETECTION — research against live page states, detection→solver payload verification

Date: 2026-09-18 · Branch: `arena/01a0b1a7-process-images-in-areana` · Status: research → implemented
Process: user request (01 approach — research live captcha pages, match exact solver payload;
02 reference — saved captcha page states; 03 implementation — parse DOM, extract + format data
for the solver, adapt detection per captcha type). Predecessor: `2026-09-17-2captcha-integration/`.

## 1. Reference material analyzed

Two ground-truth states of arena.ai's reCAPTCHA:

**A. "Captcha on" — challenge dialog** (user-pasted live markup, 2026-09-18):
`div[role="dialog"][data-state="open"]` (Radix) containing:
- `h2` "Security Verification" (sr-only + visible)
- `div.recaptcha-v2-container#recaptcha-v2-container` (304×78) wrapping
  `iframe[title="reCAPTCHA"]` with src
  `https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL&co=aHR0cHM6Ly9hcmVuYS5haTo0NDM.&hl=en&v=zqB-6Xpbd3lCIvi7Tr2D0pob&theme=light&size=normal&anchor-ms=20000&execute-ms=30000&cb=cf1ox98i3rhg`
- `textarea#g-recaptcha-response[name="g-recaptcha-response"].g-recaptcha-response` (display:none)
- footer line "Protected by reCAPTCHA"

**B. Badge (normal) state** — saved page `arena webpages/state/Arena _ Benchmark & Compare the
Best AI Models.html` (score 1.0 session, no challenge):
- `div.grecaptcha-badge` → `iframe[title="reCAPTCHA"]` whose saved-from URL (in `anchor.html`) is
  `https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0&co=…&hl=en&v=BnqMGSY_YP4cCmbNINHpJPkd&size=invisible&anchor-ms=20000&execute-ms=30000&cb=t3pnrgbyrriv`
- always-present invisible field `textarea#g-recaptcha-response-100000[name="g-recaptcha-response"]`
- NO `data-sitekey`, NO open dialog, NO "Security Verification" (0 occurrences),
  NO "Protected by reCAPTCHA" (0 occurrences), NO `recaptcha-v2-container`

**Key facts extracted**

| Fact | Evidence | Consequence |
|---|---|---|
| **Two different sitekeys coexist** | A: `k=6Le3_cYs…` (dialog) vs B: `k=6LeTGMcs…` (badge) | sitekey MUST be taken from the dialog's iframe first; page-wide fallbacks can pick the wrong key |
| `size` param discriminates the widgets | A: `size=normal` (visible 304×78 checkbox) · B: `size=invisible` (badge) | detect can derive `isInvisible` for the solver payload (2Captcha enterprise optional field, "true = no visible checkbox") |
| Dialog is enterprise (not v2) | both iframes are `/recaptcha/enterprise/anchor?ar=1` | `RecaptchaV2EnterpriseTaskProxyless` is the right task type (2Captcha docs: proxyless for most cases; arena.ai is not Google) |
| `k=` parse must survive multi-param srcs | `ar=1&k=…&co=…&hl=…&v=…&size=…&anchor-ms=…&execute-ms=…&cb=…` | regex `[?&]k=([A-Za-z0-9_-]{20,})` verified against both real srcs |
| Real widget container | A: `div.recaptcha-v2-container` (absent in B) | extra dialog-scope widget signal (survives iframe-title/src changes, e.g. saved pages where src becomes `anchor.html`) |
| "Protected by reCAPTCHA" | A: present (footer) · B: 0 occurrences | safe as DIALOG-scope text signal only |
| Response field identity | A: `id="g-recaptcha-response"` · B: `id="g-recaptcha-response-100000"` — same `name` | inject probe keyed on `name="g-recaptcha-response"` (already is) — stable across both states |

## 2. Gap analysis (current detect.js vs real states)

1. **Badge false-positive (robustness):** the page-level fallback counts any VISIBLE
   `iframe[title="reCAPTCHA"]` — the badge widget qualifies if ever rendered visible. That would
   (a) report a "captcha" in the normal state and (b) extract the BADGE's sitekey (wrong key →
   2Captcha task for the wrong widget). Empirically the badge is not visible today (manual-wait
   flow completes, so the legacy predicate flips false after dialog close) — but state B proves
   the structure; harden by excluding iframes inside `.grecaptcha-badge` from the page-level fallback.
2. **`isInvisible` not extracted/passed:** the payload omitted the docs-optional `isInvisible`;
   correct today only because the observed dialog is `size=normal`. Adapt per type: derive the
   flag from the iframe src, send it for enterprise tasks.
3. **Sitekey scoping:** the `[data-sitekey]` fallback searched the whole document; with two
   sitekeys on the page, dialog scope must take precedence.
4. **Missing real-markup signals:** `recaptcha-v2-container` and "Protected by reCAPTCHA" not
   recognized (dialog-scope only).

**Verified OK, no change needed:** dialog trigger (`role=dialog` + `data-state=open` +
"Security Verification" — present in A); enterprise classification; payload envelope
`{clientKey, task:{type, websiteURL, websiteKey}}` (matches 2Captcha createTask docs exactly);
`websiteURL = location.href`; inject target `textarea[name="g-recaptcha-response"]` (dialog-scoped
first — the field in A sits inside the dialog); stop/delete/refund flow.

## 3. Changes (implemented)

- `app/browser/captcha_js/detect.js` v2:
  - widget signal = recaptcha iframes **or** `div.recaptcha-v2-container` / `#recaptcha-v2-container` (dialog scope)
  - text signals: "Security Verification" **or** "Protected by reCAPTCHA" (dialog scope)
  - page-level iframe fallback skips `.grecaptcha-badge` descendants (badge is never a challenge)
  - new output field `invisible` (from `[?&]size=invisible` in the iframe src)
  - sitekey order: dialog iframe `k=` → dialog `[data-sitekey]` → document `[data-sitekey]` → script scan
  - output shape: `{visible, kind, sitekey, invisible, url}` (additive; old fields unchanged)
- `app/services/captcha/signals.py`: `CaptchaSignal.is_invisible: bool = False`; `from_result`
  parses `invisible` (bool-tolerant).
- `app/services/captcha/solver.py`: module-level `_task_payload(task_type, signal)` builds the
  docs-exact payload; enterprise task types additionally carry `isInvisible`. (Kept outside the
  `CaptchaSolver` class to hold the RULE 16 class-LOC budget.)

**Rejected (with rationale):**
- Touching the legacy `JS_SECURITY_DIALOG` predicate (gate + post-solve verify loop): it works
  empirically today and is shared by the non-captcha flows; changing it is a behavior change
  beyond this task (RULE 16.5: don't worsen legacy; record the badge risk as a known invariant
  instead — §5).
- Page-level "Protected by reCAPTCHA" as a standalone visibility trigger: it is the challenge
  dialog's footer line — dialog scope only, or it becomes a page-wide signal with no badge-state
  evidence either way.
- `recaptcha-v2-container` in the page-level fallback: state B shows the badge's container is a
  plain div; only the challenge dialog carries the class — dialog scope is the honest boundary.

## 4. Verified solver payload (exact, per 2Captcha docs)

```json
// POST https://api.2captcha.com/createTask  (clientKey in body, never URL/logs)
{ "clientKey": "<key>",
  "task": { "type": "RecaptchaV2EnterpriseTaskProxyless",
            "websiteURL": "https://arena.ai/image/direct",     // location.href of the challenged page
            "websiteKey": "6Le3_cYs…",                          // k= of the DIALOG iframe
            "isInvisible": false } }                            // true only when size=invisible
// poll POST /getTaskResult {"taskId": N} → {status:"ready", solution:{gRecaptchaResponse:"…"}}
// inject token → textarea[name="g-recaptcha-response"] (dialog scope) → dialog continue click
// token not verified within 20 s → deleteTask (refund) + auto_failed + manual fallback
```
Non-enterprise kind maps to `RecaptchaV2TaskProxyless` (no `isInvisible` — not a v2 field).

## 5. Known invariant (watch item)

The legacy visibility predicate (`JS_SECURITY_DIALOG`, used as the call-site gate and in the
post-solve verify loop) treats any visible `iframe[title="reCAPTCHA"]` as "dialog visible". It
remains correct ONLY while the badge widget is not visibly rendered (empirically true today —
manual waits complete, i.e. the predicate flips false after the dialog closes). If the badge
ever becomes visible, apply the same `.grecaptcha-badge` exclusion there — do not extend it now.

## 6. Verification (final numbers)

- **pytest 287 passed** (286 + 1 new: docs-exact payload / isInvisible enterprise-only).
- **node 76 passed** (`test:js`): 20 captcha tests — 5 new real-markup tests (dialog A,
  badge B, badge+dialog coexistence, invisible flag, container-only dialog).
- Coverage (branch), captcha module **92%**: api_client 99%, stats 96%, signals 95%,
  service 94%, key_store 94%, solver 84%, probes 100% (gate 80/75).
- `tools/verify_quality.py --changed --allow-legacy` → **exit 0, 0 fails**.
- radon: `_task_payload` A(2), `CaptchaSolver` A(4), `from_result` B(7).
- FakeCtrl probe dispatch fixed in the same change: it keyed inject on
  `g-recaptcha-response`+`scope` substrings, which the new detect.js comment broke;
  dispatch now uses the unique `Security Verification` marker for detect (RULE 8: fakes
  must stay honest about which probe they answer).

## 7. RULE 18 recheck (changed code)

- `_task_payload` 7 lines / 2 params; `from_result` +2 lines (still ~16, CC 7);
  `_create_task` net −1 line. No new files; `detect.js` 56 lines (probe leaf).
- `CaptchaSolver` class 145 LOC (<150 gate, unchanged band as before); payload builder
  deliberately module-level to hold that budget (not a param/LOC dodge — pure function).
