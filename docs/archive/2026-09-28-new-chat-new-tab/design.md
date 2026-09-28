# Start new chat as new tab — design (I-79)

Owner request 2026-09-28: *"in Settings add control 'start new chat as new tab'. It
should close the old URL with the old job (failed or success) and open a new pure
tab `https://arena.ai/image/direct?model_a=max`. Remember the URL of the current
job tab — verify the old tab closed; verify the new chat was created; start the
new job in the new pure chat. If the new and old URLs are the same and both are
new-chat URLs, the old one is closed."*

## 1. What exists (read before designing)

| Piece | Where | What it means for the feature |
|---|---|---|
| Post-job reset | `cooldown_service._best_effort_reset` (both job paths via `FinishCtx`) | the ONE seam; it already has a lane hook (`lane_reset`, Firefox) |
| New Chat reset + readiness proof | `browser/new_chat.py` (`_wait_page_loaded`: document complete + page ready + composer empty) | reused as the new tab's proof |
| "Is this a new chat?" | `browser/chat_page.read_chat_page` (I-74 gate) | the second proof; the next job's gate checks again |
| Pool identity | `PagePool` keyed by **CDP tab id**: cooldown, captcha debt, job count, worker number, alias number (`AliasBook`, persisted with cooldowns) | a new tab is a stranger unless the entry **moves** to the new key |
| URL rows | `UrlRow.tab_id` (rows are unique by tab id, not URL); reconciler adds rows for new tabs, retires rows of gone tabs, joins/evicts pool pages | a concurrent pass would add the new tab as a NEW worker and retire the old row |
| Reconciler mutex | `reconcile_once` skips while `bridge._auto_scan_running` | the handover holds the same flag: no pass sees a half-moved worker |
| Tab endpoints | `browser/cdp/tabs.py` (`/json/list` sync) | open/close join it |

**Measured on real Chromium 131** (sandbox, `/tmp/exp/move.py`): `/json/new` needs
**PUT** (GET → 405) and takes a percent-encoded URL intact (`?model_a=max&x=1`);
`/json/close/<id>` → "Target is closing", gone from `/json/list` in ~3 ms, a second
close → **404** (= already closed); `CDPClient.connect(new_ws)` on the SAME client
object moves it to the new tab; two tabs on the same URL coexist and closing the
old one leaves the new one working.

## 2. Decisions

* **D1 — the worker moves, the tab changes.** The old tab's pool entry (cooldown,
  debt, count, worker number, alias number + account) is re-keyed to the new tab
  id, in pool order; the URL row is re-pointed (`tab_id`, `url`), its checkbox kept.
  Pool and log states therefore read exactly as with the in-place New Chat (owner
  rule: pool/log states identical), only the tab id changes.
* **D2 — client objects move, not get replaced.** Every client connected to the old
  tab (the finish context's, the pool's registered one, `bridge.cdp` when it is on
  that tab) is `connect()`-ed to the new tab. Every holder (job controller,
  Watcher, pool) follows without being told. Clients move BEFORE the old tab closes,
  so nothing tries to reconnect to a closed tab.
* **D3 — verify before committing, roll back on failure.** The new tab must pass the
  reset's readiness proof AND `read_chat_page` = new. Failure → clients back to the
  old tab, the new tab closed, then the ordinary in-place New Chat runs — a worker
  is never lost, the failure is one warn line.
* **D4 — the old tab is closed and the close is verified**: close, then poll
  `/json/list` until its id is gone (≤ 5 s; 404 = gone). Still listed → one error
  line naming the tab (it would otherwise come back as a stranger row).
* **D5 — same URL is not special-cased away**: when the old tab already shows the
  same new-chat URL, it is still closed (one tab per worker) — logged as such.
* **D6 — the reconciler is paused for the handover** by holding
  `_auto_scan_running` (waits ≤ 10 s for a running pass; not free → no handover,
  in-place New Chat instead). A Reparse clicked meanwhile is queued as today.
* **D7 — Chrome (CDP) tabs only.** Firefox tabs are driven by Ui.Vision macros that
  never open pages (owner rule 2026-09-23); `lane_reset` keeps precedence. A
  cancelled run keeps the fast in-place hygiene reset.
* **D8 — setting**: `new_chat_new_tab` (bool, default off) + `new_chat_new_tab_url`
  (default `https://arena.ai/image/direct?model_a=max`; not http(s)+host → default),
  in the Settings **Job Cycle & Cooldown** box (the box that already says "after
  each job the tab auto-clicks New Chat"), saved/loaded with the cooldown config —
  no new bridge slot.

Rejected: *let the reconciler discover the new tab* (new worker number, lost
cooldown, old row retired by hysteresis — the pool would lie); *a new PagePool
method* (class at 15 methods = the RULE 16 fail line → module function in
`page_pool.py`); *navigate the old tab instead* (that is today's direct-open
fallback, not what was asked).

## 3. Code shape (RULE 16/18 budget)

| File | Change | Budget |
|---|---|---|
| `browser/cdp/tabs.py` | `open_tab_sync`, `close_tab_sync` (PUT /json/new, /json/close) | 2 fns ≤ 20 lines |
| `browser/page_pool.py` | `retarget_page(pool, old_id, tab)` module fn | ≤ 20 lines, file ≤ 300 |
| `core/tab_alias.py` | `AliasBook.adopt(new_id, old_id)` | 1 method (8 → 9) |
| `browser/new_chat.py` | `_wait_page_loaded` → public `wait_new_chat_ready` (structure only) | rename |
| `services/new_tab.py` (new) | setting read/clean/save + `handover(ctx, timeout)` steps | ~250 lines, fns ≤ 20 |
| `services/cooldown_service.py` | `_best_effort_reset` asks `new_tab` first (CDP, not cancelled) | +1 small helper |
| `ui/panels/page_pool.py` | cooldown get/set carry `new_tab`; parse/store → `_save_cooldown`, wording → `_cooldown_line` (slot 16 → 9 lines) | no new slot |
| `services/batch_orchestrator.py` | `_finish_and_follow`: the batch follows its worker to the new tab id | ≤ 10 lines |
| `ui/web/js/panels/new-tab-setting.js` (new) | load/show/read of the two controls; settings.js only spreads `read()` into its payload (0 lines grown — JS ratchet) | ~30 lines |
| `ui/web` (index.html) | checkbox + URL input in the Job Cycle box | |

`AliasBook` grows 8 → 9 methods (`adopt`), recorded in the baseline: the alternative — another module writing the book's private entries — is worse, and 9 is far from the fail line (15).

## 4. Tests first (RULE 8)

`tests/test_new_tab_handover.py` — real `PagePool`, real `AliasBook`, real rows; a
fake browser (tab list + open/close) and fake clients: moves the worker with its
cooldown/count/number, re-points the row, moves every client, closes + verifies the
old tab, same-URL case closes the old one, verification failure rolls back
(clients home, new tab closed, in-place reset runs), reconcile flag held and
released, not-open old tab (404) = closed. `tests/test_new_tab_setting.py` —
defaults, URL cleaning, save/load through the cooldown slots. jsdom test for the
two controls. Real-Chrome check with the app's own `CDPClient` before commit.
