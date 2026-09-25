"""The autorun page + launch URL — Ui.Vision's official command-line API.

`PAGE_HTML` is the extension's own `ui.vision.html` — the `noImport` variant of
`genHtml` in github.com/A9T9/RPA `src/common/convert_utils.js` (AGPL-3.0,
reproduced for interoperability; the docs call it "always the same page"). Its
inline script waits for the extension's content script (`data-kantu` on the
document element) and dispatches `kantuSaveAndRunMacro`; the content script
then reads the GET parameters and runs the named macro. The URL's `storage=`
parameter wins over the page's baked `storageMode`
(`src/ext/content_script/index.js`), and every parameter used here is on the
extension's `INVOKE_URL_PARAMS` whitelist.

Launch-URL parameters (ui.vision/rpa/docs — command line API): `macro` (name,
case-sensitive), `storage=browser|xfile`, `direct=1` (skip the confirm dialog),
`savelog=<full path>` (XModules write it straight to disk), `cmd_var1`–`cmd_var3`
(the macro reads them as `${!cmd_var1}`…`${!cmd_var3}`: the pause budget in ms,
the XClick target, the `selectWindow` tab target — the extension seeds exactly
`!CMD_VAR1..3`, so the macro never opens a URL), `closeRPA=1`, and
`continueInLastUsedTab=0` — the owner's protected-tab rule (2026-09-24): the
extension defaults it to `'1'` (`decorateOptions`) and then closes the tab
about to play when it differs from the last-used one
(`PANEL_CLOSE_CURRENT_TAB_AND_SWITCH_TO_LAST_PLAYED`) — i.e. the USER'S
prepared tab dies on a first run. `'0'` (parsed by `parseBoolLike`) disables
that close; the param is on the `INVOKE_URL_PARAMS` whitelist. Values are
percent-encoded; the extension decodes with `decodeURIComponent`.
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
        var onInvokeSuccess = function () {
          clearTimeout(timer)
          clearTimeout(reloadTimer)
          clearInterval(intervalTimer)
          window.removeEventListener('kantuInvokeSuccess', onInvokeSuccess)
          /* Close THIS autostart tab once the extension has accepted the run
             (kantuInvokeSuccess fires at invoke — the macro is handed to its
             tab then, not when it finishes). window.close() works for tabs the
             command line opened; for user-opened tabs it is a no-op — the tab
             stays but navigates to about:blank so it is visually gone. Only
             this spawned tab is ever touched: the run's working tabs are
             protected (continueInLastUsedTab=0 keeps them, too). */
          setTimeout(function () {
            try { window.close(); } catch (e) {}
            try { window.location.href = 'about:blank'; } catch (e) {}
          }, 500)
        }
        var timer = setTimeout(function () {
          alert('Error #203: It seems you need to turn on *Allow access to file URLs* for Kantu in your browser extension settings.')
        }, 8000)

        window.addEventListener('kantuInvokeSuccess', onInvokeSuccess)

        /* Also close on macro error — the savelog already carries the verdict. */
        var onInvokeError = function () {
          clearTimeout(timer)
          clearTimeout(reloadTimer)
          clearInterval(intervalTimer)
          window.removeEventListener('kantuInvokeError', onInvokeError)
          setTimeout(function () {
            try { window.close(); } catch (e) {}
            try { window.location.href = 'about:blank'; } catch (e) {}
          }, 500)
        }
        window.addEventListener('kantuInvokeError', onInvokeError)
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
    """The `file:///…/ui.vision.html?…` URL that runs one macro with these values.

    `continueInLastUsedTab=0` = protected tabs (bug #1): the extension's
    default '1' closes the not-last-used tab about to play — the user's own.
    """
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
        "continueInLastUsedTab": "0",
    }, quote_via=quote)
    return f"{base}?{query}"
