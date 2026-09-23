# Drop-in runner: nothing manual left (same day, second follow-up)

Owner (again): both steps must be app-driven, not manual. The external script
was never in this repo (checked every branch + history), so the repo now owns
the whole flow as `app/browser/uivision_runner.py :: run_macro()` — the only
remaining manual act is pointing the local script at it (one import), because
that script's text is not visible from here:

```python
from app.browser.uivision_runner import UivisionRun, RunHooks, run_macro

result = run_macro(UivisionRun(
    home=r"C:\Users\marni\Desktop\uivision",
    page_path=r"C:\Users\marni\Desktop\uivision\ui.vision.html",
    macro="Python_XClick_Demo", pattern="Arena",
    commands=[{"Command": "XClick", "Target": "img.png", "Value": ""}],
    firefox_exe=r"C:\Program Files\Mozilla Firefox\firefox.exe",
    savelog=r"C:\Users\marni\Desktop\uivision\logs\run.txt",
    timeout_sec=90),
    RunHooks(report=my_log))  # spawn/sleep default to the real ones
if not result["ok"]:
    my_log(f'{result["outcome"]}: {result["detail"]}', "error")
```

What `run_macro` does, in order: provision with `selectWindow|title=*Arena*`
first (idempotent) → refuse unless the on-disk macro pre-flights `ok` →
spawn Firefox with the %-encoded URL (`tab=` cannot be sent — the query is
built inside) → poll the savelog to the deadline. Outcomes
(`success|macro-error|timeout|refused`, RULE 4) each carry `detail` + `savelog`;
`os error 2` surfaces as `refused: cannot start <exe>`. Blank savelog
auto-defaults to `./uivision-logs/<macro>-<stamp>.txt`.

## Quality recheck (RULE 16 / 18)

7 runner tests (spawn + sleep faked, real wait logic — RULE 8) + 14 autorun
tests green; `verify_quality.py --changed-files` 0 fails; radon max CC 6;
`run_macro` 20 LOC / 2 params; module 138 lines (leaf, under the 150–300 band).
