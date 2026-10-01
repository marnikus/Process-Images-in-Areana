"""URL-list inline edit slots + reset-all cooldown slot (2026-10-01).

RULE 8: real PagePool + real persistence helpers; only the bridge host/log/signal
edges are faked. The edits must follow the worker/job-count state, persist, and
never fan out to unrelated rows.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.models import UrlRow
from app.persistence.config_manager import ConfigManager
from app.persistence.cooldown_store import load_stats
from app.services.run_state import cooldowns_path
from app.services.run_state import tab_label_of
from app.ui.panels.url_queue import UrlQueueInlineEditMixin, UrlQueueMixin

pytestmark = pytest.mark.unit


class Host(UrlQueueMixin, UrlQueueInlineEditMixin):
    def __init__(self, cfg: ConfigManager, pool: PagePool, rows: list[UrlRow]):
        self.config = cfg
        self._page_pool = pool
        self.state = SimpleNamespace(urls=rows)
        self.state.to_dict = lambda: {"urls": [asdict(u) for u in self.state.urls]}
        self.logs = []
        self.saved = 0
        self.pool_emits = 0
        self.persisted = 0
        self._save_arena = lambda: setattr(self, "saved", self.saved + 1)
        self._emit_pool_status = lambda: setattr(self, "pool_emits", self.pool_emits + 1)
        self._persist_cooldowns = lambda: setattr(self, "persisted", self.persisted + 1) or True
        self._log = lambda msg, level="info": self.logs.append((level, msg))
        self.undo_service = SimpleNamespace(push=lambda *a: None, history=lambda: ([], 0))
        self.undo_state_changed = SimpleNamespace(emit=lambda *a: None)
        self.history_changed = SimpleNamespace(emit=lambda *a: None)


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


def _row(url: str, tab_id: str) -> UrlRow:
    row = UrlRow.create(url, enabled=True, tab_id=tab_id)
    row.tab_id = tab_id
    return row


def test_set_url_job_count_updates_the_worker_and_persists_exact_value(cfg):
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", title="A", url="https://arena.ai/a", is_connected=True))
    row = _row("https://arena.ai/a", "t1")
    host = Host(cfg, pool, [row])

    assert json.loads(host.set_url_job_count(json.dumps({"url_id": row.id, "count": 7}))) == {"ok": True, "jobs_completed": 7}
    assert pool.get_page("t1").jobs_completed == 7
    assert load_stats(cooldowns_path(host))["https://arena.ai/a"]["jobs_completed"] == 7

    assert json.loads(host.set_url_job_count(json.dumps({"url_id": row.id, "count": 2}))) == {"ok": True, "jobs_completed": 2}
    assert pool.get_page("t1").jobs_completed == 2
    assert load_stats(cooldowns_path(host))["https://arena.ai/a"]["jobs_completed"] == 2
    assert host.pool_emits == 2 and host.persisted >= 2


def test_set_url_job_count_rejects_missing_rows_tabs_and_negative_input(cfg):
    pool = PagePool()
    row = _row("https://arena.ai/a", "ghost")
    host = Host(cfg, pool, [row])

    assert json.loads(host.set_url_job_count(json.dumps({"url_id": "missing", "count": 1})))["error"] == "row not found"
    assert json.loads(host.set_url_job_count(json.dumps({"url_id": row.id, "count": 1})))["error"] == "row tab not in pool"
    assert json.loads(host.set_url_job_count(json.dumps({"url_id": row.id, "count": -1})))["error"] == "job count must be a whole non-negative number"


def test_reset_all_url_cooldowns_changes_only_rows_with_time(cfg):
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", title="A", url="https://arena.ai/a", is_connected=True))
    pool.add_page(PageInfo(tab_id="t2", title="B", url="https://arena.ai/b", is_connected=True))
    page1 = pool.get_page("t1")
    page2 = pool.get_page("t2")
    page1.status = PageStatus.COOLDOWN
    page1.cooldown_until = 9999999999
    page1.cooldown_total = 300
    page2.jobs_completed = 9
    row1 = _row("https://arena.ai/a", "t1")
    row2 = _row("https://arena.ai/b", "t2")
    host = Host(cfg, pool, [row1, row2])

    reply = json.loads(host.reset_all_url_cooldowns())
    assert reply["ok"] is True
    assert reply["reset_count"] == 1
    assert reply["failed_rows"] == []
    assert page1.remaining_seconds(9999999999) == 0
    assert page2.jobs_completed == 9, "global cooldown reset never edits JOBS"
    assert host.pool_emits == 1 and host.persisted == 1


def test_reset_all_url_cooldowns_reports_persist_failure_with_affected_rows(cfg):
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", title="A", url="https://arena.ai/a", is_connected=True))
    page = pool.get_page("t1")
    page.status = PageStatus.COOLDOWN
    page.cooldown_until = 9999999999
    page.cooldown_total = 120
    row = _row("https://arena.ai/a", "t1")
    host = Host(cfg, pool, [row])
    host._persist_cooldowns = lambda: False

    reply = json.loads(host.reset_all_url_cooldowns())
    assert reply["ok"] is False
    assert reply["reset_count"] == 1
    assert reply["failed_rows"] == [{
        "url_id": row.id, "url": "https://arena.ai/a", "tab_id": "t1",
        "label": tab_label_of(pool, "t1"), "error": "persist failed",
    }]
    assert page.remaining_seconds(9999999999) == 0, "successful live clears stay applied"
