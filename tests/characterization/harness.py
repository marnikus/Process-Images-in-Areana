"""Golden harness: real Bridge on tmp dirs, structural trace, golden compare.

Trace (behavior contract — volatile ids/paths normalized out):
  events  [(block_id, status)] in emit order
  clicks  [visual-runner selectors] in call order
  evals   number of raw CDP evaluate calls
  signals [job_started/job_finished, normalized]
  images  [{rel, status, error}] per queue image
  files   [output basenames created]
  run_state final run state

`RUNNERS` maps name -> async runner. A4 flipped the entry to the orchestrator;
A4 switches it to the orchestrator with the SAME goldens.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from app.core.action_blocks import ActionBlock, stack_to_dicts
from app.core.models import ImageItem, UrlRow
from app.persistence.config_manager import ConfigManager
from app.ui.bridge import Bridge

from .fakes import FakeCDP, Recorder

GOLDENS = Path(__file__).parent / "goldens"
CORR_RE = re.compile(r"\d{8}-\d{6}-[A-Z0-9]{4}")


def make_block(block_id: str, **over) -> ActionBlock:
    """Deterministic block (id == type; unique within our stacks)."""
    base = dict(id=block_id, block_id=block_id, name=block_id,
                description="", icon="", enabled=True,
                pre_delay_ms=0, timeout_ms=5000, highlight_ms=10,
                highlight_duration_ms=10, confirm_pause_ms=0)
    base.update(over)
    for rk in ("use_panel_filters",):
        base.pop(rk, None)
    return ActionBlock.from_dict(dict(base))


CORE_STACK = ["OBSERVE_BASELINE", "CHECK_SECURITY", "ATTACH_IMAGE",
              "INSERT_PROMPT", "SUBMIT", "WAIT_OUTPUT", "DOWNLOAD",
              "VALIDATE", "SAVE", "ADVANCE"]

FULL_STACK = ["CUSTOM_FIND", "HIGHLIGHT", "PAUSE", "TYPE_PROMPT",
              "OBSERVE_BASELINE", "CHECK_SECURITY", "HIGHLIGHT_ATTACH",
              "ATTACH_IMAGE", "VERIFY_ATTACHMENT", "HIGHLIGHT_PROMPT",
              "INSERT_PROMPT", "VERIFY_PROMPT", "HIGHLIGHT_SUBMIT",
              "SUBMIT", "WAIT_OUTPUT", "AWAIT_PROCESSING_IMAGE",
              "DOWNLOAD", "VALIDATE", "SAVE", "ADVANCE"]


def build_stack(ids: List[str], **per_block) -> List[ActionBlock]:
    out = []
    for bid in ids:
        kw = dict(per_block.get(bid, {}))
        if bid == "PAUSE":
            kw.setdefault("extra", {"duration_ms": 10})
        if bid == "CUSTOM_FIND":
            kw.setdefault("selector", "button#go")
        out.append(make_block(bid, **kw))
    return out


def _png_bytes() -> bytes:
    return (b"\x89PNG\r\n\x1a\n" + b"\x00" * 120)


def make_images(root: Path, n: int) -> List[ImageItem]:
    imgs = []
    for i in range(1, n + 1):
        p = root / f"pic{i}.png"
        p.write_bytes(_png_bytes())
        imgs.append(ImageItem(
            id=f"img{i}", relative_path=p.name, absolute_path=str(p),
            filename=p.name, base_name=p.stem, extension=".png",
            size=len(_png_bytes()), mtime=1000.0,
            fingerprint=f"fp{i}", selected=True))
    return imgs


def make_urls(tab_ids: List[str]) -> List[UrlRow]:
    return [UrlRow.create(f"https://arena.ai/chat{i}", enabled=True, tab_id=t)
            for i, t in enumerate(tab_ids)]


def _recorders(bridge: Bridge) -> Dict[str, Recorder]:
    recs = {}
    for name in ("job_started", "job_finished", "job_action_status",
                 "arena_log", "highlight_rect", "arena_state_updated",
                 "progress_updated", "page_pool_updated",
                 "action_blocks_updated"):
        rec = Recorder()
        setattr(bridge, name, rec)
        recs[name] = rec
    return recs


def build_bridge(tmp_path: Path, stack: List[ActionBlock], n_images: int = 1,
                 tab_ids: Optional[List[str]] = None,
                 pool=None, cdp: Optional[FakeCDP] = None, watcher_on: bool = False):
    """Real Bridge wired to tmp dirs + recorders (pool None = single mode).

    watcher_on arms the session switch (S2): DEFAULT_SESSION ships it OFF,
    and with the scope gate a visible dialog is only handled while ON.
    """
    cfg = ConfigManager(str(tmp_path / "cfg"))
    if watcher_on:
        cfg.set_state(watcher_enabled=True)
    cdp = cdp or FakeCDP()
    bridge = Bridge(config_manager=cfg, state_path=tmp_path / "arena.json",
                    cdp_client=cdp)
    recs = _recorders(bridge)
    cfg.set_state(action_blocks=stack_to_dicts(stack))
    bridge.state.images = make_images(tmp_path, n_images)
    bridge.state.urls = make_urls(tab_ids if tab_ids is not None else ["tab1"])
    bridge.state.prompt["user_prompt"] = "a red circle"
    bridge._page_pool = pool
    return SimpleNamespace(bridge=bridge, recs=recs, cdp=cdp, cfg=cfg,
                           root=tmp_path)


def _events(recs) -> List[list]:
    out = []
    for _job, _bid, payload in recs["job_action_status"].calls:
        try:
            d = json.loads(payload)
        except Exception:
            continue
        out.append([d.get("block_id"), d.get("status")])
    return out


def _signals(recs) -> List[list]:
    out = []
    for job_id, path in recs["job_started"].calls:
        out.append(["job_started", Path(path).name])
    for job_id, payload in recs["job_finished"].calls:
        try:
            d = json.loads(payload)
        except Exception:
            d = {}
        out.append(["job_finished", d.get("status"),
                    bool(d.get("output_path"))])
    return out


def _images(bridge) -> List[dict]:
    return [{"rel": Path(i.absolute_path).name, "status": i.status,
             "error": i.error or ""} for i in bridge.state.images]


def _files(root: Path) -> List[str]:
    return sorted(p.name for p in root.glob("*_AI*") if p.is_file())


def collect_trace(env, clicks) -> Dict[str, Any]:
    bridge = env.bridge
    logs = [m for m, _lvl in env.recs["arena_log"].calls]
    trace = {
        "events": _events(env.recs),
        "clicks": list(clicks.calls),
        "evals": len(env.cdp.eval_calls),
        "signals": _signals(env.recs),
        "images": _images(bridge),
        "files": _files(env.root),
        "run_state": getattr(bridge, "_run_state", "?"),
        "logs": logs,
    }
    return normalize(trace)


def normalize(trace: Dict[str, Any]) -> Dict[str, Any]:
    s = json.dumps(trace, ensure_ascii=False, default=str)
    s = CORR_RE.sub("JOBID", s)
    return json.loads(s)


def golden_path(name: str) -> Path:
    GOLDENS.mkdir(exist_ok=True)
    return GOLDENS / f"{name}.json"


def check_golden(name: str, trace: Dict[str, Any]) -> None:
    """Compare (logs excluded); UPDATE_GOLDENS=1 regenerates."""
    slim = {k: v for k, v in trace.items() if k != "logs"}
    path = golden_path(name)
    if os.environ.get("UPDATE_GOLDENS") == "1" or not path.exists():
        path.write_text(json.dumps(slim, indent=1, ensure_ascii=False),
                        encoding="utf-8")
        return
    want = json.loads(path.read_text(encoding="utf-8"))
    assert slim == want, f"golden {name} drifted:\n{json.dumps(slim, indent=1)[:3000]}"


def assert_markers(trace: Dict[str, Any], markers: List[str]) -> None:
    joined = "\n".join(trace.get("logs", []))
    for m in markers:
        assert m in joined, f"log marker missing: {m!r}"


async def run_orchestrator(env) -> None:
    from app.services.batch_orchestrator import run_batch
    await run_batch(env.bridge)


RUNNERS: Dict[str, Callable] = {"orchestrator": run_orchestrator}


def arm_hooks(env, after_event: Optional[Dict[tuple, Callable]] = None,
              after_finish: Optional[Callable] = None) -> None:
    """Fire mid-run actions (cancel/stop/abort) when events land."""
    after_event = after_event or {}
    status_rec = env.recs["job_action_status"]
    orig_status = status_rec.emit

    def emit_status(job_id, block_id, payload):
        orig_status(job_id, block_id, payload)
        try:
            d = json.loads(payload)
            key = (d.get("block_id"), d.get("status"))
        except Exception:
            return
        fn = after_event.get(key)
        if fn:
            fn(env)

    status_rec.emit = emit_status
    if after_finish is not None:
        fin_rec = env.recs["job_finished"]
        orig_fin = fin_rec.emit

        def emit_fin(*args):
            orig_fin(*args)
            after_finish(env)

        fin_rec.emit = emit_fin
