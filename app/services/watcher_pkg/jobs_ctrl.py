"""Watcher job controller — pause/resume delegation, ≤50 LOC."""
from __future__ import annotations
from typing import Callable
from ..watcher_jobs import pause_jobs, resume_jobs

class WatcherJobCtrl:
    def __init__(self, config, job_runner_getter: Callable | None):
        self.config = config
        self._getter = job_runner_getter

    def set_getter(self, getter: Callable):
        self._getter = getter

    def pause(self):
        pause_jobs(self.config, self._getter)

    def resume(self):
        resume_jobs(self.config, self._getter)
