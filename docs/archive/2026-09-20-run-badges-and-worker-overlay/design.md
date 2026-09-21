# Run-status badges + worker-id overlay — design (2026-09-20)

Brief (owner): **01** the run cycle is running by default; when it is *not*
(Paused / Stopped) a visible badge says so, in **both** the Live Worker &
Queue Debug window and the Run Controls panel. **02** every pooled Chrome
tab carries a small top-middle badge with the worker's **full id** and a
**sequential number** (1, 2, 3 …) so a tab can be matched to the worker list
at a glance.

Owner clarifications (asked before design): *running by default* = badge
semantics, no auto-start; the sequential number = **pool join order, stable
for the session**, never reused.

## 1. What exists (evidence)

| Fact | Where |
|---|---|
| `run_state` has one writer, `supervisor.set_run_state`, values `idle / running / paused / stopping` | `app/services/live/supervisor.py:58`, `run_control.py:239-270` |
| It already rides `progress_updated` (`prog.run_state`) and `live_view()["run_state"]` | `layout_state.emit_arena_state`, `debug_view.live_view` |
| The only UI reader is a muted `#runStatus` text in the header (`progress.js:41`) — the Run Controls panel and the Live Debug window show nothing | `index.html:23` |
| Live Debug already renders `run <state>` at the tail of the cadence line (S9) — text, not a badge | `live-debug/render.js cadence()` |
| In-page overlays are built by Python string builders in `dom_highlight.py` and pushed with `Runtime.evaluate` (`cdp.evaluate`) — the watcher overlay is the model (top-center, `z-index` max, attribute-tagged for idempotent replace) | `dom_highlight.py:252`, `cdp_arena/highlight.py:91` |
| Every pool join ends in `finish_pool_join` (manual Add, reconciler `join_tab`); `PagePool.add_page` is the single insertion point; the client for a tab is `pool.get_clients(tab_id)` | `ui/panels/page_pool.py:66`, `page_pool.py:76,205` |
| The reconciler runs every `url_reconcile_interval_ms` in every run state and already syncs pool presence — the natural re-assert cadence for an overlay a page navigation wiped | `live/reconcile._join_and_sync` |
| `PageInfo.to_dict` (22 lines, baseline `max_func_loc` 22) is what `page_pool_updated` carries | `page_status.py:85` |

## 2. Decisions

| # | Decision | Why | Rejected |
|---|---|---|---|
| **D-1** | **No new run state, no new writer.** The badge is a *view* of the existing `run_state`: `running` → quiet, `paused` → PAUSED badge, `stopping` → STOPPING badge, `idle` → STOPPED badge. | RULE 10 (one control per decision); D-8's single writer stays. | A separate `badge_state` field (a second truth). |
| **D-2** | One JS module `js/core/run-badge.js` owns the label/class mapping and paints **every** `[data-run-badge]` element; `index.html` gets two such elements (Run Controls title bar, Live Debug head strip). | One writer for the badge; both panels stay frozen-file-cheap (markup only). | Painting from `progress.js` *and* `live-debug.js` (two copies of the mapping). |
| **D-3** | The worker number is `PageInfo.worker_no`, assigned by `PagePool.add_page` from a per-pool counter (`_next_worker_no`), **only for a first join**; a re-added (revived) tab keeps its number. Carried by `to_dict()` → `page_pool_updated`, shown in the pool table and the Live Debug worker line. | The pool is the one place that knows join order; the JS just displays. | Numbering in JS from row order (shifts when a tab leaves; contradicts the owner's choice). |
| **D-4** | The in-page badge is a Python builder `build_worker_badge_js(WorkerBadgeSpec)` in **a new leaf module `app/browser/worker_badge.py`** (not `dom_highlight.py`, which is at 320 lines with a 50-line override builder), plus `build_worker_badge_clear_js()`. Attribute-tagged (`data-arena-worker`), idempotent, top-middle, `z-index` one below the watcher overlay so the wait popup still wins, `pointer-events:none` so it never eats a click. | RULE 18.2 — a new responsibility gets its own file; RULE 16.1.5 — the excess is one JS literal. | Growing `dom_highlight.py` (already the biggest browser leaf). |
| **D-5** | Showing it is a service function `live/worker_badges.assert_badges(pool)` — for every connected page with a client, `evaluate(build_worker_badge_js(...))`, failures logged at debug and counted, never raised. Called from `finish_pool_join` (immediately on join) and from the reconciler's `_join_and_sync` (re-assert every pass: a page navigation or reload wipes injected DOM; New Chat after each job navigates). Removed by `disconnect_page_pool` / `remove_page` path via `clear`. | Same cadence as presence sync; no new timer (RULE 10: Python is the periodic writer). | A JS timer in the page re-inserting itself (survives nothing after navigation anyway). |
| **D-6** | No new slot, no new signal (Σ stays 135). Everything rides `progress_updated` and `page_pool_updated`. | D-20 of the parent chain. | — |

## 3. Interfaces (as landed)

| Symbol | Signature | Measured after |
|---|---|---|
| `page_status.PageInfo.worker_no: int = 0` | appended **last** (dataclass positional order kept) | `to_dict` **22 → 16** lines: the eight cooldown/penalty keys moved to module-level `_cooldown_dict(p)` (12 lines) — a named half of the wire form, not a `part2`; `max_class_loc` 79 → 78 |
| `page_pool.PagePool.add_page` | unchanged signature; first join ⇒ `self._next_worker_no += 1; info.worker_no = …` | **23 → 19** lines: the re-join branch is module-level `_revive(exist, info)` (9 lines, the "known tab comes back" concept); `_next_worker_no` initialised in `__init__` |
| `browser/worker_badge.py` (new) | `WORKER_ATTR`, `BADGE_Z`, `WorkerBadgeSpec(worker_no, tab_id, label="")`, `build_worker_badge_js(spec) -> str`, `build_worker_badge_clear_js() -> str` | 69 lines; builder 17 lines / CC 1; no override needed |
| `live/worker_badges.py` (new) | `async assert_badges(pool) -> int`, `async clear_badge(client, tab_id) -> bool`, `_connected_clients`, `_client_of`, `_evaluate_quietly` | 65 lines; max 8 lines / CC 5 / cog 5; 100 % covered |
| `ui/panels/page_pool.finish_pool_join` | **now `async`** (awaits `assert_badges` after `register_client`); only caller `do_connect_page_pool` awaits it | 11 lines |
| `ui/panels/page_pool.leave_pool(bridge, tab_id) -> bool` (new) | captures the client, schedules `clear_badge`, then `remove_page` — `disconnect_page_pool` calls it (12 lines, was 13) | file `max_func_loc` stays 16 |
| `live/reconcile._join_and_sync` | one awaited line after presence: `await assert_badges(pool)` | 9 lines / CC 6 (file max CC 10 unchanged) |
| `js/core/run-badge.js` (new) | `RunBadge = { VIEWS, init, view(state), apply(state), _bindLive }`; `'RunBadge'` appended to `_PANEL_INITS` on the same line | 32 lines, max CC 5 |
| `index.html` | `<span class="run-badge" data-run-badge></span>` ×2 (Run Controls `h3`, Live Debug head strip) + one `<script>` | markup |
| `css/arena.css` / `css/live-debug.css` | `.run-badge`, `--paused` (pulse) / `--stopping` / `--stopped`, `.worker-no`; `.live-no` + a 28 px first grid column | +9 / +2 |
| `page-pool/render.js._rowHtml` | `<b class="worker-no">#n</b>` inside the existing Tab ID `<td>` template line | file 119 lines, `_rowHtml` 20 — unchanged |
| `live-debug/store.js._workerLine` / `render.js._workerLine` | `no: Number(p.worker_no) \|\| 0` on the existing key line; `<span class="live-no">#n</span>` first | files 54 / 64 (+1 each, not baselined) |

## 4. Tests (RED first)

`tests/test_worker_numbering.py` — `add_page` assigns 1, 2, 3 in join order; a revive keeps its number; removal never reuses; `to_dict` carries `worker_no`; `status_snapshot` pages carry it.
`tests/test_worker_badge.py` — builder markers (attribute, `#2`, full id, top-middle, `pointer-events:none`, z-index below watcher, idempotent replace), clear JS, `node --check` parse via the payload registry; `assert_badges` evaluates once per connected page with a client, skips pages without a client, swallows evaluate errors, returns the count; `finish_pool_join` calls it; reconciler pass re-asserts.
`tests/js/test_run_badge.mjs` — mapping for four states; hidden while running; both `[data-run-badge]` elements painted; self-connects once; `index.html` has exactly two; `_PANEL_INITS` has `RunBadge`; pool row and live line show `#n`.

## 5. RULE 16 / 18 recheck (measured on the final tree)

* **RULE 18 sizes** — new files 69 / 65 / 32 lines (ideal ≤ 150); every new or touched function ≤ 19 lines (ideal ≤ 20), the only function above 15 is the JS-literal builder (17, RULE 16.1.5 does not even apply — no override used). Touched legacy hotspots **shrank**: `to_dict` 22 → 16, `add_page` 23 → 19, `disconnect_page_pool` 13 → 12; `page_status` class 79 → 78 lines.
* **RULE 16 gates** — radon max CC 6 (`_join_and_sync`, file max 10 unchanged), cognitive max 5, params max 4 (`finish_pool_join`, pre-existing), nesting ≤ 2; `verify_quality --allow-legacy --changed-files` reports **0 real fails**: the only lines are the pre-existing `max_cog` 0-baseline artefact (every file "grows" from 0 — `page_status` was already 2 at base, `page_pool` 11 at base from `wait_for_free_page`, `panels/page_pool` 6 at base from `set_page_cooldown`; none of the *new* symbols is the file maximum) and the two sandbox `libGL` coverage floors that predate S0. JS lane: `run-badge.js` max CC 5, `page-pool/render.js` 119 / 20 / CC 9 unchanged, `arena-app.js` 176.
* **Coverage** — `worker_badge.py` 100 %, `worker_badges.py` 100 % (in its own test file), `page_status.py` 100 %, project 87.89 / 84.54 (floors 86.09 / 82.01). **jscpd** 1.072 % (was 1.078). **RULE 8** every new branch has a RED-first test (5 + 10 py, 5 js). **Σ slots 135, Σ signals unchanged** (D-6).
