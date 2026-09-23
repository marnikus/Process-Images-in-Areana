# "No tab match" — the app was reading a store that does not exist (I-66)

**Date:** 2026-09-23 · **Fixes:** the I-65 tab-pattern lookup

## The report, and what was actually wrong

The user had `https://arena.ai/image/direct?model_a=max` open in Firefox, the
pattern set to `arena.ai`, and the window kept answering *"no tab matches the
pattern"*. Their own log even showed the app had the tab:

```
[11:39:01] 🔺 URL added https://arena.ai/image/direct?model_a=max (tab DAE40D29…) — new matching tab
[11:40:09] 🦊 Ui.Vision macro 'Python_XClick_Demo' → (no tab match)
```

The report's suggested causes were all about Ui.Vision — extension permissions,
`browser.tabs.query()`, a Chrome/Firefox tab-list split. **None of those were
the problem.** The bug was two defects in the I-65 code I shipped last turn,
and both are the same mistake: *code written against an imagined interface
instead of the real one.*

### Defect 1 — reading an attribute that exists nowhere

```python
def _urls_of(bridge):
    getter = getattr(bridge, "_url_rows", None)      # does not exist
    if callable(getter): ...
    return getattr(bridge, "url_rows", []) or []     # does not exist either
```

The app's URL rows live in `bridge.state.urls` — what `url_queue`,
`run_control` and `browser_tabs` all read. Neither `_url_rows` nor `url_rows`
appears anywhere in the codebase. Both `getattr`s fell through to `[]`, so the
pattern was matched against an **empty list** on every call. That is the
reported symptom exactly, and it was guaranteed for every user.

### Defect 2 — a `str()` fallback that matched the repr

```python
url = str((row.get("url") if isinstance(row, dict) else row) or "")
```

`state.urls` holds `UrlRow` **dataclasses**, so a row hit the `else` branch and
was stringified whole:

```
"UrlRow(id='url_1b6…', url='https://arena.ai/image/direct?model_a=max', enabled=True, …)"
```

That string *contains* `arena.ai`, so the pattern matched — and the function
returned the entire repr **as if it were a URL**. Nothing raised. Had defect 1
been fixed alone, the macro would have launched Firefox against a garbage
locator: a worse failure than the honest one, because it looks like it worked.

### Why the tests missed both

My I-65 tests used `[{"url": "..."}]` dicts and plain strings — shapes the app
never produces. They tested the code against its own assumptions. The fix adds
tests that use the real `UrlRow` type, and one that pins the repr trap
specifically: an object whose `repr` happens to contain the pattern must not
match.

## The fix

**`url_of(row)`** is now the single accessor: `UrlRow.url`, a dict's `url`, or
a plain string. Anything else yields `""` and therefore cannot match — no
`str(row)` fallback, because a plausible-looking wrong answer is worse than
none (RULE 4).

**`_urls_of(bridge)`** reads `bridge.state.urls`, the same store every other
panel uses.

## The report's real complaint: the failure taught nothing

The message *"no tab matches the pattern"* is identical whether the pattern is
wrong, the list is empty, or the app is reading the wrong store — which is why
the bug had to be reported rather than self-diagnosed. New `match_report()`
names what was compared:

| Situation | What the operator now sees |
|---|---|
| App has no rows | `pattern 'arena.ai' matched nothing — the app knows no URL rows yet; add the tab to the URL list, or type a full https:// URL as the pattern` |
| Pattern genuinely wrong | `pattern 'typo' matched none of 2 URL(s): https://arena.ai/…, https://…` |
| Blank field | `the tab pattern is empty — type the URL (or part of it) to open` |

It appears in the activity log, the window's match line, and the failed run's
message. Long lists truncate so one log line stays readable.

## Two claims in the report worth correcting

**"App detects Chrome tabs via CDP but Ui.Vision runs inside Firefox —
separate tab lists."** Correct as an observation, but not a defect: the design
*never* enumerates Firefox tabs. Doing so would need exactly the debugger
access I-65 removed. The pattern selects a URL from the app's own URL list and
the macro's `open` command navigates to it — the tab list the app holds is the
only one involved, by design.

**"Verify Ui.Vision uses `browser.tabs.query()` / check the manifest 'tabs'
permission."** Not applicable — no code of ours runs inside the extension. We
hand Ui.Vision a URL on the command line; it opens it. Nothing was wrong on the
extension side, which is why no amount of debugging there would have helped.

## Verification

* RED first: 5 service tests + 2 panel tests failed against the real `UrlRow`
  before the fix, then passed.
* Mutation-checked: restoring the `str(row)` fallback fails 5 tests; restoring
  the invented attribute fails 6.
* pytest **2141 passed / 0 failed**, JS **347 passed / 0 failed**
* coverage **88.70 line / 85.32 branch**; all seven uivision modules **100 %**
* gate: **0 findings** on both changed files; vulture clean (bar known Qt-slot
  false positives); radon CC all A
* RULE 18: `uivision_service.py` 192 lines, `panels/uivision.py` 135; every
  function ≤ 20 LOC except the 23-line macro builder that is mostly docstring
