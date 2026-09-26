# Firefox image job — integration plan (2026-09-25)

**Status: PLAN ONLY — no production code.** Owner instruction (verbatim essence): *"FIREFOX IMAGE JOB … do not
Implement the solution — Doc planning integration only for now"*. A ready Firefox worker must take ONE image job
from the shared queue, upload + positively verify the image, insert + verify the prompt, submit exactly once,
prove the new result belongs to this job, download + validate + save it atomically beside the source (`_AI`),
update job/worker state and enter cooldown — reusing the existing Firefox worker, Ui.Vision, macro, queue, pool,
logging, persistence and cooldown systems, **same behaviour and the same states as Chrome**, re-implemented
with Firefox Ui.Vision macros. `current/SYSTEM_OF_RECORD.md` stays untouched until the code lands (RULE 17).

Sections 14–19 below answer the owner's steps 14–19 one-to-one; §1 is the research they rest on.

---

## 1. Research — what exists today (measured, not guessed)

### 1.1 The Firefox lane is a stub that lies about success

`multi_page_dispatcher.run_claimed_image` → `page.browser == "firefox"` → `_run_firefox_claimed` →
`_firefox_and_record` → `prepare_image_for_job` (image `processing`, `attempt_count += 1`, correlation id,
`build_final_prompt`, `note_job_started`) → `_firefox_verdict` → `firefox_lane.run_firefox_macro` (the
framework-test XClick macro) → `(kind, msg)`. Kind `ok` is recorded as a **completed image with no output
file**: this is the dishonest-success path the job must replace (RULE 4, RULE 16.6).

Everything around it is already Chrome-shared and stays: `_acquire_free_in` (first free page in pool order →
`pool.mark_busy`), `_log_assign` (`📤 … BUSY`), `_start_tab_image` / `_clear_tab_image`, `_handle_result`
(image status, `job_finished`, `record_dispatch_result` → Job History, cancel → `failed "Cancelled"` with no
history row), `maybe_note_rate_limit`, `_finish_page_safely(FinishCtx(ctrl=None, client=None))` + live-bus wake,
`_feeding` (not cancel, not stop-after), `_wait_pause` (between claims).

`firefox_lane` owns the machine-wide `_MACRO_LOCK` (one Ui.Vision macro at a time: native input needs the
foreground) and the owner's inter-run gap `inter_run_delay_sec`. `run_identify` already shows the per-phase
pattern this plan generalises: write a macro file under hard-drive storage, run it on the pooled tab
(`selectWindow ${!cmd_var3}` with an EMPTY Value — never opens a page), `executeScript` → `echo MARK=${reply}`,
parse the savelog (`identify.parse_reply`). The autorun page closes only itself; `continueInLastUsedTab=0`
protects the user's prepared tab (2026-09-24 rule).

### 1.2 The Chrome pipeline (the behaviour to match)

`single_job_runner` runs the block stack `DEFAULT_STACK_ORDER`: `HIGHLIGHT_ATTACH`, `OBSERVE_BASELINE`,
`CHECK_SECURITY`, `AWAIT_PROCESSING_IMAGE`, `ATTACH_IMAGE`, `VERIFY_ATTACHMENT`, `HIGHLIGHT_PROMPT`,
`INSERT_PROMPT`, `VERIFY_PROMPT`, `HIGHLIGHT_SUBMIT`, `SUBMIT`, `WAIT_OUTPUT`, `DOWNLOAD`, `VALIDATE`, `SAVE`,
`ADVANCE`. Each block emits `JobAction(job_id, block, running|success|failed|skipped, msg)` through
`bridge._emit_job_action_status`; log lines are prefixed `[corr_id]`; the settle line is
`[corr] [Page xxxxxx] ✅ path` / `❌ path: err`.

| Step | Chrome mechanism | Reusable for Firefox? |
|---|---|---|
| Baseline | `output_probes.build_baseline_js()` | yes — plain page JS |
| Security | `JS_SECURITY_DIALOG`, only while Watcher ON (RULE 20, `captcha/policy`) | yes — JS |
| Attach | CDP `DOM.setFileInputFiles` | **no** — no CDP in Firefox |
| Verify attach | `JS_VERIFY_ATTACHMENT` | **not as is** — accepts *any* visible `blob:` preview (§6.1) |
| Insert prompt | `JS_INSERT_PROMPT` (native setter + `input`/`change`) | yes — JS |
| Verify prompt | `JS_VERIFY_PROMPT` exact equality, one retry | yes — JS |
| Submit | visual click, fallback `JS_CLICK_SEND` | click must be **XClick** (JS clicks are refused, `macro.refuse_dom_clicks`) |
| Wait | `build_check_js(old_srcs, corr, old_outputs)` + `flatten_diagnostics` | yes — JS |
| Download | in-page fetch, fallback Python urllib rejecting < 100 B / HTML | Python fetch of the correlated `src` (R2 presigned URL, no cookies needed) |
| Validate | PIL | yes |
| Save | `OutputSpec` (`_AI`, `{base}_AI_{n}{ext}`) + `get_output_path` + `atomic_write_bytes` | yes |
| Policies | B8 (after bytes are secured, later failures are warnings) · B9 (soft failures forgiven when saved) | yes |

### 1.3 States that already exist (no new enum values needed)

* `JobStatus` + `core/state_machine.JOB_TRANSITIONS`: `created → baseline_captured → attaching →
  attachment_verified → prompt_inserted → prompt_verified → submitted → waiting_generation → output_detected →
  downloading → validating → saving → completed`, plus `failed`, `needs_review`, `paused_user_action_required`,
  `interrupted`. `validate_job_transition` is used **only by tests** today — Chrome never walks this table.
* `ImageStatus`: `processing → completed | failed | needs_review | skipped`.
* `PageStatus`: `steady`, `busy`, `cooldown`, `waiting_generation`, `waiting_captcha`, `error`, `disconnected`;
  `is_free` = steady + connected + no live timer.

Owner vocabulary → existing state (the "same as Chrome" rule):

| Owner word | Existing state | Written by |
|---|---|---|
| ready / steady | `PageStatus.STEADY` | `pool.mark_steady` / `_settle_pool_steady` |
| busy | `PageStatus.BUSY` (+ `current_job_id`) | `pool.mark_busy` (claim) |
| waiting_user (manual security) | `PageStatus.WAITING_CAPTCHA` | `pool.mark_waiting(tab, "captcha")` — Chrome's own call |
| generating | `PageStatus.WAITING_GENERATION` | `pool.mark_waiting(tab, "generation")` — Chrome's own call |
| error | `PageStatus.ERROR` | `pool.mark_error` |
| needs_review | `ImageStatus.NEEDS_REVIEW` / `JobStatus.NEEDS_REVIEW` (an *image/job* state; the page settles) | job service |
| cooling | cooldown timer on the page (`start_cooldown`) | finish path |

### 1.4 The finish path (`cooldown_service`)

`finish_page_after_job(ctx)` → cancelled ? `_finish_cancelled` (reset, steady, no cooldown) : `_finish_normal`
(`register_job_done` → `_best_effort_reset` → warning on failure → `load_config` → `start_cooldown(min_seconds)`
or `_settle_pool_steady`). Deadlines persist through `bridge._persist_cooldowns()`. For Firefox
`_best_effort_reset` returns `"no CDP controller — Firefox lane (New-chat reset not applicable)"` today.

Two facts that matter for "the same as Chrome":

* **Chrome counts every non-cancelled finished job**, failures included (`register_job_done` is unconditional
  in `_finish_normal`; design `2026-09-21-job-count-is-display-only` D-2). The owner's step-18 test says "job
  count increments only after successful save". **Owner decision (Q1): do the same as Chrome** — Firefox counts
  every non-cancelled finished job exactly like Chrome (D-12).
* **Chrome always resets to New Chat** after a normal job: there is no setting. The owner writes "when this
  behavior is enabled". **Owner decision (Q2): same as Chrome** — Firefox always resets, no switch (D-13).

### 1.5 Persistence and crash handling today

* `models.JobRecord` (`job_id`, `correlation_id`, `attempt`, `status`, `baseline`, `prompt`, `submitted_at`,
  `output_src`, `output_metadata`, `saved_path`, `error`, `needs_review`, `logs`) exists in `AppState.jobs`,
  but **no pipeline writes it**. `run_control` and `queue_scan` clear `state.jobs` on Run / Scan.
* `persistence._handle_interrupted` marks in-flight job records `interrupted` and their images `failed`.
  It is dormant, because no records exist.
* `core/run_scope`: a `processing` leftover is re-run after a crash ("crash leftovers are re-run, not
  stranded"). For a job that was already submitted, that means **a second paid submit**. Chrome lives with
  this; the owner's step 16 forbids it for Firefox.
* Scanner I-46: a source with an existing `_AI` sibling is marked `completed` at scan time. This is the
  existing "the file on disk is the truth" rule that the recovery reuses.

### 1.6 Ui.Vision capability facts (docs + forum, fetched 2026-09-25)

* `executeScript` runs its Target as a function body in the page (DOM access; `return` value → `${var}`,
  Promises awaited). `executeScript_Sandbox` has no DOM and is ES5 only, so it is not used.
* **Firefox cannot upload through `type` on `input[type=file]`** (Chrome/Edge only). The supported Firefox
  route is XClick on the upload control → OS file dialog → `XType <absolute path>` → `XType ${KEY_ENTER}`. An
  old forum note says Enter sometimes failed in Firefox; the workaround was an XClick on the dialog's Open
  button.
* `onDownload | name | true` waits for the next download (up to `!TIMEOUT_DOWNLOAD`). Firefox ignores the
  rename but honours the wait. `${!LAST_DOWNLOADED_FILE_NAME}` is valid after it completes (fixed in V8.3.8).
* Ui.Vision interpolates `${…}` inside Target text. A user prompt containing `${x}` would be rewritten
  before it reaches the page (§6.2 guards against this).

---

## 2. Decisions (and the alternatives rejected)

| # | Decision | Rejected alternatives (why) |
|---|---|---|
| D-1 | **One Python-driven job, many short phase macros.** Python owns the state machine; each phase is one Ui.Vision run that does one thing and echoes `ARENA_JOB=<json>` into its savelog. | *One giant macro for the whole job:* no checkpoints, so cancel/pause/crash cannot know whether submit happened; it holds `_MACRO_LOCK` for minutes and starves every other Firefox worker; errors surface only as "macro failed". |
| D-2 | **Reuse the Chrome page JS verbatim** (`build_baseline_js`, `JS_INSERT_PROMPT`, `JS_VERIFY_PROMPT`, `JS_SEND_STATE`, `build_check_js`, `JS_SECURITY_DIALOG`, `new_chat` checks) inside `executeScript`. Selectors stay in `site_adapter` / `probe_selectors` (RULE 21). | *Firefox-specific copies of the probes:* two truths that drift (RULE 10). |
| D-3 | **Upload through the native dialog** (XClick attach → XType staged path → Enter), with the dialog closed by `${KEY_ESC}` on any failure. | *`type` on the file input:* not supported by Firefox. *Drag-and-drop simulation from JS:* needs file bytes inside the page (a cmd_var/base64 payload of several MB) and is not a native action. *Clipboard paste of the image:* no Ui.Vision primitive for binary clipboard in Firefox. |
| D-4 | **Stage an ASCII-safe unique copy** `<config>/uivision/uploads/arena_<corr8>.<ext>` and verify the preview by that exact name. | *Upload the original path:* Unicode/long paths are fragile through XType and the OS dialog, and a name shared by two jobs cannot tell a stale attachment from the right one. |
| D-5 | **Prompt as base64 in the phase macro file, decoded in the page**; readback is compared in the page *and* by SHA-256 in Python. | *XType the prompt:* slow, layout-dependent, lossy for Unicode/newlines. *cmd_var payload:* URL/argv length limits and `${…}` interpolation. *Echo the whole prompt back:* bloats the savelog and still passes through interpolation. |
| D-6 | **Submit = XClick only, write-ahead journalled**: `submitted` (with `submit_ack=false`) is persisted *before* the click. Any record at `submitted` or later is **never** clicked again. | *Retry the click on a lost ack:* can double-submit (paid). *JS click:* refused by the macro contract (native input only). |
| D-7 | **Generation wait = bounded observe macros** (in-page watch window ≤ 12 s each, lock released between). | *One long wait macro:* holds the machine-wide lock for minutes. *Fixed sleep then one check:* slow and blind to captcha and errors. |
| D-8 | **Download = Python fetch of the correlated `src`** with Content-Length / magic / PIL checks; fallback = in-page `fetch → blob → <a download>` + `onDownload \| … \| true` + `${!LAST_DOWNLOADED_FILE_NAME}`, read from the profile's download directory (a `.part` file is rejected). | *Firefox download only:* depends on the profile's download prefs and dialog settings. *Python only:* a future non-presigned `src` would break with no fallback. |
| D-9 | **A Firefox job journal** `config/firefox_jobs.json` (atomic + shape-validated, `json_store`, RULE 13) holding one `JobRecord`-shaped entry per in-flight job, plus Firefox fields. | *`AppState.jobs`:* cleared by Run/Scan, which would wipe in-flight evidence. *No journal:* crash after submit becomes a blind re-run (a second paid submit). |
| D-10 | **Reuse `JobStatus` + `JOB_TRANSITIONS`**; add exactly one edge `submitted → needs_review` (Chrome never reads the table, so Chrome is unchanged). User pause is *not* a job state: the record stays at its checkpoint. | *New Firefox states:* violates "same states as Chrome". |
| D-11 | **Pool transitions through the existing calls only** (`mark_busy`, `mark_waiting("generation"/"captcha")`, `mark_error`, `finish_page_after_job`). | *A Firefox pool path:* two truths for one decision. |
| D-12 | **Job count = Chrome's rule** (owner Q1): `register_job_done` in `_finish_normal`, +1 per finished non-cancelled job (completed, failed, needs_review); cancelled → no count. No count seam. | *Success-only for Firefox:* owner rejected ("do same as Chrome"). *Success-only for both:* a Chrome change nobody asked for. |
| D-13 | **New Chat on Firefox = XClick on `new_chat_selectors()` + the `new_chat` clean-page checks via `executeScript`**, injected into `_best_effort_reset` through `FinishCtx.lane_reset`. A failure is a warning; cooling starts anyway (Chrome parity). | *Navigate to the site URL (`open`):* the macro contract forbids opening pages (never-open rule). |
| D-14 | **Recovery inspects before it acts**: page (JOB-ID bubble, correlated result), journal checkpoint, staging download, output folder, in that order; no resubmit unless the page *proves* nothing was sent (§16). | *Re-run leftovers (today's `run_scope` behaviour):* duplicate paid submits. |

---

## 3. Architecture (planned modules, RULE 18 budgets)

```
multi_page_dispatcher._run_firefox_claimed   (thin: same claim/record/finish as today)
        └── services/firefox_job.run_job(bridge, page, img, prompt, corr)   ← replaces run_firefox_macro verdict
               ├── services/firefox_job_journal     checkpoint store (JobRecord shape, atomic JSON)
               ├── services/firefox_job_phases      one function per phase: build → run → parse → checkpoint
               │      └── firefox_lane.run_phase(bridge, page, PhaseMacro)   (lock + gap + provision + savelog)
               │             └── browser/uivision/job_macros   pure builders: commands + JS bodies per phase
               ├── services/firefox_job_output      download (python / browser fallback) + validate + atomic save
               └── services/firefox_job_recovery    startup/cancel inspection (§16)
```

| File (new unless noted) | Owns | Budget |
|---|---|---|
| `app/browser/uivision/job_macros.py` | pure macro documents per phase (`selectWindow` guard, `executeScript` bodies built from the Chrome JS, XClick/XType steps, `echo ARENA_JOB=`) + `parse_job_reply` | ≤ 300 lines, funcs ≤ 20 (JS literals carry `# ideal-size:` like `identify.py`) |
| `app/browser/uivision/upload.py` | staging copy, name rule `arena_<corr8>.<ext>`, dialog command block with ESC cleanup | ≤ 150 |
| `app/services/firefox_job.py` | orchestration: phase order, pause/cancel checks at checkpoints, result mapping to `(ok, err, status)` for `_handle_result` | ≤ 250 |
| `app/services/firefox_job_phases.py` | phase functions (baseline, security, attach, prompt, submit, wait) | ≤ 300 |
| `app/services/firefox_job_output.py` | fetch, validate, atomic save (reuses `naming`) | ≤ 200 |
| `app/services/firefox_job_journal.py` | journal store, write-ahead order, transition validation | ≤ 200 |
| `app/services/firefox_job_recovery.py` | recovery matrix §16 | ≤ 250 |
| `app/services/firefox_lane.py` (edit) | `run_phase` generalises `run_identify`'s critical section; `run_identify` becomes a caller (net shrink) | stays < 200 |
| `app/services/multi_page_dispatcher.py` (edit) | `_firefox_verdict` → `firefox_job.run_job`; no other change | ratchet 455 lines: net ≤ 0 |
| `app/services/cooldown_service.py` (edit) | `FinishCtx.lane_reset` (one defaulted field) + the `ctrl is None` branch of `_best_effort_reset` calls it | legacy 869-line hotspot: must not grow, so the job-count trio (`register_job_done`, `_stats_count`, `restore_page_stats`) moves to `services/job_count.py`, re-exported |
| `app/core/state_machine.py` (edit) | + `submitted → needs_review` | +0 lines (the set literal grows) |

Every new module sits in the existing layers (`browser/uivision` = pure builders, `services` = orchestration)
with no Qt imports. The slot surface stays at 141: no new UI in this change (owner Q2: no New Chat switch; Q3: no needs_review list).

---

## 4. The phase-macro contract

Every phase macro (one file per phase name, `Arena_Job_<Phase>.json`, rewritten under `_MACRO_LOCK` just before
its launch, like `identify.provision`):

1. `selectWindow | ${!cmd_var3} | ""` — reuse the pooled tab; the empty Value means it never opens a page (the
   extension answers `E210` if the tab is gone → `tab_gone`).
2. The phase body (table below).
3. `echo | ARENA_JOB=${reply}` — one JSON object `{phase, token, ok, …}`. `token` = the job's correlation id,
   so a reply from another job's savelog never parses as this one (`parse_job_reply` checks it).

A missing reply is `no_reply`, never success (RULE 4). The savelog verdict (`ok/error/timeout/stopped/corrupt`)
still applies first. Per-phase timeouts come from `settings.timeouts` (the same knobs as Chrome).

| Phase | Body | Native input? | Reply | Checkpoint on success |
|---|---|---|---|---|
| `baseline` | `executeScript` baseline JS + `JS_PAGE_READY` + attachment-preview count + composer text length | no | `{outputs:[src…], count, ready, previews, composer_len}` | `baseline_captured` (baseline stored) |
| `security` | `JS_SECURITY_DIALOG` (only while Watcher ON, RULE 20) | no | `{visible}` | — (drives `waiting_captcha`) |
| `attach` | FIND_RECT on attach button (RULE 1 red rect) → XClick → `pause` → XType staged path → XType `${KEY_ENTER}` → `executeScript` wait ≤ 8 s for a preview named `arena_<corr8>.<ext>` → on miss XType `${KEY_ESC}` | **yes** | `{previews:[{alt,src}], matched, dialog_closed}` | `attaching` before, `attachment_verified` after |
| `prompt` | `executeScript`: decode base64 → `JS_INSERT_PROMPT` → `JS_VERIFY_PROMPT` → SHA-256 of `el.value` | no | `{ok, len, sha256}` | `prompt_inserted`, then `prompt_verified` when Python's sha matches |
| `submit` | `executeScript` guard (prompt sha still equal, our preview still present, send enabled, no bubble with `[JOB-ID: corr]`) → `if` guard ok → FIND_RECT + **XClick** send → `executeScript` ack wait ≤ 6 s (bubble with JOB-ID, or composer cleared + send-state busy) | **yes** | `{guard, clicked, ack, bubble, composer_len}` | `submitted` (write-ahead, `submit_ack=false`) → `submit_ack=true` |
| `observe` | `executeScript` watch ≤ 12 s: `build_check_js(baseline, corr, …)` + `JS_IS_GENERATING` + security + page errors | no | `{found, candidates:[…], generating, security, error}` | `waiting_generation` → `output_detected` (src stored) |
| `browser_download` (fallback) | `executeScript` fetch → blob → anchor `download` → `onDownload \| arena_<corr8> \| true` → echo `${!LAST_DOWNLOADED_FILE_NAME}` | no | `{file}` | `downloading` |
| `reset` | FIND_RECT + XClick New Chat → `executeScript` wait for `new_chat` clean page (readyState complete, composer visible + empty, no message list) | **yes** | `{clean, reason}` | — (finish path) |
| `inspect` (recovery) | `executeScript`: bubble with JOB-ID? correlated result (`build_check_js` with stored baseline)? composer content sha? generating? | no | `{bubble, found, candidates, composer_sha, generating}` | per §16 |

Native-input phases hold `_MACRO_LOCK` for their whole run and bring the profile window to the foreground
(existing `Sequence._foreground`). Observe-only phases still take the lock, because the Ui.Vision launch
itself goes through the same command-line API, but they release it between polls. The owner's
`inter_run_delay_sec` gap applies between *jobs* only, never between phases of one job (owner decision Q4).

---

## 5. Journal and state machine

**Record** (`firefox_jobs.json`, keyed by `job_id` = correlation id): the `JobRecord` fields plus `tab_id`,
`profile_dir`, `image_rel`, `staged_upload`, `prompt_sha256`, `submit_ack`, `candidates`, `download_path`,
`bytes_sha256`, `target_path`, `checkpoint_at`. Transitions are validated with `validate_job_transition`. An
illegal transition is a bug: it is logged as an error and the job ends in `needs_review`, never silently.

**Write-ahead order** (each line = one atomic journal write *before* the side effect it names):

```
created → baseline_captured → attaching → [upload] → attachment_verified
        → prompt_inserted → [insert] → prompt_verified
        → submitted(submit_ack=false) → [XClick send] → submitted(submit_ack=true)
        → waiting_generation → output_detected(src)
        → downloading → [bytes to staging, fsync] (bytes_sha256)
        → validating → saving(target_path, bytes_sha256) → [atomic rename] → completed(saved_path)
```

The image status (`AppState.images`) is written by the dispatcher's existing `_handle_result`, exactly as for
Chrome. The journal is the Firefox-only evidence store and is **deleted per record** once the image is settled
`completed` / `failed`. A `needs_review` record stays until the user resolves it (Retry / Reset on the image,
the existing queue actions).

---

## 6. Verification details

### 6.1 Attachment (positive, stale-proof)
* **Before upload** (`baseline` reply): if `previews > 0`, the composer holds a leftover attachment. Firefox
  runs one `reset` and re-baselines; still dirty → job `failed` "stale attachment in composer" (retryable, no
  submit). Chrome's any-blob check is deliberately **not** reused as is.
* **After upload:** exactly one visible preview whose `alt` equals the staged name (or whose `src` is `blob:`
  **and** whose container carries that name). Zero → `failed` "attachment not visible"; a preview with another
  name → `failed` "wrong attachment preview"; more than one → `failed` "multiple attachments". All happen
  before submit, so all are safe to retry.
* **Source checks before any page action:** file exists, extension in the folder's supported set
  (`.png/.jpg/.jpeg/.webp`), PIL opens it, and the format matches the extension. Missing/unsupported →
  `failed` with no macro launched.

### 6.2 Prompt
* The final prompt = `build_final_prompt` (with `[JOB-ID: corr]`), UTF-8 → base64 in the macro. The page
  decodes it with `TextDecoder`, so no `${…}` can be interpolated, and newlines and Unicode survive.
* Readback: in-page `el.value === expected` **and** Python `sha256(expected) == reply.sha256` **and**
  `len` equal. Truncation or duplication fails both. One re-insert (Chrome's one retry), then `failed`
  "prompt readback mismatch".

### 6.3 Submit exactly once
* Write-ahead `submitted(submit_ack=false)`. Then one submit macro whose in-page guard refuses the click if a
  bubble with this JOB-ID already exists. The guard makes even a replayed macro idempotent.
* `ack=true` → `submit_ack=true`, log "submitted".
* No ack → log "submit uncertain", **no second click**, go straight to `observe`: a JOB-ID bubble or a
  correlated result later proves submission.
* After the grace period (2 observe windows): if the composer still holds our exact prompt sha, no JOB-ID
  bubble exists, and send is enabled, submission is **proven not delivered** → `failed` "submit not
  delivered" (retryable: a new attempt gets a new correlation id). Anything else → `needs_review`.

### 6.4 Result correlation
* `build_check_js(old_srcs=baseline.outputs, corr, old_outputs)` is Chrome's rule: an image below the
  user bubble containing `[JOB-ID: corr]` whose src is not in the baseline. Baseline membership rejects old
  results.
* Several correlated candidates → the same pick rule as Chrome's probe (its `flatten_diagnostics` choice),
  with every candidate logged (`candidates N, chose …`).
* Candidates that are not correlated are logged as `rejected (baseline | no JOB-ID | wrong JOB-ID)`.
* Generation timeout after a confirmed submit → `needs_review` (not `failed`: an automatic retry would pay
  twice). The record keeps the baseline, so a *delayed* result is collected by recovery (§16) without a
  resubmit.

### 6.5 Download, validate, save
* Python GET of the correlated `src` (timeout from settings): reject HTTP ≠ 200, `Content-Type` text/html,
  body < 100 B (Chrome's rule), `Content-Length` ≠ body length (partial), and magic bytes not
  PNG/JPEG/WebP. Bytes go to `<config>/firefox_jobs/<corr>/download.bin` via temp + fsync + rename, and
  `bytes_sha256` is journalled.
* Fallback (D-8) only when the Python fetch fails for a transport reason. The downloaded file must exist,
  must not end in `.part`, and must pass the same checks.
* PIL `verify()` + reopen `load()`; the format decides the extension (`OutputSpec.downloaded_ext`).
* Save: `get_output_path(source, OutputSpec(downloaded_ext=…))` (the `_AI`, `_AI_2` … rule; an existing
  file is never overwritten) → journal `saving(target, sha)` → `naming.atomic_write_bytes` in the source
  folder (same volume: atomic rename).
* Transient `PermissionError` / sharing violation → up to 3 retries of the whole write (bytes are in
  staging). `ENOSPC` / access denied / rename failure → `failed` with the staging bytes kept, so a Retry
  re-saves without generating again. B8 applies: once bytes are secured, a later soft failure (New Chat,
  overlay) is only a warning.

---

## 14. Pool integration

| Transition | Trigger | Call (existing) |
|---|---|---|
| ready → busy | claim | `_acquire_free_in` → `pool.mark_busy(tab, job_id)` + `_start_tab_image` (current job id, current image, started timestamp) |
| busy → waiting_generation | `waiting_generation` checkpoint | `pool.mark_waiting(tab, "generation")` (Chrome's call) |
| busy → waiting_user | `security.visible` while Watcher ON | `pool.mark_waiting(tab, "captcha")` + `note_captcha_event` (penalty stacking, Chrome parity); bounded by `watcher_captcha_timeout_sec` (I-52). Firefox has no CDP solver, so it always waits for the user (RULE 20: never solve). Cleared → back to busy |
| busy → error | tab gone (`E210`), macro corrupt, illegal transition | `pool.mark_error(tab, reason)` |
| busy → needs_review | uncertain submit / timeout after submit / cancel after submit | image `needs_review`; page settles through the finish path — counted like Chrome, except cancel-after-submit (cancel path, no count) |
| busy → cooling | successful save | `finish_page_after_job` → `register_job_done` (count) → New Chat → `start_cooldown` (deadline persisted by `_persist_cooldowns`) |
| cooling → ready | timer expiry | existing `try_expire` / `refresh_expired` |

Updated on the pool entry: `current_job_id`, `current_image`, `started_at` (claim), end timestamp and
`last_job_at` (settle), `jobs_completed` (Chrome's rule: every finished non-cancelled job, D-12), `last_error` (`mark_error` /
`_handle_result`), cooldown deadline (`start_cooldown`).

Eligibility is unchanged: `is_free` excludes busy, cooling, waiting, error, disconnected and unchecked
(removed) rows, and a disabled worker is never a candidate. Chrome's branch in `run_claimed_image` is not
touched. The native-input restriction stays: `_MACRO_LOCK` serialises every Ui.Vision run on the machine.

## 15. Post-job reset and cooldown

After a successful save: `finish_page_after_job(FinishCtx(..., ctrl=None, lane_reset=firefox_reset))` (New Chat always — owner Q2,
same as Chrome). `_best_effort_reset` calls `lane_reset(timeout)` when `ctrl is None`; the `reset`
phase macro clicks New Chat and verifies the clean page (the `new_chat` checks). A failure logs Chrome's
warning ("⚠ New-chat reset failed (reason) — cooling anyway") and the job stays completed. Then `start_cooldown(min_seconds)`
with the reason line, persisted. The page returns to ready only on expiry. A failed or needs_review job finishes
through the same `_finish_normal` (counted, reset, cooldown) exactly as Chrome. A cancelled job goes through
`_finish_cancelled` (no cooldown) — except after submit (§16).

## 16. Pause, stop, cancel, recovery

Checks run **at checkpoints only**, never inside a native-input macro: the lock is never abandoned with an OS
dialog open.

| Situation | Behaviour |
|---|---|
| Pause before submit | The job stops at the next checkpoint (record keeps its status; page stays busy, "paused" in the log). On resume it **re-verifies the last checkpoint** (attachment preview by name, prompt sha) before continuing; a failed re-verify steps back one phase (re-attach / re-insert). |
| Pause after submit | Generation continues on the site anyway. Observation and collection continue (losing the result is worse); no new job is claimed (`_wait_pause` in the feeder). |
| Stop after current | The feeder claims nothing (`_feeding`); the current job runs to its settle (completed / failed / needs_review) and its page finishes normally. |
| Cancel before submit | The next checkpoint ends the job: image `failed "Cancelled"` (Chrome's cancel path, no history row), staged upload deleted, `reset` macro clears the composer (best effort), `_finish_cancelled`. No submit ever. |
| Cancel after submit | Evidence is kept: the record → `needs_review` (baseline, JOB-ID, candidates). **No New Chat**, so the chat with the JOB-ID stays visible for the user and for recovery. The page settles steady without cooldown (Chrome's cancel parity). |
| Crash after submit | On the next start (and on first sight of the tab), every journal record at `submitted` or later runs `inspect` on its tab (identified by the stable `{profileDir}_tab{N}` id) before anything else is claimed on it. |
| Generated but not downloaded | `inspect.found` with a correlated, non-baseline src → `output_detected` → download → save. No resubmit. |
| Downloaded but not saved | Journal `downloading/validating` with `download.bin` present and matching `bytes_sha256` → validate → save. |
| Saved but state not persisted | Journal `saving(target, sha)` and `target` (or an `_AI*` sibling) exists with the same sha → `completed` (image completed, count +1, no cooldown restart). I-46 already marks such an image completed at scan time; recovery only reconciles the record. |
| Submit intent, no ack, crash | `inspect`: bubble with JOB-ID → submitted → wait/collect. No bubble, composer holds our exact prompt sha, send enabled → proven not sent → `failed` (retryable). Otherwise `needs_review`. |
| Before submit, crash | Nothing was sent: record → `interrupted` → image back to the queue (today's `run_scope` behaviour); the next job's stale-attachment check (§6.1) cleans the composer. |
| Tab gone during recovery | `E210` → record `needs_review` "tab gone — cannot prove outcome"; never resubmitted automatically. |

The pre-existing Firefox tab is never closed: all macros use `selectWindow` with an empty Value, no `open`, no
`close`/`selectWindow tab=close`, and `continueInLastUsedTab=0`. Only the autorun page closes itself. A test
scans every generated phase macro for forbidden commands (`open`, `close`, JS `click()`).

## 17. Logging (same shapes as Chrome)

Every line is prefixed `🦊 [corr]` (the lane marker + Chrome's correlation prefix) and every phase also emits
Chrome's `JobAction` with the **same block ids**, so the Action Blocks window's live views work unchanged.

| Event | Block id / status | Line |
|---|---|---|
| worker/job/attempt selected | — | `📤 path -> page <label> BUSY` (existing `_log_assign`) + `🦊 [corr] attempt N on <tab label>` |
| baseline | `OBSERVE_BASELINE` success | `Baseline N` |
| security | `CHECK_SECURITY` running/success, `Skipped (Watcher off)` | Chrome's texts |
| upload started / completed / verified | `ATTACH_IMAGE` running → success; `VERIFY_ATTACHMENT` success/failed | `upload started arena_x.png` · `dialog closed` · `verified preview arena_x.png` / `wrong preview <alt>` |
| prompt inserted / verified | `INSERT_PROMPT`, `VERIFY_PROMPT` | `inserted N chars` · `verified sha 1a2b…` / `readback mismatch (len a≠b)` |
| submit intent / submitted / uncertain | `SUBMIT` running → success / failed | `submit intent (journalled)` · `submitted (ack: bubble)` · `submit uncertain — no resubmit` |
| generation started / completed / timed out | `WAIT_OUTPUT` running → success/failed | `Waiting for generation — timeout Nms` · `Output <src60>` · `timeout — needs review` |
| candidate found / correlated / rejected | `WAIT_OUTPUT` | `candidates N` · `correlated <src60>` · `rejected <src60>: baseline` |
| download started / completed / invalid | `DOWNLOAD` | `Downloaded N` · `invalid: html / partial / <100 B` |
| validate | `VALIDATE` | `Valid png N bytes` |
| atomic save started / completed / failed | `SAVE` | `saving -> name` · `Saved name` · `save failed: <errno>` |
| pool / cooldown | — | existing `cooldown_service` lines (`_log_finish`, `_ready_line`) |
| settle | — | existing `[corr] [Page xxxxxx] ✅ / ❌` (`_log_result`) + Job History row |

No prompt text, file bytes or page text in the log: lengths, hashes and names only (matching the identify
reply rule).

## 18. Test plan (RED first; every new function gets a test, RULE 16)

Unit tests (fakes for the Ui.Vision run: `run_phase` returns canned savelog lines; the real `Sequence` in lane
tests — see the 2026-09-25 StepRecorder lesson):

* **Source/upload:** PNG, JPEG and WebP each stage as `arena_<corr8>.<ext>`; missing file and unsupported
  extension/content → `failed` with **zero** macro launches; stale preview in the baseline → reset + re-baseline,
  still dirty → fail; missing preview; wrong preview name; two previews; ESC is present in the attach macro's
  failure branch.
* **Prompt:** multiline, Unicode (Czech + emoji), text containing `${x}` round-trips through base64 (rendered
  payload executed in the Node lane `tests/js/`); truncated and duplicated readback → mismatch → one retry → fail.
* **Submit:** exactly one XClick in the submit macro; the guard refuses when the JOB-ID bubble exists; lost ack →
  no second submit macro is launched (call count); proven-not-sent → `failed`; ambiguous → `needs_review`.
* **Correlation:** baseline src rejected; wrong JOB-ID rejected; multiple candidates → Chrome's pick + all logged;
  timeout → `needs_review`; a delayed result found by recovery is collected with no submit call.
* **Download:** fetch error → fallback; `.part` rejected; HTML body, < 100 B, Content-Length mismatch, corrupt
  PNG → `invalid`, nothing saved.
* **Save:** `_AI` taken → `_AI_2`; `ENOSPC` / `PermissionError` / `replace` failure → `failed`, staging kept, no
  partial file left; transient sharing violation retried; journal at `saving` + file present → recovery completes.
* **State machine:** every journal step validated; the new edge `submitted → needs_review`; illegal edge →
  error + `needs_review`.
* **Pause/stop/cancel:** at each pre-submit checkpoint (no submit call ever); resume re-verifies; cancel after
  submit keeps the record, no reset call; stop-after claims nothing new.
* **Pool:** busy/cooling/waiting/error/unchecked pages are never claimed; `mark_waiting("generation"/"captcha")`
  called; count follows Chrome (+1 for completed/failed/needs_review, none for cancelled — same assertions as Chrome's tests); New Chat failure → warning + cooldown still started; cooldown
  deadline persisted.
* **Never close the tab:** a static scan of every built phase macro (no `open`, no `close`, no JS click; every
  `selectWindow` Value empty).
* **Chrome regressions:** the existing goldens stay byte-identical; `FinishCtx` defaults keep
  `register_job_done` unconditional for Chrome (explicit test); the full suite stays green; the coverage
  ratchet never drops.

**Manual spikes before coding (they decide details, not the design):**
* S1 — launch overhead per phase and whether the autorun launch steals focus during observe polls
  (sets the observe cadence).
* S2 — Ui.Vision `if`/`end` syntax in the installed version (submit guard).
* S3 — the Windows file dialog accepts XType path + Enter in the current Firefox; if not, use the
  XClick-on-Open fallback image.
* S4 — the arena preview's `alt` equals the uploaded filename in Firefox.
* S5 — the R2 `src` is fetchable from Python without cookies (already true for Chrome).

## 19. Acceptance mapping

| Acceptance criterion | Guaranteed by |
|---|---|
| One image completes without manual steps | phase chain §4 + D-1; spikes S1–S5 |
| Correct attachment positively verified | §6.1 unique staged name + exactly-one-preview rule |
| Submit executed once | §6.3 write-ahead + in-page guard + no-retry rule |
| Result proven new and belonging to the job | §6.4 baseline + `[JOB-ID]` correlation |
| Saved atomically beside the source | §6.5 `get_output_path` + `atomic_write_bytes` in the source folder |
| Invalid / uncertain output never completed | §6.5 checks, `needs_review` paths §6.3/§6.4/§16 |
| Queue / progress / pool / count / errors / cooldown correct | §14 existing calls, D-12 Chrome count rule, §15 |
| Firefox tab stays open | §16 last paragraph + static macro scan test |
| Chrome unchanged | D-10/D-11, `lane_reset` default `None`, goldens byte-identical |

---

## Owner decisions (2026-09-25, answers to the open questions)

* **Q1 — job count: same as Chrome.** Every finished non-cancelled job counts (D-12); the step-18 test
  asserts Chrome's rule, not success-only.
* **Q2 — New Chat: same as Chrome.** Always after a normal job, no switch, failure = warning (D-13, §15).
* **Q3 — needs_review list: no.** Existing image status + Job History row only.
* **Q4 — delay: only between jobs.** `inter_run_delay_sec` never applies between phases of one job (§4).

## Implementation — as built (2026-09-25, "implement now full")

Status: **implemented**; the plan above stays the reference, the amendments below win where they differ.

Refactor 2026-09-26: code audit + TDD refactor in `../2026-09-26-firefox-job-refactor/audit.md` (new `firefox_job_host` leaf; behaviour fixes B1 recovery fetch timeout, B2 supersede of older records of a re-queued image, B3 composer = first visible textarea) — it wins over this section where they differ.

| # | Decision / amendment | Why |
|---|---|---|
| D-2 amend | Chrome's payloads are reused verbatim but **never embedded raw**: `job_scripts` builds one expression per phase, `job_macros.loader` base64-decodes it in the page, runs it via `new Function`, awaits it and `JSON.stringify`s the reply. | Ui.Vision pastes `${var}` **raw** into `executeScript` Targets (docs: variables are not quoted), which would rewrite the JS template literals in `output_probes` / `js_snippets`. Macro-side flags therefore read `(${arenaGuard}).data.go`, never `JSON.parse(${…})`. |
| D-8 amend | Download = Python fetch only (3 tries, 3 s settle as Chrome) → magic + PIL validation → `config/firefox_jobs/<corr>/download.bin` → atomic `_AI` save. The in-page `<a download>` + `onDownload` fallback is **not built**; a fetch/validate/save failure ends `needs_review` with `output_src` journalled, so recovery can retry the fetch later without resubmitting. | Firefox cannot rename downloads and `!LAST_DOWNLOADED_FILE_NAME` is only valid after `onDownload`; the fallback adds a second write path for a case S5 may never hit. Revisit if S5 fails live. |
| D-15 | `needs_review` is **not runnable** (`run_scope`); only the image status + a Job History row show it (owner: no review list). | A review job may already have reached the site — a loop must never send it again. |
| D-16 | Recovery runs in `supervisor.run_live` via `_recover`: `recover_firefox_jobs` **before** `recover_stale_processing`. | Stale-processing recovery would re-queue a `processing` image whose message was already sent; the journal must settle it first. |
| Seams | `job_count.py` (moved out of `cooldown_service`, re-exported); `FinishCtx` gains the Firefox reset hook; `firefox_lane.run_phase(bridge, page, phase, token)` → `(kind, msg, lines)` under the machine-wide macro lock; `probe_selectors.add_files_primary` / `new_chat_primary`. | Legacy hotspots must not grow (RULE 16); selectors from one place (RULE 21). |
| Constants | observe window 12 s, 3 misses allowed, ack wait 6 s, 2 uncertain polls, attach wait 8 s, clean-page wait 15 s, security poll 5 s, pause poll 0.5 s, min download 100 B. | Chrome's own timings where one exists. |

**Live spikes (not provable in the sandbox — run on the owner's machine before trusting a batch):**

* **S1** launch overhead + focus per phase macro (how long one `Arena_Job_*` run holds the lock).
* **S2** `if_v2` / `else` / `end` syntax in the vendored Ui.Vision build.
* **S3** native dialog: XType path + `${KEY_ENTER}` accepted (2019 forum note: sometimes needs XClick "Open"). **Failed live 2026-09-26** (owner: dialog open, File name empty, dialog never closed). Fixed in `uivision/file_dialog.py`: `!StringEscape` off → quoted `C:/…` path into `!clipboard` → `XDesktopAutomation true` → Alt+N, Ctrl+A, Ctrl+V, Alt+O → browser mode; Enter (other-locale fallback) and ESC only while `document.hasFocus()` is false and our preview is absent. Still to confirm live: Alt+O on the owner's Windows locale (the Enter fallback covers a miss). **Second live report 2026-09-26:** the + now opens a popup (“Add files — Up to 15MB per file”, paperclip) and only that item opens the dialog → new selector `add_files_menu_item`, `job_scripts.upload_item_js` tags it, gated RED rect + XClick `css=[data-arena-upload-item]` before the dialog rows.
* **S4** attachment preview `alt` equals the uploaded file name.
* **S5** R2 output `src` fetchable by Python without cookies.
* **S6** CSP allows `executeScript` and a returned Promise is awaited — **evidenced** by the live `Arena_Identify` macro; still open: whether a long `ARENA_JOB=` echo line is truncated in the savelog (replies are kept small for that reason).
* React value setter under Firefox Xray wrappers (the prompt readback proves it either way — a failure ends the job before submit, never with a double send).

Quality: gate `verify_quality.py --allow-legacy --coverage-ratchet` 0 fails; pytest full suite green except the known `-n 8` flake; `npm run test:js` green; every new module ≥ 90 % line.

## Out of scope

Automatic captcha solving on Firefox (no CDP; RULE 20 wait-only), parallel Ui.Vision runs, any Chrome change
beyond the one defaulted `FinishCtx.lane_reset` field and the one extra `JOB_TRANSITIONS` edge, UI for the journal, changing the Firefox
identity rules (`{profileDir}_tab{N}` stays the stable id).
