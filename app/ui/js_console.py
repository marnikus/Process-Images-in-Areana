"""The page's JS console → stdout, with the source location.

QtWebEngine's default `javaScriptConsoleMessage` handler prints the message
only — an uncaught page error reached the owner's PowerShell as
`js: Uncaught TypeError: fn is not a function` with no file and no line,
undiagnosable (2026-09-25, reported at every startup). This module owns the
one handler `MainWindow` connects, so the diagnostic stays out of the
window class.
"""

__all__ = ["on_js_console"]


def on_js_console(message: str, level: int, line: int, source: str) -> None:
    """One JS console line: the message plus file:line when Qt names a source."""
    if source:
        print(f"js: {message} ({source}:{line})")
    else:
        print(f"js: {message}")
