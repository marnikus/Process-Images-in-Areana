"""Browser-context and Arena-account proof for a New Chat candidate."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.browser.cdp import CDPClient
from app.browser.cdp.tabs import (
    TabInfo, close_tab_sync, fetch_browser_ws_url_sync,
    open_tab_in_same_context, target_context,
)
from app.browser.cdp_arena import CDPArenaController
from app.browser.chat_page import read_chat_page
from app.browser.new_chat import ResetCtx, wait_new_chat_ready
from app.core.tab_alias import normalize_owner

IDENTITY_WAIT_SEC = 12.0
IDENTITY_REQUEST_SEC = 5.0
IDENTITY_POLL_SEC = 0.4


@dataclass
class CandidateProof:
    """Temporary clients that proved the candidate before worker mutation."""
    target: TabInfo
    owner: str
    browser_client: Any
    page_client: Any


class CandidateAttempt:
    """One candidate's temporary protocol clients and proof lifecycle."""
    def __init__(self, move):
        self.move = move
        self.browser = self.page = self.target = None
        self.context = self.owner = None

    async def run(self) -> tuple[CandidateProof | None, str]:
        try:
            proof, why = await self._prove()
        except Exception as exc:
            proof, why = None, f"candidate proof failed ({type(exc).__name__}: {exc})"
        if proof is None:
            await self._discard()
        return proof, why

    async def _prove(self) -> tuple[CandidateProof | None, str]:
        ok, why = await self._prove_source()
        if not ok:
            return None, why
        return await self._prove_candidate()

    async def _prove_source(self) -> tuple[bool, str]:
        self.browser, why = await _browser_connection(self.move.endpoint)
        if self.browser is None:
            return False, why
        found, self.context = await asyncio.wait_for(
            target_context(self.browser, self.move.old_id), timeout=IDENTITY_REQUEST_SEC)
        if not found:
            return False, "source target context is unknown; original tab retained"
        self.owner = await asyncio.wait_for(
            _read_owner(self.move.ctx.client), timeout=IDENTITY_REQUEST_SEC)
        if not self.owner:
            return False, "source Arena account is unknown; keeping the original tab"
        self.move.old_owner, self.move.old_context = self.owner, self.context
        _log(self.move, f"source {self.move.endpoint[0]}:{self.move.endpoint[1]} "
                        f"context={_context_label(self.context)} Arena owner={self.owner}", "info")
        return True, ""

    async def _prove_candidate(self) -> tuple[CandidateProof | None, str]:
        self.target, why = await asyncio.wait_for(
            _open_candidate(self.browser, self.move), timeout=IDENTITY_REQUEST_SEC + 2)
        if self.target is None:
            return None, why
        found, context = await asyncio.wait_for(
            target_context(self.browser, self.target.id), timeout=IDENTITY_REQUEST_SEC)
        if not found or context != self.context:
            return None, _context_mismatch(self.context, context, found)
        _log(self.move, f"candidate {self.target.id[:12]} context={_context_label(context)}", "info")
        self.page = await _candidate_page(self.target, self.move.endpoint)
        if self.page is None:
            return None, "could not attach a temporary client to the candidate"
        why = await self._prove_page()
        if why:
            return None, why
        return CandidateProof(self.target, self.owner, self.browser, self.page), ""

    async def _prove_page(self) -> str:
        ctrl = CDPArenaController(self.page, lambda msg: _log(self.move, msg, "info"))
        reset = ResetCtx(ctrl=ctrl, client=self.page, engine=self.move.ctx.bridge,
                         timeout_sec=min(max(1.0, self.move.timeout_sec), IDENTITY_WAIT_SEC),
                         cancel_check=lambda: bool(getattr(self.move.ctx.bridge, "_cancel_requested", False)),
                         purpose="in the candidate tab")
        ready, why = await wait_new_chat_ready(reset)
        if not ready:
            return f"candidate readiness proof failed ({why})"
        is_new, why = await asyncio.wait_for(
            read_chat_page(self.page), timeout=IDENTITY_REQUEST_SEC)
        if is_new is not True:
            return f"candidate is not a new chat ({why})"
        stable, why = await _stable_owner(self.page, self.owner, self.move.timeout_sec)
        if not stable:
            return why
        _log(self.move, f"candidate {self.target.id[:12]} verified new-chat and stable owner={self.owner}", "success")
        return ""

    async def _discard(self) -> None:
        await _disconnect(self.page)
        if self.target is not None:
            try:
                await asyncio.to_thread(close_tab_sync, *self.move.endpoint, self.target.id)
            except Exception:
                pass
        await _disconnect(self.browser)


async def prove_candidate(move) -> tuple[CandidateProof | None, str]:
    """Create/prove one candidate; failed proof closes only that candidate."""
    return await CandidateAttempt(move).run()


async def _browser_connection(endpoint) -> tuple[Any | None, str]:
    ws, err = await asyncio.to_thread(fetch_browser_ws_url_sync, *endpoint)
    if err or not ws:
        return None, f"browser-level CDP unavailable ({err})"
    client = CDPClient(*endpoint)
    try:
        connected = await asyncio.wait_for(client.connect(ws), timeout=12.0)
    except Exception:
        await _disconnect(client)
        raise
    if connected:
        return client, ""
    await _disconnect(client)
    return None, "could not connect to browser-level CDP"


async def _open_candidate(browser, move) -> tuple[TabInfo | None, str]:
    target, err = await open_tab_in_same_context(
        browser, move.endpoint, move.url, move.old_id)
    if target is None:
        return None, f"same-context candidate could not be created ({err})"
    return target, ""


async def _candidate_page(target, endpoint):
    client = CDPClient(*endpoint)
    try:
        connected = await asyncio.wait_for(client.connect(target.ws_url), timeout=12.0)
    except Exception:
        await _disconnect(client)
        raise
    if connected:
        return client
    await _disconnect(client)
    return None


async def _stable_owner(page, expected: str, timeout_sec: float) -> tuple[bool, str]:
    deadline = time.monotonic() + min(max(1.0, timeout_sec), IDENTITY_WAIT_SEC)
    stable, last = 0, ""
    while time.monotonic() < deadline:
        try:
            owner = await asyncio.wait_for(
                _read_owner(page), timeout=min(IDENTITY_REQUEST_SEC, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            owner = ""
        if owner and owner != expected:
            return False, f"Arena owner mismatch source={expected} candidate={owner}"
        stable = stable + 1 if owner == expected else 0
        last = owner or "unknown"
        if stable >= 2:
            return True, ""
        await asyncio.sleep(min(IDENTITY_POLL_SEC, max(0.0, deadline - time.monotonic())))
    return False, f"candidate Arena owner was not stably proven (last={last}; expected={expected})"


async def _read_owner(client) -> str:
    try:
        from app.browser.owner_probe import build_owner_probe, interpret_owner
        raw = await client.evaluate(build_owner_probe())
        return normalize_owner(interpret_owner(raw).get("email"))
    except Exception:
        return ""


def _context_label(context: str | None) -> str:
    return context if context is not None else "default"


def _context_mismatch(source, candidate, found) -> str:
    label = _context_label(candidate) if found else "unknown"
    return f"candidate context mismatch/unknown (source={_context_label(source)} candidate={label})"


async def dispose_proof(proof: CandidateProof, close_candidate: bool) -> None:
    """Disconnect temporary clients and close an uncommitted candidate only."""
    await _disconnect(proof.page_client)
    if close_candidate:
        try:
            await asyncio.to_thread(close_tab_sync, proof.browser_client._host,
                                    proof.browser_client._port, proof.target.id)
        except Exception:
            pass
    await _disconnect(proof.browser_client)


async def _disconnect(client) -> None:
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass


def _log(move, message: str, level: str) -> None:
    try:
        move.ctx.bridge._log(f"🗂 {move.label}: {message}", level)
    except Exception:
        pass
