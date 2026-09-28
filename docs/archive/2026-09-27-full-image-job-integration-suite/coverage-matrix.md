# Coverage matrix — every page state and job state → the test that proves it

Deliverable 15 of the owner's brief. Read with `design.md` (D-2/D-10/D-18) and
`tdd-interfaces.md` (per-stage RED branches). Lanes: **C** = Chromium (native CDP), **F** = Firefox
(adapter), **J** = jsdom (fallback). A cell shows the stage that lands it; `—` = deliberately not run
on that lane, with the narrowing recorded in the evidence bundle (D-10/D-14).

---

## 1. Page states (`fixtures.md` §3) → tests

| Page state | Scenario | Test id | C | F | J | Negative assertion (must NOT happen) |
|---|---|---|---|---|---|---|
| `ready` | `success_immediate` | `test_full_image_job.py::test_full_job_success[…]` | S4 | S6 | S6 | no submit before attach+prompt |
| `attachment_uploading` | `success_immediate` | same | S4 | S6 | S6 | no second `DOM.setFileInputFiles` |
| `attachment_ready` | `success_immediate` | same | S4 | S6 | S6 | stale tile never accepted (`stale_attachment_preview`) |
| `attachment_ready` (preview missing) | `attachment_preview_missing` | `test_full_image_job.py::[…]` | S4 | S6 | — | job must not continue to submit as "verified" |
| `attachment_ready` (upload refused) | `upload_rejected` | same file | S4 | — | — | `sendCount == 0`, no `*_AI*` file |
| `prompt_ready` | `success_immediate` | same | S4 | S6 | S6 | prompt read-back mismatch never ignored (`prompt_value_modified`) |
| `submit_enabled` | `success_immediate` | same | S4 | S6 | S6 | never click a disabled Send (`send_disabled`) |
| `submitted` | `submit_ignored` | same file | S4 | — | — | no generation started, no result invented |
| `generating` | `success_delayed` | same file | S4 | S6 | S6 | no second Send while generating (page-side `submit_ignored` guard) |
| `generation_success` | `success_immediate` / `layout_normal` | same file | S4 | S6 | S6 | baseline image never accepted (`with_baseline_old_image`) |
| `generation_error` (terminal) | `generation_error_terminal` | same file | S4 | S6 | S6 | no output file; no revival (`sendCount == 1`) |
| `generation_error` (dead request) | `generation_error_dead_request` | same file | S4 | S6 | — | **exactly** one revival, never two (D-18/L-14) |
| `generation_endless` | `generation_endless` | `test_recovery_and_reset.py::test_endless_then_next_job_succeeds` | S5 | S6 | — | pool never left `busy`; no Send during the wait |
| `generating` → spinner lost | `spinner_lost_no_output` | `test_full_image_job.py` | S5 | — | — | revival only after the 20 s grace (`app/services/captcha/recovery.py:27`) |
| `security_required` | `captcha_before_submit` (Watcher ON) | `test_captcha_scenarios.py` | S7 | — | — | the pipeline never solves/injects (I-34); Watcher OFF ⇒ zero captcha lines |
| `security_required` mid-generation | `captcha_during_generation` (ON) | same | S7 | — | — | timeout pause charged **and** capped (I-47) |
| `authentication_required` | `auth_expired_after_submit` | `test_full_image_job.py` | S5 | — | — | readiness failure is not reported as success (RULE 4); documents L-10 |
| `rate_limited` | `rate_limited` | same | S5 | — | — | penalty stacked once per failure, not per poll |
| `new_chat_ready` | every job-ending scenario | `test_recovery_and_reset.py` | S5 | S6 | — | reset failure is logged, never fatal |
| reset fails | `new_chat_reset_failure` | same | S5 | — | — | cooldown still starts; no stuck `busy` |
| New Chat href absolute | `new_chat_absolute_href` | same | S5 | — | — | pins **L-16** (honest failure), no silent "fix" |
| tab closed mid-job | `tab_closed_mid_job` | `test_tab_loss.py` | S7 | S7 | — | no second click dispatched (I-36) |

## 2. Job states (`app/core/enums.py:24-40`) → tests

| `JobStatus` | Reached by | Test | Stage |
|---|---|---|---|
| `created` → `baseline_captured` | `OBSERVE_BASELINE` | `test_full_job_success` (block-event order) | S4 |
| `attaching` → `attachment_verified` | `ATTACH_IMAGE`/`VERIFY_ATTACHMENT` | same | S4 |
| `prompt_inserted` → `prompt_verified` | `INSERT_PROMPT`/`VERIFY_PROMPT` | same | S4 |
| `submitted` | `SUBMIT` (+ page `sendCount`) | same | S4 |
| `waiting_generation` | `WAIT_OUTPUT` + pool `waiting_generation` | same | S4 |
| `output_detected` | `✅ New output verified … associated == expected` | same | S4 |
| `downloading` → `validating` | `DOWNLOAD`/`VALIDATE` | same; failure sides in `result_invalid_image`, `download_returns_html` | S4/S5 |
| `saving` → `completed` | `SAVE` + sha256 (I-57) | `test_full_job_success`, `output_name_exists` (`_AI_2`) | S4/S5 |
| `failed` | terminal error / timeout / validate failure | `generation_error_terminal`, `generation_endless`, `result_invalid_image` | S4/S5 |
| `needs_review` | strict JOB-ID mismatch path (`output_probes.py:670-684`) | `result_is_old` | S5 |
| `paused_user_action_required` | captcha wait (Watcher ON) / operator pause | `test_captcha_scenarios.py`, `test_operator_scenarios.py` | S7 |
| `interrupted` | cancel / stop-after / tab abort | `test_operator_scenarios.py` | S7 |

## 3. App-side states the brief asks to verify

| Verified thing | Where asserted | Stage |
|---|---|---|
| URL row created + enabled + linked to the tab (one row per tab, I-33) | `flow.ensure_url_row` + a second reconciler pass | S3 |
| Receiver flag + reason (I-51) | `flow.ensure_url_row` (`receiver is True`, `receiver_reason == ""`) | S3 |
| Worker enters `steady` → `busy` → `waiting_generation` → `cooldown` → `steady` | `contract.pool_states` (ordered) from `page_pool_updated` recorder | S3/S4 |
| Job-count / load balancing (I-28) | `settle` asserts `jobs_completed == 1`, next job picks the same tab | S4 |
| Queue status + progress counters + `job_finished` payload (I-39) | `settle` (`completed`, `progress.completed == 1`, payload `image_id/path/attempts/error`) | S4 |
| Error text vocabulary (`Page error: …`, `Timeout after …ms`, `send disabled`) | `contract.image_error_prefix` per scenario | S4/S5 |
| Cooldown totals incl. penalties | `contract.cooldown_total_rule` (`base`, `base+captcha`, `base+rate_limit`) | S5/S7 |
| Atomic save, no `.partial_*`, output is not the queue (RULE 23/14) | `settle` globs `*.partial_*` and deletes nothing from the queue | S4 |
| Stop/pause honoured inside the wait (RULE 7) | `test_operator_scenarios.py` (elapsed ≤ poll + 1 s) | S7 |
| Generation finished within the configured budget (the owner's "within 300 sec") | `test_timeout_contract.py::test_success_within_budget` + `clock.virtual` in the bundle | S5 |
| The 300 s production configuration end to end | `test_timeout_contract.py` (2 tests, D-8) | S5 |
| Zero captcha activity with the Watcher OFF (D-23) | counting test over logs/pool/overlay in **every** non-captcha scenario | S4 |

## 4. The brief's checklists, line by line

| Brief §6 (successful job) | Test | Brief §7 (page-reported failure) | Test |
|---|---|---|---|
| page discovered | S3 flow step 4 | upload + prompt still complete | S4 `generation_error_terminal` block events |
| URL row created and enabled | step 5 | Send occurs once | page `sendCount == 1` |
| worker enters steady | step 6 | page enters generating | page trace |
| image enters queue and is selected | step 7 | controlled error state exposed | `[role="alert"]` toast |
| dispatcher assigns the expected worker | step 9 (`📤 … -> page …` / sequential) | application detects the error | `Page error:` prefix |
| worker enters busy | pool states | no result accepted | no `output_detected` event |
| correct source image uploaded | page `alt == pic1.png` + `setFileInputFiles == 1` | no output file | `expect_nothing()` (every `*_AI*`) |
| new attachment preview verified | `VERIFY_ATTACHMENT success` | job failed with a safe reason | `image_status/error` |
| exact prompt + JOB-ID inserted | page textarea read-back | worker released per policy | `finish_page_after_job` → reset + cooldown |
| prompt readback matches | `VERIFY_PROMPT success` | retry does not reuse stale state | second attempt page trace starts at `ready` |
| Send becomes enabled | `submit_enabled` transition | | |
| one submit action occurs | `sendCount == 1` (D-18) | **Brief §8 (endless/timeout)** | **Test** |
| generation starts | spinner transition + log | waits up to the configured timeout | S5 (6 s fast / 300 s virtual) |
| result appears after the baseline | `result_is_old` negative + baseline count | never clicks Send again | `sendCount == 1` |
| result belongs to the current job | `associatedJobId == correlationId` log | expected failed state | `image_status == failed` |
| result downloads successfully | `DOWNLOAD success` + method in the bundle | no output file | `expect_nothing()` |
| bytes decode as a valid image | `VALIDATE success` (PIL 64×64) | worker not left busy forever | pool states end at `steady` |
| saved as `*_AI` / next suffix | `output_name_exists` → `_AI_2` | page reset into a clean preparing state | `new_chat_ready` trace |
| output bytes/hash match the fixture | sha256 == `result_bytes(job)` (I-57) | next job runs after recovery | the second job in the same test |
| queue item completed, count +1 | `settle` | 300 s config tested without waiting | D-8 part 2 + `test_clock.py` |
| worker cooldown → steady | pool states with `cooldown_min_seconds` small | | |

**Brief §9 (additional states)** → `design.md` §7 table (attachment/prompt/submit/result/save/reset/
captcha/operator/tab-loss groups, staged S4–S7; `restart_after_submit` explicitly out of scope,
§13 item 5). **Brief §13 (evidence)** → `design.md` §8 bundle schema. **Brief §14 (isolation)** →
`design.md` §9. **Brief §16 (acceptance)** → §5 below.

## 5. Acceptance criteria (brief §16) → where each is proven

| Criterion | Proven by |
|---|---|
| A local fake page reproduces every success and failure state deterministically | S1 `test_state_machine_walks_all_14_states` + `coverage-matrix` §1 |
| Chrome and Firefox run the same behaviour contract | S6 parametrization-only Firefox tests + `test_contract_unit.py::test_no_lane_specific_expectations` (I-55) |
| Successful simulation saves the expected bytes to the temp source folder | S4 `test_full_job_success` sha256 (I-57) |
| Error simulation creates no completed result | S4 `expect_nothing()` + `image_status == failed` |
| Endless generation times out and recovers without a stuck worker | S5 `test_endless_then_next_job_succeeds` |
| Submit occurs once per job (plus the one documented revival) | page-side `sendCount`/`resubmits` (I-58, D-18) |
| Old or unrelated images are never accepted | `with_baseline_old_image`, `result_is_old`, `stale_attachment_preview` |
| Queue, worker, progress, job-count, error, reset and cooldown states verified | §3 table |
| Full integration tests use the real app pipeline above the fake pages | `test_app_instance_has_no_patched_browser_module` (D-3) |
| No live Arena account or production network | S1 `test_no_external_urls_in_static` + `127.0.0.1`-only binding (I-56) |
| Failures produce enough evidence to diagnose the exact stage | per-step assertions in `flow.py` + the D-11 bundle + screenshot where supported |
