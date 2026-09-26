"""Firefox tabs in the one pool (I-64, 2026-09-25) — the ui-land wiring.

Owns the bridge's Firefox source and hands the services plain callables:
- `merged_listing`: Chrome's listing plus the Firefox discovery as ONE
  `TabListing` for the reconciler (a silent browser's rows are held, never aged);
- `join_any` / `join_firefox`: a Firefox id joins the pool without a CDP client
  (`finish_pool_join(..., None, None)`), labelled `{profile}_{NNNN}`;
- `install`: the `UiVisionDeps` the dispatcher's Firefox lane runs through
  (plan in a worker thread: fresh session read → address; run: the pool macro).

Profiles: only those CHECKED in the Firefox window feed the pool. None
checked means no Firefox (owner decision 2026-09-25); the framework test
keeps its own "empty = every open profile".
Imports: ui → services / browser / panels (never the reverse).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import Any, Optional

from app.browser.page_status import PageInfo
from app.browser.uivision.plan import Patterns
from app.browser.uivision.pool.locator import locate, refusal
from app.browser.uivision.pool.macro import PoolStep, pool_macro_name
from app.browser.uivision.pool.run import PoolJob, PoolRunSpec, run_pool_job
from app.browser.uivision.pool.scan import FoxScanner
from app.browser.uivision.runner import RunSeams
from app.core.tab_alias import CHROME, FIREFOX, tab_browser
from app.services.live.reconcile import ScanUnavailable
from app.services.live.row_sync import DEFAULT_PATTERN, PATTERN_KEY
from app.services.live.sources import TabListing, keys_of
from app.services.uivision_job import UiVisionDeps
from app.ui.panels.firefox_auto import PROFILE_LIST_KEY, app_config_dir, load_config


@dataclass
class Part:
    """One source's answer this pass: its tabs, whether it answered, whether it listed any."""

    tabs: list
    silent: bool = False      # raised / could not be read — hold its rows AND pages
    empty: bool = False       # answered with zero tabs — hold its rows only (old Chrome rule)


def fox_scanner(bridge) -> FoxScanner:
    """The bridge's Firefox discovery (created once, ids seeded from the persisted rows)."""
    scanner = getattr(bridge, "_fox_scanner", None)
    if scanner is None:
        scanner = bridge._fox_scanner = FoxScanner()
        rows = getattr(getattr(bridge, "state", None), "urls", []) or []
        scanner.book.seed([(u.tab_id, u.url) for u in rows if tab_browser(u.tab_id) == FIREFOX])
    return scanner


def patterns_of(cfg: dict) -> Patterns:
    """The Firefox window's two tab filters (blank = any)."""
    return Patterns(cfg.get("pattern", ""), cfg.get("url_pattern", ""))


def _log_notes(bridge, notes: list) -> None:
    """Each distinct discovery note once while it lasts (the loop runs every few seconds)."""
    old = getattr(bridge, "_fox_notes", set())
    for note in notes:
        if note not in old:
            bridge._log(f"🦊 Firefox scan: {note}", "warn")
    bridge._fox_notes = set(notes)


async def firefox_tabs(bridge) -> Optional[list]:
    """This pass's Firefox tabs; None when no profile is checked (Firefox is not a source)."""
    cfg = load_config(bridge)
    profiles = list(cfg.get(PROFILE_LIST_KEY) or [])
    if not profiles:
        return None
    scanner = fox_scanner(bridge)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, scanner.scan, profiles, patterns_of(cfg))
    _log_notes(bridge, result.notes)
    return list(result.tabs)


async def _chrome_part(fetch) -> tuple:
    """(Part, error): Chrome's answer, or the ScanUnavailable it raised."""
    try:
        tabs = list(await fetch())
    except ScanUnavailable as exc:
        return Part([], silent=True), exc
    return Part(tabs, empty=not tabs), None


async def _fox_part(bridge) -> Optional[Part]:
    """Firefox's answer; None when not configured; a crash holds its rows (never a close)."""
    try:
        tabs = await firefox_tabs(bridge)
    except Exception as exc:
        _log_notes(bridge, [f"scan failed ({type(exc).__name__}: {exc}) — Firefox rows held"])
        return Part([], silent=True)
    return None if tabs is None else Part(tabs)


def _known_keys(bridge) -> set:
    """Every key a row links or the pool holds (what a silent source may need held)."""
    rows = {u.tab_id for u in getattr(bridge.state, "urls", []) or [] if u.tab_id}
    pool = getattr(bridge, "_page_pool", None)
    return rows | set(getattr(pool, "_pages", {}) or {})


def compose(bridge, chrome: Part, fox: Part) -> TabListing:
    """One listing from two answers; ScanUnavailable only when neither browser answered."""
    if chrome.silent and fox.silent:
        raise ScanUnavailable("neither Chrome nor Firefox answered this pass")
    known = _known_keys(bridge)
    row_hold = [name for name, part in ((CHROME, chrome), (FIREFOX, fox)) if part.silent or part.empty]
    page_hold = [name for name, part in ((CHROME, chrome), (FIREFOX, fox)) if part.silent]
    return TabListing(chrome.tabs + fox.tabs, held_rows=keys_of(known, row_hold),
                      held_pages=keys_of(known, page_hold), answered=not fox.silent)


async def merged_listing(bridge, chrome_fetch) -> Any:
    """Chrome + Firefox; with no Firefox profile checked, Chrome's own answer passes unchanged."""
    chrome, error = await _chrome_part(chrome_fetch)
    fox = await _fox_part(bridge)
    if fox is None:
        if error is not None:
            raise error
        return chrome.tabs
    return compose(bridge, chrome, fox)


def fox_page_info(tab) -> PageInfo:
    """The pool row of a Firefox tab — no socket; the profile names it (`Profile1_0007`)."""
    return PageInfo(tab_id=tab.id, ws_url="", title=tab.title or tab.id, url=tab.url,
                    browser=FIREFOX, profile=tab.profile_label)


async def join_firefox(bridge, tab_id: str) -> bool:
    """Pool one discovered Firefox tab (no CDP client, no badge); False when not discovered."""
    from app.ui.panels.page_pool import finish_pool_join
    tab = fox_scanner(bridge).last_tab(tab_id)
    if tab is None:
        bridge._log(f"♻️ Firefox join skipped for {tab_id} — not in the last Firefox scan", "warn")
        return False
    await finish_pool_join(bridge, fox_page_info(tab), None, None)
    return True


async def join_any(bridge, handle: str) -> None:
    """The reconciler's join: a Firefox id joins by id, anything else is a CDP socket."""
    if tab_browser(handle) == FIREFOX:
        await join_firefox(bridge, handle)
        return
    from app.ui.panels.page_pool import do_connect_page_pool
    await do_connect_page_pool(bridge, handle)


def pool_spec(bridge, cfg: dict) -> PoolRunSpec:
    """The per-run settings from the Firefox window's config (macro name `{macro}_pool`)."""
    return PoolRunSpec(binary=cfg["binary"], macro=pool_macro_name(cfg["macro"]),
                       storage=cfg["storage"], home=cfg["home"], config_dir=app_config_dir(bridge),
                       pause_ms=int(cfg["pause_ms"]), target=cfg["target"],
                       timeout_sec=int(cfg["timeout_sec"]))


def plan_job(bridge, tab_id: str):
    """(worker thread) The PoolJob for one Firefox tab, or the named reason it cannot run."""
    cfg = load_config(bridge)
    scanner = fox_scanner(bridge)
    known = scanner.last_tab(tab_id)
    if known is None:
        return "the tab is not in the last Firefox scan (is its profile checked and open?)"
    found = scanner.locate(known.profile_dir, tab_id, patterns_of(cfg))
    if found is None:
        return "the tab is gone from its profile's session store (closed, or no longer matching)"
    address = locate(list(found.windows), found.tab.window, found.tab.index)
    if address is None:
        return refusal(list(found.windows), found.tab.window, found.tab.index)
    needle = str(bridge.config.get_state(PATTERN_KEY, DEFAULT_PATTERN) or "")
    step = PoolStep(anchor=address.anchor, offset=address.offset, needle=needle,
                    target=cfg["target"], pause_ms=int(cfg["pause_ms"]))
    return PoolJob(spec=pool_spec(bridge, cfg), tab=found.tab, window_row=found.window_row, step=step)


async def run_job(job: PoolJob, report, stop) -> Any:
    """One pool run with the lane's Stop wired into the poll."""
    return await run_pool_job(job, report, RunSeams(stop=stop))


def inter_run_delay(bridge) -> float:
    """The user's delay between Ui.Vision runs (the Firefox window's field, default 3 s)."""
    return float(load_config(bridge).get("inter_run_delay_sec", 3))


def install(bridge) -> UiVisionDeps:
    """Hand the dispatcher's Firefox lane its planner, runner and delay (boot; idempotent)."""
    deps = UiVisionDeps(plan=partial(plan_job, bridge), run=run_job,
                        delay_sec=partial(inter_run_delay, bridge))
    bridge._uivision_deps = deps
    return deps
