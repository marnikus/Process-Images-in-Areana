# Merge — branch 1's R7b (the page opener's own-socket fallback) onto the v6 opener rules

Owner directive 2026-09-30: two independent fixes for the same A2 report landed on two branches —
**base = `arena/01a0f25e`** (this branch, I-79 v6, commit `32c7897`), **branch 1 = `arena/01a0f1cf`**
(R6/R7/R7b, commits `0e6e089`, `1ba3296`, `aa6bcf6`). A branch-comparison report (owner-supplied)
recommended: *"merge B as the base and cherry-pick A's R7b (`_dial_page` when `_popup_client` is
None) — that closes B's one real gap without importing A's undisclosed-context machinery."*
This document records what was merged, what was rejected and why, per RULE 17.

## 1. What the two branches each fixed (from the report, verified against both trees)

Both removed the shared core defect: the page opener no longer adopts `sorted(fresh)[0]`; a fresh
tab must be attributed by the browser (`TargetInfo.openerId`) to the job tab. v6 additionally
skips `Target.createTarget` for a context `Target.getBrowserContexts` says is not creatable (the
"flash tab in profile 1" the owner watched); branch 1 additionally hardens the *liveness* of the
profile-locked opener (R7b) and guards an undisclosed context (R6).

## 2. Adopted — R7b, faithful to branch 1's shape

> **The popup needs a socket that really sits on the job tab. When no registered client does — or
> its popup names another opener (the socket lied) — the handover dials the job tab's own
> `ws_url`, the one socket R1 already trusts, and retries the popup once from there.**

* `OpenSpec.page_ws` (the job tab's own socket; the pipeline passes `move.old_ws`).
* `_attempt_popup(browser, client, spec)` — one attempt (v6's judge unchanged: opener-named tab
  or refusal; strangers counted).
* `Opened.wrong_opener` — strangers > 0 at the deadline (explicit flag instead of branch 1's
  substring check on the reason text).
* `_dial_page(ws_url)` — fresh `CDPClient` on the job tab's page socket; `None` on an unreadable,
  refusing or exploding connect, never a raise.
* `_worth_dialling(opened, page_client, spec)` — retry exactly when `page_client is None` or
  `opened.wrong_opener`; a blocked popup from a seated client stays final (bounded: the retry
  answers a *lying* socket, not a *refusing* page).
* `_page_opener` orchestrates: seated client → maybe one retry from the dialled socket → always
  disconnect the dialled socket; a failing retry merges both reasons into the refusal (RULE 2).

Safety is unchanged: every adopted tab still needs the same v6 opener + context proof — R7b only
improves the chance the feature *fires* instead of degrading to the in-place New Chat click (the
report's "3-profile coin flip": one profile clicks, the others open a tab).

## 3. Rejected — and why (not merged, recorded so the decision survives)

* **R6 — skip `Target.createTarget` when the job context is `""`.** An absent
  `browserContextId` in `TargetInfo` is Chrome's marker for the **default** context (v5 §4, CDP
  Target domain), not an undisclosed mystery profile. For a default-context job tab a
  context-less create lands in that *same* default profile, so `"" == ""` is a true statement
  about one profile, not a tautology; R6 would remove the cheap create path from every
  default-profile worker to guard a state Chrome does not produce. The honest version of the
  same guard is already in v6: `Target.getBrowserContexts` — create is skipped exactly when the
  browser *states* the context is not creatable.
* **R7's bare-candidate fallback** (adopt a fresh tab with *no* `openerId` and judge by context).
  It reintroduces the attribution guess v6 deleted: in the owner's concurrent world a sibling
  worker's CDP-created tab or a user-opened tab is "bare"; a matching context would adopt it, a
  differing one would roll it back (closed) — the exact cross-profile close from the report.
  Where Chrome reports no opener at all, v6's answer stands: refuse honestly, reset in place.
  Unknown is not equal (the v6 rule: identity comes from the browser, not from luck).

## 4. Structure (RULE 16 / RULE 18)

| File | Change | Size after |
|---|---|---|
| `app/services/new_tab_open.py` | `+ page_ws`, `Opened.wrong_opener`, `_strangers`, `_attempt_popup`/`_page_opener` split, `_dial_page`, `_worth_dialling`, `_quiet_disconnect`; `cdp.client` import (branch 1's placement — kept: the dial belongs beside the opener it serves, and services→browser is the legal direction). | 261 |
| `app/services/new_tab.py` | `+ page_ws=move.old_ws` in the `OpenSpec`; docstring + ideal-size note. | 341 |
| `tests/test_new_tab_handover.py` | `popup_as` fixture (the lying client), `_no_dial`/`_fake_dial_page` seams, 2 R7b tests + unreachable-socket refusal rewrite + bounded-retry guard + both-reasons refusal test. | — |
| `tests/test_new_tab_open.py` | wrong-opener flag tests, `_dial_page` unit tests (silent/refusing/exploding socket). | — |

Longest new function 20 LOC (`_page_opener`, `_wait_new_tab`), params ≤4, radon CC max B(6);
`new_tab_open` 261 lines — inside the 150–300 band; `new_tab` carries an explicit ideal-size note.

## 5. Tests (RED first, branch 1's 3-commit discipline)

RED commit `acf9bd3` — 8 failing: opener level (`wrong_opener` flag on a stranger-named popup;
blocked popup is *not* evidence; `_dial_page` silent/refusing/exploding), handover level
(no-client → dial succeeds; lying client → retried from the job tab's socket; unreachable socket
refuses; bounded-retry guard). GREEN commit `7def037` adds the both-reasons refusal test that
coverage showed unpinned (line: the retried attempt failing too). Area suites **122 passed**;
`new_tab_open`/`new_tab`/`browser_targets` 100 % line + branch; `verify_quality --changed-files`
0 fails.

## 6. Outcome

The two branches' scenario matrix after the merge — stranger adopted by sort order: **no**
(v6 R1); foreign-opener tab never closed: **yes** (v6); flash tab in profile 1 for a
non-creatable context: **no** (v6 `getBrowserContexts` gate); no client on the job tab → own
socket dial: **yes** (R7b, this merge); lying client retried from the job tab's socket: **yes**
(R7b); bounded retry (blocked popup stays final): **yes** (guard test); undisclosed-context and
no-openerId worlds: honest refusal → in-place New Chat (deliberate, see §3).

Honest limits (unchanged): no Chrome binary in this sandbox — all evidence is against the fake
browser world with the documented browser-level CDP calls; the lying-client scenario
(`popup_as`) is a model of a drifted shared socket, not a captured Chrome trace.
