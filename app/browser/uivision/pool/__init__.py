"""Firefox tabs as pool workers (I-64, 2026-09-25).

One responsibility per file:
- `identity`: stable ids `{profileDirName}_tab{N}` across rescans (pure).
- `scan`: the checked, open profiles' matching tabs, read from session stores through an mtime cache.
- `locator`: the Ui.Vision "title + relative index" address of one tab (pure).
- `macro`: the per-run pool macro (pure).
- `run`: provision → scoped foreground → launch → savelog, reusing the framework's `Sequence`.

Imports go one way: this package reads `..tabs`, `..plan`, `..macro`, `..sequence`,
`..desktop` and `app.core`, and nothing imports Qt, the bridge or `app.services`.
The service lane (`app/services/uivision_job.py`) drives it with plain values.
"""
