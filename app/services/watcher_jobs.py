"""Watcher job control — C9 split for RULE18.

Pure job pause/resume helpers with real responsibility names.
"""

from __future__ import annotations

from typing import Callable


def pause_jobs(config, job_runner_getter: Callable | None) -> None:
    if not config.auto_pause_jobs:
        return
    jr = job_runner_getter() if job_runner_getter else None
    if jr and hasattr(jr, "pause_run"):
        try:
            jr.pause_run()
        except Exception:
            pass


def resume_jobs(config, job_runner_getter: Callable | None) -> None:
    if not config.auto_pause_jobs:
        return
    jr = job_runner_getter() if job_runner_getter else None
    if jr and hasattr(jr, "resume_run"):
        try:
            jr.resume_run()
        except Exception:
            pass
