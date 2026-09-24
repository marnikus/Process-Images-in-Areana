"""The autorun page + launch URL — Ui.Vision's official command-line API.

`PAGE_HTML` is based on the extension's own `ui.vision.html` — the `noImport`
variant of `genHtml` in github.com/A9T9/RPA `src/common/convert_utils.js`
(AGPL-3.0, reproduced for interoperability; the docs call it "always the same
page"). Its inline script waits for the extension's content script (`data-kantu`
on the document element) and dispatches `kantuSaveAndRunMacro`; the content
script then reads the GET parameters and runs the named macro. The URL's
`storage=` parameter wins over the page's baked `storageMode`
(`src/ext/content_script/index.js`), and every parameter used here is on the
extension's `INVOKE_URL_PARAMS` whitelist.

Deltas from the vendored page (2026-09-24, owner batch-automation fix — record
`docs/archive/2026-09-24-uivision-first-run-and-helper-cleanup/design.md`):
the macro event is dispatched **once** (`data-kantu` already proves the content
script's listener is live; the vendored 1 s `setInterval` re-dispatch ran the
macro repeatedly while it was still executing), the tab **closes itself** on
`kantuInvokeSuccess` (+ a 120 s failsafe) so no helper tab survives the run,
and the blocking `alert()`s became an in-page banner + title + delayed
self-close (a modal must never wait for a human mid-batch).

Launch-URL parameters (ui.vision/rpa/docs — command line API): `macro` (name,
case-sensitive), `storage=browser|xfile`, `direct=1` (skip the confirm dialog),
`savelog=<full path>` (XModules write it straight to disk), `cmd_var1`–`cmd_var3`
(the macro reads them as `${!cmd_var1}`…`${!cmd_var3}`: the pause budget in ms,
the XClick target, the `selectWindow` tab target — the extension seeds exactly
`!CMD_VAR1..3`, so the macro never opens a URL), `closeRPA=1` (the extension
closes its RPA panel when the run ends). Values are percent-encoded; the
extension decodes with `decodeURIComponent`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode

PAGE_HTML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head profile="http://selenium-ide.openqa.org/profiles/test-case">
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />

<title>Ui.Vision Autostart Page</title>
</head>
<body>
<h3>Starting Browser and Ui.Vision...</h3>
<script>
(function() {
  var isExtensionLoaded = function () {
    const $root = document.documentElement
    return !!$root && !!$root.getAttribute('data-kantu')
  }
  var increaseCountInUrl = function (max) {
    var url   = new URL(window.location.href)
    var count = 1 + (parseInt(url.searchParams.get('reload') || 0))

    url.searchParams.set('reload', count)
    var nextUrl = url.toString()

    var shouldStop = count > max
    return [shouldStop, !shouldStop ? nextUrl : null]
  }
  var banner = function (text) {
    try {
      document.title = text
      var el = document.createElement('div')
      el.setAttribute('style',
        'position:fixed;top:0;left:0;right:0;z-index:2147483647;' +
        'background:#b00020;color:#fff;font:14px sans-serif;padding:10px 14px;')
      el.textContent = text
      ;(document.body || document.documentElement).appendChild(el)
    } catch (e) {}
  }
  var closeTab = function () {
    try { window.open('', '_self'); window.close(); } catch (e) {}
    setTimeout(function () { try { window.close(); } catch (e) {} }, 600)
  }
  var run = function () {
    try {
      var evt = new CustomEvent('kantuSaveAndRunMacro', {
        detail: {
          html: document.documentElement.outerHTML,
          noImport: true,
          storageMode: 'browser'
        }
      })

      // ONE dispatch: data-kantu (checked in main) is set by the extension's own
      // content script, so its listener is live. The vendored page re-dispatched
      // every second and ran the macro again while it was still executing.
      window.dispatchEvent(evt)

      if (window.location.protocol === 'file:') {
        var failsafe = setTimeout(closeTab, 120000)   // never linger, event or not
        var warn = setTimeout(function () {
          banner('Error #203: it seems you need to turn on *Allow access to file URLs* for Kantu in your browser extension settings.')
        }, 8000)
        var onInvokeSuccess = function () {
          clearTimeout(failsafe)
          clearTimeout(warn)
          setTimeout(closeTab, 2000)                  // let the run + savelog settle
        }
        window.addEventListener('kantuInvokeSuccess', onInvokeSuccess)
      } else {
        setTimeout(closeTab, 30000)
      }
    } catch (e) {
      banner('Kantu Bookmarklet error: ' + e.toString())
      setTimeout(closeTab, 8000)
    }
  }
  var reloadTimer = null
  var main = function () {
    if (isExtensionLoaded())  return run()

    var MAX_TRY   = 3
    var INTERVAL  = 1000
    var tuple     = increaseCountInUrl(MAX_TRY)

    if (tuple[0]) {
      banner('Error #204: it seems Ui.Vision is not installed yet - or you need to turn on *Allow access to file URLs* for Ui.Vision in your browser extension settings.')
      setTimeout(closeTab, 8000)
    } else {
      reloadTimer = setTimeout(function () {
        window.location.href = tuple[1]
      }, INTERVAL)
    }
  }

  setTimeout(main, 500)
})();
</script>
</body>
</html>
"""


def write_page(path) -> Path:
    """Write the autorun page (idempotent: rewritten only when the content differs)."""
    page = Path(path)
    page.parent.mkdir(parents=True, exist_ok=True)
    if not page.exists() or page.read_text(encoding="utf-8") != PAGE_HTML:
        page.write_text(PAGE_HTML, encoding="utf-8")
    return page


@dataclass(frozen=True)
class LaunchSpec:
    """One launch: the page, the macro, where the result lands, and the run's values.

    A single argument object keeps `launch_url` at one parameter (RULE 16).
    There is deliberately no URL here: the macro reuses the run's tab and never
    opens a page (2026-09-23, owner rule).
    """

    page_path: str
    macro: str
    storage: str          # "xfile" (hard drive) or "browser" (HTML5 storage)
    log_path: str         # savelog= — a FULL path (XModules write it directly)
    pause_ms: int         # cmd_var1 — the macro's wait + confirmation-rect budget (ms)
    target: str           # cmd_var2 — the XClick locator
    close_rpa: bool = True
    tab: str = ""         # cmd_var3 — the selectWindow target (`title=*…*`); a blank
                          # one can only fail (E207) — it can never open a page


def launch_url(spec: LaunchSpec) -> str:
    """The `file:///…/ui.vision.html?…` URL that runs one macro with these values."""
    base = Path(spec.page_path).resolve().as_uri()
    query = urlencode({
        "macro": spec.macro,
        "storage": spec.storage,
        "direct": "1",
        "savelog": str(Path(spec.log_path).resolve()),
        "cmd_var1": str(spec.pause_ms),
        "cmd_var2": spec.target,
        "cmd_var3": spec.tab,
        "closeRPA": "1" if spec.close_rpa else "0",
    }, quote_via=quote)
    return f"{base}?{query}"
