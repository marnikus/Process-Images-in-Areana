"""Firefox automation through the Ui.Vision RPA extension (I-63).

Firefox stays a NORMAL, visible browser: no debug port, no geckodriver, no
Selenium/Playwright/Puppeteer. The signed Ui.Vision extension (addons.mozilla.
org/firefox/addon/rpa) runs a macro from its official command-line API — the
app provisions the macro + autorun page, starts Firefox on the `file:///` URL,
and polls the savelog file for the `Status=OK` / `Status=Error:` verdict.
Desktop steps are XClick/XType (native OS input, `isTrusted: true`) through the
XModules — never DOM `click` (owner's critical rule, guarded in `macro.py`).

Modules: `macro` (the JSON builder), `autorun` (the vendored page + launch
URL), `paths` (XModule home + runtime dir), `launch` (binary + argv),
`desktop` (window pattern-match + foreground), `logread` (the completion
contract), `runner` (one run, seams injected). The UI lives in
`app/ui/panels/firefox_auto.py` + `js/panels/firefox-auto.js`.
"""

from .autorun import LaunchSpec, launch_url, write_page
from .logread import LogResult, parse_status, poll_log
from .macro import DEFAULT_MACRO_NAME, build_macro, to_json, validate_macro_name
from .runner import RunResult, RunSeams, RunSpec, run_test

__all__ = [
    "DEFAULT_MACRO_NAME", "LaunchSpec", "LogResult", "RunResult", "RunSeams", "RunSpec",
    "build_macro", "launch_url", "parse_status", "poll_log", "run_test", "to_json",
    "validate_macro_name", "write_page",
]
