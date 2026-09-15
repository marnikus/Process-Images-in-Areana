# 01 — Research, evidence, and selector strategy

## Method and limits

Inspected the tracked file tree, legacy entrypoint/bootstrap and selected persistence/browser modules, dependency/test/gate configuration, current documentation and rules, UI module inventory, and every saved HTML document outside the app's own UI. HTML was parsed offline; no saved scripts were executed, authenticated URLs opened, or generation submitted. Asset folders were inventoried by type. Minified bundles and private chat media are not evidence of a verified live action. No standalone workflow screenshots were found. Runtime visibility, event handling, authentication, original download resolution, and completion cannot be established by static HTML alone.

This is a focused architecture/source assessment, not an audit of every line in the 499 legacy Python files or every archived design. Old rule claims and coverage reports are historical, not measured results for the new app.

## Evidence register

Paths below are relative to repository root. `OLD` means `Process Images in Areana/Old App/`.

| ID | Material | Findings and relevance |
|---|---|---|
| E1 | `Directly Chat with Frontier Image Generation AI Models.html` (386,396 bytes) | Actual image-generation UI; image composer, existing submitted input image, model/loading indicators and Stop generation. Also contains another Agent Mode surface. Saved source is an exact Arena `/c/<conversation-id>` URL; keep private identifier in original evidence, not logs/examples. |
| E1a | `Directly Chat with Frontier Image Generation AI Models_files/` | 85 downloaded JS bundles, 6 CSS files, 4 HTML subdocuments, 2 PNGs, 1 JPEG, 1 extensionless resource. Assets are supporting captures, not additional complete workflow states. JPEG corresponds to the existing submitted `01-c.jpeg`; PNG references are account/branding assets, not workflow screenshots. |
| E2 | `OLD/Restore/From Webpage Code saved/Arena _ Benchmark & Compare the Best AI Models.html` (35,840,419 bytes) | Large saved **Agent Mode development conversation**, not an image-result walkthrough. No `textarea[name="message"]`, one untyped-accept file input, no form. Download file controls here relate to agent artifacts, not proof of image-original downloading. |
| E2a | Corresponding `Arena _ Benchmark & Compare the Best AI Models_files/` | Downloaded app bundles/styles, account image, reCAPTCHA anchor and three saved-resource HTML documents. Supporting resources, not image workflow evidence. |
| E3 | `OLD/Вирт чат.html` (622,976 bytes) | Legacy chat roster/message UI; Russian message placeholder and image upload. Unrelated target and personal media. Do not reuse selectors. |
| E4 | `OLD/Вирт чат privat.html` (274,103 bytes) | Legacy private chat state; not Arena image editing. Do not import conversations or account data into new app. |
| E5 | User-supplied selector snippets in task | Reported preview `02-a.jpeg`, edit placeholder, Send submit button, signed output host and open Security Verification dialog. Useful partial evidence, **not independently verified saved whole-page states**. |

All ancillary saved HTML was inspected: E1's `anchor.html` reports reCAPTCHA verification, `bframe.html` contains Verify UI, and both saved-resource files are empty documents. E2's `anchor.html` is a reCAPTCHA anchor; its three saved-resource files have no useful visible workflow content. A saved challenge frame does not establish that the parent page currently blocks the user.

Saved files contain personal account/conversation information and potentially transient signed resources. Do not reproduce raw snapshots in docs, tests, logs, or diagnostics. Sanitize before creating fixtures. Keep original evidence temporarily until the owner approves retention/deletion; never ship it with the application.

## Comparison of states

| State | E1 actual capture | E2 | Task snippets / gap |
|---|---|---|---|
| Image composer | One `form` containing message textarea, image input, Add files | No equivalent image form | Edit placeholder differs from E1's generate placeholder |
| Add/upload | `Add files`, file input accepts PNG/JPEG/WebP, `multiple` attribute | Separate generic Agent Mode file input | Missing live Add-open/menu and file-picked sequence |
| Attached before submit | Not captured; existing image is **outside** form in submitted message structure | Not relevant | Filename-preview and Remove file reported only in E5 |
| Idle Send | Image form has Stop generation, not an idle submit control | Agent UI controls cannot substitute | E5 reports `type=submit`; E1 global Send is disabled `type=button` outside image form |
| Generating | Stop generation, four global `.animate-spin` matches | Agent processing is unrelated | “Max”/canvas alone insufficient |
| Completed output | No independently verified new generated image | Artifact controls are irrelevant | Signed-host output reported in E5, no paired baseline/response capture |
| Security | reCAPTCHA badge ancestor is `visibility:hidden`; challenge ancestor also hidden | Anchor resource exists | No `[role=dialog]` in either actual full capture; E5 open dialog needs capture |
| Sign-in/error/download | Not supplied as relevant image states | Not equivalent | Blocking evidence gap |

## Selector map (proposed contracts, not shipped selectors)

Verification date for static E1/E2 observations: **2026-09-15**. Runtime verification date/version: **not yet available**.

Use role/name first, stable form relationships second, short qualified class fragments only as fallback. Require a unique intended scope; never resolve ambiguity with first/nth match. A selector matching static markup is not a readiness verdict.

| Element | Primary and ordered fallback | Scope / count / state | Required effect evidence | Source / confidence |
|---|---|---|---|---|
| Image composer | `form` containing `textarea[name="message"]` **and** image-accept file input; no verified alternative | One rendered intended image composer | Children belong to same form and configured conversation | E1 observed; dynamic stability unverified |
| Add | button role + exact name `Add files`; `button[aria-label="Add files"]` | Composer, 1, visible/enabled | Correct upload flow/input becomes usable; eventual preview verified | E1 observed; do not use generic “add” substring |
| File input | `input[type="file"]` inside composer; qualify `accept` including `image/png` if needed | Composer, 1, attached/enabled; **visibility not required** because deliberately hidden | Authorized file-input upload creates fresh composer preview matching filename/trusted file metadata | E1 observed; accepts `image/png,.png,image/jpeg,.jpg,.jpeg,image/webp,.webp`, multiple supported by markup, upload exactly one |
| Prompt | `textarea[name="message"]`; same with `autocomplete="off"`; scoped generate/edit placeholder prefix only after verification | Composer, 1, visible/enabled | Value equals complete marker + newline + exact user text | E1 generate placeholder observed; E5 edit placeholder reported |
| Send | role button, name `Send message`; `button[type="submit"][aria-label="Send message"]` if verified idle state uses it | Composer, 1; may be disabled while empty, must be enabled before action | Current marked user message plus processing/response evidence | E5 only for image submit. E1 outside-form disabled `type=button` is **not** fallback proof |
| Attachment preview | Composer-scoped `img[alt=<expected filename>]` within verified attachment group; scoped new `img[src^="blob:"]` only with trusted upload metadata | New visible preview, exactly one intended file | Filename/upload identity, novelty and input-area ownership; never old message image | E5 only; E1 `01-c.jpeg` is old submitted input and must fail |
| Remove attachment | `button[aria-label="Remove file"]` | Verified preview tile, 1 visible/enabled | That preview disappears, unrelated history untouched | E5 only; obtain pre-submit state |
| Processing | `button[aria-label="Stop generation"]`; fallback spinner near verified current model/response | Same composer/current response, visible; count scoped | Evidence of processing, not evidence of completion | E1 Stop observed; E5 Max+spinner supplementary only |
| User/assistant messages | No confirmed stable role/container selectors | Same configured conversation, current attempt | Full JOB-ID user message, following associated assistant response, explicit ordering | **Missing**; old visual alignment classes alone do not prove roles |
| Output region/image | E5 candidate `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]`; fallback scoped lazy `.aspect-square` image | Verified current assistant response, loaded; count policy needed | New versus baseline, follows current marker, complete, not input image; multi-output is review until policy approved | E5 only; these are candidates, not durable identities |
| Completion / original download | No confirmed selector | Current response, complete, permitted original asset | Download provenance, real image bytes/dimensions/format | **Missing**; Stop disappearing or image existing alone is insufficient |
| Security blocker | Visible `[role="dialog"][data-state="open"]` with Security Verification text or reCAPTCHA; fallback visibly blocking challenge iframe | Effective visibility includes ancestors and dimensions; no action into challenge | User action required; after manual resolution, safe checkpoint/readiness verified | E5 open dialog; E1 hidden badge/challenge are negative examples |
| Authentication/errors | No verified sign-in/access-denied/missing-conversation/rate-limit selectors | Target page and final destination | Explicit actionable status, never ready | **Missing**; transient text/HTTP status alone may be inconclusive |

Each future selector specification must contain primary, ordered fallbacks, parent-scope contract, `mustBeVisible`, `mustBeEnabled`, expected count, optional normalized text, effect-verification rule, evidence ID, and last verified site/date. Disabled empty Send should not make an otherwise idle page permanently unsupported: distinguish presence/readiness from action eligibility after verified inputs.

If all fallbacks fail or match ambiguously, stop; optional sanitized diagnostic evidence with consent. Never guess-click. Do not infer readiness from another composer or from a hidden CAPTCHA response field. Never use generated radix IDs, utility chains, blob URLs, expiring query strings, dimensions, or indexes as sole identity.

## Required evidence before adapter implementation

Capture the **same authorized image conversation** as screenshots plus sanitized HTML/accessibility snapshots:

1. Idle composer, Add button open, underlying image input and any menu.
2. Newly attached named image before submission (preview and Remove), then full prompt filled with enabled Send.
3. Submitted prompt/user-message boundary, processing response, and completed assistant result in order; include old result + next new result comparison.
4. Original/download UI and allowed response format/metadata; sample harmless output for validation.
5. Active Security Verification and manually cleared state; sign-in/session-expired, unavailable conversation, access denied and rate-limit/error states where available.
6. Exact approved URL rows privately supplied; supported target mode, site version/capture dates, permission to automate, and file limits.

Do not supply cookies, passwords, authorization headers, security tokens, or private unrelated conversations. Screenshots alone cannot prove DOM ordering; HTML alone cannot prove visible/enabled runtime state. If an error state cannot be captured safely, document the gap and fail closed on unknown pages rather than provoke it. Research runs once during design/adapter maintenance—not by loading and executing old saved pages every application startup.
