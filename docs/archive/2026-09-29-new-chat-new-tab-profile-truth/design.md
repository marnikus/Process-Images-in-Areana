# Fix v5 — "Start new chat as new tab": the tab's own browser profile decides (problem definition + redesign)

Supersedes the v4 attempt (`docs/archive/2026-09-29-new-chat-new-tab-full-profile/design.md`),
which kept adding *heuristics* (owner probes, cookie copies, per-endpoint counts) around a
pipeline that never actually **proved** which browser profile it was acting on.
Owner report 2026-09-29, second round on the same defect.

## 1. The report (owner's words)

> Run 2 profiles with 1 tab as worker.
> A1 — On profile 1 after job finish it opens new link and closes old — correct!
> A2 — On profile 2 after job finish it opens new link on profile 1 and closes old link on
> profile 1 — incorrect! Instead it [should] click to new chat then.
> but both should behave same as A1 if start new chat feature active!

So: with **Start new chat as new tab** ON, a finished image's worker must continue in a fresh
tab *of its own profile*, the old tab of that same profile closes, and another profile's tabs are
never touched. When that cannot be done, the reset must stay in the job's own tab (click New
Chat in place) — never half-move into a foreign profile.

## 2. Problem definition

**P1 — "which profile" is never established; it is guessed.**
The handover picks the browser endpoint from a *client object*
(`new_tab._resolve_endpoint`: pooled client → `ctx.client` → `pool._host/_port` → `127.0.0.1:9222`),
and picks the client that receives every browser command with
`_pick_client_for_context` = `move.clients[0]` = `ctx.client` (in the sequential lane that is
`bridge.cdp`, the *global* client, `batch_orchestrator._finish_and_follow`). A CDP command carries
no endpoint — it travels over whatever socket the client holds. The `host, port` arguments are only
used for the *follow-up* HTTP listing. Result: `Target.createTarget` (and the cookie/localStorage
`Runtime.evaluate`s) can execute in a **different browser** than the job's tab (A2 opens in
profile 1).

**P2 — "profile unknown" is read as "profile correct".**
`_verify_context_same` returns True when either context is empty ("empty means default or unknown"),
and `_check_owner_preserved` returns True after 3 tries when the owner probe answers nothing.
Both are "we could not check" — and both were treated as "we checked, it is fine". The one proof
that the new tab is in the worker's profile was therefore never required.

**P3 — the fallback opener is never verified at all.**
When `_try_open_same_context` fails (which it must for a regular Chrome profile context — Chrome
refuses `Target.createTarget{browserContextId}` for profiles it did not create, see §4),
`_open_and_prove` calls `open_tab_sync` = `PUT /json/new`. That endpoint always creates the tab in
the browser's **default profile** and the result is *not* context-checked. That is exactly the
reported A2: new link on profile 1, and the app then moves the worker onto it.

**P4 — the close is verified against the same possibly-wrong endpoint, and a 404 counts as proof.**
`_close_old` → `close_tab_sync(*move.endpoint, old_id)`, where a 404 is "already gone" and `_gone()`
asks the same endpoint. With a wrong endpoint both answer "gone" while the real tab lives on; the
log still prints `Old tab closed and verified gone`.

**P5 — the evidence lies.**
`_count_profile_tabs` counts per `host:port` and `_count_profile_tabs_by_owner` per owner label, so
the operator's line `tabs matching 'arena.ai/image' in profile: 2` printed 2 for a profile that had
1 — the reading that hid the imbalance `2 + 0` in the first place.

Consequence chain of the reported run: P1/P3 → the fresh tab lands in profile 1 → P2 lets it pass →
P4 reports the old tab closed → `_move_worker` re-keys the pool entry, adopts the alias and
re-points the URL row → the worker (its cooldown, job count, number and account label) is now a tab
in profile 1, the old profile's tab is closed. Profile imbalance and a mislabelled worker.

## 3. The rule this fix enforces

> **A fresh tab may replace the job's tab only when the job tab's own browser proves, in its own
> target list, that the fresh tab lives in the same browser context as the job tab. Unknown is not
> equal; another context is a refusal. When no opener can deliver such a tab, the handover declines
> (RULE 9) and the ordinary in-place New Chat runs in the job's own tab.**

Five sub-rules, one per defect:

| # | Rule | Where |
|---|---|---|
| R1 | The endpoint is the host:port of the **job tab's own socket** (`ws_url`), never a client's or the pool's default. A tab whose socket cannot be parsed is refused. | `browser_targets.endpoint_of_ws` |
| R2 | The profile truth is the **browser-level** `Target.getTargets` of that endpoint (one connection per handover, `/json/version` → browser websocket). The job tab must be in it; its `browserContextId` (absent = default context) is the expected profile. | `browser_targets.dial/targets` |
| R3 | Openers, in order: (a) `Target.createTarget` with that context (no context when the job tab is in the default one); (b) the **job tab's own page** `window.open(url, '_blank')` with `userGesture` — a page can only open into its own profile, which is the only way to reach a regular Chrome profile context; then re-read the target list and require the new tab's context to equal the job tab's. A wrong-context tab is closed again immediately; if neither opener is provable the handover is refused. | `new_tab_open` |
| R4 | The old tab is closed with `Target.closeTarget` **on that browser** and its absence is proven by the next target list; a close that leaves it listed is an error line (one retry). No HTTP close, no 404-as-proof. | `new_tab._close_old` |
| R5 | The log lines print what the browser proved: endpoint, context, owner, and the **same-profile** counts (`matching targets in this profile` / all contexts / pooled labels). | `new_tab._profile_line` |

## 4. Chrome facts this design rests on (checked, not assumed)

* `Target.*` commands are **browser-level** — they belong on the browser websocket
  (`/json/version` → `webSocketDebuggerUrl`), not on a page socket; a page session answers
  "only available on the browser target" for context commands.
  (chromedevtools protocol docs; chrome-remote-interface/puppeteer practice.)
* `Target.getTargets` **lists the tabs of every profile** of a Chrome instance and reports each
  one's `browserContextId` (the default context omits it).
* `Target.createTarget{browserContextId}` works for contexts Chrome created for DevTools (OTR),
  but **not for a regular Chrome profile**: the profile-provided id answers
  `Failed to find browser context with id …`, and without a context the tab opens in the default
  profile — the exact A2 symptom (playwright#8750; browser-harness profiles note, verified
  2026-09-20). Hence R3(b): the tab's own page is the profile-locked opener.
* `PUT /json/new` always creates in the default profile → deleted from the handover path.

## 5. Rejected shapes (and why)

* **Keep `/json/new`, verify afterwards** — the tab is already in the wrong profile; the best case
  is a rollback, and the close/move code would still have run in the wrong browser.
* **Owner-probe as the proof (v3/v4)** — the probe answers nothing on a fresh page (v4 made that a
  pass), it costs 1.5 s of retries, and it is a *label*, not the profile: cookies can be shared by
  two tabs of one profile with two logins (the observed "2 accounts on 9222"). Kept only as a
  secondary mismatch guard.
* **Cookie/localStorage copying (v4)** — copying session state between profiles is how one lands in
  the wrong account; the profile decides, nothing is copied.
* **Counting per owner (`_count_profile_tabs_by_owner`) as a profile count** — owners repeat inside
  a profile; the browser's context list is the only honest count.

## 6. Structure (RULE 16 / RULE 18 budgets)

| File | Responsibility | Size |
|---|---|---|
| `app/browser/cdp/browser_targets.py` **new** | the browser-level truth of one endpoint: `dial`, `targets`, `create`, `close`, `aclose` + pure `endpoint_of_ws`, `target_of`, `context_of`, `matching_targets`. No Qt, no services. | ~150 |
| `app/browser/page_popup.py` **new** | the page's own new tab: `build_open_tab_js(url)` + `open_tab_via_page(client, …)` (Runtime.evaluate, `userGesture`). JS literal only. | ~60 |
| `app/services/new_tab_open.py` **new** | how the fresh tab is opened in the job tab's own profile and proven there: opener strategies + one shared context verification. | ~130 |
| `app/services/new_tab_setting.py` **new** | the Settings option itself: keys, URL healing, session save/load and `wanted_url` (the UI Settings save and `cooldown_service` talk to this file, not to the pipeline). | ~50 |
| `app/services/new_tab.py` **rewritten** | the I-79 pipeline only: plan → profile read → open → prove ready/new-chat/owner → move worker → close + verify → rollback, and its logs. | 298 |
| `app/browser/cdp/tabs.py` | `open_tab_sync`, `close_tab_sync`, `open_tab_in_same_context`, `_context_of` deleted (dead once the handover owns the browser connection; RULE 16.4). | 199 → ~140 |

Every new function ≤20 LOC / ≤3 params / CC ≤10 / nesting ≤4; each file one responsibility. The
setting API the callers already used (`read_setting`/`save_setting`/`wanted_url`) lives in
`new_tab_setting.py`; `ui/panels/page_pool.py` and `cooldown_service.py` import it there.

## 7. Tests first (RULE 8) — the RED list

The fake world models what the code under test must believe: **a browser per endpoint** with
per-target contexts, and two ways a tab can appear in it (`Target.createTarget` honouring or
ignoring `browserContextId`; a page's `window.open`), plus a *refusing* browser for the
profile-context case. Tests are written before the implementation; the first six fail on the
current code.

1. RED `the new tab opens in the job tab's own profile (not the default one)` — two contexts at one
   endpoint, the job tab in the second: new tab's context == the job tab's; the other profile's tab
   untouched; worker moved; old tab closed.
2. RED `a browser that refuses a profile context is answered by the page's own new tab` — opener (b)
   runs, the new tab's opener is the job tab and its context matches.
3. RED `a blocked popup refuses the handover` — nothing opened, nothing closed, worker unmoved, and
   the reason names the profile.
4. RED `a wrong-context tab is closed again and the handover refused` — a browser that ignores
   `browserContextId`: the fresh tab is removed, the job tab stays, the worker stays.
5. RED `an unprovable profile is no handover` — `Target.getTargets` answers nothing: refuse before
   anything is opened or closed.
6. RED `the endpoint is the job tab's own socket` — the global/pooled clients sit on another
   endpoint: the browser dialled is the socket's endpoint and the other browser sees no command.
7. RED `the job tab must be in its own browser list` — an id that is not listed: refuse, no open.
8. GREEN-锁 `profile counts in the log come from the browser truth` (1 of 2, not 2 of 2).
9. Kept from I-79: ready-proof rollback, new-chat rollback, owner mismatch rollback, same-URL close,
   reconciler hold, close-failure line, in-place fallback seam, setting tests.
10. `page_popup` unit tests (blocked/allowed/error/escaping) + the JS payload syntax lane.

## 8. Out of scope

* Firefox lanes (they never open pages; `lane_reset` keeps precedence).
* Opening a tab in another profile *by request* (a profile picker) — the handover must follow the
  job tab, never choose for the user.
* Any change to the pool/alias/URL-row identity model (I-79's move is kept verbatim).

## 9. Outcome (2026-09-29)

Built exactly as §6: `browser_targets.py` (dial → `Target.getTargets`/`createTarget`/`closeTarget`,
pure `endpoint_of_ws`/`context_of`/`target_of`/`matching_targets`), `page_popup.py` (the page's own
`window.open` with `userGesture`), `new_tab_open.py` (opener strategies, a tab counts only after the
browser lists it in the job tab's own context; a wrong-context tab is closed again and reported as
`wrong-profile`), `new_tab.py` rewritten to the R1–R5 pipeline, `new_tab_setting.py` split out, and
`open_tab_sync`/`close_tab_sync`/`open_tab_in_same_context`/`_context_of` deleted from `tabs.py`
(grep-verified: no caller outside the handover).

Evidence (2026-09-29, `.venv`):

* RED first — on base `2d35536` the three new test modules fail to import; the fake world in
  `tests/test_new_tab_handover.py` (a browser per endpoint with per-tab contexts, `Target.createTarget`
  honouring or ignoring the context, the page opener, a refusing browser, a blocked popup, a silent
  target list, a close that is ignored) then pins R1–R5.
* GREEN — `tests/test_browser_targets.py` (24), `tests/test_page_popup.py` (8),
  `tests/test_new_tab_open.py` (11), `tests/test_new_tab_handover.py` (36), `tests/test_new_tab_setting.py`
  (13), plus the JS payload lane with the popup builder registered.
* Full suite: 3008 passed, 6 skipped, 3 failures that are also red on the base commit — re-checked in a
  `2d35536` worktree (`test_quality_gate.test_40loc_js_function_fails`,
  `test_single_job_runner.test_handler_map_covers_all_types`,
  `test_ui_wiring.test_closing_the_window_drops_the_cdp_socket_inside_a_guard`).
* Coverage: total 89.95 % line / 86.05 % branch; all five new/changed modules (`browser_targets`,
  `page_popup`, `new_tab`, `new_tab_open`, `new_tab_setting`) at 100 % line and branch — the guards that
  swallow a failing log sink, a failing save and a target list that dies mid-wait are pinned by tests.
* `python tools/verify_quality.py --changed-files <the eight changed app files>` → 0 fails, 0 warns.

Honest limit: this sandbox has no Chrome binary, so the A1/A2 run itself could not be reproduced
here; the profile decisions are exercised against the fake browser world, and the CDP calls used are
the documented browser-level ones in §4. On a machine with the two profiles, the log line added by
`_log_profile` (`profile host:port ctx=… owner=… — tabs matching '…': this profile: N | all
contexts: M`) names exactly which profile the browser proved before anything is opened, and a
refusal still ends in the ordinary in-place New Chat.
