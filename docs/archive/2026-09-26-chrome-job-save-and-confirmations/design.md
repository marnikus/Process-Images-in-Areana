# Chrome job — image not saved after generation + step confirmations (2026-09-26)

Owner report: *"chrome connection: unable finish job and save image after
generation. Image not saved, all before this process was done."* Plus: confirm
every step of a job (image + prompt in the composer, the job really started,
no page errors, a clean new chat, generation finished or failed) and give each
end state a clear rule: **final** or **recycle** (back in the queue).

## 1. Root cause (reproduced, not guessed)

The Chrome lane downloaded the result **through the DevTools socket**:
`JS_DOWNLOAD_IMAGE` fetched the image in the page and returned
`Array.from(new Uint8Array(buf))` — a JSON array of numbers, about 3.5–4 bytes
of JSON per image byte — in ONE `Runtime.evaluate` reply.

Experiment (real headless Chromium 153, the app's own `CDPClient` +
`download._js_download`, local PNGs served over HTTP):

| image | size | result |
|---|---|---|
| mid.png | 4.7 MB | OK, 3.2 s |
| big.png | 12.6 MB | OK, 8.5 s — reply ≈ 45 MB, just under the limit |
| huge.png | 20.3 MB | `ConnectionClosedError: sent 1009 (message too big) frame exceeds limit of 52428800 bytes` |

After the 1009 close **every later call answered `CDP not connected`** — the
client never reconnects (H5). On a slower PC even the 12 MB case hits the 30 s
command timeout, and while that one evaluate runs the socket carries nothing
else. Arena outputs are large PNGs, so the last step of a finished job killed
the connection:

* the wait/download answered nothing → "Download failed" / "not downloadable";
* the post-job New-chat reset failed on the dead socket ("⚠ reset failed —
  cooling anyway");
* every following job on that tab failed at its first probe.

Contributing defects found on the way:

* H3 — `save_image` swallowed the exception (`log.warning` only) — the job
  said only "Save failed", no reason reached the job log.
* No transient-loss recovery outside `visual_click`: the output poll, the
  download fallback and the New-chat reset all failed on the first empty answer.
* The live supervisor printed "🔌 Chrome disconnected — reconnecting" but
  nothing reconnected.
* No confirmation that the image + prompt were really in the composer at the
  moment of the click, nor that the click sent the message.

Hypotheses checked and excluded: naming/atomic save (`core/naming.py` fine),
output detection (JOB-ID correlation unchanged, still the first-class proof).

## 2. Design

### D-1 Download without the socket (fix of the root cause)

`cdp_arena/download.download_image(cdp, src, log)`:

1. `data:` src → decoded locally (no network, no socket).
2. `http(s)` src → **Python fetch first** (`utils/http_image.fetch_image`, the
   Firefox lane's gate moved to `utils` so the browser layer can use it:
   HTTP 200, not HTML, ≥ 100 bytes, full Content-Length). The presigned R2 src
   needs no cookies (Firefox design D-8 / S5). Runs in an executor — no
   CDP traffic at all.
3. Fallback (blob: src, or Python refused) → **chunked page fetch**: one
   evaluate fetches into `window.__arenaDl[key]` as base64 and returns only
   `{ok, size, b64len, contentType}`; Python pulls ≤ 1 MB slices
   (`CHUNK_CHARS`), then frees the slot. No reply ever exceeds ~1 MB, so the
   socket cannot be closed by 1009 and no single command runs for long.
   Before the fallback the link is healed (D-2).

The old number-array snippet `JS_DOWNLOAD_IMAGE` is deleted (no copy kept).

### D-2 Link healing (the socket died anyway)

`page_recovery.heal_link(cdp, report)` — the socket is closed → reconnect to the
**same tab** (`recover_page_context`), else raise `LinkLost` with the reason.
Called at: every output-poll round (`cdp_arena/output._run_wait`; `LinkLost`
aborts the wait like `PageErrorAbort` instead of burning the generation
timeout), before the page download fallback, before every step confirmation,
and at the start of the New-chat reset. The supervisor's `cdp down` wait now
really tries `reconnect_same_tab` (throttled, `RECONNECT_MS`).

### D-3 Step confirmations (Chrome lane, `services/job_confirm.py`)

One page probe — `job_scripts.composer_state_js(corr, prompt)`, built on the
Firefox prelude (`__composer`, `__previews`, `__bubble`), reused not copied
(RULE 10) — returns `{composer_len, prompt_ok, marker_in_composer, previews,
bubble, send_enabled, generating, errors}`. Python decides:

| check | when | pass | fail → |
|---|---|---|---|
| clean start | before the first block | composer empty, 0 previews | New Chat once, re-check; still dirty → fail *nothing sent* |
| composer confirmed | SUBMIT, before the click (≤ 3 s poll) | preview visible (if ATTACH ran), text area == final prompt (if INSERT/VERIFY ran) | prompt: re-insert once; still wrong / no preview → fail *nothing sent* |
| already sent | same probe | JOB-ID bubble visible → click skipped (never double-send) | — |
| send confirmed | after the click + captcha settle (≤ 8 s poll) | bubble, cleared composer or generating | composer still holds the prompt → fail *not delivered*; no evidence → warn, WAIT decides |
| no new page error | every probe | no fresh error line vs the start corpus | fail with the page error |
| saved on disk | SAVE | file exists, size == bytes | fail *save not confirmed* |
| new chat | finish seam | composer empty **and 0 previews** (probe extended) | reset failure logged |

**Fail open on an unreadable probe** (RULE 9): no answer / old page shape → one
warning, the block continues (the existing checks still run). Only a positive
negative answer blocks.

### D-4 Step tracker + final/recycle verdict (`services/job_steps.py`)

`JobSteps` keeps the furthest `JobStatus` milestone reached (rank order of
`JobStatus`, forward only — the block stack is user-configurable, so strict
`JOB_TRANSITIONS` adjacency would warn on every disabled block). Every block
success maps to its milestone and logs `✔ <milestone> — <note>`; a failure
logs `✖`. The job ends with ONE summary line:

```
[corr] 🧭 Steps ✔created ✔baseline_captured … ✖saving — FAILED at saving: <err>
       → ↻ recycle: back in the queue (attempt 1/3) · image generated but not saved
```

Recycle rule = the live loop's own rule (`run_scope.in_live_scope` inputs:
`attempt_count` vs `settings.retries.max_attempts`, read through
`live.feed.retry_cap`) so the line never promises what the loop will not do:

| furthest step | meaning | verdict |
|---|---|---|
| < submitted | nothing sent | ↻ recycle (safe) while attempts left, else ■ final |
| submitted … waiting | generation failed / timed out | ↻ recycle while attempts left, else ■ final |
| output detected … saving | generated, not saved (src logged) | ↻ recycle while attempts left, else ■ final |
| completed | saved + confirmed on disk | ■ final ✅ |
| cancelled | operator stop | ■ stopped (Retry re-queues) |

Statuses written to the queue are unchanged (completed / failed) — the tracker
reports, the orchestrators own the status (no second writer).

### D-5 Visible errors

`save_image` keeps its contract (path or `None`) but stores the reason in
`ctx.save_error` and logs `❌ Save failed: <reason>`; `_handle_save` raises
`Save failed: <reason>`. The download failure text names every method's reason.

## 3. Structure and sizes (RULE 16/18/19)

`single_job_runner.py` is a legacy hotspot (963 lines, `# ideal-size`
header). New logic goes to new modules; the runner only gains call sites, and
the validate/save helpers move out (extract on touch) so the file shrinks:

| module | role | target |
|---|---|---|
| `app/utils/http_image.py` | fetch + response gate (shared by both lanes) | ~70 lines |
| `app/browser/cdp_arena/download.py` | data: / Python / chunked page download | ~150 lines |
| `app/browser/page_recovery.py` | + `LinkLost`, `heal_link`, `reconnect_same_tab` | +30 lines |
| `app/services/job_confirm.py` | D-3 checks | ~220 lines |
| `app/services/job_steps.py` | D-4 tracker + verdict | ~170 lines |
| `app/services/job_output.py` | validate / save / saved-rect (moved) + disk confirm | ~110 lines |

Every new function: ≤ 20 lines target (30 hard), CC ≤ 10, nesting ≤ 4,
≤ 4 params. Rejected dishonest reductions: packing checks into a dict-dispatch
lambda table, `# quality-override` markers.

## 4. Tests first

* `tests/test_http_image.py` — gate + fetch (ctype returned).
* `tests/test_chrome_download.py` — real `CDPClient` over the stub websocket:
  data: URL, Python first, chunked page fallback (several slices, slot freed),
  heal before fallback, error text names both methods; no reply > 1 chunk.
* `tests/test_link_heal.py` — `heal_link` / `reconnect_same_tab` / the output
  poll aborting on `LinkLost`.
* `tests/test_job_confirm.py` — every row of the D-3 table incl. fail-open.
* `tests/test_job_steps.py` — milestones, summary line, final/recycle table.
* Existing download tests updated for the new order (Python first).
* Goldens: `evals` grows by the new probes; events / images / files unchanged
  (regenerated after review, `UPDATE_GOLDENS=1`).

## 5. As built (same day) — where it differs from §2–§4

* **Package, not five `services/*.py` files (RULE 18.3):** `app/services` already
  held 27 modules, so the new step-flow code is one sub-package
  `app/services/job_flow/` (6 files): `ctx.py` (`JobCtx`, `emit_action`,
  `report` — moved out of the runner), `steps.py` (D-4), `confirm.py` (D-3 +
  `confirm_saved`), `output.py` (VALIDATE / SAVE, D-5), and `image_output.py`.
  `image_output.py` owns the save: `output_spec` + `save_beside`, which retries a
  transient Windows sharing violation up to `SAVE_TRIES = 3` times. The Firefox
  lane re-exports it from `firefox_job_output`, so both lanes have one save owner.
* **`LinkLost`** lives in `app/utils/page_errors.py`, next to `PageErrorAbort`
  (the output poll re-raises both). `page_recovery` re-exports it.
* **Supervisor (H5):** a `cdp down` plan now tries `heal_cdp` before it waits: one
  reconnect to the same tab, at most every `RECONNECT_MS = 10 s`. If that works,
  it re-plans at once. Before this, a dropped socket kept the live run waiting
  forever.
* **Block → milestone map (`steps.BLOCK_STEP`):**

  | Block | Milestone |
  |---|---|
  | OBSERVE_BASELINE | baseline_captured |
  | ATTACH_IMAGE / VERIFY_ATTACHMENT | attachment_verified |
  | INSERT_PROMPT | prompt_inserted |
  | VERIFY_PROMPT | prompt_verified |
  | SUBMIT | submitted |
  | WAIT_OUTPUT | output_detected |
  | DOWNLOAD | downloading |
  | VALIDATE | validating |
  | SAVE | saving |

  Success appends `completed`. The confirmations add their own trail entries:
  `clean_start`, `composer`, `sent`, `saved_on_disk`.
* **Measured:** the full fast lane gives 2,642 passed / 13 skipped. JS: 428 passed.
  `verify_quality --allow-legacy` shows the same 5 fails as the base commit
  `cf44cec`, all radon-drift `max_cc` in files this change does not touch:
  `main`, `json_store`, `live/bus`, `hashing`, `win_find`. Nothing new fails.
  * Changed files stay at or under their ratchet. `single_job_runner` shrank
    from 963 to 865 lines. `download.py`, `new_chat.py` and `supervisor.py` are
    back at or under their `max_func_loc` baseline.
  * New functions: worst CC is 9 (`check_response`) and worst cognitive is 7.
    Every function is ≤ 20 lines.
  * Coverage: `single_job_runner` 86.35 (floor 85.88), `download` 98.13,
    `page_recovery` 100, `new_chat` 83.77 (floor 82.14), and 94–100 % across
    `job_flow/*`.
* **Tests as landed:**
  * `test_chrome_download.py` (17) — fake page + opener; the real websocket
    lane stays in `test_cdp_arena.py`. It also holds the `http_image` gate tests.
  * `test_link_heal.py` (13), `test_job_confirm.py` (32), `test_job_steps.py` (17).
  * `test_job_flow_confirmations.py` (7) — the real runner end to end:
    * happy path confirmed on disk
    * submit not delivered → recycle
    * already sent → no second click
    * dirty start → nothing runs
    * save reason visible
    * short write caught
    * unreadable page fails open
* **Real Chrome:** `composer_state_js` was checked on a composer fixture with
  headless Chromium 139 in three states: empty, ready (1 preview + prompt), and
  sent (bubble). The composer-empty probe in `new_chat` counts the preview.
* **Not verified:** the live arena.ai site. The owner's exact failure is still
  inferred from H1/H3/H5. The step summary line and the named download / save
  errors will show which one it was on the next run.
