# ideal-size: ~305 lines reason=single-feature module owns clamp+store+record+emit for one window; splitting would scatter one append-only log that always changes together (RULE 18.2)
"""Job history — finished-job rows for the Job History window.

Append-only log (RULE 14: history is not the queue): every `job_finished`
emission has exactly one row here, recorded at the same two settle sites
(parallel `multi_page_dispatcher._handle_result`, sequential
`batch_orchestrator.finish_image`). Cancelled images emit no `job_finished`
and leave no row — the same rule on both paths.

Persistence is `config/job_history.json` (`next_job_no` + newest-last
entries, atomic write via `persistence.json_store`, shape-validated on
load — RULE 13), trimmed to `STORE_CAP`. The display count is the user's
`job_history_limit` (one clamp owner, like `live/debug_view`).
Imports: stdlib + persistence only (no cycle with the runners).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.persistence.json_store import load_json, save_json_atomic

FILE_NAME = "job_history.json"
LIMIT_KEY = "job_history_limit"
DEFAULT_LIMIT = 50
MIN_LIMIT = 5
MAX_LIMIT = 500
STORE_CAP = 500
ERROR_KEEP = 500


def clamp_history_limit(value: Any) -> int:
    """`MIN_LIMIT…MAX_LIMIT`; garbage (None, text) becomes the default, never raises."""
    try:
        n = int(value if value not in (None, "") else DEFAULT_LIMIT)
    except (TypeError, ValueError):
        n = DEFAULT_LIMIT
    return max(MIN_LIMIT, min(n, MAX_LIMIT))


def history_limit(bridge) -> int:
    """The configured display count (clamped on read too — a hand-edited file stays safe)."""
    try:
        return clamp_history_limit(bridge.config.get_state(LIMIT_KEY, DEFAULT_LIMIT))
    except Exception:
        return DEFAULT_LIMIT


def _history_file(bridge) -> Optional[Path]:
    """The JSON file, or None when the bridge has no config dir (tests/fakes → memory only)."""
    try:
        directory = getattr(getattr(bridge, "config", None), "dir", None)
        return Path(directory) / FILE_NAME if directory else None
    except Exception:
        return None


def store_of(bridge) -> "JobHistoryStore":
    """The bridge's store (created on first use; memory-only without a config dir)."""
    store = getattr(bridge, "_job_history", None)
    if store is None:
        store = JobHistoryStore(_history_file(bridge))
        try:
            bridge._job_history = store
        except Exception:
            pass
    return store


def _coerce_saved(data: Any) -> tuple:
    """Saved doc → (`next_job_no`, entries); any wrong shape becomes a fresh log (RULE 13)."""
    if not isinstance(data, dict):
        return 1, []
    try:
        nxt = max(1, int(data.get("next_job_no", 1) or 1))
    except (TypeError, ValueError):
        nxt = 1
    rows = data.get("entries", [])
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    return nxt, rows[-STORE_CAP:]


class JobHistoryStore:
    """Thread-safe append-only log (RLock: the bg loop appends, the UI thread reads)."""

    def __init__(self, path: Optional[Path] = None, cap: int = STORE_CAP) -> None:
        self._path = Path(path) if path else None
        self._cap = max(1, int(cap or STORE_CAP))
        self._lock = threading.RLock()
        self._next_no, self._entries = _coerce_saved(load_json(self._path, {}) if self._path else {})

    def append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Stamp the next sequential job_no, trim to cap, persist; returns the stored row.

        Memory first, disk second: a failed save keeps the row for this session
        and the caller warns (RULE 2) — the next successful save heals the file.
        """
        with self._lock:
            row = {**entry, "job_no": self._next_no}
            self._next_no += 1
            self._entries.append(row)
            del self._entries[:-self._cap]
            self._save_locked()
            return dict(row)

    def recent(self, limit: int) -> List[Dict[str, Any]]:
        """Newest-first copies, capped (copies: callers must not mutate the log)."""
        with self._lock:
            n = max(0, int(limit or 0))
            rows = self._entries[-n:] if n else []
            return [dict(r) for r in reversed(rows)]

    def clear(self) -> None:
        """Empty the log (the job_no sequence keeps counting — ids are never reused)."""
        with self._lock:
            self._entries = []
            self._save_locked()

    def _save_locked(self) -> None:
        """Persist `next_job_no` + entries (errors propagate — the caller reports, RULE 2)."""
        if self._path is None:
            return
        save_json_atomic(self._path, {"next_job_no": self._next_no, "entries": self._entries})

    @property
    def total(self) -> int:
        """Stored rows (≤ cap)."""
        with self._lock:
            return len(self._entries)

    @property
    def next_no(self) -> int:
        """The job_no the next finished job gets."""
        with self._lock:
            return self._next_no


@dataclass
class HistoryInput:
    """One finished job (param object — keeps `record_history` at 1 param, RULE 19)."""

    bridge: Any
    pool: Any
    img: Any
    tab_id: str
    job_id: str
    failed: bool
    err: str


def _note_dict(bridge, name: str) -> Optional[dict]:
    """The bridge's per-job side channel (created on first use; None when unwritable)."""
    try:
        noted = getattr(bridge, name, None)
        if not isinstance(noted, dict):
            noted = {}
            setattr(bridge, name, noted)
        return noted
    except Exception:
        return None


def note_job_started(bridge, job_id: str) -> None:
    """Remember when a job left the gate (read back once, at the settle site)."""
    if not job_id:
        return
    noted = _note_dict(bridge, "_job_started_at")
    if noted is not None:
        noted[job_id] = time.time()


def note_captcha_count(bridge, job_id: str, count: int) -> None:
    """Remember how many captcha encounters the block stack drained for this job."""
    if not job_id:
        return
    noted = _note_dict(bridge, "_job_captcha")
    if noted is not None:
        noted[job_id] = max(0, int(count or 0))


def _pop_note(bridge, job_id: str, name: str):
    """One raw side-channel note (None when missing — never raises, never creates)."""
    try:
        noted = getattr(bridge, name, None)
        if isinstance(noted, dict):
            return noted.pop(job_id, None)
    except Exception:
        pass
    return None


def _take_started(bridge, job_id: str, now: float) -> float:
    """Pop the gate note for a finished job (garbage/missing → now)."""
    try:
        return float(_pop_note(bridge, job_id, "_job_started_at") or now)
    except (TypeError, ValueError):
        return now


def _take_captcha(bridge, job_id: str) -> int:
    """Pop the captcha count for a finished job (garbage/missing → 0)."""
    try:
        return max(0, int(_pop_note(bridge, job_id, "_job_captcha") or 0))
    except (TypeError, ValueError):
        return 0


def _take_context(bridge, job_id: str) -> tuple:
    """Pop (started_at, captcha) for a finished job (defaults: now, 0)."""
    now = time.time()
    return _take_started(bridge, job_id, now), _take_captcha(bridge, job_id)


def tab_label_for(pool, tab_id: str) -> str:
    """Readable `{email}_{4 digits}` handle for a recorded tab (D-7).

    History rows are written once and read long after the tab is gone, so the
    label is resolved at record time and frozen into the row. Delegates to the
    pool's one label owner (`page_pool.tab_label_of`) — a history row can never
    print a different handle than the worker table for the same tab. A vanished
    tab or an unusable pool degrades to the short id, never to an empty cell.
    """
    try:
        from app.browser.page_pool import tab_label_of
        return tab_label_of(pool, tab_id)
    except Exception:
        return str(tab_id or "")[:12]


def worker_no_of(pool, tab_id: str) -> Any:
    """The pool's numeric tab reference (D-3 `#n` badge); `""` when the tab is gone."""
    try:
        page = pool.get_page(tab_id) if pool else None
        no = getattr(page, "worker_no", 0) or 0
        return int(no) if no > 0 else ""
    except Exception:
        return ""


def _iso(epoch: float) -> str:
    """UTC ISO timestamp for a wire row (falls back to epoch 0, never raises)."""
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc).isoformat()


def _identity_fields(rec: HistoryInput) -> Dict[str, Any]:
    """Who ran it + how it ended (ids, tab, status, error)."""
    return {
        "job_id": rec.job_id or "", "tab_id": rec.tab_id or "",
        "tab_label": tab_label_for(rec.pool, rec.tab_id or ""),
        "worker_no": worker_no_of(rec.pool, rec.tab_id or ""),
        "status": "failed" if rec.failed else "completed",
        "error": str(rec.err or "")[:ERROR_KEEP],
    }


def _file_fields(rec: HistoryInput) -> Dict[str, Any]:
    """What was processed + where it landed (empty on failure — RULE 4: no destination, no path)."""
    img = rec.img
    output = getattr(img, "output_path", "") or ""
    return {
        "image_id": getattr(img, "id", "") or "",
        "image": getattr(img, "filename", "") or "",
        "image_path": getattr(img, "absolute_path", "") or "",
        "folder": str(Path(output).parent) if output else "",
        "output_path": output,
    }


def _time_fields(started: float, captcha: int) -> Dict[str, Any]:
    """When it ran (start from the gate note, finish is now) + captcha encounters."""
    finished = time.time()
    return {
        "started": _iso(started), "finished": _iso(finished),
        "started_at": started, "finished_at": finished,
        "captcha": captcha,
    }


def _build_entry(rec: HistoryInput, started: float, captcha: int) -> Dict[str, Any]:
    """The wire row: identity + files + timing (split by concept, RULE 19)."""
    return {**_identity_fields(rec), **_file_fields(rec), **_time_fields(started, captcha)}


def _log_history_failure(rec, error) -> None:
    """One warn line when a history row is lost (best effort — never raises, RULE 2)."""
    try:
        log = getattr(getattr(rec, "bridge", None), "_log", None)
        if callable(log):
            log(f"\U0001F5C2 History row lost ({error})", "warn")
    except Exception:
        pass


def record_history(rec: HistoryInput) -> Optional[Dict[str, Any]]:
    """Append one finished job + push the window (a settle site never breaks; losses warn)."""
    try:
        started, captcha = _take_context(rec.bridge, rec.job_id or "")
        row = store_of(rec.bridge).append(_build_entry(rec, started, captcha))
        emit_history(rec.bridge)
        return row
    except Exception as e:
        _log_history_failure(rec, e)
        return None


def record_dispatch_result(ctx) -> Optional[Dict[str, Any]]:
    """Parallel path adapter: ResultCtx → HistoryInput (one line at the settle site)."""
    return record_history(HistoryInput(bridge=ctx.bridge, pool=ctx.pool, img=ctx.img,
                                       tab_id=ctx.tab_id, job_id=ctx.job_id,
                                       failed=ctx.failed, err=ctx.err))


def record_batch_result(ctx, res) -> Optional[Dict[str, Any]]:
    """Sequential path adapter: (BatchCtx, ImageResult) → HistoryInput."""
    return record_history(HistoryInput(bridge=ctx.bridge, pool=getattr(ctx.bridge, "_page_pool", None),
                                       img=res.img, tab_id=ctx.tab_id, job_id=res.job_id,
                                       failed=res.failed, err=res.error))


def history_payload(bridge) -> Dict[str, Any]:
    """`{entries, limit, total, next_job_no}` — newest-first rows for the window."""
    try:
        store = store_of(bridge)
        limit = history_limit(bridge)
        return {"entries": store.recent(limit), "limit": limit,
                "total": store.total, "next_job_no": store.next_no}
    except Exception:
        return {"entries": [], "limit": DEFAULT_LIMIT, "total": 0, "next_job_no": 1}


def emit_history(bridge) -> None:
    """Push the payload on `job_history_updated` (missing signal on fakes is fine)."""
    try:
        import json

        signal = getattr(bridge, "job_history_updated", None)
        if signal is None:
            return
        signal.emit(json.dumps(history_payload(bridge), ensure_ascii=False))
    except Exception:
        pass
