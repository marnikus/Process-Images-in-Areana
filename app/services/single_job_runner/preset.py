from __future__ import annotations
from typing import Any, Optional
from .context import JobCtx

def _block_uses_preset(block: Any) -> bool:
    """Whether block requests preset loading."""
    try:
        if getattr(block, "use_preset", False):
            return True
        if getattr(block, "load_from_preset", False):
            return True
        extra = getattr(block, "extra", {}) or {}
        return bool(extra.get("use_preset") or extra.get("load_from_preset"))
    except Exception:
        return False

def _block_preset_name(block: Any) -> str:
    """Preset name from block fields."""
    try:
        name = getattr(block, "preset_name", "") or ""
        if not name:
            extra = getattr(block, "extra", {}) or {}
            name = extra.get("preset_name", "")
        return str(name or "").strip()
    except Exception:
        return ""

def _load_preset_template(ctx: JobCtx, name: str) -> Optional[str]:
    """Load template text for a named preset."""
    try:
        if not name:
            return None
        cfg = getattr(ctx.bridge, "config", None)
        if cfg is None:
            return None
        store = getattr(cfg, "presets", None)
        if store is None:
            return None
        doc = store.load_prompt_preset(name)
        if not doc:
            return None
        tmpl = doc.get("template", "") if isinstance(doc, dict) else ""
        return tmpl.strip() or None
    except Exception:
        return None

def _resolve_prompt_from_preset(ctx: JobCtx, block: Any) -> Optional[str]:
    """Resolve prompt template from preset if block requests it."""
    if not _block_uses_preset(block):
        return None
    name = _block_preset_name(block)
    if not name:
        return None
    return _load_preset_template(ctx, name)

def _build_final_from_template(corr_id: str, template: str) -> str:
    """Final prompt with correlation token."""
    try:
        from app.utils.correlation import build_final_prompt

        return build_final_prompt(corr_id, template)
    except Exception:
        return f"{template}\n\n[JOB-ID: {corr_id}]"

