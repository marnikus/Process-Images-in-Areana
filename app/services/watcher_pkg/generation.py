"""Watcher generation wait — when it starts, restarts and ends (live fix, 2026-09-27).

Owner report: "Generation timeout 677s limit 180s" was logged twice a second
forever — the generation had finished, and a NEW generation had already
started, yet the one wait never ended. Three rules now bound it:

* **Start** — a generating spinner is visible (`cdp_arena.is_generating`,
  scoped to a response header row) and no wait is running.
* **Restart** — a `[JOB-ID: …]` that was not on the page when the wait began
  appears: that is a new generation, so its clock starts from zero (one line).
* **End** — the spinner is gone (`handle_clear` resumes as before), or the
  timeout passes: ONE timeout line, overlay hidden, jobs resumed, and the wait
  stays quiet (`stale`) until the spinner disappears or a new JOB-ID appears.

Imports: `watcher_overlay` helpers only; the deps object is the handlers' own
(`HandlerDeps`) — no Qt, no CDP calls except through `cdp_probe`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Episode:
    """The generation wait the watcher is in (display + decision state only)."""

    jobs: frozenset = field(default_factory=frozenset)  # JOB-IDs on the page at (re)start
    stale: bool = False       # timed out while the spinner stays: quiet until it changes


def page_jobs(details) -> frozenset:
    """The JOB-IDs the generation probe saw on the page (none when it could not tell)."""
    jobs = details.get("jobs") if isinstance(details, dict) else None
    return frozenset(str(j) for j in jobs or () if j)


def fresh_jobs(episode: Episode, jobs: frozenset) -> frozenset:
    """JOB-IDs that appeared since the wait began — a new generation (none before a baseline)."""
    return jobs - episode.jobs if episode.jobs else frozenset()


class GenerationWatch:
    """One page's generation wait: start → (restart per new job) → clear or timeout."""

    def __init__(self, deps, log):
        self.config, self.state = deps.config, deps.state
        self.cdp_probe, self.job_ctrl = deps.cdp_probe, deps.job_ctrl
        self._deps, self._log = deps, log   # `log` binds late: `set_logger` swaps the sink
        self.episode = Episode()

    async def handle(self, cdp, is_gen: bool, details) -> bool:
        """True = this tick belongs to a generation (the loop skips the clear step)."""
        self.state.last_generation_details = details
        if not is_gen:
            self.episode = Episode()        # spinner gone: the next one is a new generation
            return False
        jobs = page_jobs(details)
        fresh = fresh_jobs(self.episode, jobs)
        if fresh or (self.state.waiting_kind != "generation" and not self.episode.stale):
            await self._start(cdp, details, jobs, fresh)
        elif not self.episode.stale:
            self.episode.jobs = self.episode.jobs or jobs
            await self._check_timeout(cdp)
        return True

    async def _start(self, cdp, details, jobs: frozenset, fresh: frozenset) -> None:
        from ..watcher_overlay import build_generation_msg
        restart = self.state.waiting_kind == "generation"
        self.episode = Episode(jobs=jobs)
        self.state.waiting_since, self.state.waiting_kind = time.time(), "generation"
        self.state.generation_waits += 1
        self.state.status = "waiting_generation"
        timeout = self.config.generation_timeout_sec
        if fresh:
            self._log(f"🔄 Watcher: new generation [{', '.join(sorted(fresh))}] — timer restarted "
                      f"(limit {timeout}s)", "info")
        else:
            self._log(f"⏳ Watcher: {build_generation_msg(details, timeout)}, pausing jobs", "warn")
        if not restart:
            await self.cdp_probe.show_overlay(cdp, "wait for finish generation", "generation", timeout)
            self.job_ctrl.pause()
        await self._deps.notifier()

    async def _check_timeout(self, cdp) -> None:
        """Past the limit: ONE line, stop waiting (overlay off, jobs resumed), stay quiet."""
        from ..watcher_overlay import is_generation_timeout
        if not is_generation_timeout(self.state.waiting_since, self.config.generation_timeout_sec):
            return
        elapsed = int(time.time() - (self.state.waiting_since or time.time()))
        self._log(f"⏰ Watcher: Generation timeout {elapsed}s limit {self.config.generation_timeout_sec}s "
                  f"— spinner still visible; stopped waiting, jobs resumed (a new generation "
                  f"or the spinner going away re-arms the watcher)", "error")
        await self.cdp_probe.hide_overlay(cdp)
        self.job_ctrl.resume()
        self.state.waiting_since, self.state.waiting_kind = None, None
        self.state.status = "watching"
        self.episode.stale = True
        await self._deps.notifier()
