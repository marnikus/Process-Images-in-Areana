# Firefox account name + visual tab id (2026-09-25)

Owner brief: "FIREFOX ACCOUNT NAME & VISUAL TAB ID". Firefox workers showed `aka_0008`;
they must show the signed-in account (e.g. `mailreceiverpro@gmail.com`), use the
profile name until it is known, and carry the same centred in-page overlay as Chrome,
formatted `<visual number># <account>` (`2# mailreceiverpro@gmail.com`).

## 1. Research — where things came from

| Question | Answer (code at `f5cb06e`) |
|---|---|
| Source of `aka_0008` | `core/tab_alias.format_alias(owner, no)` → `f"{owner or 'aka'}_{no:04d}"`. `PageInfo.alias` calls it; `page_pool._assign_alias` numbers every joined tab (the `0008`). The owner is written only by `services/live/tab_owner.resolve_owners`, which iterates `worker_badges.connected_clients` — pages with a CDP client. Firefox pages have **no client** (`pool.get_clients → (None, None)`), so their owner stayed `''` forever → `aka_NNNN`. |
| Firefox discovery | `browser_tabs.reconcile_tabs` = Chrome rows + `_firefox_rows` → `uivision.pool_tabs.firefox_rows` (session store of every open profile). Row id `{profileDir}_tab{N}`, sentinel `firefox://{id}`. |
| Worker creation | reconciler `_join_each` → `route_join_tab` → `_join_firefox` → `pool.add_page(pool_tabs.page_for(tab))` (`FirefoxPageInfo`, profile attribution rides the entry). |
| URL List / Page Pool / Live Debug / logs | all print `tab_label` = `PageInfo.alias` via `_snapshot_entry` / `tab_label_of` / JS `TabLabel.of`. One label source (I-59) — fixing `alias` fixes every view. |
| Chrome overlay | `browser/worker_badge.build_worker_badge_js` (fixed top-centre, `pointer-events:none`, `[data-arena-worker]` replaced before insert) asserted by `live/worker_badges.assert_badges` over CDP clients on join + every pass. |
| Reaching a Firefox page | only through a Ui.Vision macro (I-63): `executeScript` runs in the page, the engine wraps the body in `Promise.resolve((function(){…})())` (a returned promise is awaited), `${!cmd_var1..3}` render as JSON string literals, `echo` lines land in the savelog. |
| Page evidence | `ul[data-sidebar=menu] > button > div > span.rounded-full(img) + div.font-heading.min-w-0.flex-1.truncate` = the account (owner evidence `mailreceiverpro@gmail.com`; research HTML `zeusthunder1991@gmail.com`). Nearby semantic anchors: `data-sidebar="sidebar"/"menu"/"footer"/"rail"`, the account `<button>`, the avatar `span > img` sibling. No role/aria-label on the row. |

## 2. Identity vs display metadata (the rule this change must not bend)

| Thing | Kind | Where |
|---|---|---|
| `{profileDir}_tab{N}` | **identity** — pool key, URL-row `tab_id`, persistence key | `pool_tabs.tab_id_for` |
| `worker_no` (`#n`, overlay number) | display — session join order (I-55) | `PagePool.add_page` |
| account email | display — detected or saved last-known for the SAME key | `PageInfo.owner`, `AliasBook` (`config/cooldowns.json.aliases`) |
| profile name | display — temp name before detection | `FirefoxPageInfo.profile` / dir basename |

Nothing in this change keys on an email, a profile name, a URL, a tab index or an overlay
number. A detection failure writes nothing (the owner is only ever overwritten by a newer
verified address), so it cannot create, drop or rename a worker. Two profiles on the same
account stay two workers (two keys, two numbers).

## 3. Design

**D1 — Display name = `FirefoxPageInfo.alias`** (subclass property; `PageInfo` stays on its
class-LOC ratchet and Chrome's `{email}_{4 digits}` is untouched): detected account →
saved account of the same key (seeded by `_assign_alias`) → profile name
(`plan.profile_label`: ini name, else directory basename) → `''`, where `PageInfo.label`
falls back to the short technical id. `display_source` names the rung
(`detected|saved|profile|id`), `name_checked_at` stamps the last answer; both ride the wire.

**D2 — One identify macro, `Arena_Identify`** (`browser/uivision/identify.py`):
`selectWindow ${!cmd_var3}` (Value empty — never opens) → `executeScript <JS> | arenaIdentity`
→ `echo ARENA_IDENTITY=${arenaIdentity}`. The JS = the **existing** `owner_probe` payload
(RULE 21 selectors, one home) polled for ≤ `cmd_var1` ms (8000 — bounded in-page retry
for a still-loading sidebar), then the **existing** badge body (`worker_badge.build_badge_js_from`)
with in-page expressions: number `String(cfg.no) + '#'`, text = detected email or
`cfg.name` (fallback). `cmd_var2` carries `{no, name, clear}`, so the file is generic.
The reply is `{email, via, overlay, text}` only — probe candidates are dropped (no page
text reaches the savelog or log). `parse_reply` takes the last rendered answer (the
`Executing:` row with the literal `${…}` never parses) and validates through `interpret_owner`.

**D3 — Lane reuse** (`firefox_lane.run_identify`): the job's spec retargeted
(`macro`, `target`=payload, `pause_ms`=wait), its own savelog `identify-<stamp>.txt`
(unlinked inside the lock — never a job's `run-<stamp>.txt`), the SAME machine-wide
`_MACRO_LOCK` + `inter_run_delay_sec` gap. `storage=browser` answers `blocked` before
launch (a written macro cannot reach the browser store). `_job_run` was split into
`_planned_run` + `_fresh` so the identify path never unlinks outside the lock.

**D4 — Lifecycle** (`services/live/firefox_identity.py`): `observe(bridge, tabs, manual)`
is the new `LiveDeps.identify` seam, called at the end of `_pool_phase` (after
membership exits) and **never awaited** — discovery is never blocked. Due on: first sight,
navigation (session URL changed; the page's url/title follow the row so the macro's
title selector stays valid), reconnect (`is_connected` false→true), manual Reparse,
or number/name ≠ the overlay last aimed at. One background `drain` (lease-guarded,
600 s) runs due pages one at a time; busy pages are deferred. Failure → a concise warn
(worker id · profile · stage `macro|element` · trigger · safe reason — markup stripped,
one line, ≤ 120 chars · shown fallback) and retries at +15 / +45 / +120 s, then rests until
the next trigger. A key that left the pool while its tab is still open gets one clear run
(`{clear: true}`) — no stale overlay; a key that returns before the clear drops it (the
redraw replaces the badge anyway, `[data-arena-worker]` is removed before insert).

**D5 — Selector** (RULE 21): `account_email` gains a structural, class-free last fallback
`[data-sidebar="menu"] button span:has(> img) + div` (the text div right after the avatar),
verified RED→GREEN in `tests/js/test_firefox_identify.mjs`. Primary unchanged, so Chrome
reads exactly what it read before whenever the primary matches.

Rejected: a second Firefox-only probe/overlay (duplicate logic — §16.4); detecting inside
the job macro (it re-provisions per job and has no free `cmd_var`); keying the saved name
by profile (two tabs of one profile are two workers); awaiting the macro inside the pass
(a slow Firefox would stall Chrome's reconciliation).

## 4. Numbers (RULE 16 / 18 recheck)

| File | Lines | Max func LOC | Max CC | Max cognitive | Params ≤ |
|---|---:|---:|---:|---:|---:|
| `browser/uivision/identify.py` (new) | 139 | 15 | 7 (`parse_reply`) | 8 | 3 |
| `services/live/firefox_identity.py` (new) | 250 | 17 | 9 (`_trigger`) | 7 | 4 |
| `services/firefox_lane.py` | 130 → 163 | 21 (`run_identify`) | 7 (unchanged) | 7 (unchanged) | 4 (unchanged) |
| `browser/uivision/pool_tabs.py` | 106 → 121 | 18 (unchanged) | 8 (unchanged) | 8 (unchanged) | — |
| `browser/worker_badge.py` | 69 → 90 | 17 (= baseline) | 2 | 1 (= base) | 1 (= baseline, `BadgeExprs` param object) |
| `services/live/reconcile.py` | 375 → 378 | 18 (unchanged) | — | 8 (unchanged) | — |
| `ui/panels/browser_tabs.py` | 683 → 685 | 20 (unchanged) | — | 7 (unchanged) | — |

`reconcile.py` / `browser_tabs.py` are over the 300-line ideal already; this change adds
only the seam field + one guarded call (+3) and one wiring argument + import (+2) instead of
growing either with logic. The `max_cog 0→N` ratchet lines the gate prints for touched
legacy files are the documented stale-baseline noise (`QUALITY_RECHECK.md`): per-function
cognitive maxima are identical to base in every legacy file.

## 5. Tests

* `tests/test_firefox_identity_characterization.py` — written first, green at base: stable key,
  rejoin keeps numbers, two profiles = two workers, Chrome label shape, Chrome badge JS
  byte-identical (sha256 goldens).
* `tests/test_uivision_identify.py` — macro shape (never opens/clicks), probe + badge reuse,
  only `${!cmd_var1..2}` in the JS, rendering, payload, reply parsing (template row ignored,
  last wins, invalid dropped, no candidates), provision, separate savelog.
* `tests/js/test_firefox_identify.mjs` — the rendered payload EXECUTED in jsdom on the
  evidence markup: success (one centred click-through overlay `2#mailreceiverpro@gmail.com`),
  delayed load, missing element (bounded wait → fallback name), class-free fallback selector,
  composer never labels, stale overlay replaced/duplicates removed, clear-only.
* `tests/test_firefox_identity.py` — temp name = profile (never `aka`), fallback rungs,
  success → every view, missing element (warn fields + 15/45/120 then rest), delayed load,
  macro failure/crash (markup stripped), no regression of a known account, duplicate
  accounts, navigation/reconnect/manual, account change, busy deferral, stale clear,
  rejoin redraw, lease.
* `tests/test_firefox_identify_lane.py` — `run_identify` spec/lock/savelog, browser storage
  blocked, waits behind a job macro; reconcile hands rows + manual flag to the seam; `live_deps` wiring.

## 6. Gate results (2026-09-25)

* Full suite 2324 passed / 13 skipped; Node 397 pass / 0 fail.
* Fresh branch coverage (line %, branches): `identify.py` 95.9 (4/4), `firefox_identity.py` 97.4
  (36/38), `pool_tabs.py` 100, `worker_badge.py` 100, `firefox_lane.py` 86.7 (7/10),
  `reconcile.py` 97.7, `browser_tabs.py` 90.5, `tab_owner.py` 93.5.
* `verify_quality.py --allow-legacy --coverage-ratchet --js --changed-files <9 app files>`: the only
  fails are `ratchet-max_cog 0→N` on five legacy files. Running it on the **base** version of the same
  files gives exactly the same output, so this is stale-baseline noise (QUALITY_RECHECK.md), not growth.
* `pre_push_check.sh --changed` can't diff in this clone because origin/main has no merge-base with HEAD,
  so the gate was run with an explicit `--changed-files` list instead.
