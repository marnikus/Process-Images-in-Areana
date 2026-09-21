# Merging the Job History window into the readable-tab-ids branch

**Date:** 2026-09-21
**Source:** `arena/01a0c3a5-process-images-in-areana` (2 commits — the window + its quality pass)
**Target:** this branch, which had already landed I-59 (readable `{email}_{4 digits}` tab ids + the always-visible countdown).

Both branches grew from the same parent (`d8fa79c`), so the two feature commits
were cherry-picked rather than squashed — the history of the feature and its
quality pass stays readable.

## 1. The textual conflict (one)

`package.json` — both branches appended new files to the `test:js` list.
Resolved as a **union**, not a side-pick: the target's three new suites
(`test_pool_tab_id`, `test_countdown_visible`, `test_tab_label_views`) and the
source's `test_job_history_panel` all run. 38 + 1 = 39 suites. Taking either
side whole would have silently stopped running four test files.

## 2. The semantic conflict (the one that mattered)

Nothing else conflicted textually, but the two features disagreed about **what
names a tab**.

* This branch's D-7 rule: every view and every log line prints the readable
  handle `{email}_{4 digits}`; the 32-hex CDP id stays the identity key
  (RULE 15) and lives in the tooltip. One formatter owns it on each side —
  `page_pool.tab_label_of` (Python) and `core/tab-label.js` (JS).
* Job History was written before that rule existed, so its "Tab ID" column
  rendered the raw hex truncated to 8 characters.

Merging the text cleanly would have shipped a window that disagrees with every
other window about the same tab — exactly the failure D-7 exists to prevent.

**Resolution — reuse the owners, do not re-implement them.**

* `job_history.tab_label_for(pool, tab_id)` delegates to `page_pool.tab_label_of`,
  so the history row and the worker table can never print different handles.
  The import is function-local: `app/browser` must not depend on `app/services`,
  and this keeps the arrow pointing down with no cycle.
* The label is **resolved at record time and frozen into the row**. History
  outlives the tab it describes (RULE 14: history is not the queue) — a job that
  finished an hour ago must keep the name it ran under, even after the tab
  closed and the pool forgot it. Looking the label up at render time would blank
  out exactly the rows a user reads history for.
* `tab_id` is still written to every row unchanged: identity stays the CDP id.
* JS `_tabCell` prefers the frozen `tab_label`, falls back to the live pool
  lookup (rows written before this merge), then to the short id — never an empty
  cell. The tooltip carries `handle · full-hex` when a real handle exists, and
  the bare hex otherwise, so the pre-existing tooltip contract still holds.

## 3. Window count

`window_catalog` went 16 → 17 (`GRID_VERSION` 6 → 7) in the source branch;
older layouts migrate by appending the missing leaf, never by rejecting. The
System of Record still said "16 windows" in three places — updated, and the
`job_history` row added to the window table.

## 4. Dependencies

No new runtime dependency on either side: `requirements.txt` is untouched and
`job_history.py` imports stdlib + `persistence.json_store` only. The only
manifest change is the `test:js` suite list above. `npm install` restores the
existing dev tools (jsdom, c8, jscpd, acorn); `pip install -r requirements.txt`
is unchanged. Qt needs `libgl1` present to import in a headless sandbox.

## 5. Verification

| Gate | Before the merge | After |
|---|---|---|
| pytest (`not e2e and not slow`) | 1925 passed | **1963 passed**, 4 skipped |
| `npm run test:js` | 313 (309 pass, 4 skip) | **328 (324 pass, 4 skip)** |
| `verify_quality.py --changed` | — | **PASSED**, 0 fails |
| `job_history.py` coverage | 100% (source branch) | **100% line + branch** kept |

Seven tests were added for the integration itself (4 Python, 4 JS — one Python
test covers the import guard so the module stays at 100%): the row freezes the
handle, history and the worker table agree on the same tab, a vanished tab or a
dead pool degrades to the short id, and a legacy row with no stored label still
resolves through the live lookup.
