# Round 3 — "Start new chat as new tab" opens on the wrong profile: the proof can certify its own counterexample

Owner report 2026-09-30 (third round on this defect; supersedes nothing — it extends the
v5 rule set of `docs/archive/2026-09-29-new-chat-new-tab-profile-truth/design.md`, whose
pipeline stays in place).

## 1. The report (owner's words)

> Run 2 profiles with 1 tab as worker.
> A1 — On profile 1 after job finish it open new link and close old — correct!
> A2 — On profile 2 after job finish it open new link on profile 1 and close old link on
> profile 1 — incorrect! Instead it click to new chat than.
> (same problem if 3 profile open — than one use click on new chat but others use new open tab)
> but both should behave same as A1 if start new chat feature active!

Desired behaviour: with the option ON, **every** profile's finished worker continues in a
fresh tab *of its own profile* (A1's behaviour), the old tab of that same profile closes,
and no other profile's tabs are touched. The in-place New Chat click is a last resort, not
a coin flip between profiles.

## 2. What runs today (v5, unchanged pipeline)

`new_tab.handover` → endpoint from the job tab's own socket (`ws_url`, R1) → browser-level
target list (R2) → read the job tab's `browserContextId` as its profile → opener (a)
`Target.createTarget{browserContextId}` → opener (b) the job tab's own page `window.open`
→ prove the fresh tab is in the job tab's context (R3) → move the worker → close + verify
the old tab (R4) → log what the browser proved (R5). Refusal falls back to the in-place
New Chat (RULE 9).

## 3. Problem definition

**RC-1 — the proof accepts `"" == ""`: "not disclosed" is read as "default profile".**
`_profile_truth` reads the job tab's context; the default context carries no
`browserContextId`, so it reads `""`. Opener (a) then runs `Target.createTarget` **without
a context**, Chrome lands the tab in the **default** profile, and `_proven` compares
`"" == ""` — a tautology that certifies its own counterexample. For a job running in a
second regular Chrome profile the handover therefore *provably* opens the fresh tab in
profile 1 and closes the job's old tab: exactly A2. The load-bearing v5 assumption is the
§4 bullet "Target.getTargets … reports each one's browserContextId (the default context
omits it)" — that holds for the contexts DevTools itself creates (OTR/incognito), but a
**regular profile's tabs are not addressable as browser contexts** (v5's own §4:
`createTarget{browserContextId}` answers *Failed to find browser context with id …*), so
for them nothing distinguishes "profile 2 whose id was never disclosed" from "default".
The v5 fake world models profiles *as* contexts — the listing always discloses them — so
this combination could never be expressed there.

**RC-2 — the only profile-locked opener is skipped or unavailable, which is why the
behaviour diverges between profiles.**
(a) runs first and, under RC-1, "succeeds" — so the page opener never gets its turn; when
(a) does fail (a disclosed context Chrome refuses), opener (b) refuses unless some client
object happens to sit on the job tab at that instant (`_popup_client`), because the
handover never uses the one socket it already trusts: the job tab's own `ws_url`. That is
the 3-profile coin flip in the report: a profile whose tab has a registered client opens a
new tab, a profile whose shared client had drifted elsewhere clicks New Chat in place,
and a run where (a) "succeeds" leaks into profile 1.

Consequence chain for A2: RC-1 → the fresh tab lands in the default profile → `"" == ""`
passes → `_connect_all`/`_prove_new_chat` run against it → `_move_worker` re-keys the pool
entry and the URL row onto a profile-1 tab → `_close_old` closes the job's tab.

## 4. The rule this round adds (R6–R7; R1–R5 stay)

> A fresh tab may replace the job's tab only on a **non-degenerate** proof. Silence is
> never evidence: a context comparison proves something only when the job tab carries a
> real, disclosed `browserContextId`. The page's own `window.open` counts when the fresh
> tab names the job tab as its opener (`openerId`) — Chrome can only open a tab into the
> opener's own profile, so provenance pins the profile even where contexts are never
> disclosed. When no client sits on the job tab, the opener connects to the job tab's own
> socket instead of refusing. Unknown stays unknown and ends in the in-place New Chat.

| # | Rule | Where |
|---|---|---|
| R6 | Opener (a) `Target.createTarget` runs **only** when the job tab's context is disclosed (non-empty). A `""` job context may never trigger it: the creator's result would be compared with the same `""` it produced. | `new_tab_open.open_in_profile` |
| R7 | Opener (b)'s tab is accepted when (i) it lists `openerId == job tab` — profile by Chrome's window-open lock; or (ii) `openerId` is not reported and the disclosed contexts are equal **and non-degenerate**. A fresh tab that names a *different* opener is refused and left alone (it may be a human's tab). | `new_tab_open._proven` |
| R7b | The page opener first uses a client that sits on the job tab, else connects to the job tab's own `ws_url` (`_dial_page`); a provenance rejection by a drifted client retries once from that honest socket. | `new_tab_open._page_opener` |

## 5. Rejected shapes

* **Trust `"" == ""` when "some other tab discloses a context"** — disclosure is not
  uniform: a browser can report an incognito context while regular profiles stay silent;
  a positive elsewhere does not make this job's `""` mean "default".
* **Owner/account probe as the profile proof** — a label, not a profile (v5 §5, kept).
* **Keep (a) for `""` and verify afterwards** — the wrong-profile tab already exists at
  that point; the best case is a rollback, and under RC-1 the "verification" is the bug.
* **Close every rejected fresh tab** — after a wrong-opener rejection the tab names
  another opener; it may be the user's. Leaving a stray is recoverable, destroying a
  stranger's tab is not.
* **Always page-opener-first** — (a) is sound and dependency-free wherever the context is
  disclosed (an OTR context); it stays first in that case.

## 6. Tests first (RULE 8) — the RED list

The fake world grows two knobs that mirror reality without assuming it: `hide_contexts`
(the listing never carries `browserContextId`, while the fake still *knows* each tab's
internal profile) and a popup opener override (a client whose socket disagrees with the
tab it claims). Written before the fix; the first four fail on the current code:

1. RED `a job tab whose profile is never disclosed proves itself by its own silence` —
   hidden contexts, job tab really in profile 2: current code createTargets into the
   default profile, the tautology passes, the worker moves (A2 reproduced). Expected:
   the creator never runs; the page opener's tab (openerId = job tab) wins; the other
   profile untouched.
2. RED `an undisclosed profile with a blocked popup refuses instead of creating` — the
   same hidden world with `popup_allowed = False`: no mutation, refusal names the popup,
   `create` never called.
3. RED `a fresh tab opened by another tab is not the job's new tab` — provenance
   rejection (wrong `openerId`), retried from the job tab's own socket and won there;
   the foreign tab is neither adopted nor closed.
4. RED `no client on the job tab is dialed from its own socket` — `_dial_page` seam:
   a refused CDP creator plus zero registered clients still opens via the job tab's
   socket; with the dial dead, the old refusal remains (in-place fallback).
5. Unit REDs in `test_new_tab_open.py`: the creator never runs for a `context_id=""`
   spec; a disclosed-but-different `openerId` is refused and not closed.

## 7. Honest limit

No Chrome binary exists in this sandbox and the browser CDNs are unreachable, so the
A1/A2 run itself cannot be replayed here (the same limit v5 recorded). The fix is sound
under **either** Chrome behaviour: if regular profiles do disclose contexts, R6 is a
no-op for them (their context is non-empty) and nothing changes; if they do not, the
tautology is gone and the provenance rule carries the proof.
