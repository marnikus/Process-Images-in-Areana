"""The autorun page + launch URL — Ui.Vision's official command-line API.

`PAGE_HTML` is the extension's own `ui.vision.html` — the `noImport` variant of
`genHtml` in github.com/A9T9/RPA `src/common/convert_utils.js` (AGPL-3.0,
reproduced for interoperability; the docs call it "always the same page"). Its
inline script waits for the extension's content script (`data-kantu` on the
document element) and dispatches `kantuSaveAndRunMacro`; the content script
then reads the GET parameters and runs the named macro. The URL's `storage=`
parameter wins over the page's baked `storageMode`
(`src/ext/content_script/index.js`), and every parameter used here is on the
extension's `INVOKE_URL_PARAMS` whitelist — plus `autoclose`, which is
deliberately OFF the whitelist: the extension ignores unknown parameters, and
the page's own JS reads it.

Launch-URL parameters (ui.vision/rpa/docs — command line API): `macro` (name,
case-sensitive), `storage=browser|xfile`, `direct=1` (skip the confirm dialog),
`savelog=<full path>` (XModules write it straight to disk), `cmd_var1`–`cmd_var3`
(the macro reads them as `${!cmd_var1}`…`${!cmd_var3}`: the pause budget in ms,
the XClick target, the `selectWindow` tab target — the extension seeds exactly
`!CMD_VAR1..3`, so the macro never opens a URL), `closeRPA=1` (closes only the
extension's RPA panel, and only on success — verified in `genPlayerPlayCallback`),
`autoclose=<sec>` (the page's self-cleanup timer, the protected-tab rule's
backstop — see below). Values are percent-encoded; the extension decodes with
`decodeURIComponent`.

The page's contract (verified against the V9 source, 2026-09-24):
`kantuInvokeSuccess` fires when the macro is DISPATCHED, not when it finishes,
so the page never closes or navigates this tab at that moment — it only stops
re-dispatching. Closing happens in exactly two places, both scoped to THIS tab
(a script can only close the tab it runs in): the macro's pinned final cleanup
pair (`selectWindow` to `PAGE_TITLE_SELECTOR` → `TAB=CLOSE`) after the work,
and the `autoclose` backstop after the run's verdict window, for the error
paths the macro cannot reach (a missing tab stops the macro before its
cleanup). Either way, a tab that predated the run is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode

# The page's <title> — the macro's cleanup pair selects the autostart tab by
# this exact title, so the constant is the single owner (a test pins that the
# HTML carries it).
PAGE_TITLE = "Ui.Vision Autostart Page"
PAGE_TITLE_SELECTOR = f"title=*{PAGE_TITLE}*"

# How far past the run's own deadline the backstop may fire — the macro's
# cleanup has long completed in a healthy run (the timer is then moot).
BACKSTOP_MARGIN_SEC = 120

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
  /* Backstop cleanup (the protected-tab rule): after the run's verdict window
     has long passed, THIS tab removes itself if the macro never did (the
     macro's own final cleanup pair closes it after a successful run). A tab
     can only be closed by a script running in that tab — no other tab, user
     tab included, is ever reachable from here. */
  var backstopSec = parseInt(new URL(window.location.href).searchParams.get('autoclose') || 0, 10)
  var closeSelf = function () {
    if (document.title !== 'Ui.Vision Autostart Page') return
    try { window.close(); } catch (e) {}
    setTimeout(function () {
      try { window.location.href = 'about:blank'; } catch (e) {}
    }, 400)
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

      window.dispatchEvent(evt)
      var intervalTimer = setInterval(() => window.dispatchEvent(evt), 1000);

      if (window.location.protocol === 'file:') {
        /* kantuInvokeSuccess fires at DISPATCH, not at completion (verified
           in the extension source) — so it must NOT close or navigate this
           tab: the macro is now the extension's business, and its cleanup
           pair owns the closing. Only stop the re-dispatch interval. */
        var onInvokeSuccess = function () {
          clearTimeout(timer)
          clearTimeout(reloadTimer)
          clearInterval(intervalTimer)
          window.removeEventListener('kantuInvokeSuccess', onInvokeSuccess)
        }
        var timer = setTimeout(function () {
          alert('Error #203: It seems you need to turn on *Allow access to file URLs* for Kantu in your browser extension settings.')
        }, 8000)

        window.addEventListener('kantuInvokeSuccess', onInvokeSuccess)
      }
    } catch (e) {
      alert('Kantu Bookmarklet error: ' + e.toString());
    }
  }
  var reloadTimer = null
  var main = function () {
    if (isExtensionLoaded())  return run()

    var MAX_TRY   = 3
    var INTERVAL  = 1000
    var tuple     = increaseCountInUrl(MAX_TRY)

    if (tuple[0]) {
      return alert('Error #204: It seems Ui.Vision is not installed yet - or you need to turn on *Allow access to file URLs* for Ui.Vision in your browser extension settings.')
    } else {
      reloadTimer = setTimeout(function () {
        window.location.href = tuple[1]
      }, INTERVAL)
    }
  }

  if (backstopSec > 0) {
    setTimeout(closeSelf, backstopSec * 1000)
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
    """One launch: page, macro, result file, and the run's values (one argument
    object keeps `launch_url` at one parameter, RULE 16). Deliberately no URL:
    the macro reuses the run's tab and never opens a page (2026-09-23, owner
    rule). `backstop_sec` (last, so positional constructors survive) arms the
    page's self-cleanup timer; 0 = no timer."""

    page_path: str
    macro: str
    storage: str          # "xfile" (hard drive) or "browser" (HTML5 storage)
    log_path: str         # savelog= — a FULL path (XModules write it directly)
    pause_ms: int         # cmd_var1 — the macro's wait + confirmation-rect budget (ms)
    target: str           # cmd_var2 — the XClick locator
    close_rpa: bool = True
    tab: str = ""         # cmd_var3 — the selectWindow target from the owner's
                          # patterns; blank can only fail (E210), never open a page
    backstop_sec: int = 0  # autoclose= — page self-cleanup timer; 0 = no timer


def _query_params(spec: LaunchSpec) -> dict:
    """The official launch params; `autoclose` rides last, only when armed."""
    query = {
        "macro": spec.macro,
        "storage": spec.storage,
        "direct": "1",
        "savelog": str(Path(spec.log_path).resolve()),
        "cmd_var1": str(spec.pause_ms),
        "cmd_var2": spec.target,
        "cmd_var3": spec.tab,
        "closeRPA": "1" if spec.close_rpa else "0",
    }
    if spec.backstop_sec > 0:
        query["autoclose"] = str(spec.backstop_sec)   # off-whitelist: the extension ignores it
    return query


def launch_url(spec: LaunchSpec) -> str:
    """The `file:///…/ui.vision.html?…` URL that runs one macro with these values."""
    base = Path(spec.page_path).resolve().as_uri()
    return f"{base}?{urlencode(_query_params(spec), quote_via=quote)}"
