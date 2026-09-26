"""One job's step flow and output, confirmed step by step (2026-09-26).

The Chrome block runner (`services.single_job_runner`) uses this package for
everything that proves a step happened. The Firefox lane shares only the save
path (`image_output`).

* `ctx` — `JobCtx` (one image run through one tab), `emit_action`, `report`.
* `steps` — the step tracker: milestones, confirmations, the one
  "🧭 Steps" summary line, and the final / recycle verdict.
* `confirm` — page confirmations: clean start, composer ready (image + prompt),
  sent (new job started), and saved on disk.
* `output` — VALIDATE / SAVE handlers; a save failure keeps its reason.
* `image_output` — the `_AI` name beside the source, plus an atomic write that
  retries transient Windows sharing errors. Both lanes use it.

Design: docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md.
Layer: services — imports browser, core and utils; never Qt or panels. Nothing
is re-exported here: import the submodule you need, so `single_job_runner` stays
the only module that wires the whole package together.
"""
