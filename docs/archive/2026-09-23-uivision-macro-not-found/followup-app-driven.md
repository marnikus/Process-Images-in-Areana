# Follow-up: both manual steps are now app-driven (same day)

Owner: "you should fix it by yourself in code … it all in app driven not
manually" — the two steps from `diagnosis.md` (§4 selectWindow-first, §5
pre-flight) are now code in `app/browser/uivision_autorun.py`. The external
runner keeps only the spawn + savelog wait (needs a real Firefox, untestable
here — RULE 8 keeps that out of the repo); every decision moved into the
tested gate:

```python
from app.browser.uivision_autorun import (autorun_query, launch_plan,
    macro_document, provision_macro)

provision_macro(HOME, "Python_XClick_Demo",
                macro_document("Python_XClick_Demo", "Arena", commands))
plan = launch_plan(HOME, AUTORUN_PAGE,
                   autorun_query("Python_XClick_Demo", SAVELOG_PATH))
if not plan["ok"]:
    log(plan["error"], "error")  # missing | invalid | savelog — never launch
    return
if plan["dropped"]:
    log(f"dropped ignored autorun param(s): {plan['dropped']}", "warn")
subprocess.Popen([FIREFOX_EXE, plan["url"]])  # encoded, no tab=, savelog dir exists
```

## New API (4 functions, all covered)

* `with_tab_reuse(pattern, commands)` — prepends
  `selectWindow | title=*<pattern>*` unless already first (idempotent, so
  re-provisioning never stacks duplicates); blank pattern leaves commands alone.
* `macro_document(name, pattern, commands)` — full runnable JSON (`Name` without
  folder/`.json`, `CreationDate`, tab-reusing `Commands`).
* `provision_macro(home, name, document)` — atomic write (tmp + replace, so the
  extension never reads a half-written file) to `<home>/macros/<name>.json`,
  creating dirs; returns the path.
* `launch_plan(home, page_path, query)` — the gate: refuses with
  `{"ok": False, "error": "macro missing|invalid: <path>"}` unless the on-disk
  macro pre-flights `ok`; drops unknown keys (`tab=`) and reports them in
  `"dropped"`; creates the savelog parent dir; returns the %-encoded URL.

## Quality recheck (RULE 16 / 18)

14 tests green; `verify_quality.py --changed-files` 0 fails; radon max CC 8
(`launch_plan` — every branch is a real decision: macro ok? savelog given? dir
writable? which keys dropped? — lowering it further would mean deleting a
decision or hiding a branch in a one-line helper, both forbidden by §16.2);
longest function 17 LOC; module 150 lines, in the 150–300 file sweet spot.
