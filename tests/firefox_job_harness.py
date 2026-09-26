"""Shared harness for the Firefox image job tests (design D-1, 2026-09-25).

`Site` stands in for `firefox_lane.run_phase` ONLY — every job module above
it is real. It answers each phase macro the way the Ui.Vision savelog does
(`[echo] ARENA_JOB={token, phase, data}`), from a per-phase script: a list is
consumed one item per launch (the last item repeats), an item may be a dict
of `{phase: data}`, a callable `(job_token) -> dict`, or a raw
`(kind, message, lines)` verdict.
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace as NS

from PIL import Image

from app.browser.page_pool import PagePool
from app.browser.uivision import pool_tabs as pt
from app.services import firefox_job as fj
from app.services import firefox_job_output as out
from app.services import firefox_job_result as fres
from app.services import firefox_lane as fl
from app.services.firefox_job_journal import journal_of
from app.services.firefox_job_phases import prompt_text, sha_of, utf16_len

TAB = "9THrgpBc.Profile1_tab1"
NEW_SRC = "https://r2.arena.ai/new.png"


def image_bytes(fmt: str = "PNG", size=(64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, fmt)
    return buffer.getvalue()


def source_image(folder: Path, name: str = "photo.png", fmt: str = "PNG") -> Path:
    path = folder / name
    path.write_bytes(image_bytes(fmt))
    return path


class Site:
    """The scripted Firefox page (see module doc)."""

    def __init__(self, **script):
        self.script = {k: (list(v) if isinstance(v, list) else [v]) for k, v in script.items()}
        self.calls: list = []
        self.phases: list = []

    def item_for(self, phase: str):
        queue = self.script.get(phase) or [{}]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    async def __call__(self, bridge, page, phase, token):
        self.calls.append(phase.phase)
        self.phases.append(phase)
        item = self.item_for(phase.phase)
        if callable(item):
            item = item(token)
            if asyncio.iscoroutine(item):
                item = await item
        if isinstance(item, tuple):
            return item
        lines = tuple("[echo] ARENA_JOB=" + json.dumps({"token": token, "phase": p, "data": d})
                      for p, d in item.items())
        return "ok", "macro completed", lines


def baseline(previews=None, **extra):
    data = {"srcs": ["https://r2.arena.ai/old.png"], "outputs": [], "previews": previews or [],
            "composer_len": 0, "errors": "", "security": False, "ready": {"ready": True}}
    data.update(extra)
    return {"baseline": data}


def attached(ext: str = ".png"):
    return lambda token: {"attach": {"previews": [{"alt": f"arena_{token}{ext}", "blob": True}],
                                     "matched": 1}}


def prompt_ok(prompt: str):
    text = prompt_text(prompt)
    return {"prompt": {"ok": True, "len": utf16_len(text), "sha256": sha_of(text), "error": ""}}


def sent(ack: str = "bubble"):
    return {"guard": {"go": True, "bubble": False, "promptOk": True, "attachmentOk": True,
                      "sendEnabled": True},
            "submit": {"ack": ack, "bubble": ack == "bubble", "composer_len": 0}}


def observed(found=True, src=NEW_SRC, job=None, **extra):
    def reply(token):
        data = {"found": found, "diag": {"ready": found, "src": src if found else "",
                                         "associatedJobId": job or token, "expectedJobId": token,
                                         "mismatch": []},
                "security": False, "generating": not found, "errors": "", "bubble": True,
                "previews": [], "composer_sha": ""}
        data.update(extra)
        return {"observe": data}
    return reply


def happy_site(text: str, ext: str = ".png", **over) -> Site:
    script = {"baseline": baseline(), "attach": attached(ext), "prompt": prompt_ok(text),
              "submit": sent(), "observe": observed(), "reset": {"reset": {"clean": True, "state": {}}}}
    script.update(over)
    return Site(**script)


class Bridge:
    """Duck-typed bridge: settings, config dir, flags, and every emit captured."""

    def __init__(self, config_dir: Path, images=()):
        settings = NS(timeouts={"generation": 30, "download": 5},
                      output={"suffix": "_AI", "preserve_format": True, "overwrite": False})
        self.state = NS(settings=settings, images=list(images), recalculate_progress=lambda: None)
        stored = {}
        self.config = NS(dir=str(config_dir), get_state=lambda k, d=None: stored.get(k, d),
                         set_state=lambda k, v: stored.__setitem__(k, v))
        self._cancel_requested = self._pause_requested = False
        self.logs: list = []
        self.actions: list = []
        self.saves = 0

    def _log(self, message, level="info"):
        self.logs.append((level, message))

    def _emit_job_action_status(self, action):
        self.actions.append((action.block, action.status, action.message))

    def _emit_pool_status(self):
        pass

    def _save_arena(self):
        self.saves += 1

    def text(self) -> str:
        return "\n".join(m for _, m in self.logs)


def firefox_pool() -> PagePool:
    pool = PagePool(logger=lambda m, l="info": None)
    tab = pt.FirefoxTab(id=TAB, url="https://arena.ai/c/7", title="A", profile="P1",
                        profile_dir="/x/P1", ws_url=f"firefox://{TAB}")
    pool.add_page(pt.page_for(tab))
    return pool


def image(path: Path):
    return NS(id="img-1", absolute_path=str(path), relative_path=path.name, status="processing",
              error=None, output_path=None)


def wire(monkeypatch, site: Site, fetched=None):
    """Only the Firefox boundary is faked: run_phase, the inter-job gap, the result GET."""
    monkeypatch.setattr(fl, "run_phase", site)

    async def no_gap(_bridge):
        return None

    monkeypatch.setattr(fl, "job_gap", no_gap)
    monkeypatch.setattr(fres, "FETCH_SETTLE_S", 0)
    data = image_bytes() if fetched is None else fetched
    replies = list(data) if isinstance(data, list) else [data]

    def fake_fetch(src, timeout, opener=None):
        item = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(out, "fetch", fake_fetch)


async def run(tmp_path: Path, site: Site, monkeypatch, prompt="[JOB-ID: c1]\nmake it red",
              corr="c1", src_name="photo.png", fmt="PNG", bridge=None, fetched=None):
    """One job end to end → (verdict, bridge, img, reset_out)."""
    wire(monkeypatch, site, fetched)
    src = source_image(tmp_path, src_name, fmt)
    img = image(src)
    bridge = bridge or Bridge(tmp_path / "cfg", [img])
    reset_out: list = []
    start = fj.JobStart(bridge=bridge, pool=firefox_pool(), tab_id=TAB, img=img, corr=corr, prompt=prompt)
    verdict = await fj.run_job(start, reset_out)
    return verdict, bridge, img, reset_out


PROMPT = "[JOB-ID: c1]\nmake it red"


def blocks(bridge, status="success"):
    """The Chrome-shaped action blocks the job logged with `status`."""
    return [b for b, s, _ in bridge.actions if s == status]


def record(bridge, corr="c1"):
    """The journal record of `corr` as the job left it."""
    return journal_of(bridge).get(corr)
