# Design — Ui.Vision runs find their tabs by URL pattern as well as title

Date: 2026-09-24 · Owner request: *"It find a tab by name pattern but I need also
option to find Tab by URL pattern match like `https://arena.ai/image/`. If search by
tab name pattern is empty that mean search any. If search by tab url pattern is
empty that mean search any."*

## Semantics (the owner's rule, as code)

Two independent, optional filters over every open tab of every profile:

| title pattern | URL pattern | what matches |
|---|---|---|
| `X` | `Y` | tabs whose title contains `X` **and** whose URL contains `Y` |
| `X` | *(blank)* | tabs whose title contains `X` (today's behaviour, unchanged) |
| *(blank)* | `Y` | tabs whose URL contains `Y` — the new option |
| *(blank)* | *(blank)* | **every** open tab (each pattern "any"); detect warns loudly |

`plan.matches(title, url, pattern, url_pattern)` is the one predicate — blank means
any, matching is case-insensitive substring on both sides.

## How a URL match becomes a macro run (the constraint)

Ui.Vision's `selectWindow` can address a tab only by `title=…` glob or relative
`tab=N` — there is no URL selector (and `tab=N` was rejected on 2026-09-23: it
depends on which window received the autorun tab and can click the wrong tab).
So the URL pattern is a **matching** predicate in Python over the session stores
(which carry URLs); each matched tab is still **addressed** by its own title glob
(`plan.selector_for`, unchanged). Consequence, handled honestly (RULE 4):

* A matched tab with an **empty title** (e.g. `about:blank`) cannot be selected —
  `plan.split_unaddressable` separates it, detect warns per skipped tab, and the
  run plan holds only addressable tabs.
* **URL-only search with nothing matched** (or a silent store) cannot build the
  fallback selector — the run is `blocked` before any file is written, with the
  message naming exactly that ("the macro selects tabs by TITLE — open the page
  or add a title pattern").
* Both patterns blank + a silent store → `blocked` ("nothing to search"); both
  blank + open tabs → the macro runs on every open tab, behind a detect warning.

## Changes

* **`plan.py`** — `matches` (the predicate), `describe_search` (`title “X” + URL
  “Y”` / `any title + URL “Y”` / `any tab`), `plan_targets(sessions, pattern,
  url_pattern="")`, `split_unaddressable` (addressable vs titleless). `selector_for`,
  `runs`, `clashes`, `summarize` unchanged.
* **`runner.py`** — `RunSpec.url_pattern` (appended last, default `""`, so
  positional constructors survive); detect reports the search line, warns on the
  every-tab case, skips titleless matches; `_fallback_or_block` replaces the
  blank-pattern block (both-blank vs URL-only-no-match get different messages);
  `Sequence._foreground` uses the first non-blank pattern as its window needle.
* **`firefox_auto` config** — new `url_pattern` key (DEFAULT_SESSION, validate
  TEXT_FIELDS, `build_spec`, the run header line); retired `"url"` stays retired.
* **UI** — `faUrlPattern` input in `index.html` (faPattern relabelled "Tab title
  pattern (blank = any)"), `FIELDS` table in `firefox-auto.js`, `FA_IDS` + `CFG`
  in the JS test.

## Sizes (RULE 18) and gates (RULE 16)

`matches` CC 8 / `describe_search` CC 7 / `split_unaddressable` CC 7
(radon, all ≤ 10); worst cognitive in the touched files 9 (≤ 15); every
function ≤ 30 LOC / ≤ 4 params; `run_test` hosts the no-match decision in
`_fallback_or_block`; `plan.py` ≈ 173 lines, `sequence.py` ≈ 201, `runner.py`
≈ 372 (ideal-size reason comment refreshed).
RED-first tests: matching matrix + describe/split in `test_uivision_plan.py`;
runner URL-only / combined / every-tab / blocked paths in
`test_uivision_runner.py`; config round-trip in `test_firefox_auto_panel.py`;
field table in `tests/js/test_firefox_auto_panel.mjs`.
