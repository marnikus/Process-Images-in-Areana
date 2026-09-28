# Evidence — what the app does today (every claim with `file:line`)

Research for `docs/archive/2026-09-27-full-image-job-integration-suite/design.md`. Read at
`02e0240` (S7 receiver flag + the ⊘ icon, I-51), 2026-09-27. Nothing here is a proposal; §9–§10
are the only sections that describe what is **missing or wrong**.

Method: read the whole run path top-down (slot → supervisor → orchestrator/dispatcher →
`single_job_runner` → `cdp_arena` → `cdp/`), then the three contracts a fake page must satisfy
(CDP wire, selector registry, in-page JS payloads), then every test asset that already exists.
`grep -ril "firefox|ui.vision|uivision|kantu|xmodule"` over `app/`, `tests/`, `docs/`,
`*.bat`, `*.sh`, `package.json` returns **0 files** — the Old-App Firefox/Ui.Vision worker the
owner's inspiration text assumes does not exist in this repo (§9 L-9).

---

## 1. The real path — owner's 5 steps → the app's 16

| # | Owner's step | Real entry point | What happens | Observable |
|---|---|---|---|---|
| 1 | *detect the web page* | `Bridge.get_tabs()` `app/ui/panels/browser_tabs.py:401`; `auto_connect_scan(source)` `:423`; the boot-started reconciler `app/services/live/reconcile.py:192` | one pass = `fetch_tabs` (HTTP `/json/list`) → removal table → claim/add rows → **join pool** → presence → commit + `wake("urls")` (`reconcile.py:136-178`) | log `🤖 Auto-connect: +N rows, …`; `bridge.state.urls` grows; `_url_pass_count` |
| 2 | *create URL* | `add_url(url)` `app/ui/panels/url_queue.py:139` (manual) or `url_policy.add_rows` via `_apply_adds` `reconcile.py:104` (auto) | `UrlRow.create` `app/core/models.py:26`, identity = CDP **target id** in `tab_id` (I-33), never the URL alone | `bridge.state.urls[i].{id,url,enabled,tab_id,receiver,receiver_reason}` |
| 3 | *add page to pool* | `connect_page_pool(ws_url)` `app/ui/panels/page_pool.py:140` → `do_connect_page_pool` `:78-93` | real `CDPClient` connect + real `CDPArenaController` + `PageInfo(tab_id, ws_url, title, url)` → `finish_pool_join` → `pool.register_client` | `get_page_pool_status()` `:104` → `{total, steady, busy, cooling, pages[]}`; log `Pool add <id> steady` `app/browser/page_pool.py:96` |
| 4 | *select image + send as job* | `set_folder_path` `app/ui/panels/queue_scan_folder.py:91` → `commit_folder` `:65`; `scan_folder()` `app/ui/panels/queue_scan.py:253` (non-blocking, `run_off_ui_thread` `:58`); `bulk_select(sel, filter)` `:297`; `set_prompt(t)` `app/ui/panels/app_settings.py:264`; `save_settings(json)` `:271`; **`start_run()`** `app/ui/panels/run_control.py:230-247` | scan → queue rows; `run_scope` filters (I-44); gates `check_start_inputs` + `check_start_ready` `:85-96`; `recover_stale_processing`; `schedule_batch(self, run_live(self))` | `bridge.state.images[].status`; `_run_state == "running"`; `🚀 Run started: N images…` |
| 5a | *image + prompt in textarea, verified* | `ATTACH_IMAGE` → `cdp_arena/attach.py:28` (`DOM.setFileInputFiles` via `app/browser/cdp/dom.py:86-108`) then `verify_attachment` `:18`; `INSERT_PROMPT` → `cdp_arena/submit.py:16` (`JS_INSERT_PROMPT`), `VERIFY_PROMPT` reads the value back (`JS_VERIFY_PROMPT` `submit.py:31`) | the prompt is `[JOB-ID: <corr>]\n<user prompt>` (`app/utils/correlation.py:13-15`, RULE 22) | block statuses via `job_action_status`; the page's own textarea value |
| 5b | *Send button on* | `submit_when_ready` `cdp_arena/submit.py:76-84` polls `JS_SEND_STATE` `:62-72` until `enabled`, ≤8 s | `found/visible/enabled` from `button[aria-label="Send message"]` presence selector | `send disabled` failure text when it never enables |
| 5c | *generation starts* | `SUBMIT` → `_submit_visual`/`_submit_fallbacks` `single_job_runner.py:205-238` → `visual_click.find_and_click` → in-page `target.click()` `app/browser/dom_highlight_js.py:160`; then `WAIT_OUTPUT` `_handle_wait:488-505` | spinner `div.animate-spin` + `span.truncate` "Response A/B" = generating (`site_adapter.py:32`) | `⏳ Generating <label> spinner visible` `app/browser/output_wait.py:57-63`; pool → `waiting_generation` |
| 5d | *generation finishes, new image on page* | `wait_for_new_output_with_spec` `output_wait.py:196-221` polling `JS_CHECK_NEW_OUTPUT_V3` `app/browser/output_probes.py:73-733` | new `img` **not in baseline**, below the prompt block, `complete && naturalWidth>0`, `associatedJobId == correlationId` (strict, RULE 22/15) | `✅ New output verified: … associated X == expected X` `output_wait.py:66-77`; GREEN collect rect |
| 5e | *saved within 300 s* | `DOWNLOAD` `single_job_runner.py:367` → `cdp_arena/download.py:70-78` (in-page `fetch` → canvas → Python `urllib`); `VALIDATE` `:554` (PIL); `SAVE` `:562` → `get_output_path` + `atomic_write_bytes` `app/core/naming.py:65-97` | `<base>_AI.<ext>` beside the source, unique suffix `_AI_{n}` unless overwrite (RULE 23) | `image.output_path`, `status=completed`, `progress.completed`, file bytes on disk |
| 5f | *page returns error / refuses* | error scan every poll: `build_error_scan_js` `app/utils/page_errors.py:118-139` + `match_page_error` `:85-92` → `PageErrorAbort` → `_poll_diag_or_revive` `cdp_arena/output.py:86-101` | a **fresh** line matching `ERROR_PATTERNS` `page_errors.py:15-39` aborts the wait (I-30) instead of burning the timeout | job `failed` with `Page error: <line>`; rate-limit lines stack the penalty (`is_rate_limit_error` `:95`, `maybe_note_rate_limit` `app/services/cooldown_service.py:438`) |
| 5g | *endless generation → restart page* | timeout in `_check_timeout` `output_wait.py:160-176`; then `finish_page_after_job` `cooldown_service.py:637` → `_finish_normal:771` → `_best_effort_reset:658` → **`reset_to_new_chat`** `app/browser/new_chat.py:183-194` (click `a[href="/image/direct"]` via the visual runner, then wait document complete + page ready + composer empty `:157-181`) | the page returns to a clean preparing state; the tab then cools down (`start_cooldown`) and flips COOLDOWN→STEADY on expiry (`page_status.try_expire:71`) | `↩ New Chat clicked …`, `↩ New-chat reset ready`, pool row countdown, `jobs_completed` ++ |
| 6 | *worker/queue/cooldown states* | `register_job_done` `cooldown_service.py:669`, `mark_steady/mark_error/mark_waiting` `page_pool.py:120-152`, `feed.commit_queue` (I-48) | pool status + queue status + progress are three separate read models | `page_pool_updated`, `arena_state_updated`, `progress_updated` |

**Two run shapes share one pipeline.** Sequential: `run_live` `app/services/live/supervisor.py:134`
→ `plan_pass:61` → `run_pass:93` → `prepare_batch` `app/services/batch_orchestrator.py:383` →
`_try_parallel:406` (needs ≥2 free allowed tabs) → `_run_sequential:346` → `_run_one_image:319`.
Parallel: `dispatch_parallel` `app/services/multi_page_dispatcher.py:343` → `run_one_image_on_page:277`
(`_acquire_free_in:114` = checked rows only, I-33) → both end in
`run_blocks_for_image` `app/services/single_job_runner.py:947-958` over the **same** handler map
`:739-765`. A full-integration test therefore covers both shapes with the same fake pages.

---

## 2. Frozen contract A — the CDP surface the app speaks

This is the complete list. A lane that answers these eight families **is** a Chrome, as far as
this app is concerned (`design.md` D-12 builds the Firefox adapter on exactly this table).

| # | Method / endpoint | Call site | Params the app sends | Reply the app reads |
|---|---|---|---|---|
| A1 | `GET http://<host>:<port>/json/list` | `app/browser/cdp/tabs.py:87` (`fetch_tabs_sync`), `app/browser/cdp/client.py:36` (aiohttp fast path) | — | `[{id,title,url,webSocketDebuggerUrl,type}]` → `parse_tabs` `app/browser/cdp_protocol.py:91-104`; `type != "page"` and devtools URLs are dropped (`is_devtools_url`) |
| A2 | `GET /json/version` | `app/browser/cdp/probe.py:30` (diagnose only) | — | `{Browser, webSocketDebuggerUrl}` |
| A3 | port probe | `tabs.py:_is_port_open` (TCP connect, 1 s) | — | open/closed → the honest "Chrome not running" message `tabs.py:89` |
| A4 | WS connect | `app/browser/cdp/connect.py:26-42` (7 candidate URLs: `ws_url`, normalized, `localhost`↔`127.0.0.1`, rebuilt from tab id) | — | `websockets.connect(max_size=50 MB, open_timeout=10)` `:117-122` |
| A5 | `Page.enable` `DOM.enable` `Runtime.enable` `Network.enable` | `connect.py:105-108` | — | failures are swallowed (`log.debug`) — a lane may answer `{}` |
| A6 | `Runtime.evaluate` | `transport.py:140-153` — **the only probe path** | `{expression, returnByValue: true, awaitPromise: true}`, timeout 30 s | `{"result":{"result":{"value":…}}}`; `{"result":{"exceptionDetails":…}}` → kind `js`; `{"error":{code,message}}` → kind `protocol`; transport raise → kind `transport` (`_decode_reply:166-178`, I-36) |
| A7 | `DOM.getDocument` / `DOM.querySelector` / `DOM.querySelectorAll` / `DOM.setFileInputFiles` | `app/browser/cdp/dom.py:26 / 35 / 44 / 53`, orchestrated by `attach_image_cdp:86-108` | `{depth:0}` · `{nodeId, selector}` · `{nodeId, files:[absPath]}` | `{root:{nodeId}}` · `{nodeId}` (**0 = not found**, the attach loop tries the 3 selectors in order `:79-84`) · `{}` |
| A8 | `Page.reload` | `app/browser/cdp_arena/state.py:73` (`reload_page`) | `{}` | falls back to `evaluate("window.location.reload(); true")` `:76` |

Clicks are **not** CDP `Input.dispatchMouseEvent`: the shared visual runner clicks **inside the
page** (`target.click()` in `app/browser/dom_highlight_js.py:160`, dispatched from
`visual_click.find_and_click`). Consequence for the fake pages: a plain DOM `click` handler is
enough, and no lane needs native input — which is why the whole suite is headless-safe and why
the brief's "visible desktop / one native-input test at a time" section does not apply here
(`design.md` §13 item 9 — the `e2e_desktop` marker stays reserved and unused).

Network domain events are consumed **only** by the captcha recorder
(`app/services/captcha_recording/network.py:67-70,104`), which never starts while the Captcha
Watcher is OFF (D-23 / I-34). A lane may therefore ignore `Network.*` entirely as long as the
Watcher stays OFF — asserted, not assumed (`coverage-matrix.md` row C-14).

---

## 3. Frozen contract B — the page contract (selector registry)

One source of truth: `app/browser/site_adapter.py` (RULE 21), read by every payload through
`app/browser/probe_selectors.py`. **A fake page that satisfies this table satisfies the app.**

| Key | `site_adapter.py` | Primary | What the fake page must do | Blocks / probes served |
|---|---|---|---|---|
| `prompt_textarea` | `:120` | `textarea[name="message"]` (fallbacks `textarea[placeholder^="Describe"]`, `textarea[rows="1"]`), scope `form`, visible+enabled | accept a value set through the **native setter** + `input`/`change` events (`JS_INSERT_PROMPT` `app/browser/cdp_arena/js_snippets.py:39-60`), keep it readable for the read-back | `INSERT_PROMPT`, `VERIFY_PROMPT`, `HIGHLIGHT_PROMPT`, `TYPE_PROMPT`, page-loaded + composer-empty probes (`new_chat.py:43-60`) |
| `send_button` | `:135` | `button[aria-label="Send message"]:not([disabled])`; presence selector `button[aria-label="Send message"]` | `disabled` while the composer is empty (real page adds `opacity-50 pointer-events-none`), enabled after prompt/attachment; count clicks | `SUBMIT`, `HIGHLIGHT_SUBMIT`, `JS_SEND_STATE`, readiness gate |
| `file_input` | `:61` | `form input[type="file"][accept*="image"]` (hidden), presence `input[type="file"]` | be a real `<input type=file accept="image/*">` so `DOM.setFileInputFiles` / `set_input_files` lands and fires `change` | `ATTACH_IMAGE` (A7) |
| `add_files_button` | `:44` | `button[aria-label="Add files"]`, scope `form:has(textarea[name="message"])` | exist and be clickable (the app highlights it; the upload itself goes to the input) | `HIGHLIGHT_ATTACH`, `CUSTOM_FIND` |
| `attachment_preview_container` / `_image` | `:77` / `:89` | `div.flex.flex-wrap.gap-2` · `div.flex.flex-wrap.gap-2 img[alt]` (fallbacks `img[src^="blob:"]`) | after `change`, render a preview tile with `alt=<file name>` and a `blob:` src (`URL.createObjectURL`) | `VERIFY_ATTACHMENT` (`JS_VERIFY_ATTACHMENT` `js_snippets.py:111-129`) |
| `remove_file_button` | `:105` | `button[aria-label="Remove file"]` | remove the tile on click | `CUSTOM_FIND`, the `upload_rejected` scenario |
| `output_region` | `:151` | `div.no-scrollbar.relative.flex.w-full.flex-1.flex-col.overflow-x-auto`, presence `div.no-scrollbar` | be the conversation/message container; readiness gate probes the presence selector | `OBSERVE_BASELINE`, readiness |
| `output_image` | `:167` | `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]` + 13 fallbacks (`img[src*="messages-prod."]`, `div.no-scrollbar img[src^="https://"]`, `main img`, …) | the generated result `<img>` must match the **primary** (see D-6: the marker is a path segment on the local origin), be `complete` with `naturalWidth>0`, and sit in a message block whose text carries the `[JOB-ID: …]` | `WAIT_OUTPUT` (`JS_CHECK_NEW_OUTPUT_V3`), `DOWNLOAD` |
| `processing_spinner` | `:32` | `div.animate-spin` (user HTML: `div.h-5.w-5.flex-shrink-0.animate-spin > canvas`, sibling `span.truncate` = "Response A"/"Response B") | visible ⇒ generating; must disappear before the result is accepted | `WAIT_OUTPUT`, `AWAIT_PROCESSING_IMAGE` (`app/browser/processing_probe.py`), `JS_IS_GENERATING` `js_snippets.py:200-212` |
| `model_label` | `:18` | `span.truncate` scoped to `div.flex.min-w-0.flex-1.items-center.gap-2`, text `Max` | present so the spinner label probe resolves | spinner detail log |
| `security_dialog` | `:194` | `div[role="dialog"][data-state="open"]` + text `Security Verification` | only for the captcha scenarios; with the Watcher OFF the app must do **nothing at all** (D-23) | `CHECK_SECURITY`, `captcha_js/visible.js`, `detect.js` |
| `recaptcha_iframe` | `:208` | `iframe[title="reCAPTCHA"]` / `#recaptcha-v2-container` | placeholder only — never a live Google frame (RULE 20, brief §1) | detection kind |
| `composer_form` | `:224` | `form:has(textarea[name="message"])` | wrap input + textarea + Send | scope for all of the above |
| `new_chat_button` | `:238` | `a[href="/image/direct"]` inside `li[data-sidebar="menu-item"]`, label `span` "New Chat" | **real navigation** to a clean page (the reset waits for `readyState == complete` + readiness + empty composer) | `ADVANCE` / post-job reset (`new_chat.py:183`) |

Readiness composite = `prompt_textarea` + `send_button` + `file_input` + `output_region`
(`site_adapter.py:257-264` → `probe_selectors.readiness_checks():56-62` → `JS_PAGE_READY`
`js_snippets.py:182-200`); a fresh new chat tolerates missing file/output
(`new_chat.py:139-152`). Error scan selectors are separate and **not** in the registry:
`[role="alert"],[role="alertdialog"],[aria-live="assertive"],[class*="toast"],[data-toast],
[class*="Toast"],[class*="error-banner"],[class*="error-toast"],[class*="alert-banner"]` + any
`div` containing "trace id" (`page_errors.py:118-139`) — the fake page's error/rate-limit states
must render into one of those.

---

## 4. Frozen contract C — the in-page payloads that must actually execute

RULE 8 + I-38: these are code, not strings. The fake pages are the first place where **all** of
them run against one coherent DOM in the right order.

| Payload | Source | Depends on (fake-page behaviour) |
|---|---|---|
| `JS_BASELINE_V3` | `app/browser/output_probes.py:22-71` | skips `blob:` and `<50 px` icons, reads `getBoundingClientRect().top`, `getComputedStyle(el).opacity`, spinner visibility via `offsetParent` |
| `JS_CHECK_NEW_OUTPUT_V3` | `output_probes.py:73-733` | `ol.flex-col-reverse` / `flex-direction: column-reverse` detection `:96-108`; `/\[JOB-ID:\s*([^\]\s]+)\]/g` scan of message text `:121-165`; container walk `div.flex.min-w-0.flex-1.flex-col.items-end, div.group, div.flex.flex-col, div[data-message-id]` `:155`; below/above-prompt geometry; `naturalWidth` preference; strict `associatedJobId == correlationId` gate `:670-684` |
| `JS_INSERT_PROMPT` / `JS_VERIFY_PROMPT` | `cdp_arena/js_snippets.py:39-60 / 85-95` | React-style native value setter + `input`/`change`; visible-composer choice (`offsetParent !== null`) |
| `JS_SEND_STATE` / `JS_CLICK_SEND` | `js_snippets.py:63-78 / 89-110` | `disabled` property truth, `mousedown`/`mouseup`/`click` dispatch, click counted once |
| `JS_VERIFY_ATTACHMENT` | `js_snippets.py:111-129` | preview tile with `alt` or `blob:` src |
| `JS_PAGE_READY` / `JS_IS_GENERATING` / `JS_SECURITY_DIALOG` | `js_snippets.py:182-212`, `app/browser/captcha_js/visible.js` | readiness composite, spinner, dialog predicate |
| `JS_DOWNLOAD_IMAGE` | `js_snippets.py:130-181` | same-origin `fetch(url,{credentials:'include',mode:'cors'})` → bytes array; canvas `toDataURL` fallback (needs a **decodable** image, so the fixture must be real PNG bytes); HTML/`<100 B` rejection |
| FIND / CLICK / HIGHLIGHT / CLEAR / watcher overlay | `app/browser/dom_highlight.py:186-320`, `dom_highlight_js.py:1-161` | `scrollIntoView`, `getBoundingClientRect`, overlay `div[data-arena-highlight]` with `pointer-events:none`, `__arenaStash` reuse between phases (I-1) |
| new-chat page-loaded / composer-empty | `app/browser/new_chat.py:43-60` | `document.readyState`, textarea presence + empty value |
| error scan | `app/utils/page_errors.py:118-139` | `innerText` of alert/toast regions, ≤3 "trace id" divs |

---

## 5. Knobs that already exist ⇒ this suite needs **zero** production change

| Need | Existing knob | Where |
|---|---|---|
| generation timeout 300 s | `save_settings({"generation_timeout": 300})` → clamp 30…3600 → `state.settings.timeouts["generation"]` + `config.set_state(watcher_generation_timeout_sec=…)` | `app/ui/panels/app_settings.py:72-84,271-286`; default is **180** (`app/core/models.py:159-165`) |
| short injected timeout for fast tests | the `WAIT_OUTPUT` block's own `timeout_ms` wins over settings | `app/services/single_job_runner.py:493` |
| CDP host/port per test | `config.set_state(cdp_host=…, cdp_port=…)` / `set_cdp_connection` slot | `app/persistence/config_manager.py:16-17`, `app/ui/panels/cdp_tools.py:146-158`, read at `app/ui/bridge_context.py:159-160` |
| URL pattern so `127.0.0.1` tabs are auto-connected | `config.set_state(url_pattern=…)`; blank pattern matches every URL | `reconcile.py:143`, `app/services/auto_connect.py:38-44` |
| no cooldown wait between jobs | `cooldown_min_seconds=0` (`0` disables), `cooldown_enabled` | `app/services/cooldown_service.py:58-70`, `app/core/cooldown.py:29-38` |
| block stack per scenario | `config.set_state(action_blocks=stack_to_dicts(stack))` | `tests/characterization/harness.py:106-121` already does exactly this |
| Captcha Watcher OFF (default) ⇒ zero captcha activity | `captcha_in_scope(bridge)` fail-closed | `app/services/captcha/policy.py`, I-34/D-23; `watcher_on=True` arms it (`harness.py:100-108`) |
| real Bridge with no Qt | `qt_compat` dummies; signals are replaceable objects | `app/ui/qt_compat.py:11-31`; `harness.py:94-103` swaps in `Recorder`s |
| app async work without a Qt loop | the bridge owns a daemon bg loop; slots schedule onto it | `app/services/run_state.py:83-131` (`ensure_bg_loop`, `schedule_coro`, `schedule_batch`) |

---

## 6. Test assets to reuse (do not rebuild)

| Asset | What it gives | Reuse in this suite |
|---|---|---|
| `tests/characterization/harness.py` | real `Bridge` on tmp dirs + `Recorder` signals + trace normalization + golden compare + `run_supervisor` (`:211-250`) that drives the real `run_live` and arms the stop lever | the app-instance builder and the trace shape are lifted into `tests/e2e/app_instance.py` / `evidence.py` (D-3, D-11) |
| `tests/characterization/fakes.py` | `FakeCDP`, `FakeCtrl`, `install_patches` — the **component** lane | stays where it is; the e2e lane must NOT use it (RULE 8: it deletes the thing under test) |
| `tests/fakes/cdp_stub_server.py:26-104` | a real websocket CDP stub + a real HTTP `/json/list` stub, ephemeral 127.0.0.1 ports | the skeleton for the jsdom lane's server and for the Firefox adapter's discovery surface |
| `tests/conftest.py` | session loop, `isolated_*` tmp fixtures, `cdp_server`/`FakeCDPServer`, auto-marking by path (`:33-43`) | new markers + auto-mark for `tests/e2e/**` (D-19) |
| `tests/js/page_harness.mjs`, `fake_dom.mjs` | whole-page V8 sandbox harness for the app's own UI | pattern for the jsdom lane's Node sidecar |
| `tests/js/test_captcha_saved_page.mjs` | runs the real probes in jsdom against the owner's **saved real pages**, `skip` when absent | the precedent for the skip-gated saved-page cross-check (D-15) |
| `pytest.ini` markers | `unit / integration / e2e / slow / serial` (`--strict-markers`) | `e2e` finally gets a real meaning; add `e2e_browser`, `e2e_desktop`, `e2e_slow` (D-19) |
| `tools/verify_quality.py`, `tools/pre_push_check.sh` | the gate; scans **only** `app/` (`verify_quality.py:162`, `:179`) and `app/ui/web` for JS | `tests/e2e/**` is out of scope for size/CC (RULE 16.0) but not for RULE 18 ideals (`quality-budget.md` §2) |
| coverage floors | line **86.36** / branch **82.33** (`tools/quality_baseline.json`) | must not drop — see `quality-budget.md` §4 for why skipping is safe |
| **the app's own sanitized capture stack** | `app/browser/recording_js/snapshot.js:18,20` (full redacted DOM snapshot), `recording_probes.py:19,24,29,34` (observer / netwrap / flush / snapshot builders), `app/services/recording/proberun.py:42` (`snapshot_html`), `store.py:41,55,71` (session folder: `session.json` + `NNNN.html` + `events.jsonl`, atomic, `MAX_HTML_LINE = 2000`), `sanitizer.py:13,27,37,53`, `app/services/captcha_recording/network.py:20,23,36` + `sanitize.py:10,12,16,28,35` (`safe_url` / `redact_text` / `clean_mapping`); roots `config/captcha_recordings/` (`captcha_recording/store.py:113`, SYSTEM_OF_RECORD row 22) and `logs/recordings/` (`app/ui/panels/recording_sessions.py:20,44`) | **DOM-side capture and the one redaction vocabulary** for the fixture ingest (D-23, `record-replay.md` §6) — imported read-only, never re-implemented (RULE 21). Note `netwrap.js:3`: it *never* records bodies ⇒ image bytes must come from a HAR export |

---

## 7. Environment facts at plan time (measured, not assumed)

| Fact | Measurement |
|---|---|
| No browser binaries in this workspace | `which google-chrome chromium chromium-browser firefox` → nothing; `node -v` = v22.22.3 |
| No Python test deps installed here | `pytest`, `PySide6`, `websockets`, `PIL`, `radon`, `aiohttp`, `qasync`, `playwright` all `ModuleNotFoundError`; no `.venv/` |
| No JS deps installed here | `node_modules/` absent ⇒ `jsdom` unavailable until `npm install` |
| Consequence | every browser lane must **skip loudly** when its binary/deps are missing (RULE 4: empty ≠ broken), and the doc-only phase can be verified by reading, not running |
| Repo state | single visible commit `02e0240` (2026-09-21) `S7 receiver flag + the ⊘ icon (I-51)`; branch `arena/01a0e1fe-process-images-in-areana` |
| Saved real page committed | `docs/research/Directly Chat with Frontier Image Generation AI Models.html`, 386 396 bytes, tracked |
| Saved real pages NOT committed | `.gitignore` `arena webpages/`; `tests/test_repo_hygiene.py:24-27` fails the suite if anything under it is tracked (I-43) |
| Committed fixture budget | the patchset cap (~128 MB / 10 000 files) and `.gitignore` mean fixtures must be **small hand-rebuilt HTML + a few tiny PNGs**, never saved page dumps |

---

## 8. Latent defects found while researching (numbering continues the L-series)

L-1…L-8 belong to `docs/archive/2026-09-20-dynamic-urls-and-worker-debug/` (L-1 landed in S1;
L-5…L-8 still open per `docs/README.md:72`). New, all test-relevant, **none fixed by this plan**
(it is test-only): each becomes an assertion of *current* behaviour plus a recorded gap.

| ID | Defect | Evidence | Why the suite must know |
|---|---|---|---|
| **L-9** | **No Firefox / Ui.Vision worker exists.** The brief's Firefox lane has no production counterpart | `grep -ril "firefox\|ui.vision\|kantu\|xmodule"` → 0 files; the only browser code is `app/browser/cdp*` | the Firefox lane must be a **test-side adapter** (D-1/D-12), not a "worker path" |
| **L-10** | `test_url` is a stub: any `http`-prefixed string becomes `ready` with **no** reachability / auth / readiness probe, although SYSTEM_OF_RECORD row 1 promises `unreachable / auth_required / not_ready`; the enum vocabulary differs too | `app/ui/panels/url_queue.py:185-197` vs `docs/current/SYSTEM_OF_RECORD.md:36` vs `app/core/enums.py:3-11` (`READY/UNAVAILABLE/AUTH_REQUIRED/CAPTCHA_REQUIRED/UNSUPPORTED/ERROR`) | an `authentication_required` fake page cannot be asserted through `test_url`; the suite asserts the **readiness probe** (`is_page_ready`, `cdp_arena/state.py:34`) and the doc/enum drift is recorded, not silently "fixed" by a test |
| **L-11** | `reload_page` (the "restart the page" recovery the brief asks for) is **not wired into any pipeline path** — only `mixins.py:126` exposes it and `tests/test_cdp_arena.py:411` calls it. Post-timeout recovery is New Chat reset only | `app/browser/cdp_arena/state.py:69-91`; callers: none in `services/` | the endless-generation test asserts **New Chat → clean preparing state** (what exists) and records reload-based recovery as a follow-up, instead of asserting a behaviour the app does not have |
| **L-12** | the poll interval of the generation wait is hard-coded (`PollSpec(…, poll_interval=2.0)`), so a "short timeout" test still pays ≥2 s per poll and cannot be tightened without a production change | `app/browser/cdp_arena/output.py:187-188` | the fast-lane time budget in `quality-budget.md` §5 is computed with 2 s polls; the virtual clock (D-9) patches the wait modules rather than the interval |
| **L-13** | the `e2e` marker exists but marks only 4 sash-grid smoke tests that never touch a browser; there is **no** test anywhere that runs one job against a page | `pytest.ini:8`, `tests/conftest.py:33-38`, `tests/integration/test_sash_webengine.py:18-19` | this suite is what gives `e2e` its meaning; the marker policy must not break the existing 4 tests |
| **L-14** | a dead-generation toast triggers **one bounded resubmit** (`MAX_RESUBMITS = 1`) that is armed for *every* generation wait, not only under captcha — so "submit happens exactly once" is false as a blanket rule | `app/services/captcha/recovery.py:27-28,130-162`; armed unconditionally at `app/services/single_job_runner.py:267` (`_arm_revival`) | the submit-count contract is stated per scenario (D-18): `sendCount == 1` for success/timeout/terminal-error, `== 2` for the dead-request toast and the spinner-loss scenarios |
| **L-15** | `run_off_ui_thread` uses the thumbnail executor when present, so a scan completes on a **worker thread** with no completion signal the test can await — only `_scan_in_progress` and the queue contents | `app/ui/panels/queue_scan.py:58-66,253-267` | the e2e driver polls with a deadline (`wait_until`, D-4) instead of awaiting a slot return; a scan is "done" when `images` stops changing and `_scan_in_progress` is False |

---

## 9. Gaps this suite closes

| ID | Gap | Closed by |
|---|---|---|
| G-1 | no local page that satisfies the selector registry exists — every browser-side test today uses a scripted `FakeCtrl` (`tests/characterization/fakes.py:37-118`) that answers whatever the test wants | the fake site (`fixtures.md`) |
| G-2 | the three contracts in §2–§4 have never been exercised **together** in one process | the one global test per scenario × lane (D-2) |
| G-3 | no proof that the saved `*_AI.png` bytes are the **job's** bytes (only that a file appeared: `harness.py:163` globs `*_AI*` names) | D-7 deterministic per-job bytes + sha256 assertion |
| G-4 | no proof that Send is clicked exactly once **from the page's side** | D-17 page-side event log + `sendCount` |
| G-5 | the 300 s production configuration has never been asserted (default is 180 s, `app/core/models.py:159`) | D-8 two-part contract |
| G-6 | endless generation → recovery → **next job succeeds** has never been tested end to end (`tests/test_cooldown_service.py` patches `reset_to_new_chat` in 11 places) | scenario `generation_endless` + the recovery follow-up job |
| G-7 | the Firefox side of the behaviour contract does not exist at all (L-9) | D-12 adapter lane, same `contract.py` |
| G-8 | no failure artifact that says *which stage* broke (the brief §16 last line) | D-11 evidence bundle |
| G-9 | page-error / rate-limit / auth / security states have unit coverage of the **regexes** (`tests/test_page_errors.py`) but never of a page that actually renders them | scenarios E-1…E-6, C-13…C-15 |
