# Fix v6 — the handover must adopt only the tab its own page opened, and must not fire a create it can prove wrong (problem definition + design)

Fourth round on the same owner report. v3/v4 added heuristics around a guessing pipeline; v5
(`docs/archive/2026-09-29-new-chat-new-tab-profile-truth/design.md`) rebuilt the pipeline on profile
truth (endpoint, context, proof, close) — and the owner reports the A2 symptom **again** on the v5
code. This pass defines what can still go wrong in v5 by reading the code, and removes it.

## 1. The report (owner's words, 2026-09-30)

> bug appear again — incorrect fresh open new link on wrong profile.
> Run 2 profiles with 1 tab as worker.
> A1 — On profile 1 after job finish it opens new link and closes old — correct!
> A2 — On profile 2 after job finish it opens new link on profile 1 and closes old link on
> profile 1 — incorrect! Instead it clicks to new chat then.
> (same problem if 3 profiles open — then one uses click on new chat but others use new open tab)
> but both should behave same as A1 if start new chat feature active!

## 2. Problem definition — what v5 still guesses or fires blindly

The v5 pipeline is id-proven end to end **except at two points**:

**P1 — "which fresh tab is mine" is a sort-order guess (`new_tab_open._wait_new_tab`).**
The page opener (`window.open`) snapshots the browser's target list, fires, then polls the list and
adopts `sorted(fresh)[0]` — the first new page target of ANY origin. The browser reports which tab
a page opened (`TargetInfo.openerId`) — the repo's own test fake has modelled that field since v5 —
but the code never reads it. Any other fresh page target in the diff is therefore adoptable:

* the **other worker's fresh tab** (2–3 workers finish within seconds of each other — the exact
  owner setup; the reconciler flag only serialises a handover for 10 s, a slower one proceeds);
* a **speculation/prerender page** (Chrome lists prerenders as `type:"page"` targets);
* an **extension- or DevTools-created surface**.

Adoption happens **before** the context proof, so two failure shapes follow. When the adopted
stranger shares the job tab's context (two workers on the default context of one Chrome), the proof
**passes** and the worker is moved into a tab of the other profile — the other finish then closes or
loses its own tab. When the context differs, the proof refuses and the rollback **closes the
stranger** — visibly killing the tab the other profile's finish had just opened, which then finds
nothing and degrades to the in-place New Chat click. Both owner-observed shapes — "opened/closed on
profile 1 during profile 2's finish" and "one profile clicks new chat, the others open a tab" — are
exactly these two shapes.

**P2 — the first opener is fired even when the browser has already said it cannot honour the
context (`new_tab_open._create_opener`).**
`Target.createTarget{browserContextId}` only works for contexts Chrome itself can create into; for
a regular Chrome person-profile it either refuses (playwright#8750) or — the owner-evidenced shape —
**silently lands the tab in the default profile**. v5 handles both honestly (proof → refuse →
rollback), but the attempt itself is the visible bug: a link flashes open **in profile 1's window**
and is closed again during profile 2's finish, and the finish burns the round-trip before falling
back to the page opener. CDP answers "which contexts can I create into" directly:
`Target.getBrowserContexts` (browser-level, same socket as `Target.getTargets`). v5 never asks.

Consequence chain of the reported run: profile 2's finish fires a create it could have known was
wrong (P2) → a default-profile tab flashes open and is rolled back (the owner's "new link on
profile 1 … closed") → the finish falls back to the page opener / in-place click, and when another
worker's fresh tab is in the diff it is adopted or killed (P1) → cross-profile moves, cross-profile
closes, "one clicks, the others open".

## 3. The rule this fix enforces

> **A fresh tab may be adopted only when the browser's own TargetInfo names the job tab as its
> opener; an unnamed or foreign-opener fresh tab is never adopted and never closed by us. And the
> create opener is not fired for a context the browser has stated it cannot create into — for a
> regular profile the job tab's own page is the opener, fired first.**

| # | Sub-rule | Where |
|---|---|---|
| R1 | The page opener's diff is filtered by `openerId == the job tab's id`. One poll: adopt only a tab the browser says THIS page opened; no opener-named tab by the deadline is a refusal that says so. Unknown opener id (a caller that cannot name its tab — today only bare test clients) keeps the context-only rule. | `new_tab_open._wait_new_tab` / `_ours` |
| R2 | `Target.getBrowserContexts` is read once per handover. A non-empty job context that is **absent** from the creatable set skips `Target.createTarget` entirely — no flash tab in the default profile, nothing to roll back. An unanswerable list or the default context (`""`) keeps today's create-first order. | `new_tab_open._create_opener` / `_not_creatable` |
| R3 | The context proof, readiness proof, owner guard, close-verification and rollback stay exactly as v5 built them (R3–R5 there). The new filters only decide **which tab enters** the proofs. | `new_tab_open._proven`, `new_tab` |

Chrome facts this rests on (checked, not assumed):

* `Target.getTargets` lists tabs of every profile with their `browserContextId`, and `TargetInfo`
  carries `openerId` — the opener of a `window.open` tab (chromedevtools Target domain; the v5
  fake already models it).
* `Target.createTarget` cannot target a regular profile's context; without a context the tab opens
  in the **default** profile (playwright#8750; browser-harness "Multiple Chrome profiles" note,
  verified live 2026-09-20 — the same conclusion v5 §4 recorded).
* `Target.getBrowserContexts` (browser-level) answers the array of context ids `createTarget`
  accepts; the default context needs no id at all (Target domain docs).

## 4. Rejected shapes (and why)

* **Adopt `sorted(fresh)[0]` but add more proofs around it (v4's shape)** — the guess survives; a
  stranger that shares the context still passes every proof. The identity must come from the
  browser, not from luck.
* **Serialize handovers with a new global lock** — the reconciler flag already serialises them for
  10 s; a lock would turn a slow handover into a 10 s stall for the second worker and still not
  identify tabs. Opener identity removes the interference itself.
* **Skip `Target.createTarget` for every non-empty context** — a DevTools-created context (OTR) is
  creatable and create is the cheaper opener (no page involvement); the creatable set decides, not
  the context's emptiness.
* **Treat `subtype: "prerender"` specially** — with R1 a prerender that did not name our tab as its
  opener is already invisible; adding subtype branches would be a second rule for a solved case.

## 5. Structure (RULE 16 / RULE 18 budgets)

| File | Change | Size |
|---|---|---|
| `app/browser/cdp/browser_targets.py` | `BrowserTargets.get_browser_contexts()` — the creatable set, `(set(), why)` on failure (same `_reply` shape as `targets`). | ~170 |
| `app/services/new_tab_open.py` | `OpenSpec.opener_id`; `_ours` filter; `_wait_new_tab(browser, before, timeout, opener_id)`; `_not_creatable` gate in `_create_opener`; refusal text names the page-route reason. | ~155 |
| `app/services/new_tab.py` | `_run` passes `opener_id=move.old_id` (the job tab names itself as the opener). | +1 line |

Every edited function stays ≤20 LOC / ≤4 params / CC ≤10; no new file, no new module boundary.

## 6. Tests first (RULE 8) — the RED list

`tests/test_new_tab_open.py` (opener level):

1. RED `the popup tab is identified by its opener, never by sort order` — two fresh tabs appear,
   a stranger that sorts first and the opener-named tab: the opener-named one is adopted.
2. RED `a stranger fresh tab alone is never adopted and never closed` — only a foreign-opener tab
   appears: refusal, the stranger stays open, nothing of ours is closed.
3. RED `create is skipped when the browser says the context is not creatable` — no create call, no
   rollback close, the page opener's tab wins.
4. GREEN-guard `a creatable context still uses the create target` and `the default context still
   creates without an id`.
5. `an unanswerable context list keeps the create attempt` (legacy order, honest refusal text).
6. `the refusal names the page route when create was skipped` (RULE 2 log honesty).

`tests/test_new_tab_handover.py` (pipeline level):

7. RED `a regular-profile handover never flashes a tab into the default profile` — the owner's
   Chrome shape (create accepted-but-default-landing): no create call at all, worker lands in the
   opener-named popup tab of its own profile, old tab closed.
8. RED `a stray tab in the popup diff is left alone` — a stranger that sorts first appears with the
   popup: the worker still moves onto ITS opener-named tab, the stranger stays open.

`tests/test_browser_targets.py`: `get_browser_contexts` answer + error shapes.

## 7. Out of scope

* Firefox lanes (never open pages), the pool/alias/URL-row identity model (I-79's move), the
  10 s reconciler-flag cap (a waiter degrades honestly to the in-place click; a lock would not
  identify tabs), prerender `subtype` handling (dead under R1), and any change to the setting UI.

## 8. Outcome (2026-09-30)

Built exactly as §5–§6, RED-first: the nine new tests failed on the pre-fix tree for the
predicted reasons (sort-order adoption, the always-fired create, the missing
`get_browser_contexts`), then went green on the v6 code.

Evidence (this sandbox, `.venv`):

* `tests/test_new_tab_open.py` 20, `tests/test_new_tab_handover.py` 38,
  `tests/test_browser_targets.py` 28, plus the kept `test_page_popup.py` (8) and
  `test_new_tab_setting.py` (13) — area total 114, all green.
* Full suite: **3 221 passed, 13 skipped, 3 failed** — the same three failures the v5 outcome
  recorded as red on the base commit (`test_quality_gate.test_40loc_js_function_fails`,
  `test_single_job_runner.test_handler_map_covers_all_types`,
  `test_ui_wiring.test_closing_the_window_drops_the_cdp_socket_inside_a_guard`); re-verified red
  on a clean `5e175f13` worktree (JS lane: `acorn` not installed in the sandbox).
* Coverage (area suites): `new_tab_open` 100 % line / 100 % branch, `new_tab` 100 %, `new_tab_setting`
  100 %, `browser_targets` 100 % (the dead-socket branch of `get_browser_contexts` pinned too).
* `tools/verify_quality.py --changed-files <the six changed files> --allow-legacy` → 0 fails
  (one warn: `coverage.json [missing]`, sandbox).
* RULE 16/18 re-check: longest new/edited function `_wait_new_tab` 19 LOC / 4 params / CC 6;
  `_run` 20 LOC (+1 line for the opener argument, the audit's own P7 extraction); radon CC max in
  the touched modules is 8 (`matching_targets`, pre-existing); files 186 / 190 / 334 lines — inside
  or at the ideals; no new function over 20 LOC, no new file.
* End-to-end owner-world repro (one Chrome, two person-profile contexts, one worker each,
  create-accepts-but-lands-default Chrome): pre-fix A2 produced `closed == [P1-TAB, NEW2, P2-TAB]`
  — the fresh tab for profile 2 flashed into profile 1's default context and was rolled back
  (the reported "opened on profile 1, closed on profile 1"). Post-fix: `creates == []`, each
  worker moved to the tab **its own page opened** (`openerId`-proven), `closed == [P1-TAB, P2-TAB]`,
  rows and pool re-keyed per worker. Honest limit, unchanged from v5: this sandbox has no Chrome
  binary, so the run itself is exercised against the fake browser world; the CDP calls used are
  the documented browser-level ones (§3).
