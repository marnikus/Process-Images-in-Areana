# Fixtures — the fake pages, their state machine and their bytes

Companion to `design.md` (decisions D-5…D-7, D-15…D-17) and `evidence.md` §3–§4 (the contracts
these pages must satisfy). Everything here is a **specification**; no code exists yet.

Source of truth for the DOM: the committed saved page
`docs/research/Directly Chat with Frontier Image Generation AI Models.html` (386 396 B, tracked,
an **empty chat** state saved from `https://arena.ai/image/direct`) read together with
`docs/current/DOM_SELECTORS.md` and `app/browser/site_adapter.py`. The owner's local git-ignored
`arena webpages/state*` dumps (captcha-on, normal) are design-time evidence only (I-43).

---

## 1. Fixture inventory — 10 saved states → 10 reproducible page states

| # | Real saved state (research) | Fixture | How it is produced | App probes it exercises |
|---|---|---|---|---|
| F1 | clean ready page (the committed dump: empty `ol.flex-col-reverse`, composer, badge) | `chat.html` + `scenario=ready_only` | server renders the skeleton, no conversation items | `JS_PAGE_READY` (`js_snippets.py:182-200`), readiness composite (`site_adapter.py:257-264`), `OBSERVE_BASELINE` with 0 outputs |
| F2 | image selected, preview visible | `attachment_ready` | page JS handles the real `change` event of the file input → `URL.createObjectURL` tile | `JS_VERIFY_ATTACHMENT` (`js_snippets.py:111-129`), `ATTACH_IMAGE` (A7 `DOM.setFileInputFiles`) |
| F3 | prompt entered | `prompt_ready` | value set through the native setter by the app itself | `JS_INSERT_PROMPT` / `JS_VERIFY_PROMPT` (RULE 22 read-back) |
| F4 | generation running (Response A/B spinner) | `generating` | scenario timer keeps `div.animate-spin` visible | `JS_CHECK_NEW_OUTPUT_V3` spinner branch (`output_probes.py:697`), `JS_IS_GENERATING`, `AWAIT_PROCESSING_IMAGE` (`app/browser/processing_probe.py`) |
| F5 | generation completed with image | `generation_success` | new `<li>` message block + result `<img>` under `/cdn/.r2.cloudflarestorage.com/<job>.png` | baseline→new correlation, JOB-ID association, `JS_DOWNLOAD_IMAGE` |
| F6 | page generation error | `generation_error` | `[role="alert"]` toast with the scenario's text | `build_error_scan_js` + `match_page_error` (`page_errors.py:85-139`), `PageErrorAbort`, revival (D-18) |
| F7 | security verification visible | `security_required` | Radix-shaped `div[role="dialog"][data-state="open"]` + "Security Verification" + placeholder reCAPTCHA frame | `captcha_js/visible.js`, `detect.js`, `CHECK_SECURITY`, `handle_captcha` wait-only path (Watcher ON only) |
| F8 | authentication / sign-in required | `authentication_required` | a **different route** (`/signin`) with no composer | readiness gate fails with reasons (`is_page_ready`), `new_chat` never reached; documents L-10 (`test_url` cannot see it) |
| F9 | rate-limit message | `rate_limited` | toast "Daily limit reached — try again tomorrow" | `is_rate_limit_error` (`page_errors.py:94`) → `maybe_note_rate_limit` (`cooldown_service.py:438`) → stacked penalty |
| F10 | clean New Chat page | `new_chat_ready` | real navigation to `/image/direct` (the anchor click) → skeleton again, composer empty | `reset_to_new_chat` (`new_chat.py:183-194`): document complete + readiness (fresh-chat tolerance `:139-152`) + empty composer |

Not fixtures (deliberately): screenshots (brief §4 forbids them as the implementation), the raw
saved dumps (secrets + 386 KB each), any live Google/reCAPTCHA asset (RULE 20).

---

## 2. The page skeleton — element-by-element contract

Real snippets below are quoted from the committed dump (whitespace trimmed); the fixture keeps the
attributes the registry needs and drops the rest. "States" = the page states in which the element
must be present/visible.

| Element | Fixture markup (required attributes in **bold**) | Registry key | States |
|---|---|---|---|
| Composer form | `<form class="**flex w-full flex-col** items-start justify-center p-2">` (real dump) | `composer_form` (`site_adapter.py:224`) | all except F8 |
| Prompt textarea | `<textarea **rows="1"** **name="message"** **autocomplete="off"** **placeholder="Describe the image you want to generate…"** class="box-border w-full flex-none resize-none … max-h-[40vh] p-1 md:p-3 md:min-h-[72px]" style="height:48px !important">` (real dump) | `prompt_textarea` (`:120`) | all except F8; **empty** in F1/F10 |
| File input | `<input **accept="image/png,.png,image/jpeg,.jpg,.jpeg,image/webp,.webp"** multiple tabindex="-1" class="**hidden**" **type="file**" style="border:0;clip:rect(0,0,0,0);clip-path:inset(50%);height:1px;…">` (real dump) | `file_input` (`:61`) | all except F8; hidden but present (readiness uses the presence selector `input[type="file"]`) |
| Add-files button | `<button type="button" **aria-label="Add files"** class="touch-hitbox text-text-secondary …">` inside `<div class="mr-1 flex h-8 min-w-0 **items-center gap-2**">` (real dump) | `add_files_button` (`:44`) | all except F8 |
| Send button | `<button … class="… **opacity-50 pointer-events-none**" **disabled** type="button" **aria-label="Send message**"><svg …/></button>` (real dump, empty-composer form) — the fixture removes `disabled` + the two classes as soon as the composer has a prompt or an attachment | `send_button` (`:135`) | all except F8; enabled from `submit_enabled` |
| Attachment preview | `<div class="**flex flex-wrap gap-2**">` → tile `<div class="group relative overflow-hidden rounded-lg **h-16 w-16**">` → `<img **alt="<file name>"** src="blob:…" data-w="64" data-h="64">` + `<button **aria-label="Remove file"**>` | `attachment_preview_container` (`:77`), `attachment_preview_image` (`:89`), `remove_file_button` (`:105`) | `attachment_ready` … `submitted` |
| Conversation list | `<ol class="mt-8 flex w-full max-w-screen-xl grow **flex-col-reverse** justify-end gap-4 overscroll-none pb-2 duration-500">` (real dump — **the live layout is column-reverse**) inside `<div class="**no-scrollbar relative flex w-full flex-1 flex-col overflow-x-auto** transition-[max-height] duration-300">` (real dump) | `output_region` (`:151`), reverse-layout detection `output_probes.py:96-108` | all except F8 |
| User message block | `<li data-message-id="m<n>" class="flex min-w-0 flex-1 flex-col **items-end**"><div class="…"><p>[JOB-ID: 20260927-101504-A7F3]\na red circle</p></div></li>` — the **exact** text the app inserted, so the JOB-ID regex `output_probes.py:121` finds it | correlation anchor | from `submitted` |
| Assistant/result block | `<li data-message-id="m<n+1>" class="flex min-w-0 flex-1 flex-col"><div class="flex gap-3"><img **src="/cdn/.r2.cloudflarestorage.com/<job>.png"** class="**aspect-square** cursor-pointer w-full" loading="lazy" data-w="64" data-h="64"></div></li>` | `output_image` (`:167`) | `generation_success` (+ `result_after_timeout`) |
| Baseline (old) image | same shape, `src="/cdn/.r2.cloudflarestorage.com/baseline-old.png"`, rendered **before** the run starts | `output_image` — must be captured by `OBSERVE_BASELINE` and never accepted | F1 variant `with_baseline` |
| Spinner row | `<div class="flex min-w-0 flex-1 items-center gap-2"><div class="**h-5 w-5 flex-shrink-0 animate-spin**"><canvas width="28" height="28"></canvas></div><span class="**truncate**">Response A</span></div>` (user HTML quoted in `site_adapter.py:38`) | `processing_spinner` (`:32`), `model_label` (`:18`) | `generating`, `generation_endless` |
| Model row (idle) | `<div class="flex min-w-0 flex-1 items-center gap-2"><span class="**truncate**">Max</span></div>` (real dump) | `model_label` | `ready` … `submitted` |
| Error / rate-limit toast | `<div **role="alert"** class="error-toast …">Generation failed — internal error. Trace ID: 8f3a-2c</div>` (must match one of the `page_errors.py:118-124` scan selectors) | — | `generation_error`, `rate_limited` |
| Security dialog | `<div **role="dialog"** **data-state="open"** class="…">… <h2>Security Verification</h2> … <iframe **title="reCAPTCHA"** src="/assets/recaptcha-placeholder.html"></iframe> <div id="**recaptcha-v2-container**"></div></div>` | `security_dialog` (`:194`), `recaptcha_iframe` (`:208`) | `security_required` |
| reCAPTCHA badge (always) | `<div class="**grecaptcha-badge**" data-style="bottomright" style="width:256px;height:60px;position:fixed;**visibility:hidden**;display:block;right:-186px">` (real dump) — present in **every** state, never a challenge | badge exclusion (`docs/archive/2026-09-18-captcha-visual-await/design.md`) | all |
| New Chat link | `<li **data-sidebar="menu-item"**><a **data-sidebar="menu-button"** **href="/image/direct"** …><svg …/><span>**New Chat**</span></a></li>` (real dump has the same node with an **absolute** href — see §9 L-16) | `new_chat_button` (`:238`) | all except F8 |
| Sign-in page (F8) | `/signin` route: heading "Sign in to Arena", no form, no textarea | readiness must fail with `prompt not found` / `send not found` | `authentication_required` |
| Watcher overlay host | none — the app injects its own overlay (`dom_highlight.py:304-320`); the fixture only has to tolerate `position:fixed` children with `pointer-events:none` | I-1 | all |

Rules: no external URL anywhere (no fonts, no analytics, no CDN, no Google frame — I-56); no
generated ids the registry does not use; every `<img>` carries `data-w`/`data-h` so the jsdom
layout shim can answer `naturalWidth` (D-14); all timings come from the scenario JSON, never from
`Math.random()`.

---

## 3. Page state machine

States (`body[data-arena-state]` mirrors the current state — **test-only**, no app selector reads
it): `ready`, `attachment_uploading`, `attachment_ready`, `prompt_ready`, `submit_enabled`,
`submitted`, `generating`, `generation_success`, `generation_error`, `generation_endless`,
`security_required`, `authentication_required`, `rate_limited`, `new_chat_ready`.

| From | To | Trigger | Observable marker (contract B) |
|---|---|---|---|
| `ready` | `attachment_uploading` | file input `change` (real upload from A7 / `set_input_files`) | preview container created, tile not yet rendered |
| `attachment_uploading` | `attachment_ready` | scenario `upload_delay_ms` (default 120) | tile `img[alt=<name>]` + `blob:` src visible |
| `attachment_uploading` | `ready` | scenario `upload_rejected` | tile never rendered, `[role="alert"]` "Upload failed — file rejected" |
| `attachment_ready` | `prompt_ready` | textarea value set (native setter + `input`/`change`) | value equals the inserted prompt |
| `prompt_ready` | `submit_enabled` | same tick (React-style enable) unless scenario `send_disabled` | Send loses `disabled` + `opacity-50 pointer-events-none` |
| `submit_enabled` | `submitted` | Send click (**counted**, `sendCount++`, `trigger:"send"`) | user message `<li>` with the exact prompt text appended; composer cleared; textarea disabled until reset |
| `submitted` | `generating` | scenario `spinner_delay_ms` (default 50) | `div.animate-spin` + `span.truncate` "Response A" visible |
| `submitted` | `security_required` | scenario `captcha_before_submit` | dialog `data-state="open"` + "Security Verification" |
| `generating` | `generation_success` | scenario `generation_ms` (300 default) | spinner removed; result `<li>` + `<img>` appended after the user block |
| `generating` | `generation_error` | scenario `error_at_ms` | toast text from the scenario (`terminal` / `dead_request` / `rate_limit`) |
| `generating` | `generation_endless` | scenario `endless: true` | spinner stays forever, nothing else changes |
| `generating` | `spinner_lost_no_output` (a `generating` variant) | scenario `spinner_lost_at_ms` | spinner removed, **no** result — the revival signature (`recovery.py:126-133`) |
| `generation_success` | `new_chat_ready` | New Chat anchor click → **real navigation** to `/image/direct` | document complete, empty `ol`, empty composer, badge still present |
| `generation_error` / `generation_endless` | `new_chat_ready` | same | same |
| any | `authentication_required` | scenario `auth_expired_after_submit` → navigate `/signin` | readiness fails, no composer |
| any | `ready` | `POST /__test/reset` (test-only) | skeleton re-rendered without navigation |

Every transition is `POST`ed to `/__test/event` (D-17): `{t, from, to, trigger, detail, sendCount}`.
Guard rails in the page: a second Send while `generating` is recorded as `trigger:"submit_ignored"`
and changes nothing (so a double-submit bug is visible but does not corrupt the state); a result is
only ever appended for the job id parsed out of the submitted prompt (so a stale result cannot be
manufactured by accident).

---

## 4. Scenario schema + the 20 scenarios

```json
{"name": "generation_endless",
 "route": "/image/direct", "with_baseline": true,
 "states": ["ready","attachment_uploading","attachment_ready","prompt_ready","submit_enabled",
            "submitted","generating","generation_endless"],
 "timings": {"upload_delay_ms": 120, "spinner_delay_ms": 50, "generation_ms": null},
 "flags": {"endless": true, "send_disabled": false, "submit_ignored": false,
           "prompt_modified": false, "preview_missing": false, "stale_preview": false,
           "result_is_old": false, "result_invalid": false, "download_html": false,
           "captcha_before_submit": false, "auth_expired_after_submit": false,
           "rate_limit": false, "new_chat_fails": false, "layout": "reverse"},
 "error_text": null,
 "expected": {"send_count": 1, "result_served": false}}
```

| Scenario | Key flags / timings | Expected app outcome (contract row) |
|---|---|---|
| `success_immediate` | `generation_ms 300`, reverse layout | job completed, `<base>_AI.png` = `result_bytes(job)`, `sendCount 1` |
| `success_delayed` | `generation_ms 4000` | same, wall time ≈ 4 s + the 3 s settle before `download_image` (`single_job_runner.py:333-336`) |
| `layout_normal` | `layout: "normal"` (`ol` without `flex-col-reverse`) | same — proves the below/above-prompt branch both ways (`output_probes.py:496-505`) |
| `with_baseline_old_image` | `with_baseline true` | the old image is in the baseline and is **never** accepted |
| `upload_rejected` | alert on upload | `ATTACH_IMAGE`/`VERIFY_ATTACHMENT` fail, no submit (`sendCount 0`), job failed, nothing saved |
| `attachment_preview_missing` | `preview_missing true` | `VERIFY_ATTACHMENT` fails with `Not found: …`; job outcome per `required` flag (RULE 9 / B9 forgiveness) |
| `stale_attachment_preview` | `stale_preview true` (a tile from a previous job stays) | the app must verify the **new** tile (`alt == pic1.png`), not the stale one |
| `prompt_value_modified` | page truncates the value after insert | `VERIFY_PROMPT` mismatch (RULE 22) |
| `send_disabled` | `send_disabled true` | `submit_when_ready` → `send disabled` (`cdp_arena/submit.py:80-84`), `sendCount 0` |
| `submit_ignored` | click recorded, no state change | no `submitted` transition, wait times out, `sendCount 1` |
| `generation_error_terminal` | "Generation failed — internal error. Trace ID: …" | fast abort (I-30), `Page error: …`, `sendCount 1`, nothing saved |
| `generation_error_dead_request` | "Something went wrong while generating… Please try again." | one revival (`sendCount 2`, `trigger:"resubmit"`), then failure (D-18/L-14) |
| `rate_limited` | "Daily limit reached — try again tomorrow" | failure text carries the rate-limit signal; `cooldown_total == base + rate_limit_penalty` |
| `generation_endless` | `endless true` | timeout at the configured value, `sendCount 1`, reset → `new_chat_ready`, next job succeeds |
| `spinner_lost_no_output` | spinner removed at 25 s (test: 3 s) with no result | revival window matures (`RESUME_GRACE_SEC 20`) ⇒ `sendCount 2`, then timeout |
| `result_after_timeout` | result appended 2 s **after** the timeout | the job already failed; no save happens after the fact (RULE 15 fails closed) |
| `result_is_old` | serves `baseline-old.png` bytes for the result | rejected (baseline + JOB-ID), nothing saved |
| `result_invalid_image` | 1×1 corrupt PNG / truncated bytes | `VALIDATE` fails (`verification.py:38-71`), nothing saved |
| `download_returns_html` | result URL answers HTML with `Content-Type: image/png` | `JS_DOWNLOAD_IMAGE` rejects (`<html` check), Python fallback rejects (`download.py:39-42`), job failed |
| `output_name_exists` | test pre-creates `<base>_AI.png` | saved as `<base>_AI_2.png` (RULE 23, `app/core/naming.py:14,24,65`) |
| `destination_readonly` | test chmods the folder (POSIX) / ACL skip on Windows | honest failure, no `.partial_*` left (RULE 23) |
| `new_chat_reset_failure` | `new_chat_fails true` (anchor missing) | `↩ New-chat reset failed: …`, job outcome unchanged, cooldown starts, pool never stuck busy |
| `new_chat_absolute_href` | anchor `href="https://arena.ai/image/direct"` (as in the committed dump) | **documents L-16**: FIND fails on all three candidates, reset fails, job still completes |
| `captcha_before_submit` | dialog before submit, Watcher **ON** | `handle_captcha` waits (`waiting_captcha` pool row + overlay), never solves in the pipeline (I-34) |
| `captcha_during_generation` | dialog appears while generating, Watcher ON | generation timeout paused + capped (I-47), `+Ns captcha wait (cap Ms)` in the text |
| `authentication_required` / `auth_expired_after_submit` | `/signin` route | readiness fails with reasons; no job dispatched (or job failed after submit); documents L-10 |

(`expected` in the schema is documentation for the fixture author; the **authoritative**
expectations live in `tests/e2e/contract.py` — one owner, D-10.)

---

## 5. Fake images — bytes, hashes, uniqueness

| Fixture | Size | Purpose | Bytes |
|---|---|---|---|
| `fixtures/source-1.png` | 48×48, <1 KB | the real source image copied into the temp folder before the scan | solid colour + a `tEXt` `arena-fixture=source-1` |
| `fixtures/source-2.png` | 48×48 | the second (unselected / second-job) source | `arena-fixture=source-2` |
| `fixtures/baseline-old.png` | 32×32 | the pre-existing page image that must never be accepted | `arena-fixture=baseline-old` |
| `fixtures/result-base.png` | 64×64 | the pre-generated "AI result" the page posts (owner: *"fake it with just saved pre-generated image posted in html"*) | `arena-fixture=result-base` |
| `fixtures/hashes.json` | — | sha256 + dimensions of all four, asserted by `test_fakesite_unit.py` so a fixture edit is a visible contract change | — |

`artifacts.result_bytes(job_id)` = `result-base.png` + one `tEXt` chunk `arena-job-id=<job_id>`
inserted before `IEND` (pure `struct`/`zlib`, ~20 LOC, no Pillow needed to build; Pillow is used
only to *verify* dimensions the way `VALIDATE` does). Consequences: bytes are a deterministic
function of the job id, decodable as a real PNG, 64×64 (>0, RULE 15), distinguishable from every
other fixture, and served only after the configured generation transition (D-7). The same function
is used by the page (server side) and by the assertion (test side) — one owner, no copies.

Served URLs: `/cdn/.r2.cloudflarestorage.com/<job-id>.png` (result, D-6),
`/cdn/.r2.cloudflarestorage.com/baseline-old.png` (baseline), `/assets/recaptcha-placeholder.html`
(inert frame), `/assets/fake-arena.js`, `/assets/fake-arena.css`. Every URL is same-origin.

---

## 6. Server routes

| Route | Method | Purpose | Notes |
|---|---|---|---|
| `/image/direct` | GET | the chat page (F1…F7, F9, F10) | renders `chat.html` with the resolved scenario baked into `body[data-scenario]` + a `<script>` config object |
| `/signin` | GET | F8 authentication state | no composer at all |
| `/assets/*` | GET | js/css/placeholder frame | no external requests, cache-control no-store |
| `/cdn/.r2.cloudflarestorage.com/<name>.png` | GET | result / baseline bytes | `<name>` = job id ⇒ `result_bytes(job_id)`; `Content-Type: image/png`; `download_returns_html` overrides both |
| `/__test/state` | GET | current state + scenario + counters | debugging + evidence |
| `/__test/log` | GET | ordered event log (D-17) | the page-trace evidence source |
| `/__test/scenario` | POST | switch scenario mid-test (recovery job) | sets the cookie so a navigation keeps it |
| `/__test/event` | POST | page → server transition report | fire-and-forget, `keepalive: true` |
| `/__test/reset` | POST | re-render the skeleton without navigation | used by teardown and `new_chat_reset_failure` |
| `/__test/health` | GET | liveness for the fixture setup | first thing `wait_until` checks |

All `/__test/*` routes 404 unless the server was built with `allow_control=True`; the server binds
`127.0.0.1` and refuses non-`Host: 127.0.0.1|localhost` requests (I-56).

---

## 7. Layout + geometry contract

The committed dump proves the live conversation list is `ol.flex-col-reverse` (§2), so:

* the **default** fixture layout is `reverse` — the app's `layoutReverse` branch
  (`output_probes.py:96-108`) is the normal path, and the result must be *visually* below the user
  prompt block, which in a reversed flex column means **earlier in DOM order**;
* `layout_normal` is the variant scenario, so both branches of
  `output_probes.py:496-505`/`:596-604` are covered;
* geometry the probes need: distinct `rect.top` per message block (≥80 px apart), non-zero
  `width/height` on the result image, `offsetParent !== null` for everything visible,
  `getComputedStyle(img).opacity == "1"` (the baseline probe reads it, `output_probes.py:36,45`);
* real browsers provide all of this natively; the jsdom lane reproduces it with the layout shim
  (D-14) from document order + `data-w`/`data-h`, which is why every fixture `<img>` carries them;
* the result image must be `complete && naturalWidth > 0` **before** the app polls it: the page
  waits for the `load` event of the injected `<img>` before flipping to `generation_success`
  (otherwise the test would race the decode — a real-browser-only flake the fixture must own).

---

## 8. Sanitization + hygiene rules (brief §4, I-43)

1. No secrets, cookies, tokens, e-mails, account names, or user data — the fixtures are written
   from scratch; nothing is copied verbatim from a saved dump except **markup shape**.
2. No external asset, script, font or endpoint; `test_fakesite_unit.py` greps `static/*` for
   `http://`, `https://`, `//` protocol-relative URLs and fails on any (the one allowed literal is
   the `.r2.cloudflarestorage.com` **path segment**, which is same-origin — the guard asserts it is
   never a host).
3. No live reCAPTCHA: the frame is a local inert HTML placeholder; the badge is a styled `div`.
   Nothing in the suite solves, submits or bypasses a captcha (RULE 20).
4. Generated ids that the registry does not use are dropped; ids the registry *does* use
   (`recaptcha-v2-container`, `g-recaptcha-response`) are kept byte-identical.
5. Selectors stay synchronized with `app/browser/site_adapter.py` by construction: the guard test
   resolves **every** primary + fallback of all 15 registry keys in the fixture DOM (jsdom) and
   reports which ones match — a registry edit that the fixture does not follow fails the suite.
6. Nothing under `arena webpages/`, `config/`, `logs/` is read at test time; the skip-gated
   cross-check (`tests/js/test_e2e_fixtures_vs_saved_page.mjs`) reads the owner's dumps only when
   present and never writes them anywhere (I-43, `tests/test_repo_hygiene.py`).
7. Each fixture element is documented with the probe/action it supports (§2 last column) — the
   brief's "document which application probe each element supports".

---

## 9. What the fixtures surface (defects, recorded not fixed)

| ID | Finding | Evidence | Plan |
|---|---|---|---|
| **L-16** | The committed saved page's New Chat anchor is `href="https://arena.ai/image/direct"` (absolute), while **all three** registry candidates require the literal `href="/image/direct"` — on that page state the post-job reset cannot find the button | dump: `<a … data-sidebar="menu-button" … href="https://arena.ai/image/direct"><svg …/><span>New Chat</span></a>` vs `site_adapter.py:238-250` | default fixture uses the **relative** href (matching `DOM_SELECTORS.md` §"user HTML 2026-09-16") so the reset path is testable; **capture #2 of `record-replay.md` §9 settles this with a fact** (the read-back prints the literal `href`); scenario `new_chat_absolute_href` reproduces the absolute form and pins today's honest outcome (`↩ New-chat reset failed: new-chat button not found`, job still completes, cooldown still starts). Follow-up (production, out of scope): add `a[href$="/image/direct"]` as a candidate in `site_adapter.py` + `DOM_SELECTORS.md` |
| **L-17** | The saved empty-chat page contains **no** `.r2.cloudflarestorage.com` / `messages-prod` image at all, so the primary output selector's evidence comes only from a generating/completed state that is not committed | `grep -c` = 0 for both markers in the dump; `DOM_SELECTORS.md:199` says the same | the result/baseline fixtures **are** that missing evidence, committed as tiny PNGs + the `/cdn/.r2…/` route, so the primary selector is exercised by a test rather than by a note. **Closed by D-23**: capture #1 (a finished generation) yields the real result bytes + the real `.r2…` URL shape through `tools/har_ingest.py` (`record-replay.md` §6, §9) |
| L-10, L-11, L-12, L-14, L-15 | see `evidence.md` §8 | — | asserted as current behaviour; recorded as follow-ups |

---

## 10. Provenance — where each fixture's facts come from (D-23, `record-replay.md`)

`committed-dump` = the committed saved page `docs/research/Directly Chat with Frontier Image
Generation AI Models.html` (an **empty** chat); `recorded:<n>` = the owner capture of that priority
in `record-replay.md` §9, reduced by `tools/har_ingest.py`; `synthesized` = built from
`DOM_SELECTORS.md` + the app's own probe requirements because no real state can be captured.

| Fixture | State | Provenance today | Becomes | Capture that upgrades it |
|---|---|---|---|---|
| F1 | `ready` (empty chat) | committed-dump | committed-dump + `recorded:3` | #3 generating page (same shell, spinner up) |
| F2 | `attachment_ready` | synthesized (from `site_adapter.py:77,89` + the dump's file input) | `recorded:1` | #1 finished generation (upload happened there) |
| F3 | prompt inserted | synthesized (`JS_VERIFY_PROMPT` contract) | `recorded:1` | #1 |
| F4 | `generating` | synthesized (`div.animate-spin` + `span.truncate` from user HTML notes) | **`recorded:3`** | #3 — the dump is empty, so this is the biggest gap after F5 |
| F5 | `generation_success` | synthesized tiny PNGs (D-7) | **`recorded:1`** — real result bytes + sha256 + the real `.r2…` URL shape | #1 (closes **L-17**) |
| F6 | `generation_error` | synthesized toast text matched against `page_errors.py:15-39,64-66` | `recorded:4` | #4 — the wording decides the revival branch (D-18) |
| F7 | rate limit | synthesized (`page_errors.py:47-57`) | `recorded:5` | #5 |
| F8 | `authentication_required` | synthesized `/signin` route | `recorded:6` | #6 |
| F9 | captcha/badge | committed-dump (`.grecaptcha-badge`, always present, `visibility:hidden`) | committed-dump + route C session | #7 (the app's own recorder) |
| F10 | `new_chat_ready` | committed-dump anchor (**absolute** href ⇒ L-16) | **`recorded:2`** | #2 (settles **L-16**) |
| — | `generation_endless` | synthesized | synthesized | cannot be captured (negative state) |

Rule: a fixture whose provenance is `synthesized` must say **which contract line forced its shape**
(the table's third column does), so a reviewer can tell "invented" from "derived". After S1a every
upgraded row cites its `MANIFEST.json` capture id and date.
