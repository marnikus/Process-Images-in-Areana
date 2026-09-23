# Firefox automation via the Ui.Vision RPA extension — design (2026-09-22)

Owner request (abridged): *remove the Firefox and Edge debugger/CDP approach; leave only
Chrome as it was before. Firefox stays a normal browser — automation runs through the
Ui.Vision RPA extension + native OS input. Create a new window “Firefox auto with
Extension”. Build the simple framework test now (macro `Python_XClick_Demo`: open URL →
pause → XClick “New Chat” → echo done; Python launches it via subprocess and polls the
log); it will later be replaced with the same functionality Chrome has. Never use
`--start-debugger-server`, geckodriver, Selenium, Playwright or Puppeteer; always XClick
(native, `isTrusted: true`), never DOM `click`; Firefox must be visible and foreground.*

## 1. Research — the official Ui.Vision framework (measured, with sources)

All facts below were read from the official docs and the open-source extension itself
(`github.com/A9T9/RPA`, AGPL — the command-line contract was verified in its source).

* **Command Line API** (`ui.vision/rpa/docs/#cmd`): the browser is started (or an already
  running instance is asked) to open the **autorun page** `ui.vision.html` — exported once
  from the extension’s *Settings → API* tab, “always the same page”. GET parameters on its
  `file:///` URL drive everything:
  `macro=NAME` (case-sensitive), `direct=1` (skip the confirm dialog), `storage=browser|xfile`
  (macro lives in HTML5 storage or on the hard drive), `savelog=FILE`, `cmd_var1..cmd_var10`
  (readable in the macro as `${!cmd_var1}`…), `closeRPA=0|1` (default 1), `closeBrowser=0|1`
  (default 0), `folder=`, `nodisplay=1`, `continueInLastUsedTab=0|1`.
  Official Firefox example from the docs:
  `"C:\Program Files\Mozilla Firefox\firefox.exe" "file:///D:/test/ui.vision.html?macro=demoframes&cmd_var1=hello%21world&…&direct=1&savelog=logfirefox.txt"`.
* **Autorun page mechanism** (`src/common/convert_utils.js generateEmptyHtml`,
  `src/ext/content_script/index.js`): the page’s inline script waits for the extension’s
  content script (`documentElement[data-kantu]`), then dispatches `kantuSaveAndRunMacro`
  every second; the content script reads the query (`storage` wins over the page’s baked
  `storageMode`, fallback `browser`) and asks the background to run the named macro.
  File-URL access must be allowed for the add-on (the page alerts Error #203/#204 otherwise).
  The exact page template is vendored into this repo (`app/browser/uivision/autorun.py`)
  so the app provisions it itself — no manual export step.
* **Result reporting** (`src/index.js` `genPlayerPlayCallback`): with `savelog=`, when the
  macro finishes the extension writes one text file whose **first line** is
  `Status=OK` or `Status=Error: <message>`, second line `###`, then the run log.
  A `savelog` value containing `/` or `\` is a full path and (V8.1.3+, **XModules
  installed**) is written directly to disk — faster and more reliable than the download
  fallback. So Python polls one file: exists → parse first line. This is exactly the
  official scripts’ contract (`command-line/python/run-and-check-result.py`,
  `command-line/powershell/*.ps1`: poll for the file, `Status=OK` check, timeout branch).
* **Macro JSON format** (`convert_utils.toJSONString`): `{"Name", "CreationDate",
  "Commands": [{"Command", "Target", "Value", "Description"}]}`. Hard-drive storage keeps
  it as `<home>/macros/<Name>.json` (folders = subpaths). `<home>` is the XModule home
  folder (extension *Settings → XModule*), default `<User Desktop>/uivision`
  (`src/services/xmodules/xfile.ts initConfig`).
* **XClick** (`ui.vision/rpa/docs/xclick`, Desktop Automation XModule): sends **native OS
  mouse events**; locators are an element locator (`xpath=…`, `id=…` — the extension runs
  `getBoundingClientRect()` and clicks the centre natively), an image (`img.png@@0.8`),
  OCR text (`XClickText|*New Chat*`), or raw `x,y`. “For desktop automation you must use
  XClick” — DOM `click` is JS-level (`isTrusted:false`), XClick is real input
  (`isTrusted:true`). Requires the XModules/Desktop App; the browser must be unlocked
  and, for native input to land, **foreground** — the official demo macros pair X commands
  with `bringBrowserToForeground` (`src/config/preinstall_macros.js` DemoXClick/DemoXType).
* **Firefox add-on**: signed, on AMO — `addons.mozilla.org/en-US/firefox/addon/rpa`
  (V10.0.276 at research time). XModules/Desktop App installer: `ui.vision/rpa/x/download`
  (V1) / forum pin (V2). No geckodriver, Selenium, Playwright or Puppeteer anywhere —
  the extension runs inside the user’s normal Firefox.

## 2. Architecture

```
Python app (new window “Firefox auto with Extension”)
  ├─ finds Firefox OS windows whose title matches the user pattern (ctypes; foreground them)
  ├─ provisions: macro JSON → <XModule home>/macros/Python_XClick_Demo.json
  │              autorun page → config/uivision/ui.vision.html   (both idempotent)
  ├─ launches:  firefox.exe "file:///…/ui.vision.html?macro=…&storage=xfile&direct=1
  │              &savelog=<config/uivision/logs/run-<ts>.txt>&cmd_var1=<url>&cmd_var2=<target>&closeRPA=1"
  │              (no -no-remote, no debugger flag → the RUNNING Firefox opens one tab)
  ├─ Ui.Vision macro: open ${!cmd_var1} → bringBrowserToForeground → pause
  │              → XClick ${!cmd_var2} (native OS click) → echo done
  └─ polls the savelog file (stop-honoured, bounded) → Status=OK / Status=Error / timeout
```

* **D-1 — Chrome untouched.** The CDP pipeline, pool, reconciler and Settings block keep
  working exactly as before; the browser registry (`app/browser/browsers.py`) shrinks to
  the one Chrome row (still data-driven: binaries, dir flag, launch command, capabilities).
* **D-2 — the debugger approach is deleted, not disabled.** `app/browser/rdp/`,
  `bidi.py`, `attached.py`, `endpoints.py`, `protocols.py`, `firefox_profiles.py`,
  `stealth.py`, `cdp/remote.py` and the Edge registry row are removed; `CDPClient` loses
  the RemoteMixin (plain CDP again); round-11 machinery that only existed for the parked
  Firefox socket goes with it (`UrlRow.browser`, `RemovalSpec.unconfirmed`,
  `LiveDeps.retry_browser`, `sync_pool_presence(unconfirmed)`), and `UrlRow.from_dict`
  becomes the tolerant dict→row funnel so old `urls.json` files that still carry a
  `browser` key load fine (RULE 13). A source-lock test bans the debugger vocabulary
  (`--start-debugger-server`, `rdp`, `bidi`, `geckodriver`, …) from production code.
* **D-3 — one new package** `app/browser/uivision/` (browser layer, no Qt): `macro.py`
  (the JSON builder — XClick-only, `click` is never emitted), `autorun.py` (the vendored
  page + launch-URL builder), `paths.py` (XModule home, macro path, runtime dir),
  `launch.py` (binary resolution, argv, subprocess), `desktop.py` (window
  pattern-match/foreground via `app/utils/win_find` + `win_popup`), `logread.py`
  (poll + status parse; empty/broken/timeout distinct, RULE 4), `runner.py` (one test run,
  reports every step through a callback, RULE 2/5, stop predicate RULE 7).
* **D-4 — the window is the 18th registered window** (RULE 10 / I-51): one row in
  `core/window_catalog.WINDOWS` (`firefox_auto`, “Firefox auto with Extension”),
  `GRID_VERSION` 7 → 8, same-line appends in `constants.js` / `store.js` /
  `_PANEL_INITS` / `index.html`, panel `js/panels/firefox-auto.js`
  (`window.FirefoxAutoPanel`), Python panel `app/ui/panels/firefox_auto.py` with **4 new
  slots** (`get/save/run/stop_firefox_auto*`) and one new signal `firefox_auto_updated`
  (slot surface 137 → 141, frozen set updated deliberately).
* **D-5 — the pattern field is the control element**: Python matches **OS window titles**
  (a normal browser offers nothing else — no tab API without a debug channel). Matched
  Firefox windows are raised to the foreground before launch; the macro repeats it
  in-page with `bringBrowserToForeground`. Empty match is reported distinctly from a
  failed launch (RULE 4) but does not block the run (the macro’s `open` still navigates).
* **D-6 — settings live in one dict** `firefox_auto` in `config/session.json`
  (`pattern`, `url`, `target`, `macro`, `storage` (`xfile` default | `browser`), `home`,
  `binary`, `timeout_sec` 15…600 default 90, `pause_ms` 500…30000 default 3000),
  validated/clamped on save and on load; runtime files under `config/uivision/`
  (git-ignored like all of `config/`, I-43). The window-title pattern is a different
  decision from the URL-row `url_pattern` (different browser, different mechanism) —
  no RULE 10 duplication.
* **D-7 — `storage=browser` fallback**: without the FileAccess capability the macro must
  be imported once through the extension UI; the app still writes the JSON (import
  artefact) and says so. `savelog` then falls back to the browser download folder — the
  window shows which log path applies.

## 3. Removal inventory

Delete: `app/browser/rdp/` (9 files), `bidi.py`, `attached.py`, `endpoints.py`,
`protocols.py`, `firefox_profiles.py`, `stealth.py`, `cdp/remote.py`;
tests `test_rdp_{wire,actors,connection,client,profile,session}.py`, `test_bidi.py`,
`test_firefox_cue.py`, `test_partial_pass.py`, `test_pool_rdp_join.py`, `test_attached.py`,
`test_browser_scan.py`, `tests/fakes/rdp_stub_server.py`, `js/test_browser_one_pass.mjs`;
conftest `_fast_firefox_allow_wait`; main_window `_drop_browser_sockets` RDP branch;
index.html prefs/stealth/Prepare-Profile markup; browser-connection.js prepare/prefs code.

Shrink: `browsers.py` (Chrome-only registry + `ScanNote`/`scan_line` move in),
`cdp/client.py` (no RemoteMixin), `cdp/dom.py` (no capability gate), `browser_tabs.py`
(one Chrome listing seam, `ScanUnavailable` moves to `live/reconcile.py`),
`cdp_tools.py` (no prefs/prepare/protocol branches), `panels/page_pool.py`
(no handle grammar — host/port/tab from the ws URL), `reconcile.py` / `url_policy.py` /
`auto_connect.py` (round-11 machinery), `models.py` (`UrlRow.browser` → `from_dict`),
`app_settings.py` (tolerant load). Rewrite: `test_browser_profiles.py`,
`test_browser_endpoints.py` (fold into profiles), `test_browser_config_slots.py`,
`js/test_browser_selector.mjs`; touch every test that pinned removed behaviour.

## 4. Tests (RULE 8 — real things, RED where possible)

* `test_uivision_macro.py` — JSON shape, `${!cmd_var1/2}` wiring, **no DOM `click` ever**
  (positive control: XClick present), name sanitisation (path traversal refused).
* `test_uivision_autorun.py` — vendored page carries the real contract markers
  (`kantuSaveAndRunMacro`, `data-kantu`), launch URL has every documented parameter,
  values URL-encoded, `file:///` grammar.
* `test_uivision_launch.py` — argv never contains a debugger/automation flag
  (`--start-debugger-server`, `--remote-debugging-port`, `-no-remote`, geckodriver),
  binary defaults per OS, real `subprocess` seam faked at Popen.
* `test_uivision_desktop.py` — pure title/process matching over injected window lists;
  foreground count; non-Windows no-op is honest (RULE 4).
* `test_uivision_logread.py` — real files: OK / Error / timeout / stopped / partial;
  first-line contract; stop honoured inside the poll (RULE 7).
* `test_uivision_runner.py` — end-to-end with fake launcher + real log writer: step
  reports in order, outcomes, files provisioned on disk.
* `test_firefox_auto_panel.py` — the 4 slots against the real mixin host: round-trip,
  clamps, run schedules + emits, stop flag; `test_no_firefox_debugger.py` — source lock.
* Window contract: `test_window_catalog.py` (18, v8, migration), `test_bridge_slots.py`
  (141 + packing), `test_ui_wiring.py`, `js/test_firefox_auto_panel.mjs` (whole-page
  boot: mount, init, Save/Run reach the slots), rewritten `js/test_browser_selector.mjs`.

## 5. Docs (RULE 17)

This design → archive (this file). `SYSTEM_OF_RECORD.md`: I-62 rewritten (Chrome-only
registry + Firefox-over-extension, rounds 8–11 superseded), §2 row 19 and §11 gain the
18th window, §7 module table updated, history pointer added, footer dated.
`docs/README.md` map updated. No AGENT_RULES change (rule numbers are stable).

## 6. Deviations / notes

* The owner’s sketch said `firefox -new-tab ui.vision.html?macro=…`; the official contract
  is `firefox.exe "file:///…/ui.vision.html?macro=…"` (a running instance opens the URL in
  a new tab by itself — `-new-tab` is not a Firefox flag). Implemented per the docs.
* `closeBrowser` stays 0 (default): the user’s Firefox is theirs — the run must never
  close the browser (critical rule: normal, visible browser).
* On timeout the official script kills the launched process; we do **not** kill Firefox
  (it is the user’s session and, with a running instance, the launched process already
  exited after handing the URL over). The timeout is reported honestly with the log path.
* XClick coordinates are screen coordinates — a locked desktop or a background Firefox
  cannot receive native input (documented in the window’s help lines).
