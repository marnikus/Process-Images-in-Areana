"""Open the fresh worker tab inside the job tab's own profile — and prove it (I-79, R1–R7).

Two openers, in this order:

(a) `Target.createTarget` on the endpoint's browser connection, carrying the job tab's
    `browserContextId` — **only when the job tab's profile is disclosed** (R6): a
    context-less create lands in the default profile, and comparing that result with the
    same `""` it produced would certify the reported A2 bug as "proven";
(b) the **job tab's own page**: `window.open(url, '_blank')` with `userGesture` — a page
    can only open a tab into its own profile, which is the only route into a regular
    Chrome profile (design §4). The tab counts when the browser lists it with
    `openerId == job tab` — provenance pins the profile even where contexts are never
    disclosed (R7). A tab that names another opener is refused and left alone (it may be
    a human's), and a provenance refusal is retried once from the job tab's own socket
    (R7b): no registered client may decide which profile the worker lands in.

A tab counts only after the browser's own target list confirms it: a wrong-context tab is
closed again immediately, a wrong-opener tab is never touched. When neither opener is
provable the handover is refused — the caller then runs the in-place New Chat in the
job's own tab, which cannot touch another profile (RULE 9).

RULE 18: file 150-300 ideal, func 4-20 LOC, params ≤4. Imports: cdp.browser_targets +
cdp.client + page_popup.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.browser.cdp import browser_targets as bt
from app.browser.cdp.client import CDPClient
from app.browser.page_popup import open_tab_via_page

_POLL_SEC = 0.2
_PAGE = "page"
_NO_TAB = "the page opened no tab (nothing new in the target list)"
_NO_CLIENT = "no client is connected to the job tab"
_SKIP_CDP = ("cdp creation not used: the browser discloses no profile for the job tab "
             "(a context-less create lands in the default profile)")
_WRONG_OPENER = "the fresh tab was opened by another tab"


@dataclass
class OpenSpec:
    """What to open, in which context, and how long to wait for it to appear."""

    url: str
    context_id: str = ""
    timeout_sec: float = 5.0
    opener_id: str = ""     # the job tab: whose page must have opened the fresh one (R7)
    page_ws: str = ""       # the job tab's own socket: the opener's honest fallback (R7b)


@dataclass
class Opened:
    """The opener's answer: a proven tab id, or the reason this opener failed."""

    tab_id: str = ""
    reason: str = ""
    wrong_profile: bool = False


def _ids(target_infos: list[dict]) -> set:
    return {str(i.get("targetId")) for i in target_infos if i.get("type", _PAGE) == _PAGE}


def _opener_of(info: dict) -> str:
    """`openerId` — the tab whose page opened this one; "" when the browser reports none."""
    value = info.get("openerId")
    return str(value) if isinstance(value, str) else ""


def _fresh(target_infos: list[dict], before: set) -> list[dict]:
    """Page targets that were not in the `before` snapshot."""
    ids = _ids(target_infos) - before
    return [i for i in target_infos
            if i.get("type", _PAGE) == _PAGE and str(i.get("targetId")) in ids]


def _sorted_ids(infos: list[dict]) -> list[str]:
    return sorted(str(i.get("targetId")) for i in infos)


def _candidate(fresh: list[dict], opener_id: str) -> str:
    """The fresh tab to judge now: ours by provenance, else one the browser attributes to
    nobody (a Chrome that reports no `openerId` leaves its verdict to `_proven`), else `""`
    — a tab naming ANOTHER opener never wins while ours may still be coming."""
    mine = [i for i in fresh if opener_id and _opener_of(i) == opener_id]
    bare = [i for i in fresh if not _opener_of(i)]
    return _sorted_ids(mine or bare)[0] if (mine or bare) else ""


def _verdict(seen: str, opener: str, context_id: str, opener_id: str) -> tuple[str, str]:
    """Provenance first, then the disclosed-context rule (R6/R7): `("", "")` = proven.

    An undisclosed profile may pass only by provenance: `"" == ""` would compare the
    answer "never disclosed" with itself and prove nothing about the profile (RC-1).
    """
    if opener_id and opener:
        if opener == opener_id:
            return "", ""
        return "wrong-opener", f"{_WRONG_OPENER} ({opener[:12]}) — not the job's own page"
    if seen != context_id:
        return "wrong-context", (f"the new tab landed in another profile "
                                 f"(ctx {seen or 'default'} ≠ {context_id or 'default'}) — refused")
    if not context_id:
        return "unprovable", ("the browser discloses no profile for this tab and the fresh "
                              "tab names no opener — profile unknown")
    return "", ""


async def _proven(browser, tab_id: str, context_id: str, opener_id: str = "") -> tuple[str, str]:
    """`("", "")` only when the browser's own list proves the tab (R3 + R7).

    The kinds matter: `wrong-context` is the A2 condition and must be reported as such,
    `wrong-opener` names a tab somebody else opened, while `no-answer`/`not-listed` are
    cases where the browser never had a chance to be wrong.
    """
    target_infos, err = await browser.targets()
    if err:
        return "no-answer", err
    seen = bt.context_of(target_infos, tab_id)
    if seen is None:
        return "not-listed", f"the new tab {tab_id[:12]} is not listed in the job browser"
    return _verdict(seen, _opener_of(bt.target_of(target_infos, tab_id) or {}),
                    context_id, opener_id)


async def _wait_new_tab(browser, before: set, opener_id: str, timeout_sec: float) -> tuple[str, str]:
    """Poll this browser's list until a page target that was not there before appears.

    The job's own page's tab wins at once (`openerId` == job tab, R7); a fresh tab the
    browser attributes to no opener is the immediate candidate (a Chrome that reports no
    opener leaves its verdict to `_proven`); a tab naming ANOTHER opener never wins while
    ours may still be coming — at the deadline it is returned so `_proven` can refuse it.
    """
    deadline = time.monotonic() + max(timeout_sec, _POLL_SEC)
    while True:
        target_infos, err = await browser.targets()
        if err:
            return "", err
        fresh = _fresh(target_infos, before)
        hit = _candidate(fresh, opener_id)
        if hit:
            return hit, ""
        if time.monotonic() >= deadline:
            return (_sorted_ids(fresh)[0], "") if fresh else ("", _NO_TAB)
        await asyncio.sleep(_POLL_SEC)


async def _create_opener(browser, spec: OpenSpec) -> Opened:
    """(a) browser-level `Target.createTarget` in the job tab's disclosed context (R6)."""
    tab_id, err = await browser.create(spec.url, spec.context_id)
    if not tab_id:
        return Opened(reason=err)
    kind, why = await _proven(browser, tab_id, spec.context_id)
    if not kind:
        return Opened(tab_id=tab_id)
    await browser.close(tab_id)                       # an unprovable tab never stays behind
    return Opened(reason=why, wrong_profile=(kind == "wrong-context"))


async def _attempt_popup(browser, client, spec: OpenSpec) -> Opened:
    """One page-opener attempt: evaluate on `client`, then judge its fresh tab (R7)."""
    if client is None:
        return Opened(reason=_NO_CLIENT)
    target_infos, err = await browser.targets()
    if err:
        return Opened(reason=err)
    ok, why = await open_tab_via_page(client, spec.url, spec.timeout_sec)
    if not ok:
        return Opened(reason=why)
    tab_id, why = await _wait_new_tab(browser, _ids(target_infos), spec.opener_id, spec.timeout_sec)
    if not tab_id:
        return Opened(reason=why)
    kind, why = await _proven(browser, tab_id, spec.context_id, spec.opener_id)
    if not kind:
        return Opened(tab_id=tab_id)
    if kind != "wrong-opener":                        # ours by timing; a foreign opener's tab stays
        await browser.close(tab_id)
    return Opened(reason=why, wrong_profile=(kind == "wrong-context"))


async def _dial_page(ws_url: str):
    """A fresh connection to the job tab's own page — the opener needs a socket there (R7b).

    The handover already trusts this socket (it dialled the browser from it, R1); when no
    registered client sits on the job tab, this is the same truth, one page connection on.
    """
    endpoint = bt.endpoint_of_ws(ws_url or "")
    if endpoint is None:
        return None
    client = CDPClient(*endpoint)
    try:
        connected = await client.connect(ws_url)
    except Exception:
        return None
    return client if connected else None


def _worth_dialling(opened: Opened, page_client: Any, spec: OpenSpec) -> bool:
    """Retry from the job tab's own socket: none sat there, or the one used lied (R7b)."""
    if not spec.page_ws:
        return False
    return page_client is None or _WRONG_OPENER in opened.reason


async def _page_opener(browser, page_client, spec: OpenSpec) -> Opened:
    """(b) the job tab's own page — the only opener that reaches a regular profile.

    First the client that already sits there; when it is missing, or its popup failed the
    provenance proof (wrong `openerId`), the honest fallback is the job tab's own socket.
    """
    tried = await _attempt_popup(browser, page_client, spec)
    if tried.tab_id or not _worth_dialling(tried, page_client, spec):
        return tried
    client = await _dial_page(spec.page_ws)
    if client is None:
        return Opened(reason=f"{tried.reason}; the job tab's socket could not be reached")
    try:
        return await _attempt_popup(browser, client, spec)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def _refusal(created: Opened, paged: Opened) -> str:
    """Both openers' reasons, wrong-profile first: the log must name the profile that was lost."""
    first, second = (created, paged) if created.wrong_profile else (paged, created)
    reasons: list = []
    for reason in (first.reason, second.reason):
        if reason and reason not in reasons:
            reasons.append(reason)
    return "; ".join(reasons) or "no opener could prove a tab in the job tab's profile"


async def open_in_profile(browser, page_client, spec: OpenSpec) -> Opened:
    """Try both openers; a tab counts only on a non-degenerate proof of the job's profile."""
    created = await _create_opener(browser, spec) if spec.context_id else Opened(reason=_SKIP_CDP)
    if created.tab_id:
        return created
    paged = await _page_opener(browser, page_client, spec)
    if paged.tab_id:
        return paged
    return Opened(reason=_refusal(created, paged),
                  wrong_profile=created.wrong_profile or paged.wrong_profile)
