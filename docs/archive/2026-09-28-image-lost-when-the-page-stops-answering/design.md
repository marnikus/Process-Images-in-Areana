# An image that is on the page is never lost — design (2026-09-28)

Owner report (2026-09-28 08:28–08:32, job `20260928-082831-F8KU`): *"still some
problems to save image on page"* — the run failed, nothing was saved, and the
generated image stayed on the arena.ai page until the app reset the chat.

This is the follow-up to the 2026-09-27 round (`I-70`…`I-73`, dialogs / liveness /
home-loop / 5 s page checks). I-73 promised *"the image is seen as soon as the page
answers"*; this log shows the app failing that promise, so the contract is tightened
and the missing half is added: when the wait gives up, the app now takes the image
that is on the page instead of only reporting the timeout.

## 1. Evidence — what the owner log says

```
08:28:31 [F8KU] Starting icon-process-gears.png with URL …/image/direct?model_a=max
08:29:35 🔌 CDP socket went silent (last message 64 s ago: reply 0.7 KB; largest
         145.0 KB DOM.setChildNodes) while the tab still answers — re-dialling it
08:29:36 ⏳ page context unavailable (ConnectionError: CDP not connected) — waiting 1s (attempt 1/3)
08:29:41 [F8KU] Attachment verified: Found via blob
08:29:44 ✅ CLICK success: clicked …(Send)…
08:29:46 🔍 Output check: no_new
08:29:48 ⏳ Generating Max spinner visible
08:29:50 🛡️ Captcha detected (recaptcha_enterprise, sitekey=set) via check-security
08:29:56 [Watcher] ⏳ Watcher: wait for finish generation Max (timeout 180s), pausing jobs
08:30:58 🔍 Output check: page_unresponsive — page not answering (TimeoutError: CDP command
         Runtime.evaluate timed out after 30.0s; last message 0 s ago: DOM.childNodeInserted 0.8 KB …)
08:30:58 ✅ Spinner gone, scanning for new image below prompt          ← the same second
08:31:01 🔌 CDP socket went silent (last message 0 s ago: Runtime.consoleAPICalled 1.8 KB …)
         while the tab still answers — re-dialling it
08:31:01 [Watcher] ✅ Watcher: generation finished after 65s — clearing overlay, resuming
08:31:32 [F8KU] 🔄 Generation stalled (spinner lost, no output) — resubmitting once
08:32:06 🔌 CDP socket went silent (last message 64 s ago: reply 0.7 KB …) — re-dialling it
08:32:06 Attach failed: Failed to get document root
08:32:06 [F8KU] 🔄 Resubmit re-attach: Failed to get document root (FAILED)
08:32:06 CDP not connected
08:32:06 [F8KU] 🔄 Resubmit prompt re-insert: Not connected (FAILED)
08:32:06 [F8KU] 🔄 Resubmit Send: Not connected (FAILED)
08:32:08 [F8KU] ❌ Failed icon-process-gears.png: Wait failed: Timeout after 120000ms —
         last check: page_unresponsive (…; last message 30 s ago: reply 0.7 KB …)
         (+6s captcha wait (cap 300s, 293s left))
08:32:08 ↩ Resetting to new chat after generation        ← the page (and its image) goes away
```

Read as a chain:

1. every `page_unresponsive` poll in the log carries a **30 s** evaluate timeout —
   the check itself asks 5 s (I-73), so the timeout belongs to the probes around it
   (`_security_gate`'s `is_security_dialog_visible`, the error scan, the final
   baseline) which still use the 30 s command default;
2. **"✅ Spinner gone" is printed the same second as "page not answering"** — a poll
   that answered *nothing* is read as "the spinner is gone";
3. that false reading starts the revival's dead window, so at `08:31:32` the app
   fires `Generation stalled (spinner lost, no output)` — a claim about the page it
   never observed (the page had not answered for 34 s);
4. the resubmit runs into a **re-dial** (`08:32:06`) and every one of its three steps
   reports FAILED (`Failed to get document root`, `CDP not connected` twice) with no
   recovery in between — the one bounded resubmit the design allows is spent on a
   one-second socket wobble;
5. the wait times out at 120 s; the runner raises `Wait failed: …`, and the finish
   path **resets the tab to a new chat** — if the generation did put an image on the
   page, it is now unreachable, which is exactly what the owner reports.

Also note: 5 re-dials in 4 minutes, two of them while the socket was hearing Chrome
(`last message 0 s ago`), each one dropping in-flight commands.

## 2. Root causes

| # | Root cause | Where |
|---|---|---|
| RC-1 | A poll that answered nothing is read as a state ("spinner gone"), so the wait's spinner memory is cleared and the revival's dead window starts from a non-event | `output_wait._process_spinner` |
| RC-2 | The revival treats a no-answer poll as "not live" (`_live_request`), so `dead_since` starts and matures → `Generation stalled …` for a page that never said anything | `services/captcha/recovery._note_activity` |
| RC-3 | The probes around the output check still ask the 30 s command default (`is_security_dialog_visible`, `is_page_ready`, `capture_baseline`, `get_generation_state`, the recovery's `document_readyState`), so one poll can cost ≥30 s on a busy page — I-73 applied to the check only | `cdp_arena/state.py`, `page_recovery._document_answers` |
| RC-4 | A re-dial is decided on *receive* silence alone: a socket that is merely idle, or that starts hearing Chrome while we ping it, is disconnected in place — which kills in-flight commands (the resubmit's three FAILED lines) | `cdp/liveness.revive_silent_socket` |
| RC-5 | The bounded resubmit has no page-context recovery: a momentary `CDP not connected` is reported as three failures instead of being waited out (`page_recovery.recover_page_context` already exists for exactly this) | `services/captcha/recovery._resubmit` |
| RC-6 | When the wait finally times out on a page that was not answering, nothing looks again: the image that is on the page is never taken, and the post-job reset navigates away from it | `cdp_arena/output` (`_map_wait_result`) |

## 3. Decisions

**D-1 (RC-1) — a poll that did not answer is not a state.** `page_recovery.unanswered_diag(diag)`
is the one predicate (`reason == "page_unresponsive"`). `_process_spinner` keeps the
spinner memory and prints nothing for such a poll: the wait already told the reason
(`🔍 Output check: page_unresponsive …`, I-71).

*Rejected:* treating `no_result` the same way — a probe that *ran* and answered
nothing is a real answer (RULE 4 keeps it), only a timed-out page is unknown.

**D-2 (RC-2) — a no-answer poll neither starts nor matures the death window.**
`_note_activity` returns after the dead-generation-toast check when the diag is
unanswered: the page said nothing, so there is no evidence of death. A live signal
(spinner / new pixels) still stands the markers down, and the toast path is
untouched.

**D-3 (RC-3) — every probe on the wait path asks the check budget (5 s).**
`page_check` (I-73) becomes the only way the state probes evaluate: `capture_baseline`,
`is_page_ready`, `is_security_dialog_visible`, `get_generation_state`,
`page_recovery._document_answers`. `evaluate(..., timeout=)` stays the door for page
*actions* (attach, submit, highlight, download) — unchanged.

*Rejected:* lowering the transport's default timeout — that would silently shorten
every job action too, and the 30 s default is what makes a slow action survive.

**D-4 (RC-4) — a socket that is hearing Chrome is never re-dialled.** After the
fresh-socket probe answers, `revive_silent_socket` checks `heard_recently` again:
a message that arrived while we pinged means our socket is alive (the page was
busy) → report alive, no re-dial. The wedge case (our socket hears nothing while
the tab answers a fresh one) still re-dials, and I-72's log line is unchanged.

**D-5 (RC-5) — the resubmit waits out a lost page context.** `_resubmit` runs
`page_recovery.recover_page_context` first (3 attempts, bounded, reported through
the policy's own reporter); if the page does not come back, the resubmit is
*s skipped with one line* instead of three FAILED lines — the wait then keeps the
honest timeout path. A ctrl without a client (tests, Firefox lane) skips the
recovery and behaves exactly as before.

**D-6 (RC-6) — the timeout gets one bounded look at the page it lost.** New
`page_recovery.await_page_answer(cdp, budget_s)` (ping → bounded re-dial → ping,
`AWAIT_ANSWER_S` = 20 s) and `cdp_arena/output._rescue_after_timeout`: when the wait
result is a timeout **and** the page was unresponsive, the wait waits for the page to
answer again and then polls **without gates and without the revival gate**; a ready
answer is returned as `completed` (with a `rescued` marker and one log line
`🛟 the page answered again — the image that was on it is taken`). The rescue never
submits, never settles a captcha and never runs when the page was answering all
along (a plain slow generation keeps its honest timeout).

*Rejected:* extending the generation timeout when the page is silent — the owner's
budget stays the owner's budget, and a page that never comes back must still fail
honestly (RULE 4). The rescue is bounded, one-shot, and only converts a *known*
failure (`page_unresponsive`) into a look.

**Not changing (recorded, not forgotten).** The post-job New Chat reset still runs
after a failed job — the rescue is what protects the image, and I-74's gate resets
before the next job anyway, so a page kept "for evidence" would buy nothing the
rescue does not already give. The security gate's own semantics (settle only while
the Watcher is ON) are untouched.

## 4. Structure (RULE 18 ideals, RULE 19 order)

| File | Change | Size check |
|---|---|---|
| `app/browser/page_recovery.py` (181) | `+unanswered_diag` (4 lines), `+await_page_answer` (14 lines), `_document_answers` → `page_check` | file < 300, func ≤ 20, CC ≤ 10 |
| `app/browser/output_wait.py` (236) | `_process_spinner` guard clause (nesting first: an early return, no new branch depth) | unchanged size band |
| `app/browser/cdp_arena/output.py` (234) | `+_rescue_after_timeout`, `+_rescue_look`, `+_log_line`; `_run_wait` calls the rescue before mapping | new funcs ≤ 20 lines, ≤ 4 params |
| `app/browser/cdp_arena/state.py` (100) | 4 probes → `page_check` | one-line edits |
| `app/browser/cdp/liveness.py` (171) | `revive_silent_socket`: one re-check + one return (no new nesting) | CC ≤ 10 kept |
| `app/services/captcha/recovery.py` (223) | `_note_activity` guard; `+_context_back`; `_resubmit` calls it | new func ≤ 20 lines, file < 300 |

No new module, no new class, no new signal slot, no selector change
(`DOM_SELECTORS.md` untouched). Direction of imports unchanged: `browser/` never
imports `services/`; `services/captcha/recovery` imports `app.browser.page_recovery`
(already the case for the runner).

## 5. Tests (RULE 8 — each fails on the pre-change code)

| Behaviour | Test |
|---|---|
| D-1 a no-answer poll never logs "spinner gone" and keeps the spinner memory | `tests/test_page_unresponsive.py::test_a_no_answer_poll_is_not_a_spinner_gone` (+ golden log list) |
| D-2 a no-answer poll does not mature the revival's window (no resubmit after the grace) | `tests/test_captcha_recovery.py::test_a_no_answer_poll_never_matures_the_death_window` |
| D-3 the state probes ask 5 s | `tests/test_page_unresponsive.py::test_the_state_probes_ask_the_check_budget` |
| D-4 a socket that speaks while we ping is not re-dialled | `tests/test_cdp_liveness.py::test_a_socket_that_speaks_while_we_ping_is_not_redialled` |
| D-5 the resubmit recovers a lost context (and skips honestly when it cannot) | `tests/test_captcha_recovery.py::test_resubmit_recovers_the_page_context_first`, `…::test_resubmit_skips_when_the_page_never_comes_back` |
| D-6 the rescue takes the image after the page answers; a page that never answers still fails honestly; an ordinary timeout is not rescued | `tests/test_page_unresponsive.py::test_a_timeout_on_a_frozen_page_rescues_the_image_when_it_comes_back`, `…::test_a_page_that_never_answers_keeps_the_honest_timeout`, `…::test_the_rescue_does_not_run_for_a_plain_timeout` |

No new JS probe (no jsdom test). Existing goldens must stay byte-identical for the
normal paths (`tests/characterization/test_batch_goldens.py`).

## 6. RULE 16 / RULE 18 budget

* no new function > 30 LOC, none > 4 params, no class change;
* CC ≤ 10 / cognitive ≤ 15 / nesting ≤ 4 on every touched function (`radon cc -s`
  before and after; the six touched files have no function at C or worse today and
  must not gain one);
* every new library function is covered by the tests above; the touched modules are
  already ≥ 80 % covered;
* proof commands: `tools/verify_quality.py --changed --allow-legacy`, the fast lane
  and `pytest tests`, coverage JSON vs the stored baseline.

## 7. As built (2026-09-28)

Test names as landed: `test_every_state_probe_on_the_wait_path_asks_the_check_budget`,
`test_the_page_context_recovery_probe_asks_the_check_budget`,
`test_a_no_answer_poll_is_not_a_spinner_gone`,
`test_a_timeout_on_a_frozen_page_rescues_the_image_when_it_comes_back`,
`test_a_page_that_never_answers_keeps_the_honest_timeout`,
`test_the_rescue_does_not_run_for_a_plain_timeout`,
`test_a_no_answer_poll_never_matures_the_death_window`,
`test_a_real_spinner_loss_after_a_frozen_stretch_still_fires`,
`test_resubmit_recovers_the_page_context_first`,
`test_resubmit_skips_when_the_page_never_comes_back`,
`test_a_ctrl_without_a_client_resubmits_exactly_as_before`,
`test_a_socket_that_speaks_while_we_ping_is_not_redialled`,
`test_the_rescue_keeps_looking_until_the_image_is_readable`,
`test_a_rescue_that_never_reads_an_image_gives_up_honestly`,
`test_a_rescue_read_that_raises_is_no_result`,
`test_a_broken_wait_log_sink_never_breaks_the_rescue`,
`test_a_raising_re_dial_inside_the_wait_window_is_swallowed`,
`test_get_generation_state_reports_a_raising_probe`,
`test_document_answers_false_when_the_probe_raises`,
`test_a_raising_context_recovery_still_resubmits`.

Shapes the ratchet forced (RULE 16 R0.3, file maxima must not grow):

* `cdp_arena/output`: D-6 is `_rescue_after_timeout` (guards) → `_rescue_look`
  (one recursive poll per call, no loop nesting) → `_rescue_read` (the guarded read);
  the mapping moved to `_map_wait_rescue`, and the wait's log sink is
  `functools.partial(_log_line, spec)` — `_run_wait` lost its nested `_log`.
* `captcha/recovery`: the old `_resubmit` keeps its 15-line/CC-7 shape; the gate is
  `_resubmit_or_skip` → `_context_back` (+ `_sink` for the policy reporter), and
  `_maybe_resume` calls `_resubmit_or_skip`.
* Coverage of the rescue paths: `ComesBackLate` (answers but is not ready yet →
  retry; never ready → give up), `AnswersThenBreaks` (a raising check is a
  "no result" look) and a raising log sink (RULE 2) — four more tests in
  `tests/test_page_unresponsive.py`.
* `_map_wait_result`'s final baseline goes through `_baseline_or_empty`: a raising
  capture on an answered page must not replace the honest timeout text (RULE 4).
* Two test doubles gained the transport's `timeout=` keyword
  (`tests/test_page_recovery.py`, `tests/test_visual_click_recovery.py`) because the
  state probes and `_document_answers` now go through `page_check`.
