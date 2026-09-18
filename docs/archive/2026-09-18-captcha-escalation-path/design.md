# Captcha escalation path: all real-user-detection mechanics + the full-path solve

## 1. Report

User (2026-09-18, round 11): saved the webpage state **with the captcha dialog
on screen** and asked to (a) research that state for **all** real-user-detection
mechanics — "if has more than just one captcha mechanics it should [be] solved
to path" — and (b) prepare a detailed doc of what should be implemented.

The research could not rely on the saved dialog alone: the dialog markup shows
the *result* of a decision, not the decision itself. This round closes the loop
by reading **arena's own production bundle source** (the saved webpage's
`_files/*.js.download` chunks — same build as the live chat page) and tracing
every captcha/anti-bot mechanism from its code, not from symptoms.

Research artifacts now in the repo: the saved captcha-on page lives at
`arena webpages/captcha on/(12) Directly Chat with Frontier Image Generation
AI -captcha Models.html` (+ `_files/`: loader stub `enterprise.js.download`,
framework chunk `1798-42faed5e41cbb308.js.download`, the reCAPTCHA anchor
iframes). Corroboration from it: the dialog widget's DIALOG sitekey is
**absent from the saved DOM** — the only key on screen is the badge/execute
key `6LeTGMcs…`; `6Le3_cYs…` exists only in the bundle, passed to
`grecaptcha.enterprise.render()` at runtime. That is exactly why the render
hook captures `opts.sitekey` from the call itself (§2.4). The dialog
mechanism's code chunk (`13w27x7e30p8h.js.download`, module `980034`) loads
on demand on the chat page and was read from the earlier full-build save
(`Process Images in Areana/Old App/Restore/From Webpage Code saved/`).

## 2. Research — the full real-user-detection stack (from bundle source)

Sources: `13w27x7e30p8h.js.download` (module `980034` — the captcha module,
module `448808` — the dialog), `0c9g1bw9g4lc9.js.download` (error constants,
module `895259`), `1dbt0dsleyebh.js.download` (classic chat flows,
`useMultiStreamChat`/`useRetryStreamChat`), `17uw37vd_1wh0.js.download`
(agentic submit), `1rm2fon6qx80w.js.download` (rerun), `enterprise.js.download`
(Google reCAPTCHA **enterprise loader stub**), `3i-6xyh4rphqd.js.download`
(feedback votes).

### 2.1 There are FOUR mechanisms — only one of them blocks

| # | Mechanism | Where | Interactive? | Blocks generation? |
|---|-----------|-------|--------------|--------------------|
| 1 | **Cloudflare edge** bot scoring (botScore 99, ja4, ASN 30764 — earlier rounds) | network edge | no (real Chrome passes) | no — we drive a real Chrome via CDP |
| 2 | **reCAPTCHA v2 Enterprise, invisible badge** — always-present `.grecaptcha-badge` widget, pre-rendered by the loader stub (`cfg['render'].push('6LeTGMcs…')`), `size=invisible`, `anchor-ms=20000` | page background | no | no — passive scoring only |
| 3 | **reCAPTCHA Enterprise `execute`** (arena calls it "v3") — `getRecaptchaV3Token(action)` = `window.grecaptcha.enterprise.execute("6LeTGMcs…", {action})`; token attached to **every** mutating request as `recaptchaV3Token` in the body | every submit | no | no — but a low score is what makes the server escalate |
| 4 | **reCAPTCHA v2 Enterprise visible dialog** — the "Security Verification" escalation | on demand | **yes — this is the block** | **yes** |

Layer 4 is the only one we must *solve*. Layers 2–3 are passive scoring that
we ride along with (their tokens are collected automatically by the real
widget); layer 1 is already passed by driving a real browser.

Actions seen on layer 3: `chat_submit`, `chat_retry`, `chat_rerun`,
`agentic_chat_submit`, `mutation_feedback`, `review_feedback`,
`pairwise_feedback` (the "turnstile" in arena's analytics names is just the v3
token — there is **no Cloudflare Turnstile widget** anywhere in the app).

### 2.2 Layer 4, end to end — the escalation path in arena's own code

**Step A — the trigger.** The request goes out first, with its (automatically
collected) `recaptchaV3Token`. The server decides the score/risk is too low
and answers the request **not-ok** with body `{"error": "recaptcha
validation failed"}` — the exact constant
`RECAPTCHA_VALIDATION_FAILED_MESSAGE` from module `895259`.

**Step B — the escalation wrapper** (module `980034`,
`withRecaptchaV2Escalation`):

```js
let i = await t();                                // original request
if (!i.ok) {
  let s = await i.clone().json().catch(()=>null);
  if (s?.error === "recaptcha validation failed") {
    let r = await e({source, trigger_reason});    // ← opens the dialog, awaits token
    i = await t(r);                               // ← RETRY the SAME request with the token
  }
  if (!i.ok) throw new RecaptchaWrappedRequestError(errorMessage, i);
}
```

**Step C — the dialog + token promise** (`useGetRecaptchaV2Token`):

1. state atom `idle → container-mounting` → a `div.recaptcha-v2-container`
   mounts (this is what our detect probe sees);
2. `window.grecaptcha.enterprise.render(container, {
     sitekey: "6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL",   // the DIALOG key
     callback: t => { clearTimeout(c); state="idle"; resolve(t); },  // ★
     "error-callback": () => reject("V2 rendering failed"),
     theme })`
   — the dialog sitekey is **different** from the badge/execute key
   (`6LeTGMcs…`);
3. **60 s timeout** from render: `setTimeout(…, 6e4)` → reject "reCAPTCHA V2
   token timed out" (state back to `idle`);
4. state → `challenging` → the `SecurityVerificationModal` opens. The modal
   is a **pure presentation shell** (vaul Drawer on desktop, Dialog on
   mobile, `showCloseButton: false`, no Continue button, `onOpenAutoFocus`
   prevented) — it renders the widget element passed as a prop and **nothing
   else**.

**The ★ line is the whole game.** When a human checks the box, Google's
widget calls `options.callback(token)` — that closure is the *only* thing
that (i) closes the dialog and (ii) resolves the promise so step B's retry
runs with the token. The widget has no external handle: the callback lives in
a closure inside `grecaptcha.enterprise.render`'s arguments.

**Step D — the retry contract.** Every escalated endpoint re-sends the same
body with the v2 token swapped in:

```js
body: JSON.stringify({ …, ...(token ? {recaptchaV2Token: token, recaptchaV3Token: null}
                                   : {recaptchaV3Token: v3Token}) })
```

Escalated endpoints (all same shape): `POST /nextjs-api/stream/create-chat`
(agentic), `POST /nextjs-api/stream/create-evaluation`,
`POST /nextjs-api/stream/post-to-evaluation/{id}`,
`PUT /nextjs-api/stream/retry-evaluation-session-message/{id}/messages/{mid}`,
`POST /nextjs-api/stream/rerun/{id}`.

**Step E — success path.** retry ok → analytics `recaptcha_v2_completed` →
`{id}` returned → chat session created → streaming starts. Failure →
`RecaptchaWrappedRequestError` → UI error toast; the state is already `idle`,
so the dialog is closed even on failure.

### 2.3 Why the round-10 fix could not complete the flow (now provable)

Round 10 injected the token into `#g-recaptcha-response` + patched
`grecaptcha.getResponse` + force-closed the dialog + re-sent the prompt.
That is **a different transaction than the app's**: the retry in step D is
performed by the app's own closure with its own original message body —
nothing we can do to the textarea makes that closure run. The re-send was a
proxy that re-triggered the whole escalation (new v3 score, possibly new
challenge) instead of completing the original request with a valid v2 token.
Hence "token accepted / dialog closed" kept meaning "intermediate state" and
the generation never resumed.

### 2.4 The hook point

`enterprise.js.download` (the loader) creates `window.grecaptcha.enterprise`
as a **plain object** (`a[E] = a[E] || {}`) and the real library later
assigns `render`/`execute`/`ready` onto that same object. Arena reads
`window.grecaptcha.enterprise.render` **at call time**. Therefore wrapping
the `render` property *before the first escalation* captures the callback
closure for every challenge, on every reload, per document:

```js
const orig = ent.render;
ent.render = (container, opts) => {
  window.__arenaV2Challenge = {
    sitekey: opts.sitekey, ts: Date.now(),
    solve: (tok) => { opts.callback(tok); return true; }
  };
  return orig.call(ent, container, opts);
};
```

Calling `__arenaV2Challenge.solve(token)` with a 2Captcha token then executes
**arena's own canonical path**: dialog closes (step C.★), promise resolves,
the app retries its original request with `recaptchaV2Token`, server
accepts, generation streams. No re-send needed — the solve returns *to the
path*, exactly as the user demanded.

## 3. Design — solving the full path

### 3.1 Phase 1 (this round) — capture the callback, resolve it with 2Captcha

**New file `app/browser/captcha_js/recaptcha_hook.js`** (~70 lines, IIFE):

- idempotent per document (`window.__arenaRecaptchaHook` guard) — safe to
  evaluate at attach *and* on every later reload;
- wraps `grecaptcha.enterprise.render` once `render` exists (polls every
  200 ms for up to 30 s — the gstatic library may load after our script);
- on each render call stores `window.__arenaV2Challenge = {sitekey, ts,
  solve(token)}` (overwrite-on-each-challenge is correct: the app's state
  machine renders one widget at a time);
- returns `{installed, fresh, ready}` for the attach log line.

**Install points (both, cheap):**

1. `CDPClient._connect_inner` — after the websocket handshake succeeds:
   `Page.enable` + `Page.addScriptToEvaluateOnNewDocument(source=hook)`
   (survives every in-page reload/navigation) + one immediate
   `Runtime.evaluate(hook)` for the current document. One choke point for
   every tab the app attaches to.
2. `service.detect_signal` — re-evaluate the hook (idempotent no-op if
   present) as defense-in-depth for tabs attached by an older app version or
   pages loaded before the app connected.

**`inject.js` change — order flips.** First step becomes:

```js
const ch = window.__arenaV2Challenge;
if (ch && typeof ch.solve === "function") {
  const ok = ch.solve(token);
  if (ok) return {ok: true, path: "hook", cb: "hook", cbCalled: true};
}
```

then the existing field/anchor-cb/getResponse logic stays as the fallback
(`path: "field"`). The result shape keeps the `cb`/`cbCalled` keys the
solver already logs, so **the solver needs no logic change** — only the
log line now shows `cb=hook` and the dialog closes itself within ~1 s,
inside the existing `VERIFY_GRACE_SEC` window, so force-close stays unused
on the happy path.

**`detect.js` change** — add evidence for the log/scan:

```js
out.hook = { ready: !!(window.grecaptcha && window.grecaptcha.enterprise
  && window.grecaptcha.enterprise.render),
  captured: !!(window.__arenaV2Challenge && window.__arenaV2Challenge.sitekey),
  sitekey: (window.__arenaV2Challenge || {}).sitekey || "",
  ageSec: window.__arenaV2Challenge ? (Date.now() - window.__arenaV2Challenge.ts)/1000 : -1 };
```

`signals.CaptchaSignal` gains a `hook: dict` field (default `{}`) and the
detect log line appends `hook=captured(sitekey=…XXXX, age=Ns)` /
`hook=ready` / `hook=absent` — the user sees **why** the path will or
will not be the canonical one, per RULE 2.

**Timing analysis (must stay honest in logs):**

- arena's 60 s timer starts at `render`; our budget = detect (~1 s) +
  createTask (~1 s) + 2Captcha solve (10–60 s typical) + resolve (<1 s).
- 2Captcha tokens are valid 120 s — plenty for the immediate app retry.
- If the 60 s expires first, arena's promise rejects *before* our resolve;
  the callback still closes the dialog but the retry does **not** run —
  the app shows its own error and the round-10 bridge re-send retries the
  prompt (new escalation cycle, new 60 s window). So the worst case is one
  wasted cycle, not a deadlock.
- Consequence: the solver logs the remaining margin when it captures a
  challenge (`🤖 challenge captured (sitekey=…XXXX, 60 s window)`) and
  warns when polling exceeds ~45 s into it.

**What stays unchanged:** detect/visible predicates (badge exclusion!),
per-tab non-blocking inflight map, key masking (RULE 20), overlay + manual
fallback, force-close + re-send as the last-resort fallback, stats/penalty.

### 3.2 Phase 2 (documented, not implemented) — network-level retry

If a future build ever stops exposing the callback in a hookable way, the
research above gives an alternate full-path solve that touches only the API
contract (stable: endpoint + error string + `recaptchaV2Token` field):
intercept the failed response of the five endpoints and re-POST the same
body with `recaptchaV2Token: <2Captcha token>` (CDP `Fetch` domain or a
Playwright route). Not done now — phase 1 is canonical and needs no network
interception; this stays documented per RULE 11 (don't add what isn't
needed).

### 3.3 Phase 3 (documented, not implemented) — prevent the escalation

Hooking `grecaptcha.enterprise.execute` to substitute a 2Captcha V3 token
(`RecaptchaV3TaskProxyless`, per action) *before* each submit could keep the
server from escalating at all. Cost: one 2Captcha task per submit. Deferred —
the v2 solve only fires when escalation actually happens, which is rarer.

## 4. Implementation plan (RULE 18 sizes, RULE 16 gates)

| File | Change | Budget |
|------|--------|--------|
| `app/browser/captcha_js/recaptcha_hook.js` | new — hook IIFE | ~70 lines |
| `app/browser/captcha_js/inject.js` | hook-first branch (5 lines) + `path` in results | 55 → ~62 |
| `app/browser/captcha_js/detect.js` | `out.hook` block (5 lines) + log note | 64 → ~70 |
| `app/browser/captcha_probes.py` | `build_hook_js()` (3 lines) | 66 → ~70 |
| `app/browser/cdp_client.py` | `_install_captcha_hook()` called from `_connect_inner` after ws up (≤15 lines, ≤3 params) | +16 |
| `app/services/captcha/signals.py` | `CaptchaSignal.hook: dict` + `from_result` mapping (≤4 lines) | 75 → ~80 |
| `app/services/captcha/service.py` | hook re-eval in `detect_signal` (3 lines) + log-line fragment | +6 |
| `app/services/captcha/solver.py` | log the capture window + 45 s warning (≤6 lines across existing fns) | +6 |
| `tests/js/test_captcha.mjs` | hook install/capture/solve tests + inject hook-first test | +~80 |
| `tests/test_captcha_solver.py` (+completion) | signal.hook mapping, probe builder, log lines | +~40 |

Gates: pytest + node `--test` green; `CODE_VERIFICATION` gate 0 fails after
`rm -f .coverage coverage.json`; then RULE 18 + RULE 16 self-review; commit +
push `arena/01a0b1a7-process-images-in-areana` (no force; re-check
`ls-remote` for the user's snapshot races first).

## 5. Open questions / risks

1. **Build drift**: the hook depends on `grecaptcha.enterprise` staying a
   plain property object and arena calling `.render` through it. Both are
   stable Google/arena patterns; the detect `hook=absent` evidence makes
   drift visible in the log immediately, and the field+re-send fallback
   (round 10) still degrades gracefully.
2. **60 s window vs 2Captcha latency**: see §3.1 timing — worst case is a
   wasted cycle, never a hang; surfaced in logs, not hidden.
3. **Multiple rapid challenges**: the app renders one widget at a time
   (single state atom + in-flight dedupe in its own code); our capture is
   overwrite-latest, matching that.
4. **Layer 1 (Cloudflare)**: unchanged — real Chrome via CDP passes the edge
   today (every round's evidence); no action.
