"""Offline target selection; a discovered match is never proof of a live connection."""

from dataclasses import dataclass
from enum import StrEnum

from image_queue.domain.urls import UrlRow
from image_queue.domain.validation import ContractError


class MatchStatus(StrEnum):
    DISABLED = "disabled"
    MISSING = "page_not_open"
    UNIQUE = "exact_candidate"
    AMBIGUOUS = "choose_tab"


@dataclass(frozen=True, slots=True)
class PageTarget:
    """Minimal discovery data. No websocket endpoint, cookies or private title in logs."""

    target_id: str
    url: str
    kind: str = "page"


@dataclass(frozen=True, slots=True)
class TabMatch:
    """Candidates only; transport and page readiness must be checked separately."""

    row_id: str
    status: MatchStatus
    target_ids: tuple[str, ...] = ()


def match_open_tabs(row: UrlRow, targets: tuple[PageTarget, ...]) -> TabMatch:
    """No fuzzy fallback, auto-navigation or implicit choice of duplicate exact tabs."""
    if not row.enabled:
        return TabMatch(row.row_id, MatchStatus.DISABLED)
    ids = [target.target_id for target in targets if target.target_id]
    if len(ids) != len(set(ids)):
        raise ContractError("tab discovery: duplicate target IDs; refresh before connecting")
    candidates = tuple(target.target_id for target in targets if _matches(row, target))
    if not candidates:
        return TabMatch(row.row_id, MatchStatus.MISSING)
    status = MatchStatus.UNIQUE if len(candidates) == 1 else MatchStatus.AMBIGUOUS
    return TabMatch(row.row_id, status, candidates)


def _matches(row: UrlRow, target: PageTarget) -> bool:
    return bool(target.target_id) and target.kind == "page" and target.url == row.exact_url
