# The Firefox image job — upload → prompt → one submit → correlate → download → atomic save (2026-09-25)

Owner brief (steps 14–19, "FIREFOX IMAGE JOB"): a ready Firefox worker takes one
image from the shared queue and completes the **whole** workflow without manual
job steps — attach the image and verify it, insert the prompt and read it back,
submit exactly once, prove the result belongs to this job, download it, validate
and save it atomically beside the source, update job/worker state, then enter
cooldown. Everything must be the *same behaviour as Chrome*, re-integrated with
Firefox UI macros; Chrome must not change.

Today the Firefox lane runs the framework test (`Python_XClick_Demo`, one XClick)
and `_firefox_verdict` maps the savelog kind to completed/failed — steps 14–19
do not exist (`firefox_lane.py`, `multi_page_dispatcher._firefox_verdict`).

## 1. Facts this design rests on (measured, with sources)

| Fact | Where it comes from |
|---|---|
| Firefox has **no CDP file input**: the extension API cannot set `input[type=file]`; the official way is real-user simulation — `XClick` the page element to open the file dialog, `XType` the absolute path, then confirm | ui.vision docs *Form Filling and File Upload* ("File upload with Selenium IDE-style commands works only in Chrome and Edge… use XTYPE and XCLICK for Firefox"); *XType* page; forum thread 1709 (Firefox demo macro) |
| On Firefox the confirming **Enter** is the flaky half; the documented fallback is desktop mode (`XDesktopAutomation \| true`) so the click/keys go to the OS dialog | same docs + forum 1709/9995 |
| `if / else / end` and `gotoIf / label` exist; the `if` target is a **JS eval** (`executeScript_Sandbox`), so a boolean variable compares as `if \| ${arenaGuard} == true` | ui.vision docs *If - elseif - else - end* |
| Per run the launch URL seeds exactly **three** variables (`${!cmd_var1..3}` = pause budget, XClick target, tab target) — everything else must be baked into the macro file | `autorun.launch_url`, `macro.py`, `test_uivision_autorun.py` |
| The savelog is written **when a run ends** (`Status=OK|Error: …`, `###`, then the log); the app reads it after each run | `uivision/logread.py`, extension `genPlayerPlayCallback` |
| Selectors may only reach a probe through `probe_selectors` (RULE 21); probe files may not contain selector literals | `app/browser/probe_selectors.py`, `tests/test_probe_selectors.py` |
| Chrome's attach/preview contract: preview must match the file name, a wrong attachment is removed if safe and the job **stops before submit** | `docs/workflow_diagram.md:190`, `DOM_SELECTORS.md` §A–D |
| Chrome's output contract: baseline before submit → spinner → new node not in baseline → `complete && naturalWidth>0` → prefer the largest → fetch (credentials/cors) → canvas fallback | `DOM_SELECTORS.md` §E–F, `output_probes.py`, `cdp_arena/js_snippets.JS_DOWNLOAD_IMAGE` |
| The correlated arena output is an `https://….r2.cloudflarestorage.com/…` URL — the probes **skip `blob:`** nodes | `DOM_SELECTORS.md` §E, `output_probes.py:32/402/544` |
| `naming.OutputSpec` / `get_output_path` / `atomic_write_bytes` are the one `_AI` family (unique `{base}_AI_{n}{ext}`, mkstemp+replace) | `app/core/naming.py`, RULE 23 |
| The post-job cycle already resets the page and starts the cooldown; the Firefox branch returns "no CDP controller" today | `cooldown_service._finish_normal`, `_best_effort_reset` |

## 2. Decisions

* **D-1 — five stage macros, one run each, all under the existing lock/gap.**
  `Arena_Job_Prepare_<corr>` / `_Submit_` / `_Fetch_` / `_Probe_` / `_NewChat_`
  (per-job names: the file is rewritten per job and the extension can never
  serve a cached copy). Each stage is one `Sequence.execute([run])` exactly like
  `run_identify`, so launch, foregrounding, savelog polling, cancel and the
  machine-wide `_MACRO_LOCK` + inter-run gap are reused unchanged. `cmd_var1` =
  the stage's in-page budget, `cmd_var2` = the stage's XClick locator (when the
  stage clicks), `cmd_var3` = the tab target.
* **D-2 — the job payload lives in the macro file, not on the command line.**
  Only three cmd_vars exist and the payload (prompt text, file name, token,
  baseline srcs, selector lists) is large, multiline and Unicode. Each stage
  writes its own macro JSON with the payload as a JS object literal — the
  `identify.py` precedent (one JS literal, trivial Python around it) — and the
  prompt never travels through `XType`.
* **D-3 — two phases with the app's checkpoint between them.**
  `Prepare` (attach → verify → prompt → read back → guard) ends; the app logs
  every state, honours Pause/Stop/Cancel (a cancel *before* submit leaves the
  composer untouched and is provably not a submission), then `Submit` re-verifies
  and clicks. One run could not act on "attachment verified" before Send, and the
  savelog would hide the verdict until the end.
* **D-4 — native attach, verification is the only acceptance.**
  `XClick` on the *Add files* button (its locator is computed in-page from the
  site_adapter list and returned as `xpath=…`, so RULE 21 still owns the
  selector) → `XType` the absolute path → Enter (retried once in desktop mode).
  Acceptance: **exactly one** preview that is NEW since the baseline and matches
  the sent file name (or an empty-alt `blob:` preview = the site's own rendering).
  Extra/stale tiles ⇒ refuse before submit (`stale attachment from a previous job`
  is a named reason); the prepare stage removes one stale tile first as a bounded
  best effort.
* **D-5 — prompt insertion by JS, verified by read-back.**
  The composer value is set through the prototype's own setter (React-safe) and
  read back; the check is string equality plus length and FNV-1a over UTF-16
  code units — the identical hash exists in JS and Python, so a truncated or
  duplicated read-back is proved. Two attempts, then the guard refuses.
* **D-6 — submit exactly once, guarded in the macro.**
  `if | ${arenaGuard} == true` immediately in front of the single `XClick`; the
  guard re-checks the prompt read-back, the single attachment, an enabled Send
  and the absence of a security dialog, and the reason rides the echo line. The
  macro stores the click count (`1`/`0`). The app never runs `Submit` a second
  time unless the recovery decision proves the first one never happened.
* **D-7 — result correlation never guesses.**
  A candidate must be an output-image match that is not in the baseline, not a
  `blob:`, not inside this job's own message container, and positioned after the
  `[JOB-ID: <corr>]` container when that container is found. Several candidates ⇒
  `needs_review` (the largest is recorded as evidence, never as the result); a
  timeout with the token on the page ⇒ `needs_review`; no token and no candidate
  ⇒ the submit never happened (`fresh`).
* **D-8 — download: page bytes first, Python second.**
  The `Fetch` stage runs the *same order Chrome does* (in-page `fetch` with
  credentials, then the page's own `<img>` → canvas → `toDataURL`) and echoes
  `ARENA_DATA=<base64>`. The app's fast path for an `https:` src is the shared
  `browser/image_fetch.fetch_bytes` (extracted from the Chrome fallback, so both
  browsers download through one function); `Fetch` runs when the src is not
  http(s) or when that fetch fails. Bytes are validated by PIL (width/height > 0,
  > 100 bytes, not HTML) before anything is written.
* **D-9 — atomic save with a recoverable staging file.**
  The final name comes from `get_output_path` (never overwriting an existing
  `_AI` file). Bytes are written first to `<dir>/.<final-name>.part`
  (`atomic_write_bytes`), then renamed onto the final name, so
  "downloaded but not saved" is a state the app can finish rather than repeat.
* **D-10 — a per-job journal makes the recovery rules decidable.**
  `<config>/firefox/jobs/<image-id>.json` (through `json_store.save_json_atomic`)
  records phase, token, image, tab, staging/final paths, result src and attempts
  at every checkpoint. Recovery (before any retry) reads journal → final file →
  staging file → page probe: final exists ⇒ completed (no resubmit); staging ⇒
  validate + finish the save; journal says submitted ⇒ collect the existing
  result (probe for it) and never resubmit; submitted without evidence ⇒
  `needs_review`.
* **D-11 — reset through the existing seam, cooldown unchanged.**
  `cooldown_service._best_effort_reset` gains a Firefox branch that runs
  `Arena_Job_NewChat` (native New Chat click → bounded clean-state read-back).
  Success ⇒ the existing cooldown start/persist path; failure ⇒ the existing
  warning *after a successful save*. A tab that must keep its in-flight evidence
  (cancel after submit / uncertain) is **not** reset: `FinishCtx.preserve` keeps
  the page in ERROR so no new job is handed to it.
* **D-12 — never open or close a tab.** Every stage starts with `selectWindow`
  on the pooled tab with an EMPTY Value (a missing tab fails the run with `E210`
  — it can never open one), and no stage contains an open/close command; the
  preexisting Firefox tab is untouched by cleanup and recovery.

## 3. Chrome parity table (step 17 — the same states)

| Chrome state / log (`single_job_runner`, `JobStatus`) | Firefox stage that produces it |
|---|---|
| worker/job/attempt selected (`prepare_image_for_job`, `_log_assign`) | shared dispatcher (unchanged) + the lane's stage log lines |
| `OBSERVE_BASELINE` → "Baseline N" | `Prepare` `ARENA_STATE` |
| `ATTACH_IMAGE` → "Attachment verified: …" | `Prepare` XClick+XType, `ARENA_ATTACH` |
| `VERIFY_ATTACHMENT` → "Verify attachment failed: preview not found …" | `ARENA_ATTACH` `ok:false` + reason (stale/wrong/no preview) |
| `INSERT_PROMPT` / `VERIFY_PROMPT` → "Verified …" | `ARENA_PROMPT` (length + hash) |
| `SUBMIT` → "Clicked …"/"Submit via fallback" | `ARENA_GUARD` + `ARENA_SUBMIT` |
| `WAIT_OUTPUT` → "Waiting for generation — timeout …ms" | `ARENA_RESULT` (spinning/timed_out) |
| `DOWNLOAD` → "Downloaded N" / "Not downloadable" | `image_fetch` / `Fetch` `ARENA_DATA`, "Download failed: …" |
| `VALIDATE` → "Valid .ext N bytes" | `firefox_result.validate_bytes` |
| `SAVE` → "Saved <name>" | `get_output_path` + `atomic_write_bytes` |
| pool state + cooldown transition | shared `PagePool` marks + `finish_page_after_job` |

## 4. Files

| Action | Path | What |
|---|---|---|
| new | `app/browser/uivision/job_probes.py` | shared prelude + page-state/attachment/locate/fetch probe bodies |
| new | `app/browser/uivision/job_submit_probes.py` | prompt-insert, guard, result-correlation probe bodies |
| new | `app/browser/uivision/job_macro.py` | payload from `probe_selectors`, the five macro documents, provisioning, log paths |
| new | `app/browser/uivision/job_replies.py` | savelog `ARENA_*` parsing + every stage verdict (pure) |
| new | `app/browser/image_fetch.py` | the plain-HTTP byte fetch extracted from the Chrome download fallback |
| edit | `app/browser/cdp_arena/download.py` | `_python_download` delegates to `image_fetch` (Chrome behaviour unchanged) |
| new | `app/services/firefox_job.py` | the stage machine: checkpoint, pause/stop/cancel, correlation, outcome |
| new | `app/services/firefox_result.py` | download/validate/staging/final atomic save (`naming` + `image_fetch`) |
| new | `app/services/firefox_journal.py` | per-job journal (`json_store`) |
| new | `app/services/firefox_recovery.py` | the recovery decision table |
| edit | `app/services/firefox_lane.py` | `run_job_stage`, `reset_page` (same lock + gap) |
| edit | `app/services/multi_page_dispatcher.py` | Firefox branch runs the job; `ResultCtx.status` (needs_review); finish preserve/count |
| edit | `app/services/cooldown_service.py` | `_best_effort_reset` Firefox branch; `FinishCtx.preserve` |
| new | `tests/test_firefox_job_*.py`, `tests/test_firefox_result.py`, `tests/test_firefox_recovery.py`, `tests/js/test_firefox_job_probes.mjs` | the step-18 list |

## 5. Tests first (step 18 list → where)

`tests/test_firefox_job_macro.py` — macro shape per stage (no open/close command,
one XClick in front of the Send guard, payload selectors come from site_adapter,
unique per-job names); `tests/test_firefox_probe_gates.py` — the RULE 21 wiring
(the payload embeds the `site_adapter` lists, PROBE_FILES lint);
`tests/test_firefox_job_replies.py` — every verdict: stale attachment, wrong
file, extra tile, truncated/duplicated prompt, Unicode/multiline hashing,
guard reasons, exactly-once count, correlation (new/old/ambiguous/uncertain);
`tests/test_firefox_result.py` — HTML/short/corrupt download, staging + finalize,
`_AI` naming with existing outputs, ENOSPC/EACCES/rename failure;
`tests/test_firefox_job_flow.py` — happy path, submit-once, lost acknowledgment
(no resubmit), invalid/uncertain never completed, needs_review, pause/stop/cancel
before and after submit, job-count only after a successful save, reset failure is
a warning; `tests/test_firefox_recovery.py` — the decision table with real files;
`tests/js/test_firefox_job_probes.mjs` — the rendered probe bodies executed in
jsdom against a fake DOM (attach new/stale/wrong, prompt insert+readback incl.
Unicode, guard yes/no, result correlation, clean state); plus registration in
`tests/test_js_payload_syntax.py` (`_BUILDERS_COVERED`), `tests/test_probe_selectors.py`
and `package.json`.

## 6. Quality (RULE 16/18) — current vs target

Current maxima of the touched legacy files (`tools/quality_baseline.json`):
`cooldown_service.py` max_func_loc 22 / max_cc 9 / max_params 4 / 67 funcs;
`multi_page_dispatcher.py` 20 / 8 / 4 / 34; `single_job_runner.py` 26 / 7 / 4 / 80
(untouched by this round); `firefox_lane.py` and `uivision/identify.py` are not
baselined yet. Targets: every new module ≤ 20 lines per function, ≤ 4 params,
≤ 4 nesting, ≤ 300 lines; the two edited legacy files keep their maxima and grow
only by one small helper each (`_firefox_reset`, `_firefox_job`); the ratchet is
re-run over the changed files at the end.

**Rejected dishonest reductions** (each would lower a number without lowering
risk): splitting `cooldown_service._best_effort_reset` across files; moving the
macro JSON literal into a data file to dodge the JS-literal rule; shrinking
docstrings to clear a length count; parameter objects invented only to hide a
5th parameter; marking the ambiguous-result branch as "best effort" to avoid the
`needs_review` path.

## 7. Out of scope (explicit)

* CAPTCHA solving on Firefox: a visible security dialog is *reported* — the job
  settles before submit (or keeps in-flight evidence after it) and is marked
  `needs_review`; the human solves it and Retries. No solver, no auto-click on
  the dialog.
* The framework-test window keeps running `Python_XClick_Demo`; the job macros
  are separate documents (the same XModule home, different names).
* Non-ASCII **file paths**: `XType` types keystrokes into the OS dialog, so a
  path with characters the layout cannot produce may be mistyped; the lane warns
  once and the attach verification stays the authority (it refuses, never
  guesses).
* Any change to the Chrome pipeline beyond the shared `image_fetch` extraction
  (its tests stay green, byte-for-byte behaviour).

## 8. As built (2026-09-25)

Delivered as designed. Rounds: the probe/macro/reply trio + `image_fetch`
extraction; `firefox_result` + `firefox_journal` + `firefox_recovery`; the
`firefox_job` stage machine + lane/dispatcher/cooldown seams; tests; then the
living truth in `docs/current/SYSTEM_OF_RECORD.md` (I-65) and README.

## 9. Amendment (2026-09-26) — a locate answer is the bare locator

Field report (the owner's live log, 2026-09-26 19:15): every prepare run died
after 4–6 s with `Status=Error: Unexpected token (1:2)`, the stage logged
`prepare macro: error` and "🛑 needs review: the prepare macro answered nothing",
the page was parked in `needs_review` (no reset, no cooldown, no new job), and
the next image repeated the identical error byte for byte.

Cause: `job_probes._LOCATE_TEMPLATE` answered a JSON envelope
(`{"ok": true, "loc": "xpath=…"}`) where both consumers need the bare value.
The macro's guard is a Ui.Vision `if` whose Target is **evaluated as
JavaScript** (`executeScript_Sandbox` runs an ES5 sandbox): the JSON quotes
double up inside the already-quoted condition, the parse fails, and the `if`
aborts the whole macro before any command runs — which is exactly why nothing
was ever attached. The second consumer, `XClick ${arenaX}`, is a native locator
in the Value column: a JSON blob could never resolve there either.

Fix: `_LOCATE_TEMPLATE` returns `pick ? xpathOf(pick) : ''` — the variable *is*
the locator, and `''` is the guard's own false case. `job_replies.locate_verdict`
already parsed exactly that shape, so no Python consumer changed.

Invariant (now pinned by tests): an answer consumed in a JS-evaluated field or
as an `XClick`/locator target must be **bare** — `xpath=…`, `''`, `true`,
`false`. Only `arenaRemove`, `arenaAttach`, `arenaSend`, `arenaNewChat` and
`arenaGuard` are consumed that way; the JSON answers (`arenaState*`,
`arenaPrompt`, `arenaAttachRep`, `arenaResult`, `arenaData`) are echo-only and
parsed by Python from the savelog.

Locks:

* `tests/js/test_firefox_job_probes.mjs` (29) builds the five real documents with
  the Python builder, derives each answer by **executing the owning probe body**
  against a markup and an empty page state (never a typed-in answer — the first
  version of this lock passed with the broken producer), parses every `if`
  target with acorn in ES5 mode for every answer combination, pins the guard
  counts (prepare 2, submit 1, newchat 1, probe 0, fetch 0) and asserts every
  `XClick` target is `''` or `xpath=/…`. With the old JSON answer six tests fail;
  with the fix 29/29 pass.
* `tests/test_firefox_job_macro.py` adds the Python-side view: only JS-safe
  answers may appear inside an `if`/`XClick` target (located by name, so a new
  macro cannot skip the rule), the locate probe's body contains no
  `JSON.stringify`, and the baked payload stays a quoted JS string literal.
