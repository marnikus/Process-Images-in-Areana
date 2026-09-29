"""Open the fresh worker tab inside the job tab's own profile — and prove it (I-79 v5, R3).

Two openers, in this order:

(a) `Target.createTarget` on the endpoint's browser connection, carrying the job tab's
    `browserContextId` — works for the contexts Chrome itself created for DevTools;
(b) the **job tab's own page**: `window.open(url, '_blank')` with `userGesture` — a page can only
    open a tab into its own profile, which is the only route into a regular Chrome profile
    (design §4).

A tab counts only after the browser's own target list confirms its context: a tab that landed in
another context is closed again immediately and the opener reports why (`wrong_profile`). When
neither opener is provable the handover is refused — the caller then runs the in-place New Chat in
the job's own tab, which cannot touch another profile.

RULE 18: file 150-300 ideal, func 4-20 LOC, params ≤4. Imports: cdp.browser_targets + page_popup.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.browser.cdp import browser_targets as bt
from app.browser.page_popup import open_tab_via_page

_POLL_SEC = 0.2
_PAGE = "page"


@dataclass
class OpenSpec:
    """What to open, in which context, and how long to wait for it to appear."""
    url: str
    context_id: str = ""
    timeout_sec: float = 5.0


@dataclass
class Opened:
    """The opener's answer: a proven tab id, or the reason this opener failed."""
    tab_id: str = ""
    reason: str = ""
    wrong_profile: bool = False


def _ids(target_infos: list[dict]) -> set:
    return {str(i.get("targetId")) for i in target_infos if i.get("type", _PAGE) == _PAGE}


async def _proven(browser, tab_id: str, context_id: str) -> tuple[str, str]:
    """`("", "")` only when the browser's own list places `tab_id` in the job tab's context (R3).

    The kinds matter: `wrong-context` is the A2 condition and must be reported as such, while
    `no-answer`/`not-listed` are cases where the browser never had a chance to be wrong.
    """
    target_infos, err = await browser.targets()
    if err:
        return "no-answer", err
    seen = bt.context_of(target_infos, tab_id)
    if seen is None:
        return "not-listed", f"the new tab {tab_id[:12]} is not listed in the job browser"
    if seen != context_id:
        return "wrong-context", (f"the new tab landed in another profile "
                                 f"(ctx {seen or 'default'} ≠ {context_id or 'default'}) — refused")
    return "", ""


async def _wait_new_tab(browser, before: set, timeout_sec: float) -> tuple[str, str]:
    """Poll this browser's list until a page target that was not there before appears."""
    deadline = time.monotonic() + max(timeout_sec, _POLL_SEC)
    while True:
        target_infos, err = await browser.targets()
        if err:
            return "", err
        fresh = _ids(target_infos) - before
        if fresh:
            return sorted(fresh)[0], ""
        if time.monotonic() >= deadline:
            return "", "the page opened no tab (nothing new in the target list)"
        await asyncio.sleep(_POLL_SEC)


async def _create_opener(browser, spec: OpenSpec) -> Opened:
    """(a) browser-level `Target.createTarget` in the job tab's context."""
    tab_id, err = await browser.create(spec.url, spec.context_id)
    if not tab_id:
        return Opened(reason=err)
    kind, why = await _proven(browser, tab_id, spec.context_id)
    if not kind:
        return Opened(tab_id=tab_id)
    await browser.close(tab_id)                       # an unprovable tab never stays behind
    return Opened(reason=why, wrong_profile=(kind == "wrong-context"))


async def _page_opener(browser, page_client, spec: OpenSpec) -> Opened:
    """(b) the job tab's own page — the only opener that reaches a regular profile."""
    if page_client is None:
        return Opened(reason="no client is connected to the job tab")
    target_infos, err = await browser.targets()
    if err:
        return Opened(reason=err)
    ok, why = await open_tab_via_page(page_client, spec.url, spec.timeout_sec)
    if not ok:
        return Opened(reason=why)
    tab_id, why = await _wait_new_tab(browser, _ids(target_infos), spec.timeout_sec)
    if not tab_id:
        return Opened(reason=why)
    kind, why = await _proven(browser, tab_id, spec.context_id)
    if not kind:
        return Opened(tab_id=tab_id)
    await browser.close(tab_id)
    return Opened(reason=why, wrong_profile=(kind == "wrong-context"))


def _refusal(created: Opened, paged: Opened) -> str:
    """Both openers' reasons, wrong-profile first: the log must name the profile that was lost."""
    first, second = (created, paged) if created.wrong_profile else (paged, created)
    reasons: list = []
    for reason in (first.reason, second.reason):
        if reason and reason not in reasons:
            reasons.append(reason)
    return "; ".join(reasons) or "no opener could prove a tab in the job tab's profile"


async def open_in_profile(browser, page_client, spec: OpenSpec) -> Opened:
    """Try both openers; a tab counts only when the browser puts it in the job tab's context."""
    created = await _create_opener(browser, spec)
    if created.tab_id:
        return created
    paged = await _page_opener(browser, page_client, spec)
    if paged.tab_id:
        return paged
    return Opened(reason=_refusal(created, paged),
                  wrong_profile=created.wrong_profile or paged.wrong_profile)
