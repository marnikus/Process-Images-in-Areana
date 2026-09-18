"""Active-composer discovery and evidence for reference-image attachment."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

_JS_DIR = Path(__file__).with_name("attachment_js")


@dataclass(frozen=True)
class AttachmentEvidence:
    ok: bool
    reason: str
    previews: tuple[str, ...] = ()


@lru_cache(maxsize=3)
def _probe(name: str) -> str:
    return (_JS_DIR / name).read_text(encoding="utf-8")


def build_verify_js(expected_filename: str, baseline: Iterable[str]) -> str:
    return f";({_probe('verify.js')})({json.dumps(expected_filename)},{json.dumps(list(baseline))})"


def _target_js(marker: str, selectors: list[str] | None) -> str:
    return f";({_probe('target.js')})({json.dumps(marker)},{json.dumps(selectors or [])})"


def _cleanup_js(marker: str) -> str:
    return f";({_probe('cleanup.js')})({json.dumps(marker)})"


def _valid_source(image_path: str) -> Path:
    source = Path(image_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Reference image is not a file: {source}")
    return source


async def _mark_target(cdp: Any, selectors: list[str] | None) -> dict[str, Any]:
    marker = secrets.token_hex(12)
    result = await cdp.evaluate(_target_js(marker, selectors))
    if not isinstance(result, dict) or not result.get("ok"):
        error = result.get("error") if isinstance(result, dict) else "no probe result"
        raise RuntimeError(f"Attachment target unavailable: {error}")
    return result


async def _target_node(cdp: Any, marker: str) -> int:
    document = await cdp.get_document()
    root_id = document.get("nodeId") if isinstance(document, dict) else None
    if not root_id:
        raise RuntimeError("Attachment target unavailable: no document root")
    node_id = await cdp.query_selector(root_id, f'[data-arena-upload-target="{marker}"]')
    if not node_id:
        raise RuntimeError("Attachment target disappeared before file selection")
    return node_id


async def _cleanup_target(cdp: Any, marker: str) -> None:
    try:
        await cdp.evaluate(_cleanup_js(marker))
    except Exception:
        pass


async def attach_file(cdp: Any, image_path: str,
                      selectors: list[str] | None = None) -> AttachmentEvidence:
    """Set a local file on the active composer's marked input."""
    try:
        source = _valid_source(image_path)
        target = await _mark_target(cdp, selectors)
    except Exception as exc:
        return AttachmentEvidence(False, str(exc))
    try:
        node_id = await _target_node(cdp, str(target["marker"]))
        if not await cdp.set_file_input_files(node_id, [str(source)]):
            return AttachmentEvidence(False, "DOM.setFileInputFiles returned a protocol error")
        reason = f"Attached {source} to active composer ({target.get('prompt', 'prompt')})"
        return AttachmentEvidence(True, reason, tuple(target.get("previews") or ()))
    except Exception as exc:
        return AttachmentEvidence(False, str(exc))
    finally:
        await _cleanup_target(cdp, str(target["marker"]))
