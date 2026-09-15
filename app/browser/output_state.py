"""Output state — pure helpers for new-output detection (no CDP/Qt).

Owns: URL normalization, size/reference predicates, fallback decision,
interpretation of JS check dict into stable status. Browser layer may
import this; this imports only stdlib. See RULE 21, RULE 15.
"""

from __future__ import annotations

from typing import Any


def normalize_src_key(src: str) -> str:
    """Strip query/hash, keep stable tail for R2 rotation."""
    if not src:
        return ""
    base = src.split("?", 1)[0].split("#", 1)[0]
    return base[-120:]


def normalize_old_keys(srcs: list[str] | None) -> set[str]:
    """Build set of normalized keys from baseline srcs."""
    if not srcs:
        return set()
    return {normalize_src_key(s) for s in srcs if s}


def _num_value(source: dict, key: str) -> int:
    """Safe int from JS dict (missing or bad becomes 0)."""
    val = source.get(key, 0)
    if isinstance(val, (int, float)):
        return int(val)
    return 0


def _rect_width(cand: dict[str, Any]) -> int:
    """Displayed width from nested rect dict."""
    rect = cand.get("rect")
    if not isinstance(rect, dict):
        return 0
    return _num_value(rect, "width")


def _cls_value(cand: dict[str, Any]) -> str:
    """Class string from className or cls key."""
    for key in ("className", "cls"):
        val = cand.get(key, "")
        if val:
            return str(val)
    return ""


def _has_50vh(cls: str) -> bool:
    """Generated images use 50vh utility."""
    return "50vh" in cls


def _has_cover_large(cls: str, rect_w: int) -> bool:
    """Cover plus displayed width looks generated."""
    return "object-cover" in cls and rect_w >= 100


def _has_square_large(cls: str, rect_w: int) -> bool:
    """Square plus displayed width looks generated."""
    return "aspect-square" in cls and rect_w >= 150


def is_large_candidate(cand: dict[str, Any]) -> bool:
    """True when displayed or intrinsic size looks generated."""
    width = _num_value(cand, "width")
    rect_w = _rect_width(cand)
    cls = _cls_value(cand)
    if width >= 200 or rect_w >= 200:
        return True
    if _has_50vh(cls):
        return True
    if _has_cover_large(cls, rect_w):
        return True
    return _has_square_large(cls, rect_w)


def _is_small_thumb(cls: str, rect_w: int) -> bool:
    """Thumbnail by displayed width or utility class."""
    if rect_w and rect_w <= 140:
        return True
    if "w-32" in cls:
        return True
    if "h-16" in cls:
        return True
    return "w-16" in cls


def is_reference_candidate(cand: dict[str, Any]) -> bool:
    """True when small thumbnail inside a job bubble."""
    if not cand.get("insideJob"):
        return False
    rect_w = _rect_width(cand)
    cls = _cls_value(cand)
    return _is_small_thumb(cls, rect_w)


def select_best_fallback(details: list[dict]) -> dict | None:
    """Pick largest bottom-most large candidate from allNew."""
    if not details:
        return None
    large = [d for d in details if d.get("isLarge")]
    pool = large if large else details
    if not pool:
        return None
    return max(pool, key=_fallback_rank)


def _fallback_rank(cand: dict[str, Any]) -> tuple:
    """Rank for fallback: larger width wins, then lower top."""
    width = cand.get("width", 0) or 0
    top = cand.get("top", 0) or 0
    return (width, top)


def should_accept_fallback(spinning: bool, stable: int, elapsed: float) -> bool:
    """Accept newest-large after spinner gone plus stability."""
    if spinning:
        return False
    if stable < 3:
        return False
    return elapsed >= 10.0


def is_terminal_ready(result: dict[str, Any]) -> bool:
    """JS says ready with usable src."""
    return bool(result.get("ready") and result.get("src"))


def is_loading_reason(reason: str) -> bool:
    """Reasons that mean image exists but not yet viewable."""
    return reason in ("not_complete", "zero_width", "hidden", "loading")


def is_order_wait_reason(reason: str) -> bool:
    """Order gate says await next image above current prompt."""
    return reason in (
        "no_exact_above_found_wait_next",
        "image_above_belongs_to_previous_prompt_await_next",
        "generating_no_new_yet",
        "no_new",
    )


def describe_order(result: dict[str, Any]) -> str:
    """Compact order diagnostics for logs (RULE 2)."""
    order = result.get("orderCheck", "") or ""
    job = result.get("jobFound")
    top = result.get("jobTop")
    prev = result.get("prevJobTop")
    valid = result.get("validAbove")
    invalid = result.get("invalidAbove")
    all_new = result.get("allNew")
    reason = result.get("reason", "")
    return (
        f"reason={reason} jobFound={job} jobTop={top} "
        f"prevTop={prev} valid={valid} invalid={invalid} "
        f"allNew={all_new} order={order[:160]}"
    )


def flatten_diagnostics(check: dict[str, Any]) -> dict[str, Any]:
    """Copy order keys to top level for bridge logs compat."""
    keys = ("orderCheck", "jobFound", "jobTop", "prevJobTop", "nextJobTop")
    keys += ("validAbove", "validBelow", "invalidAbove", "allNew", "allJobs")
    keys += ("poolKind", "reason", "jobId", "allNewDetails", "belowDetails")
    return {k: check.get(k) for k in keys if k in check}
