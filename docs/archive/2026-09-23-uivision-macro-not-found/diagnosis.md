# Ui.Vision "Can't find macro with name Python_XClick_Demo" — diagnosis (2026-09-23)

Log excerpt that started this: `provision: macro written:
C:\Users\marni\Desktop\uivision\macros\Python_XClick_Demo.json`, then
`[error] Can't find macro with name "Python_XClick_Demo"` + savelog timeout —
**still failing after the Home directory was changed** to
`C:\Users\marni\Desktop\uivision`.

## Ranked causes (check in this order)

### 1. Home changed in the wrong Firefox profile (most likely)
Extension settings — Home directory AND storage mode — are stored **per Firefox
profile**. The machine has **10 profiles**; the launcher spawns Firefox without
`-P`, so it opens the default profile, which still has the old
`D:\Google Drive\...` Home or browser-storage mode.
**Decisive check:** in the SAME profile the launcher opens, open Ui.Vision →
macros panel in hard-drive mode (disk icon on the tab). If
`Python_XClick_Demo` is NOT listed there, Home/mode is wrong in THAT profile —
full stop. Fix: set Home + hard-drive mode in that profile (or launch with
`-P <profile>` / `--profile <path>` for the profile you already fixed), then
restart ALL Firefox instances.

### 2. Storage-mode mismatch
The autorun URL says `storage=xfile` (hard drive). If the launch profile is
still in browser-storage mode, the lookup goes to the wrong store. The
hard-drive icon must be visible on the Ui.Vision tabs.

### 3. Autorun URL not URL-encoded (explains the savelog timeout by itself)
"The command line is actually a URL" (ulrich, forum.ui.vision/t/5481) — spaces
must be `%20`. Both the page path (`D:\Google Drive\...`, raw spaces in a
`file:///` URL) and the savelog value (`savelog=D:\Google Drive\...\run-....txt`)
break when sent raw: the page may not load and the query truncates at the first
space, so no savelog is ever written → timeout even if the macro were found.
Fix: `app/browser/uivision_autorun.py` (`page_file_url`, `build_autorun_url` —
spaces → `%20`, never `+`, never raw), or move the autorun page + logs to a
space-free path. Also: savelog's parent `logs\` dir must already exist, and a
Google-Drive-synced folder can lock files mid-write.

### 4. `tab=title=*Arena*` is not a real parameter
Documented autorun keys (ui.vision/rpa/docs, Command Line API): `macro`,
`folder`, `storage`, `savelog`, `closeRPA`, `closeBrowser`, `direct`,
`cmd_var1..3`. `tab=` is silently ignored — harmless for "can't find macro",
but tab reuse must be the macro's first command:
`selectWindow | title=*Arena*` (ui.vision/rpa/docs/selenium-ide/selectwindow).
`unknown_query_keys()` flags these; `select_window_command()` builds the command.

### 5. Macro file not (yet) visible to the extension
Hard-drive mode reads `<Home>/macros/*.json`; the file must be valid Ui.Vision
JSON (dict with a `Commands` list). A newly written file needs an extension
panel refresh / browser restart before it is listed. `macro_status()` pre-flights
this (`ok | missing | invalid`) — never launch on anything but `ok`.

### 6. `os error 2` (system cannot find the file specified)
The launcher spawned a binary/path that does not exist — verify `firefox.exe`
path and that every directory in the autorun/savelog paths exists.

### 7. "Windows matching the pattern: 0" (app-side, separate bug)
Tabs match `Arena` but the window check returns 0: the check compares the wrong
strings (exact match, or raw `&amp;` session titles vs `&` OS titles like
`... — Mozilla Firefox`). Fix: `window_title_matches()` — unescape,
case-insensitive substring on both sides.

## Code landed with this doc
`app/browser/uivision_autorun.py` (8 pure helpers) + `tests/test_uivision_autorun.py`
(9 tests). RULE 16: longest function 12 LOC, ≤3 params, radon CC ≤5, nesting ≤1.
