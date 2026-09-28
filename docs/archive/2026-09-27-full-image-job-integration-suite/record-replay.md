# Record & replay — research, the pick, and the capture instructions

Added 2026-09-27 (research round, same day as the plan). Owner question: *"research the
record/replay technologies and combine the one that suits most; then tell me what to prepare, what
to record, and with which tool."* Answer in one line:

> **Pick: HAR (HTTP Archive 1.2) as the fixture-provenance format** — recorded by the browser's own
> DevTools export (primary) or Playwright's built-in HAR recorder (scripted), sanitized and reduced
> by a small owner-run ingest tool, and **replayed by the fake-site server this plan already
> designs** (not by a service virtualizer). The repo's own sanitized DOM-snapshot recorder covers
> the DOM side. New decision **D-23**; it amends **D-15** and closes **L-17**.

Everything below is plan/instructions — no code was written, no tool installed, nothing recorded.

---

## 1. The constraints a recording technology has to satisfy here

| # | Constraint | Source |
|---|---|---|
| C-1 | **Zero production change** — no `app/` edit, no new runtime dependency in the app | `design.md` D-20 |
| C-2 | **No heavy runtime in the test budget** — this machine has python3.11 (no pytest/PySide6/Pillow), node v22 (no `node_modules`), no JVM, no Docker, no browser binaries | `evidence.md` §7 |
| C-3 | **Fake page only, never a live site in an automated test** | I-56, RULE 20 |
| C-4 | **Nothing raw is ever committed** — `config/`, `logs/`, `arena webpages/` are untracked and guarded | I-43, `tools/pre_push_check.sh:40-46`, `tests/test_repo_hygiene.py:25-26` |
| C-5 | **Determinism**: identical bytes on every run, per job id | I-57, D-7 |
| C-6 | **The page owns its state machine** — replay must not become the behaviour engine | D-17 |
| C-7 | **Evidence for the gaps**: real result-image bytes + the real result URL shape (L-17), the real New Chat `href` (L-16), the real generating-state DOM | `evidence.md` §8, `fixtures.md` §9 |
| C-8 | Both lanes (Chromium native CDP, Firefox through the adapter) — the *recorder* runs once by hand, so lane support is irrelevant; the *replayer* must not depend on a lane-specific browser API | D-1, D-12, D-13 |
| C-9 | The fixtures must satisfy the selector registry (contract B) and the in-page payloads (contract C) | `evidence.md` §3, §4 |

## 2. What was researched (status checked 2026-09-27)

| Technology | Category | Status / facts found | Cost here | Verdict |
|---|---|---|---|---|
| **HAR 1.2** | format | De-facto standard, spec frozen (1.2, 2011; 1.3 never gained traction). `response.content.text` + `content.encoding:"base64"` is explicitly *"useful for including binary responses (e.g. images)"*, and a decoded blob should be *byte-for-byte identical* to what the browser used — http://www.softwareishard.com/blog/har-12-spec/ | none (JSON) | **PICK (format)** |
| **Chrome/Edge DevTools HAR export** | recorder | Chromium ≥130 exports **sanitized by default** — `Save all as HAR (sanitized)` / `Export HAR (sanitized)` strips `Cookie`, `Set-Cookie`, `Authorization`; the sensitive variant is opt-in behind a preference — https://developer.chrome.com/docs/devtools/network/reference , https://developer.chrome.com/blog/new-in-devtools-130 | none (browser built-in) | **PICK (recorder #1)** |
| **Firefox "Save All As HAR"** | recorder | Same W3C-schema JSON, but the export **does not sanitize** cookies/auth — treat every Firefox HAR as holding a live session token — https://crosscheck.cloud/blogs/capture-share-network-logs-debugging/ | none | cross-check only, never committed |
| **Playwright HAR** | recorder + replayer | `record_har_path` / `record_har_mode` / `record_har_omit_content` on `new_context()` and `launch_persistent_context()`; `page.route_from_har(har, url=…, not_found="abort"\|"fallback", update=bool, update_content="embed"\|"attach", update_mode="full"\|"minimal")`; CLI `npx playwright open --save-har=… --save-har-glob='**/host/**' URL`. Written on `context.close()` (close in a `finally`). Re-recording **replaces** the file — one HAR = one session ⇒ one HAR per page state. Service-worker requests bypass HAR routing (`service_workers="block"`). `route_from_har` must be registered before other `page.route()` handlers — https://playwright.dev/python/docs/mock , https://playwright.dev/python/docs/api/class-browsercontext | `playwright>=1.40.0` is **already pinned** (`requirements.txt:2`) | **PICK (recorder #2 + optional replay check)** |
| Playwright over an app-driven browser | replay constraint | `connect_over_cdp` is Chromium-only and *"significantly lower fidelity"*; recording **on an existing context is not possible**; third-party matrices list `page.route()` interception as unsupported in CDP-connect mode (use the CDP `Fetch` domain) — https://playwright.dev/python/docs/api/class-browsertype , https://github.com/microsoft/playwright/issues/29065 , https://docs.browserless.io/baas/advanced-configurations/playwright-customizations | — | ⇒ HAR replay must **not** sit inside the app-driven lane (D-13); see §7 |
| **The repo's own recorder** | DOM/state snapshots | `app/browser/recording_js/snapshot.js:18,20` — full `<!DOCTYPE html>` + cloned `document.documentElement.outerHTML`, recaptcha fields redacted **in the page**, capped at 2 MB; builders `app/browser/recording_probes.py:19,24,29,34`; capture `app/services/recording/proberun.py:42`; store `app/services/recording/store.py:41,55,71` (`session.json` + `NNNN.html` + `events.jsonl`, atomic, line-bounded `MAX_HTML_LINE = 2000`); sanitizer `app/services/recording/sanitizer.py:13,27,37,53` (`redact_dom_html`, `redact_url` with `_SECRET_PARAMS = token\|session\|auth\|key\|signature\|secret\|password\|bft\|^k$\|^cb$`); CDP `Network.*` collector `app/services/captcha_recording/network.py:20,23,36` + redaction helpers `app/services/captcha_recording/sanitize.py:10,12,16,28,35` (`safe_url` drops query+fragment, `redact_text` kills bearer/≥80-char tokens, `clean_mapping` redacts secret-named keys). Two git-ignored roots: `config/captcha_recordings/` (`app/services/captcha_recording/store.py:113`, manager `:24`, SYSTEM_OF_RECORD row 22) and `logs/recordings/` (`app/ui/panels/recording_sessions.py:20,44`) | none | **PICK (recorder #3, DOM side)** |
| — but it is body-free | limit | `app/browser/recording_js/netwrap.js:3` — *"Never records bodies or headers (RULE 20)"*; the recording is captcha-triggered (`app/services/recording/recorder.py:1-7` — *"Starts AFTER the captcha is confirmed ON"* — and `:47` takes the first snapshot) | — | ⇒ it can never supply image bytes ⇒ **HAR is the necessary complement** |
| Polly.js (Netflix) | in-page HTTP record/replay | JS library, HTTP only (no WebSocket), Mocha/QUnit first-class (other frameworks need adapters); repo alive but release-only — last publish `v6.0.7` 2025-05-31, docs last touched 2022, tests 2021, 58 open issues — https://github.com/Netflix/pollyjs | Node runtime **inside the page under test** | REJECT — it intercepts a JS app's fetch/XHR; our app under test is Python over CDP, and the page is ours |
| WireMock 3.x | service virtualization | Standalone JAR/Docker; `--proxy-all=<origin> --record-mappings --root-dir`; scenario state machines; fault injection (delays, timeouts, status codes) — https://wiremock.org/docs/solutions/service-virtualization/ | **JVM or Docker** in a Python/Node suite; TLS MITM to record an HTTPS origin | REJECT as primary — it virtualizes an HTTP *service*; our fixtures need an in-page state machine + control API + event log (D-17). Its scenario/fault vocabulary independently validates our design |
| Mountebank | service virtualization | Original maintainer ended development May 2024; the maintenance fork was **archived 2025-08-06**; package health "maintenance: Inactive", last npm release ~2 years (2.9.1) — https://github.com/bbyars/mountebank/issues/784 , https://github.com/mattherman/mountebank , https://security.snyk.io/package/npm/mountebank | Node impostor server | REJECT — unmaintained |
| Nock | Node HTTP interceptor | Actively maintained (14.0.10) but intercepts Node's `http` at socket level — *"cannot run in a browser… no help for browser traffic"* — https://npm-compare.com/axios-mock-adapter,fetch-mock,msw,nock | Node | REJECT — wrong runtime (Python app), wrong layer |
| Cypress `cy.intercept()` | E2E + fixtures | Stub responses from fixture files inside Cypress tests | would **replace** the whole framework | REJECT — the app is driven from Python over CDP; Cypress cannot own the app process (D-3) |
| Selenium + BrowserMob Proxy | proxy record/replay | BrowserMob: *"no longer actively maintained, no releases since 2016"*; successor = BrowserUp Proxy (JVM MITM) — https://www.rubydoc.info/gems/browsermob-proxy | JVM proxy + CA | REJECT — dead proxy, and Selenium is not our driver |
| mitmproxy | proxy record/replay | Python, active; first-class HAR since 10.1: `save.har @all out.har`, `mitmdump --set hardump=dump.har`, `hardump=-` to stdout, and it can *read* HAR (`mitmproxy -r x.har`) — https://www.mitmproxy.org/posts/har-support/ | `pip install mitmproxy` + a **machine-wide CA** + browser proxy config | HOLD as fallback (§5 route D) — owner-run only, never automated |
| Percy / Chromatic | visual state | Cloud visual-regression diffing; captures pixels for comparison, does not replay interactive state | SaaS + network | REJECT — the plan already excludes UI visual regression (`design.md` §13 item 7); screenshots stay a per-lane capability (D-10/D-14) |
| Mocky / FakeJSON | hosted fake APIs | Third-party hosted response generators | fixture data on someone else's server | REJECT — violates C-3/I-56 (no external network) |

## 3. Why HAR wins (scored against §1)

| | HAR + DevTools/Playwright | WireMock | Polly.js | mitmproxy | in-house recorder alone |
|---|---|---|---|---|---|
| C-1 zero app change | ✅ | ✅ | ✅ | ✅ | ✅ |
| C-2 no new runtime | ✅ browser built-in (Playwright already pinned) | ❌ JVM/Docker | ⚠️ Node in-page | ⚠️ pip + CA | ✅ |
| C-3/C-4 offline + nothing raw committed | ✅ sanitized-by-default export + our redaction pass | ⚠️ records credentials unless configured | ⚠️ | ❌ CA + full traffic | ✅ |
| C-5 determinism | ✅ bytes are frozen in the file | ✅ | ✅ | ✅ | ⚠️ no bytes |
| C-6 page owns behaviour | ✅ HAR is passive by nature — it cannot fake a state machine | ❌ tempts you to move behaviour server-side | ❌ | ❌ | ✅ |
| C-7 closes L-17 (result bytes + URL shape) | ✅ base64 bodies are byte-identical | ✅ | ✅ | ✅ | ❌ body-free |
| C-8 lane-independent | ✅ a file, not a browser API | ✅ | ❌ browser-only | ✅ | ✅ |
| C-9 serves contracts B/C | ✅ DOM + asset evidence | ⚠️ | ⚠️ | ⚠️ | ✅ DOM only |

**The division of labour this creates** (the actual "combine" answer): HAR carries **bytes and
shapes** (assets, the generated result image, JSON response shapes); the repo's snapshot recorder
carries **structure** (selectors, class names, text, mutation order); the planned fake site carries
**behaviour** (the 14-state machine, `/__test/*` scenario control, `sendCount` instrumentation).
No single product does all three, and the expensive mistake would be buying a service virtualizer
for the behaviour part that D-17 already puts in the page.

## 4. What to prepare (owner checklist, before any capture)

| # | Prepare | Why | Where / cost |
|---|---|---|---|
| P1 | Chrome or Chromium **≥ 130** (check `chrome://version`) | sanitized-by-default HAR export | already installed; or `python -m playwright install chromium` (the plan's lane browser) |
| P2 | Your own signed-in arena.ai session | only *you* may authorize a live capture (RULE 20) — the suite itself never touches the network | your browser profile |
| P3 | A capture folder **outside the repo**, or `arena webpages/captures/` inside it | both are already untracked and guarded (`.gitignore:17` for `logs/`, hygiene gate for `arena webpages/`) ⇒ a raw capture can never be committed by accident | free |
| P4 | `npm ci` **only** if you want the scripted Playwright recorder (route B) | `npx playwright open --save-har` needs `node_modules`; the Python route needs only the already-pinned `playwright` | ~1 min |
| P5 | Disk: ~50–300 MB per capture session (page bundles + images); committed output is only the extracted artifacts (a few hundred KB) | HAR with content is big; that is why raw files stay local | free |
| P6 | A naming convention: `<YYYYMMDD>-<state>-<n>.har` / `.html` / `.probes.json` / `.png` + one `MANIFEST.txt` per session (browser + version, page path, account role, captcha seen? y/n, generation wall time, conversation-list layout reverse? y/n) | the ingest writes provenance into `fixtures/recorded/MANIFEST.json`; without it a fixture cannot be traced to a capture | free |
| P7 | Time: a real generation takes ~30–180 s; the **endless/timeout state cannot be captured live** (it is a negative state) — it stays synthesized | `fixtures.md` §4 (`generation_endless`), D-8 | — |
| P8 | Read §10 (rules + ethics) once | redaction is mandatory, not optional | — |

## 5. What to record, and with which tool

### 5.1 The artifact set per page state

| # | Artifact | Tool | Format | Committed? |
|---|---|---|---|---|
| A1 | Network archive **with content** | DevTools `Save all as HAR (sanitized)` **or** `npx playwright open --save-har` | `.har` (JSON, base64 bodies) | ❌ raw stays local; only extracts |
| A2 | Full DOM snapshot | DevTools Console `copy(document.documentElement.outerHTML)` — same shape as `app/browser/recording_js/snapshot.js:18` | `.html` | ❌ raw; extracts only |
| A3 | **Probe read-back** (the highest-value artifact) | Console snippet in §5.4 | `.probes.json` | ✅ sanitized (it is already just booleans/strings) |
| A4 | The generated result image | right-click → *Save image as*, or extracted from A1 (`mimeType: image/*`) | `.png`/`.webp` | ✅ only after the ingest re-encodes it as the 64×64 fixture base or stores it verbatim with its sha256 |
| A5 | Full-page screenshot | DevTools ⌘/Ctrl+Shift+P → *Capture full size screenshot* | `.png` | ❌ (evidence for you, not for git) |
| A6 | API response **shapes** | extracted from A1 by the ingest | `fixtures/api-shapes.json` (keys + types, values dropped) | ✅ |
| A7 | Mutation/timing trace (optional) | the app's own recorder, route C | `events.jsonl` | ❌ |

### 5.2 Route A — DevTools HAR (primary; zero install)

1. Sign in, open the image chat page (`/image/direct`).
2. F12 → **Network** → tick **Preserve log** and **Disable cache**; leave the filter empty (the
   result image request is on a different host and must be in the file).
3. Produce the state: upload an image, type a prompt with a JOB-ID line, press Send, wait for the
   result (or trigger the error/rate-limit/sign-in state you are capturing).
4. Right-click any request → **Save all as HAR (sanitized)** → `captures/<date>-<state>-1.har`.
   Never use *with sensitive data*; if you ever must, that file never leaves the machine.
5. Console: `copy(document.documentElement.outerHTML)` → paste into `<date>-<state>-1.html`.
6. Console: paste the §5.4 snippet → `copy(JSON.stringify(readback, null, 1))` →
   `<date>-<state>-1.probes.json`.
7. Screenshot + *Save image as* for the result (A4/A5).
8. Append the MANIFEST line (P6).

### 5.3 Route B — Playwright (scripted, reproducible)

```bash
# you log in by hand in the opened browser; the HAR is written when you close it
npx playwright open --save-har="captures/<date>-<state>.har" \
                    --save-har-glob="**/arena.ai/**" https://arena.ai/image/direct
```

Python equivalent for a capture script (owner-run, never in CI) — `record_har_content="embed"`
keeps bodies inside the file, `service_workers="block"` because service-worker requests bypass HAR
routing, and the HAR is only written on `context.close()`, so close it in a `finally`.

### 5.4 The probe read-back snippet (paste into the real page's Console)

It prints exactly what the app's own probes would see, so a capture can be validated against
contracts B and C *before* any fixture is written. It is read-only (no clicks, no mutations) and it
re-uses the app's selector strings by hand — the ingest test then asserts the fake page answers the
same way (`evidence.md` §3/§4, D-15):

```js
(() => {
  const q = (s) => document.querySelector(s);
  const ta = q('textarea[name="message"]');
  const send = q('button[aria-label="Send message"]');
  const ol = q('ol');
  const imgs = [...document.querySelectorAll('img')].map((i) => ({
    src: (i.currentSrc || i.src || '').split('?')[0].slice(-80),
    natural: [i.naturalWidth, i.naturalHeight], opacity: getComputedStyle(i).opacity }));
  return {
    ready: { textarea: !!ta, rows: ta?.getAttribute('rows'), value_len: ta?.value.length ?? -1,
             file_input: !!q('input[type="file"]'), add_files: !!q('button:has(svg)') },
    send: { found: !!send, disabled: send?.disabled ?? null,
            aria: send?.getAttribute('aria-label') ?? null },
    generating: { spinner: !!q('div.animate-spin'), label: q('span.truncate')?.textContent ?? null },
    layout: { tag: ol?.tagName ?? null, reverse: !!q('ol.flex-col-reverse'),
              flexDirection: ol ? getComputedStyle(ol).flexDirection : null },
    outputs: imgs.filter((i) => /r2\.cloudflarestorage\.com|messages-prod/.test(i.src)),
    new_chat: [...document.querySelectorAll('a')].filter((a) => /image\/direct/.test(a.getAttribute('href') || ''))
                .map((a) => a.getAttribute('href')),
    security: { dialog: !!q('[role="dialog"]'), badge: !!q('.grecaptcha-badge'),
                badge_visible: q('.grecaptcha-badge') ? getComputedStyle(q('.grecaptcha-badge')).visibility : null },
    jobids: (document.body.innerText.match(/\[JOB-ID:\s*[^\]\s]+\]/g) || []).slice(0, 5),
  };
})()
```

The `new_chat` array settles **L-16** with a fact (relative `href="/image/direct"` vs absolute
`https://arena.ai/image/direct`), and `outputs` settles **L-17** (does a generating/finished state
really expose `.r2.cloudflarestorage.com/` URLs, and in which layout order).

### 5.5 Route C — the app's own recorder (DOM side, already sanitized)

With the Captcha Watcher **ON**, every visible captcha encounter on a CDP-backed tab starts a
bounded recording automatically (`config/captcha_recordings/<session-id>/`: manifest, append-only
DOM-mutation and sanitized network-lifecycle events, capped textual bodies, gzip DOM checkpoints —
SYSTEM_OF_RECORD row 22); the **Records** window (`recordings`) lists sessions, lets you label
ground truth and diff two sessions side by side, and has an *Open folder* action. Use it for the
`security_required` state and for mutation order. It cannot give you image bytes
(`app/browser/recording_js/netwrap.js:3`) — that is route A/B's job.

### 5.6 Route D — mitmproxy (fallback only)

`mitmdump --set hardump="captures/<state>.har"` with the browser proxied and the mitmproxy CA
installed. Use it only when DevTools cannot hold the capture (very long generations, or a scripted
capture without DevTools open). It is a machine-wide trust change: owner-run, never automated, never
in CI, and its output goes through the same §6 sanitization.

### 5.7 What NOT to record

Cookies, `Set-Cookie`, `Authorization`, `cf_clearance`, `g-recaptcha-response` tokens, the 2Captcha
key, account e-mail/username, conversation text beyond the `[JOB-ID: …]` line, signed-URL query
strings (`X-Amz-Signature`, `signature=`, `token=`, `Expires`+`Signature` pairs). Chrome's sanitized
export removes three of these for you — **the rest is your job and the ingest's** (§6, §10).

## 6. From capture to fixture — the planned ingest (`tools/har_ingest.py`, owner-run)

Not built yet; specified here so the captures you take today are usable by the stage that lands it.
Budget: ≤150 LOC, functions ≤20 lines, ≤3 params (`quality-budget.md` §3 pattern), **never** part of
`pre_push_check.sh`, browser-free, and its own unit tests run in the default lane (<1 s).

```text
captures/<date>-<state>-1.har  ─┐
captures/<date>-<state>-1.html ─┼─► tools/har_ingest.py ─► tests/e2e/fixtures/recorded/
captures/<date>-<state>-1.probes.json ─┘                        ├─ MANIFEST.json   (provenance + sha256 per artifact)
                                                                ├─ result-<state>.png (bytes, sha256 → fixtures/hashes.json)
                                                                ├─ api-shapes.json  (keys+types only, values dropped)
                                                                ├─ probe-readbacks/<state>.json   (A3, committed)
                                                                └─ facts/<state>.md (element facts for fixtures.md §2)
```

1. **Filter** entries by a host allowlist (`arena.ai`, `*.r2.cloudflarestorage.com`, `www.gstatic.com`)
   — everything else is dropped before anything is written.
2. **Sanitize with the app's own vocabulary, imported read-only (RULE 21 — one redaction source, no
   second copy):** `app/services/captcha_recording/sanitize.py:16` `safe_url` (drops query +
   fragment ⇒ kills signed-URL credentials while keeping the host/path shape D-6 needs), `:28`
   `redact_text` (bearer + ≥80-char token shapes), `:35` `clean_mapping` (secret-named keys), and
   `app/services/recording/sanitizer.py:53` `redact_url` (`_SECRET_PARAMS` list) + `:37`
   `redact_dom_html` for the HTML side.
3. **Extract**: `mimeType: image/*` bodies → bytes files + sha256; the document response → the
   element-facts rows; JSON bodies → shape skeletons (keys + types, values dropped); A3 → verbatim
   (it is already only booleans/short strings).
4. **Prove determinism**: the ingest is a pure function of its inputs, so re-running it on the same
   capture yields identical sha256s — a unit test asserts that (this is what makes I-57 evidence,
   not hope).
5. **Refuse to write** anything that still matches a secret pattern (`Bearer `, `eyJ`, ≥80-char
   token, `signature=`, an e-mail shape) — fail closed, the same standard as
   `app/services/captcha_recording/recorder.py:148` ("fail closed on violation").

**What is deliberately NOT taken from the capture:** no verbatim HTML is served (D-15 — the fake page
is rebuilt so it can be stateful, deterministic and free of third-party assets); no cookies/headers
are replayed (the local server is same-origin, the app needs none); no timings are replayed (the
state machine owns timing through `generation_ms`, D-17).

## 7. Replay — where the recorded bytes are actually used

| Use | Mechanism | Which plan item it strengthens |
|---|---|---|
| The saved file must equal the job's bytes | `result_bytes(job_id)` = the **recorded** result PNG (or the synthesized 64×64 base when no capture exists) + a `tEXt arena-job-id` chunk | I-57, D-7 — and it **closes L-17** with real evidence |
| The output-image primary selector needs `.r2.cloudflarestorage.com/` in the resolved `src` | the `/cdn/.r2.cloudflarestorage.com/<jobid>.png` route serves exactly the recorded bytes with the recorded `Content-Type` | D-6, `fixtures.md` §6 — the path trick is now proven against a recorded URL shape, not assumed |
| The fake page's payloads must look like the real ones | `api-shapes.json` is the checklist the page JS is reviewed against | contract C, `evidence.md` §4 |
| Fixtures must not drift from reality | **optional** S6 test: a *Playwright-owned* Chromium context loads the recorded page shell offline with `route_from_har(har, not_found="abort")` and asserts every registry selector still resolves | R6 — deliberately **not** inside the app-driven lane: `connect_over_cdp` is lower fidelity, cannot record on an existing context, and `page.route()` interception is not supported there (§2) |
| jsdom lane | consumes the same extracted artifacts (no browser, no HAR routing) | D-14 |

## 8. Tools summary — install, owner, when

| Tool | Role | Install | Who runs it | When | What lands in git |
|---|---|---|---|---|---|
| Chrome/Edge DevTools | primary recorder (A1/A2/A3/A5) | none (≥130) | **owner, by hand** | fixture refresh | nothing raw |
| Playwright CLI/Python | scripted recorder (A1) + optional asset-fidelity replay | `npm ci` (CLI) or the already-pinned `playwright` | owner; the replay check is a test | capture; S6 opt-in | extracted artifacts only |
| App's Records window / recorder | DOM + mutation capture, already sanitized (A7) | none | owner (Watcher ON + a captcha) | captcha states | nothing (`config/` is git-ignored) |
| mitmproxy | fallback recorder | `pip install mitmproxy` + CA | owner | only if routes A/B fail | nothing |
| `tools/har_ingest.py` *(planned)* | HAR → sanitized fixtures + hashes | in-repo, stdlib + the app's own redaction helpers | owner, manually; guarded by unit tests | after each capture | `tests/e2e/fixtures/recorded/**` (sanitized) |
| Rejected | Polly.js, WireMock, Mountebank, Nock, Cypress, BrowserMob/BrowserUp, Percy/Chromatic, Mocky/FakeJSON | — | — | — | reasons in §2 |

## 9. Capture schedule — what to record first (mapped to the stages)

| Priority | State to capture | Fixture it feeds | What it settles | Usable when |
|---|---|---|---|---|
| 1 | a **finished generation** (result image visible) | F5 `generation_success` | **L-17** (real result bytes + URL shape + layout order), I-57 evidence | A1 + A3 + A4 present, `outputs[]` non-empty in A3 |
| 2 | the **New Chat** anchor | F10 `new_chat_ready` | **L-16** (relative vs absolute `href`) | A3 `new_chat[]` shows the literal `href` |
| 3 | a **generating** page (spinner up) | F4 `generating` | spinner markup, `Response A/B` label text, conversation-list layout | A3 `generating.spinner == true` + A2 |
| 4 | a **page error / refusal** toast | F6 `generation_error` | the exact toast wording ⇒ which `ERROR_PATTERNS` / `DEAD_GENERATION_PATTERNS` branch fires (D-18's submit count depends on it) | A2/A3 contain the toast text; A1 shows the failing request status |
| 5 | a **rate-limit** message | F9 `rate_limited` | `RATE_LIMIT_PATTERNS` wording + penalty path | toast text matches `page_errors.py:47` patterns |
| 6 | the **sign-in / auth** route | F8 `authentication_required` | L-10 honesty (what a not-ready page really looks like) | A1 shows the redirect, A2 has no composer |
| 7 | a **captcha** encounter | `security_required` | route C already does this automatically | a session folder exists under `config/captcha_recordings/` |
| — | endless generation | `generation_endless` | **cannot be captured** (negative state) — stays synthesized | n/a |

Stages: captures 1–3 before **S1** (the fixture freeze), 4–6 before **S4/S5**, 7 before **S7**.
The ingest tool itself lands as **S1a** (§11), between S1's fixture skeleton and S1's fixture freeze.

## 10. Rules, risks and ethics

* **Raw captures never enter git.** Put them in `arena webpages/captures/` (or outside the repo):
  `tools/pre_push_check.sh:40-46` and `tests/test_repo_hygiene.py:25-26` already fail a push that
  tracks anything under `config/`, `logs/` or `arena webpages/` (I-43).
* **Sanitized ≠ safe.** Chrome's export strips three headers only; tokens in query strings (signed
  CDN URLs) and personal data in bodies survive. The §6 redaction pass is mandatory, and a test
  asserts committed artifacts contain no `Bearer`, no ≥80-char token, no `signature=`/`X-Amz-*`, no
  e-mail shape.
* **No live site in an automated test** (RULE 20 / C-3): recording is a human, owner-authorized,
  one-off act; the suite only ever talks to `127.0.0.1` (I-56).
* **Captures go stale.** The site changes classes; `MANIFEST.json` records the capture date and
  browser, and the drift guards are the registry-resolution test plus the skip-gated
  `tests/js/test_e2e_fixtures_vs_saved_page.mjs` (D-15).
* **License/ethics.** Do not redistribute recorded HTML/CSS/JS assets; commit only small derived
  artifacts (a generated image you own, hashes, shape skeletons, probe read-backs). If in doubt keep
  them local — every lane is skip-gated, so the suite degrades to a loud skip, never a lie. These
  techniques are for testing your own automation against pages you are authorized to use; never for
  cloning or deceiving.

## 11. Deltas to the rest of this plan (applied in this round)

| Doc | Delta |
|---|---|
| `design.md` | new **D-23 HAR-first fixture provenance** (this file is its evidence); **D-15** amended — "rebuilt, not dumped" becomes "rebuilt **from recorded evidence**, never served verbatim"; risk **R6** downgraded (drift is now detected against a dated capture); stage **S1a** inserted (owner-run ingest between the fixture skeleton and the fixture freeze) |
| `fixtures.md` | new **§10 Provenance** — per fixture: `committed-dump` / `recorded:<capture-id>` / `synthesized`, and which capture closes L-16/L-17 |
| `evidence.md` | §6 gains the in-house recorder as a reusable asset; **L-17** gains its closure path |
| `quality-budget.md` | `tools/har_ingest.py` + `tests/e2e/test_har_ingest_unit.py` budget rows (owner-run, out of the push budget, browser-free) |
| `tdd-interfaces.md` | **S1a** interfaces + 5 RED tests (sanitize-equivalence with the app's helpers, determinism, host allowlist, fail-closed on secrets, shape extraction) |
| `docs/README.md` | one clause on the existing archive row (RULE 17) |
| `docs/current/SYSTEM_OF_RECORD.md` | **untouched** — still plan-only; I-55…I-59 and row 22's pointers land with the code |

## 12. RULE recheck for this round

* **RULE 16** — no `app/` change; the only new tool (`tools/har_ingest.py`) is owner-run, outside
  the push budget, with its own browser-free tests; `tools/` is not in the size/CC scope
  (`verify_quality.py:162` scans `app/`), so it carries a self-imposed RULE 18 budget instead.
* **RULE 17** — this is a dated archive file in the plan folder; `docs/README.md` gains a clause;
  `docs/current/*` untouched until code lands.
* **RULE 18** — this file ~330 lines, read section-wise from `README.md` (not a context file);
  planned ingest ≤150 LOC / ≤20-line functions / ≤3 params.
* **RULE 21** — redaction and selectors are **imported, not copied**: `sanitize.py` /
  `sanitizer.py` for redaction, `probe_selectors.py` for selectors; the §5.4 snippet is a *capture
  aid* for a human console, never a second registry inside the app or the fixtures.
* **RULE 8 / RULE 20** — evidence comes from the real page (recorded by you, once), while every
  automated run stays offline against a fake page; no captcha is ever solved or bypassed by this
  round (§5.5 only *observes* what the app's own recorder already produces).
