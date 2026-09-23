# Design — readable tab ids + a countdown that never hides (2026-09-21)

User report (three windows): (1) the worker table shows a 32-hex CDP target id —
"it must be `{email}_{4-digit}`, e.g. `marnikus@gmail.com_3045`, so I can see at a
glance which account a tab belongs to and talk about a specific tab"; (2) the URL
List must show the same readable id, "consistently across all views that
reference a tab"; (3) the countdown timer "disappears / shows only `+ 15:00`, not
real time elapsing" — "it hides after Cancel current run and sometimes after
other manipulations, and it does not come back although the cooldown is still
active — it must never hide: whenever time is elapsing, show it (00:00 when
ready)". Mandate: TDD (tests first), seam-violation and integration/boundary
tests, RULE 16/18 recheck at the end.

Owner decisions taken before the design (three-question round):
* **D0-1** a captcha/rate-limit penalty on a tab that is not cooling becomes a
  **live timer at once** (never a hidden debt); if a job is still running on that
  tab the debt starts cooling the moment the job ends.
* **D0-2** the 4-digit number is **persisted per tab** (keyed by the CDP tab id,
  next to the already-persisted cooldowns) — the same tab keeps `_3045` tomorrow.
* **D0-3** when the account cannot be read the prefix is **`aka`** (`aka_3045`).

Baseline radon (6.0.1, this tree): `page_status.py` `try_expire A(2)`,
`remaining_seconds A(1)`; `cooldown_service.py` `add_captcha_penalty A(2)`,
`start_cooldown A(3)`, `_settle_pool_steady A(2)`, `_finish_cancelled A(1)`;
`page_pool.py` `add_page A(3)`, `_snapshot_entry A(2)`. Every edited function
stays ≤ CC 10, ≤ 30 LOC, nesting ≤ 4; no file may grow past its baselined
`max_func_loc` (RULE 18).

## Research (what the code does today)

* **F-1 the render is status-gated, the timer is field-based.** Both countdown
  cells open with the same test — `page-pool/render.js cooldownCell`:
  `if ((p.status||'') === 'cooldown' && remaining > 0)`, `url-list/render.js
  fillCoolCell`: `if (page.status==='cooldown' && (page.cooldown_remaining||0)>0)`
  — and `PageInfo.remaining_seconds()` itself returns 0 for every status but
  `COOLDOWN` (`page_status.py`). So the *only* thing the user can see of a timer
  is a status string. `mark_steady` (`page_pool.py`) sets `status = STEADY` and
  leaves `cooldown_until`/`cooldown_total` untouched, and `_finish_cancelled`
  reaches it through `_settle_pool_steady` — Cancel is exactly the "timer gone,
  cooldown still there" path the user reports.
* **F-2 a penalty on a resting tab is a debt that never elapses.**
  `add_captcha_penalty` / `add_rate_limit_penalty` extend a *cooling* tab, else
  they add `pending_penalty`. Nothing ticks that number down; it is only
  consumed by the next `start_cooldown` (after the tab's next job). The cell then
  renders `_cooldownPendingHtml` — `+15:00 pending` — the exact frozen
  "countdown" of the screenshot. The tab is also *not* gated (a STEADY page with
  `pending_penalty` passes `is_free()`), so the "15 minutes" it displays do not
  exist in time at all.
* **F-3 the gate ignores a live timer.** `is_free()` = `status == STEADY and
  is_connected` — a tab whose `cooldown_until` is in the future but whose status
  was clobbered (any `mark_busy`/`mark_steady`/`mark_waiting`) is handed the next
  job while its countdown is hidden in the same instant.
* **F-4 persistence is status-gated too.** `cooldown_store._persistable` saves a
  page only when `status == "cooldown" and until > now`, or when a debt exists —
  so a live timer on a status-clobbered page is not written and a restart loses
  it for real.
* **F-5 the ticker is fine — checked and refuted.** `page-pool.js init()` does
  `setInterval(()=>this.tickCountdowns(), 1000)` and `url-list.js` has its own
  1 s interval; both live 1 s tickers exist. The frozen `+15:00` is F-2 (a debt
  has nothing to tick).
* **F-6 no account probe exists.** `PageInfo` has no owner field,
  `site_adapter.SELECTORS` (15 entries) has no account entry, `DOM_SELECTORS.md`
  has no row. Real DOM evidence *does* exist in this tree:
  `docs/research/Directly Chat with Frontier Image Generation AI Models.html`
  — the sidebar account row is
  `<ul data-sidebar="menu"><button …><div …><span …>avatar</span>
  <div class="font-heading min-w-0 flex-1 truncate text-left text-sm font-normal">
  zeusthunder1991@gmail.com</div></div></button></ul>`
  (same string also in the Next.js RSC payload — not usable as a probe source:
  it sits inside a `<script>` text node).
* **F-7 the 4-digit number must outlive the entry it is stored with.** The
  existing `config/cooldowns.json` `entries` map is *evicted by design*:
  `load_entries` drops idle-expired entries, `save_pool_snapshot` pops the entry
  of any page that is not cooling/pending. A tab id number stored there would be
  forgotten the first time its timer ends. The alias map needs its own section.

## Decisions

* **D-1 (F-1, F-3, F-4) the timer is the authority; the status is a label.**
  `PageInfo.remaining_seconds(now)` reads the clock only (`cooldown_until - now`,
  clamped ≥ 0) — no status test; `is_cooling(now)` is `remaining_seconds() > 0`;
  `is_free()` additionally requires `remaining_seconds() == 0`, so **no code path
  can dispatch a tab whose timer is still running**, whatever the status says.
  `try_expire` refuses to touch a live timer and only reports `True` for a real
  `COOLDOWN → STEADY` flip (it still clears residue fields of an expired pause on
  any status). `status_snapshot.cooling` counts `is_cooling()` (a timer), and
  `cooldown_store._persistable` becomes status-independent (`until > now or
  pending > 0`) so a live timer survives a restart even if the label was wrong.
* **D-2 (F-2, D0-1) a penalty starts cooling a resting tab.** One shared
  `_stack_penalty(page, extra, reason)` replaces the duplicated branch in
  `add_captcha_penalty` / `add_rate_limit_penalty`: cooling → extend the live
  timer; **busy → keep the debt** (`pending_penalty`, the running job's debt);
  resting (steady/error/disconnected) → **arm a live timer for the penalty now**
  (status `COOLDOWN`, `until = now + extra + any debt`, `total` = that length,
  reason `captcha penalty` / `rate-limit penalty`), so a debt owed from an
  interrupted job joins the timer instead of being dropped. The countdown
  therefore always ticks; there is no such thing as a displayed-but-not-elapsing
  penalty.
* **D-3 (F-1) no settle path may strand a debt.** `_finish_cancelled` and the
  cooldown-off branch of `_finish_normal` go through `_settle_pool_steady`, which
  now marks the page steady first (Cancel still skips the *pause*) and then
  **materialises** a stacked debt into a live timer (`stacked penalty`), logging
  it (`⏳ … pause skipped (cancel) — stacked penalty cooling 15:00`). A user
  Reset stays an explicit "ready now": it clears the live timer **and** the debt
  of a resting page; a *busy* page is untouched, so I-27's "the running job's
  debt survives to its finish" holds (that finish then materialises it).
* **D-4 (F-1, F-2) one display rule, both views — nothing hides.** Ordering in
  `cooldownCell` and `fillCoolCell`: (1) `remaining > 0` → a ticking `MM:SS`
  (`data-cool-left` + `data-cool-at`, ` / total` when known) **whatever the
  status is**; (2) else a debt → `00:00` + the honest chip `+15:00 debt`
  (`title="Stacked penalty — starts cooling when this job ends"`), never a bare
  `+15:00` that looks like a timer; (3) the URL row additionally keeps its
  `🔵 busy` marker while a job runs (the pool row's own status column carries
  that); (4) else `00:00` (green "ready" hint in the URL list). `—` remains only
  for "no pooled tab" — that is not a timer. `tickCountdowns` prefers the
  element's own `data-cool-at` (fallback: snapshot age) and keeps writing
  `00:00`, so the value only ever counts down.
* **D-5 (F-6, D0-2, D0-3) readable tab id `{email}_{4-digit}`.** New pure core
  module `core/tab_alias.py`: `format_alias(owner, no)` → `marnikus@gmail.com_3045`
  / `aka_0001` (owner lowercased+trimmed, `no` zero-padded to 4, `''` when
  `no == 0`); `email_from_probe(raw)` validates a probe reply (JSON/str/dict,
  `^\S+@\S+\.\w{2,}$`, ≤ 64 chars, lowercased, anything else → `''`);
  `next_alias_no(taken)` → highest-used + 1, wrapping into the lowest free gap
  once 9999 is passed (never reuses a live number); `AliasBook` — the in-memory
  registry (`no_for`/`owner_for`/`remember`/`as_dict`), no I/O. A new browser
  leaf `browser/owner_probe.py` builds the probe JS (RULE 21: selectors arrive
  from `probe_selectors.account_email_probe()`, only placeholders inside) and
  `services/live/tab_owner.resolve_owners(pool)` evaluates it per pooled page —
  the same best-effort loop that already pushes the worker badge (join + every
  reconciler pass; a failed probe never clobbers a known email, RULE 15-safe).
  `site_adapter` gains `account_email` (primary + fallbacks from the F-6 DOM
  evidence, plus a bounded heuristic scan of the sidebar/menu/button text that
  skips script/style/composer nodes) with its own `DOM_SELECTORS.md` row.
  `PageInfo` gains `alias_no` / `owner` + an `alias` property; `PagePool.add_page`
  assigns the number once per tab (via the injected `AliasBook`), the badge and
  every tab-referencing view read `page.alias`, and the hex id stays as the
  identity key (pool key, action attributes, `title` tooltips).
* **D-6 (D0-2, F-7) the numbers persist in their own section.**
  `config/cooldowns.json` gains `aliases: {tab_id: {no, email, seen}}` written by
  `save_pool_snapshot` from the pool pages (merged with what is on disk, capped at
  200, most recent first) and read once at pool construction
  (`bridge_context.wire_page_pool` → `AliasBook(load_aliases(path))`).
  `save_entries` (the undo path) preserves the section it does not own. A tab
  that re-joins keeps its number *and* its last known email — the label never
  regresses to `aka_…` just because the probe has not run yet.
* **D-7 which views show it.** Worker table (`#N <alias>`, `title` = full hex),
  URL list (new `Tab` column between `URL` and `Status`, filled from the same
  pool snapshot the cooldown/jobs cells use; `—` when the row's tab is not
  pooled), Live Debug worker line, the in-page worker badge (`#N <alias>`), and
  the timer log lines in `cooldown_service` + `page_pool.add_page` through one
  `_label(pool, tab_id)` helper (falls back to the 12-char id prefix). Panels
  that only *act* on a tab id keep the raw key.

## Rejected alternatives (dishonest reductions, RULE 16.6)

* Drive the cells from `status` and just add `-2` display branches — the status
  is what lied in the first place (F-1/F-3); a second gate would keep hiding a
  timer the moment another path touches the status.
* Keep the debt and only rename it (`debt +15:00`, no timer) — the owner chose
  D0-1: the displayed 15 minutes must exist in time.
* Materialise the debt only in the reconciler pass — up to one interval (60 s at
  the maximum setting) of "ready" tab with a hidden 15 min on it, and the
  reported Cancel path has no pass of its own.
* Make the debt tick down as if it were cooling while the tab is *busy* — the
  timer would run out during the job and the pause would effectively disappear;
  the debt stays a debt until the job ends (D-3 materialises it there).
* Store the alias number in the existing `entries` map — F-7: it is pruned by
  design the moment the timer ends.
* Allocate the number in a snapshot/render path — the number would follow dict
  order and churn between passes; allocation belongs to the join (one site,
  next to `worker_no`).
* Read the email from the RSC payload in the page's `<script>` text — a probe
  that depends on a framework's serialization format (and RULE 21 keeps element
  finding in `site_adapter`); the sidebar row is the visible truth anyway.
* Rewrite every `str(tab_id)[:12]` log line in the codebase — the views are the
  reference surface (D-7); the timer lines are the ones the user reads while
  the reported bug happens, the rest is churn.

## Files

| File | Change |
|---|---|
| `app/core/tab_alias.py` (new) | `format_alias`, `email_from_probe`, `next_alias_no`, `AliasBook`, limits |
| `app/browser/owner_probe.py` (new) | probe JS (placeholders only), reply → `{email, via}` |
| `app/browser/page_status.py` | `alias_no`/`owner`/`alias`; timer-first `remaining_seconds`/`is_cooling`/`is_free`/`try_expire`; `to_dict` |
| `app/browser/page_pool.py` | `AliasBook` injection + `_assign_alias` in `add_page`/`_revive`, `tab_label` in `_snapshot_entry`, timer-based `cooling` |
| `app/browser/site_adapter.py`, `app/browser/probe_selectors.py` | `account_email` selector + probe accessor (RULE 21) |
| `app/services/cooldown_service.py` | `_stack_penalty`, `_arm_timer`, monotone `start_cooldown`, `_materialise_debt` in `_settle_pool_steady`, resting-reset clears the debt, `_cooldown_suffix`/`_label` wording |
| `app/services/live/tab_owner.py` (new) | `resolve_owners(pool)` (join + pass), best-effort |
| `app/services/live/worker_badges.py` | badge shows `page.alias` (fallback: the id) |
| `app/persistence/cooldown_store.py` | `load_aliases`/`save_aliases` + `aliases` section, status-free `_persistable` |
| `app/services/run_state.py`, `app/ui/bridge_context.py` | persist/load the alias book with the pool |
| `app/ui/web/index.html`, `js/panels/url-list/render.js`, `js/panels/url-list.js` | `Tab` column + label cell |
| `js/panels/page-pool/render.js`, `actions.js` | D-4 rule, `data-cool-at`, label in the row |
| `js/panels/live-debug/{render,store}.js` | label in the worker line |
| tests | see below |

## Tests first (RED at `8db8ec6`)

Python — `tests/test_tab_alias.py` (pure functions + `AliasBook`, boundary:
`9999` wrap, all-taken, `no == 0`, over-long / malformed probe replies),
`tests/test_tab_owner.py` (probe → `page.owner`, bad reply keeps the known
email, a raising client is skipped, no client = untouched),
`tests/test_page_pool_alias.py` (`add_page` allocates once, a persisted book
keeps the number across pools/re-joins, `tab_label` in the snapshot, `aka_`
prefix, hex fallback), `tests/test_probe_selectors.py` (+ the new probe file is
in the RULE 21 lint and the payload wiring),
**`tests/test_cooldown_timer_visible.py`** — the seam/integration suite the user
asked for, driving the real `PagePool` + `cooldown_service` + fake bridge:
penalty on a resting tab → live timer + `cooldown_remaining > 0` in the snapshot
(RED: today `+15:00 pending`, `remaining == 0`); Cancel with a debt → live timer
and the page is not free (RED: today STEADY + pending debt + `is_free() True`);
cooldown-off finish with a debt → the same (RED); `start_cooldown` never
shortens a live timer (RED: today it overwrites `until`); the seam violation
`mark_steady` on a page with a live timer → still cooling, still counted, still
not free (RED); `try_expire` never voids a live timer (RED); the user's whole
scenario in one integration test (join → busy → captcha → cancel → snapshot has
the ticking value *and* the readable label) (RED); a live timer on a
status-clobbered page survives `save_pool_snapshot` → `load_entries` (RED).

JS — `tests/js/test_countdown_visible.mjs` (countdown for any status with
`cooldown_remaining > 0`; `00:00` when ready; `+15:00 debt` chip; the 1 s tick
decreases and lands on `00:00`; the URL cell the same), `tests/js/test_tab_label_views.mjs`
(pool row shows the label with the hex in `title`; `tab_label` absent → short
hex; Live Debug line; the URL list `Tab` header + cell + `—` when not pooled),
and `tests/js/test_pool_tab_id.mjs` (round 1) restated for the label.

Superseded by this design (documented behaviour change, D0-1): the legacy
assertions that a penalty on a *resting* tab stays `pending_penalty` — those
tests are re-pointed at the new rule (busy tab → debt; resting tab → live
timer), never deleted.

Gates: full `pytest`, `npm run test:js` (+ the two new files added to the
explicit list in `package.json`), radon/CC/LOC on every changed file, coverage
ratchet, scoped `tools/verify_quality.py --changed-files …`.

## Landed shape (2026-09-21, after the RULE 18 recheck)

* **One label source, three layers:** `PageInfo.label` (alias, else the short id) →
  `app/browser/page_pool.tab_label_of(pool, tab_id)` (read through the pool's public
  `get_page`, missing pool safe — `services/run_state.py` re-exports it so panels never
  import browser at top level; `multi_page_dispatcher` / `batch_orchestrator` import it
  from the browser module) → JS `core/tab-label.js` `TabLabel.of(tabId, page)`.
  Log lines re-pointed: `page_pool.add_page` (`Pool add …`), `finish_pool_join`
  (`Pool added …`), `disconnect_page_pool`, `_mark_steady_emit`, `_log_no_ctrl`,
  `_log_assign`, `_log_stay_reason`, `_announce_restore`, browser_tabs ×3, and the
  Captcha Watcher through a new `WatcherDeps.label` (default: short id; `watcher_solver`
  injects the pool label).
* **`PagePool.tab_label` was rejected by the gate** (`class PagePool LOC 152 > 150`,
  `methods 16 > 15`) — the helper is module-level over `get_page`, the class did not grow.
* **JS modules (no frozen file grew):** `url-list/cells.js` (Tab + Cooldown cells, 92),
  `page-pool/cells.js` (the Cooldown cell, 38), `page-pool/ticker.js` (the 1 s tick, 34),
  `core/tab-label.js` (19); `page-pool/render.js` 119 → 95, `actions.js` 134 → 121,
  `store.js` 32 → 31, `url-list/render.js` 74 → 46. `index.html` loads
  `core/tab-label.js` before the pool panel, `page-pool/cells.js` + `ticker.js` after
  `store.js`. The URL list sees the same label because the `Tab` cell is filled by the
  same per-page loop that already filled the cooldown/jobs cells, and the label itself
  comes from that page object (`TabLabel.of(tab_id, page)`).
