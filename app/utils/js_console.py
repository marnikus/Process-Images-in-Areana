"""Page-console → app-log line: `js: <message> (<source>:<line>)`.

2026-09-25: an uncaught page error reached the terminal as a bare
`js: fn is not a function` with no location — untraceable. The page's
console (via `_ConsolePage` in `app/ui/main_window.py`) flows through
`js_console_line` so the NEXT error names the file that threw (RULE 4).
"""

# QWebEnginePage.JavaScriptConsoleMessageLevel → logger level name.
_LEVELS = {0: "info", 1: "warning", 2: "error"}


def js_console_line(level, message, location) -> tuple:
    """(logger level, line) for one console message — `location` is `src:line`."""
    key = getattr(level, "value", level)
    lvl = _LEVELS.get(key, "info") if isinstance(key, int) else "info"
    return lvl, f"js: {message} ({location})"
