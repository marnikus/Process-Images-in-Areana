"""Publish aggregate watcher state and a compact per-page summary."""
from __future__ import annotations

class WatcherStatePublisher:
    """Build the stable public aggregate from live and retired page counters."""

    def __init__(self, state, totals):
        self.state, self.totals = state, totals

    def publish(self, pages: list) -> None:
        self._publish_waiting(pages)
        self._publish_activity(pages)
        self._publish_counts(pages)
        self.state.page_states = [self._page_summary(page) for page in pages]

    def _publish_waiting(self, pages: list) -> None:
        kinds = {page.state.waiting_kind for page in pages if page.state.waiting_kind}
        starts = [page.state.waiting_since for page in pages if page.state.waiting_since]
        self.state.status = self._aggregate_status(kinds)
        self.state.waiting_kind = next(iter(kinds)) if len(kinds) == 1 else ("mixed" if kinds else None)
        self.state.waiting_since = min(starts) if starts else None

    def _publish_activity(self, pages: list) -> None:
        self.state.last_captcha_detected = any(page.state.last_captcha_detected for page in pages)
        self.state.last_generation_details = next(
            (page.state.last_generation_details for page in reversed(pages)
             if page.state.last_generation_details), {})

    def _publish_counts(self, pages: list) -> None:
        self.state.generation_waits = self.totals["generation_waits"] + sum(
            page.state.generation_waits for page in pages)
        self.state.captcha_waits = self.totals["captcha_waits"] + sum(
            page.state.captcha_waits for page in pages)

    @staticmethod
    def _aggregate_status(kinds: set[str]) -> str:
        if "captcha" in kinds:
            return "waiting_captcha"
        return "waiting_generation" if kinds else "watching"

    @staticmethod
    def _page_summary(page) -> dict:
        return {"tab_id": page.target.tab_id, "label": page.target.label,
                "status": page.state.status, "waiting_kind": page.state.waiting_kind,
                "waiting_since": page.state.waiting_since, "available": page.available}


