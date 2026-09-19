"""Action Blocks for Arena — stacking jobs with visual confirmations.

Restored from Old App's configurable action-block system (Find & Click),
adjusted for Arena image-to-image workflow.

Old App pattern:
- Registry self-registration via block_id
- BlockField: ONE setting = panel entry + cleaning + visual-click keyword
- DeclaredSettings: FIELDS tuple drives constructor, to_dict, config_schema
- FindClickBlock: finds something, RED outline, pause, ORANGE outline, click
- MarkerBlock: engine-driven

Arena adaptation:
- Each job (image processing) is a stack of blocks
- Visual runner restored: RED find, ORANGE click, GREEN collect, BLUE prompt, YELLOW submit
- Generic CUSTOM_FIND block allows clicking any btn/text area with visual confirmations
- All block settings plain instance attributes (RULE 3) for round-trip via to_dict()
- Durations configurable per block and saved in preset JSON (all UI params storable)
- Persistence: config/arena.json + config/session.json + custom_blocks presets

Blocks:
- CUSTOM_FIND: generic find & click (click on btn, text areas)
- OBSERVE_BASELINE, CHECK_SECURITY (captcha), HIGHLIGHT_ATTACH, ATTACH_IMAGE, VERIFY_ATTACHMENT
- HIGHLIGHT_PROMPT, INSERT_PROMPT, VERIFY_PROMPT
- HIGHLIGHT_SUBMIT, SUBMIT, WAIT_OUTPUT, AWAIT_PROCESSING_IMAGE (waiting), DOWNLOAD, VALIDATE, SAVE, ADVANCE
- PAUSE, HIGHLIGHT (pure visual)
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any
import copy
import json
import uuid

RETIRED_KEYS = [
    "use_panel_filters",
    "skip_if_backlog",
    "backlog_threshold",
    "file_pattern",
    "rotation_mode",
    "simulate_dialog_old",
]

BLOCK_DEFINITIONS = {
    "CUSTOM_FIND": {
        "name": "Find & Click",
        "description": "Generic visual click — click on btn, text areas, images. RED outline on found, pause, ORANGE on click target.",
        "icon": "search",
        "default_enabled": True,
        "default_selector": "button",
        "default_label_selector": "",
        "default_match_text": "",
        "default_match_mode": "contains",
        "default_click_enabled": True,
        "default_click_selector": "",
        "default_highlight_enabled": True,
        "default_color": "#ff2d2d",
        "default_timeout_ms": 10000,
        "default_pre_delay_ms": 200,
        "default_highlight_ms": 2000,
        "default_confirm_pause_ms": 700,
        "required": False,
        "category": "action",
        "allow_duplicate": True,
        "labels": {
            "custom_name": "Block name (shown in stack & logs)",
            "selector": "① Element to find — the clickable box (CSS)",
            "label_selector": "② Separate text element inside it to confirm (CSS, optional)",
            "match_text": "Text it must contain (empty = first match) — {{job_id}} = job id",
            "match_mode": "Match mode — contains or exact",
            "click_enabled": "Click after found",
            "click_selector": "Or click this inner element instead (CSS, optional)",
            "highlight_enabled": "Visual confirmation — 🟥 red outline on found, 🟧 orange on click target",
            "color": "Highlight color (hex)",
            "confirm_pause_ms": "Pause after found, to eyeball red outline (ms)",
            "highlight_ms": "How long each outline stays visible (ms)",
            "pre_delay_ms": "Pre-delay (ms)",
            "timeout_ms": "Timeout (ms)",
            "enabled": "Enabled",
        },
    },
    "OBSERVE_BASELINE": {
        "name": "Observe Baseline",
        "description": "Capture existing outputs count before generation",
        "icon": "visibility",
        "default_enabled": True,
        "default_selector": "div.no-scrollbar img[src*=\".r2.cloudflarestorage.com/\"]",
        "default_color": "#5AA9FF",
        "default_timeout_ms": 10000,
        "default_pre_delay_ms": 200,
        "default_highlight_ms": 1200,
        "default_confirm_pause_ms": 0,
        "default_highlight_enabled": False,
        "required": True,
        "category": "observe",
        "labels": {
            "selector": "Baseline output selector",
            "highlight_enabled": "Draw GREEN outline on baseline count",
            "highlight_ms": "Highlight duration (ms)",
            "pre_delay_ms": "Pre-delay (ms)",
        },
    },
    "CHECK_SECURITY": {
        "name": "Check Security Verification Dialog",
        "description": "Detect CAPTCHA / security verification, pause for manual solve (never bypass). Visualize pause state in webpage corner — unmistakable.",
        "icon": "captcha",
        "default_enabled": True,
        "default_selector": "div[role=\"dialog\"][data-state=\"open\"], iframe[title*=\"reCAPTCHA\"], div:has-text(\"Security Verification\"), div:has-text(\"captcha\"), [data-testid=\"security-dialog\"]",
        "default_match_text": "Security Verification",
        "default_color": "#FF6B6B",
        "default_timeout_ms": 5000,
        "default_pre_delay_ms": 200,
        "default_highlight_ms": 2000,
        "default_confirm_pause_ms": 0,
        "default_highlight_enabled": True,
        "required": False,
        "category": "security",
        "labels": {
            "selector": "Security dialog selector (CSS) — detects captcha, shows ON PAUSE badge",
            "match_text": "Text that indicates security dialog",
            "highlight_enabled": "Visual confirmation + pause corner overlay",
            "highlight_ms": "Highlight duration (ms)",
        },
    },
    "HIGHLIGHT_ATTACH": {
        "name": "Highlight Attach Input",
        "description": "Visual rect over file input before attaching (GREEN)",
        "icon": "highlight",
        "default_enabled": True,
        "default_selector": "input[type=\"file\"]",
        "default_color": "#4ADE80",
        "default_timeout_ms": 5000,
        "default_pre_delay_ms": 100,
        "default_highlight_ms": 2000,
        "default_confirm_pause_ms": 300,
        "default_highlight_enabled": True,
        "required": False,
        "category": "visual",
        "labels": {
            "selector": "File input selector",
            "color": "Highlight color",
            "highlight_ms": "Duration (ms)",
            "confirm_pause_ms": "Pause after found (ms)",
        },
    },
    "ATTACH_IMAGE": {
        "name": "Attach Image",
        "description": "Attach image via CDP DOM.setFileInputFiles, verify preview. Human-like flow with visual confirmation.",
        "icon": "attach_file",
        "default_enabled": True,
        "default_selector": "input[type=\"file\"]",
        "default_label_selector": "",
        "default_match_text": "",
        "default_click_selector": "button[aria-label=\"Add files\"]",
        "default_color": "#00FF00",
        "default_timeout_ms": 15000,
        "default_pre_delay_ms": 300,
        "default_highlight_ms": 2000,
        "default_confirm_pause_ms": 700,
        "default_highlight_enabled": True,
        "default_click_enabled": True,
        "required": True,
        "category": "action",
        "labels": {
            "selector": "File input selector (hidden input)",
            "click_selector": "Button that opens file dialog (human-like, optional)",
            "highlight_enabled": "Draw confirmation outlines (red=find, orange=click)",
            "confirm_pause_ms": "Pause after found (ms)",
            "highlight_ms": "Outline visible (ms)",
            "pre_delay_ms": "Pre-delay (ms)",
            "timeout_ms": "Verify preview timeout (ms)",
        },
    },
    "VERIFY_ATTACHMENT": {
        "name": "Verify Attachment",
        "description": "Check attachment preview exists (div.flex.flex-wrap.gap-2 img)",
        "icon": "fact_check",
        "default_enabled": True,
        "default_selector": "div.flex.flex-wrap.gap-2 img",
        "default_color": "#00FF00",
        "default_timeout_ms": 8000,
        "default_pre_delay_ms": 200,
        "default_highlight_ms": 1500,
        "default_highlight_enabled": True,
        "required": False,
        "category": "verify",
        "labels": {
            "selector": "Attachment preview selector",
            "highlight_enabled": "Highlight preview",
        },
    },
    "HIGHLIGHT_PROMPT": {
        "name": "Highlight Prompt",
        "description": "Visual rect over prompt textarea (BLUE)",
        "icon": "highlight",
        "default_enabled": True,
        "default_selector": "textarea[name=\"message\"]",
        "default_color": "#00AAFF",
        "default_timeout_ms": 5000,
        "default_pre_delay_ms": 100,
        "default_highlight_ms": 2000,
        "default_highlight_enabled": True,
        "required": False,
        "category": "visual",
        "labels": {
            "selector": "Prompt textarea selector",
            "color": "Color",
            "highlight_ms": "Duration (ms)",
        },
    },
    "INSERT_PROMPT": {
        "name": "Insert Prompt",
        "description": "Insert final prompt with [JOB-ID] token, verify read-back",
        "icon": "edit",
        "default_enabled": True,
        "default_selector": "textarea[name=\"message\"]",
        "default_color": "#00AAFF",
        "default_timeout_ms": 10000,
        "default_pre_delay_ms": 200,
        "default_highlight_ms": 1500,
        "default_highlight_enabled": True,
        "required": True,
        "category": "action",
        "labels": {
            "selector": "Textarea selector",
            "highlight_enabled": "Highlight textarea before insert (BLUE)",
            "pre_delay_ms": "Pre-delay (ms)",
        },
    },
    "VERIFY_PROMPT": {
        "name": "Verify Prompt",
        "description": "Read back textarea value and verify exact match with token",
        "icon": "verified",
        "default_enabled": True,
        "default_selector": "textarea[name=\"message\"]",
        "default_color": "#00AAFF",
        "default_timeout_ms": 5000,
        "default_pre_delay_ms": 100,
        "default_highlight_ms": 1000,
        "required": False,
        "category": "verify",
        "labels": {
            "selector": "Textarea selector",
        },
    },
    "HIGHLIGHT_SUBMIT": {
        "name": "Highlight Submit",
        "description": "Visual rect over Send button (YELLOW)",
        "icon": "highlight",
        "default_enabled": True,
        "default_selector": "button[aria-label=\"Send message\"]",
        "default_color": "#FFAA00",
        "default_timeout_ms": 5000,
        "default_pre_delay_ms": 100,
        "default_highlight_ms": 2000,
        "default_highlight_enabled": True,
        "required": False,
        "category": "visual",
        "labels": {
            "selector": "Send button selector",
            "color": "Color",
            "highlight_ms": "Duration (ms)",
        },
    },
    "SUBMIT": {
        "name": "Submit Once",
        "description": "Click Send button once, confirm processing state, fallback to icon button.",
        "icon": "send",
        "default_enabled": True,
        "default_selector": "button[aria-label=\"Send message\"]:not([disabled])",
        "default_label_selector": "",
        "default_match_text": "",
        "default_click_selector": "",
        "default_fallback_selector": "form:has(textarea[name=\"message\"]) button[aria-label=\"Send message\"]:not([disabled]), div.flex.items-center.gap-2 button[aria-label=\"Send message\"]:not([disabled]), form button:has(svg):not([disabled])",
        "default_fallback_text": "",
        "default_color": "#FFAA00",
        "default_timeout_ms": 15000,
        "default_pre_delay_ms": 500,
        "default_highlight_ms": 2000,
        "default_confirm_pause_ms": 700,
        "default_highlight_enabled": True,
        "default_click_enabled": True,
        "required": True,
        "category": "action",
        "labels": {
            "selector": "Send button selector (CSS) — primary should be :not([disabled])",
            "fallback_selector": "Fallback button selector",
            "fallback_text": "Fallback icon text",
            "highlight_enabled": "Visual confirmation outlines",
            "confirm_pause_ms": "Pause after found (ms)",
            "highlight_ms": "Outline visible (ms)",
            "pre_delay_ms": "Pre-delay (ms)",
            "timeout_ms": "Timeout waiting for enabled button (ms)",
        },
    },
    "WAIT_OUTPUT": {
        "name": "Wait New Output",
        "description": "Wait for genuinely new output image (baseline comparison), understands spinner as generating indicator. GREEN rect on new output. User can set max waiting time in Settings → Generation timeout.",
        "icon": "hourglass_top",
        "default_enabled": True,
        "default_selector": "div.no-scrollbar img[src*=\".r2.cloudflarestorage.com/\"], div[data-testid=\"output\"] img, div.no-scrollbar img, img.aspect-square.cursor-pointer, main img[src*=\".r2.cloudflarestorage.com/\"]",
        "default_color": "#00c853",
        "default_timeout_ms": 120000,
        "default_pre_delay_ms": 500,
        "default_highlight_ms": 3000,
        "default_highlight_enabled": True,
        "required": True,
        "category": "wait",
        "labels": {
            "selector": "Output image selector",
            "timeout_ms": "Max wait (ms) — user can override via Settings Generation timeout (e.g. 120000 = 2 min)",
            "highlight_enabled": "🟢 Highlight new output",
            "highlight_ms": "Highlight duration (ms)",
            "pre_delay_ms": "Pre-delay (ms)",
        },
    },
    "AWAIT_PROCESSING_IMAGE": {
        "name": "Wait for Image to Finish Generating",
        "description": "Waiting block when system detects awaiting elements e.g. processing image, awaiting API result. Shows waiting state clearly, not error. Does NOT return error on timeout if non-required, waits up to user-configured max time.",
        "icon": "await_result",
        "default_enabled": True,
        "default_selector": "div:has-text(\"Processing\"), div:has-text(\"Generating\"), [data-state=\"loading\"], .spinner, [aria-busy=\"true\"]",
        "default_match_text": "Processing",
        "default_color": "#FFAA00",
        "default_timeout_ms": 120000,
        "default_pre_delay_ms": 300,
        "default_highlight_ms": 2000,
        "default_confirm_pause_ms": 0,
        "default_highlight_enabled": True,
        "required": False,
        "category": "process",
        "allow_duplicate": True,
        "labels": {
            "selector": "Processing indicator selector — detects awaiting elements",
            "match_text": "Text that indicates processing",
            "highlight_enabled": "Visual confirmation — shows waiting state",
            "timeout_ms": "Max wait for processing to finish (ms)",
            "highlight_ms": "Highlight duration (ms)",
        },
    },
    "DOWNLOAD": {
        "name": "Download Highest Quality",
        "description": "Download new output image, pick highest quality src",
        "icon": "download",
        "default_enabled": True,
        "default_selector": "",
        "default_color": "#00FFAA",
        "default_timeout_ms": 30000,
        "required": True,
        "category": "action",
        "labels": {
            "timeout_ms": "Download timeout (ms)",
        },
    },
    "VALIDATE": {
        "name": "Validate Image",
        "description": "Validate downloaded bytes is valid image, not HTML, dimensions >0 via PIL",
        "icon": "verified",
        "default_enabled": True,
        "default_selector": "",
        "default_color": "#00FFAA",
        "default_timeout_ms": 5000,
        "required": True,
        "category": "verify",
    },
    "SAVE": {
        "name": "Save *_AI.ext Atomically",
        "description": "Save beside source with _AI suffix, unique if exists, atomic write",
        "icon": "save",
        "default_enabled": True,
        "default_selector": "",
        "default_color": "#4ADE80",
        "default_timeout_ms": 5000,
        "required": True,
        "category": "persist",
        "extra_defaults": {"suffix": "_AI", "overwrite": False},
        "labels": {
            "suffix": "Suffix (e.g. _AI)",
            "overwrite": "Overwrite if exists",
        },
    },
    "ADVANCE": {
        "name": "Advance & Persist",
        "description": "Mark job completed, recalculate progress, persist state atomically",
        "icon": "check_circle",
        "default_enabled": True,
        "default_selector": "",
        "default_color": "#4ADE80",
        "default_timeout_ms": 2000,
        "required": True,
        "category": "persist",
    },
    "PAUSE": {
        "name": "Custom Pause",
        "description": "Pause N ms — for waiting, manual observation, ON PAUSE state",
        "icon": "pause",
        "default_enabled": True,
        "default_selector": "",
        "default_color": "#888888",
        "default_timeout_ms": 1000,
        "default_pre_delay_ms": 0,
        "required": False,
        "category": "control",
        "allow_duplicate": True,
        "extra_defaults": {"duration_ms": 1000},
        "labels": {
            "duration_ms": "Duration (ms) — shows ON PAUSE in corner",
            "enabled": "Enabled",
        },
    },
    "HIGHLIGHT": {
        "name": "Highlight Only",
        "description": "Pure visual confirmation — highlight element without clicking",
        "icon": "center_focus_strong",
        "default_enabled": True,
        "default_selector": "div",
        "default_label_selector": "",
        "default_match_text": "",
        "default_color": "#00c853",
        "default_timeout_ms": 5000,
        "default_pre_delay_ms": 100,
        "default_highlight_ms": 2000,
        "required": False,
        "category": "visual",
        "allow_duplicate": True,
        "labels": {
            "selector": "Element to highlight (CSS)",
            "label_selector": "Inner text element (CSS, optional)",
            "match_text": "Text it must contain (empty = first)",
            "color": "Color",
            "highlight_ms": "Duration (ms)",
            "pre_delay_ms": "Pre-delay (ms)",
        },
    },
}

DEFAULT_STACK_ORDER = [
    "HIGHLIGHT_ATTACH",
    "OBSERVE_BASELINE",
    "CHECK_SECURITY",
    "AWAIT_PROCESSING_IMAGE",
    "ATTACH_IMAGE",
    "VERIFY_ATTACHMENT",
    "HIGHLIGHT_PROMPT",
    "INSERT_PROMPT",
    "VERIFY_PROMPT",
    "HIGHLIGHT_SUBMIT",
    "SUBMIT",
    "WAIT_OUTPUT",
    "DOWNLOAD",
    "VALIDATE",
    "SAVE",
    "ADVANCE",
]

BUILTIN_BLOCKS = []
for _bid, _def in BLOCK_DEFINITIONS.items():
    BUILTIN_BLOCKS.append(
        {
            "block_id": _bid,
            "name": _def.get("name", _bid),
            "icon": _def.get("icon", "extension"),
            "description": _def.get("description", ""),
            "category": _def.get("category", "action"),
            "required": _def.get("required", False),
            "allow_duplicate": _def.get("allow_duplicate", False),
            "defaults": {
                "selector": _def.get("default_selector", ""),
                "label_selector": _def.get("default_label_selector", ""),
                "match_text": _def.get("default_match_text", ""),
                "match_mode": _def.get("default_match_mode", "contains"),
                "click_enabled": _def.get("default_click_enabled", True),
                "click_selector": _def.get("default_click_selector", ""),
                "fallback_selector": _def.get("default_fallback_selector", ""),
                "fallback_text": _def.get("default_fallback_text", ""),
                "highlight_enabled": _def.get("default_highlight_enabled", True),
                "color": _def.get("default_color", "#FF0000"),
                "timeout_ms": _def.get("default_timeout_ms", 10000),
                "pre_delay_ms": _def.get("default_pre_delay_ms", 200),
                "highlight_ms": _def.get("default_highlight_ms", 2000),
                "confirm_pause_ms": _def.get("default_confirm_pause_ms", 700),
                "enabled": _def.get("default_enabled", True),
                **(_def.get("extra_defaults", {})),
            },
            "labels": _def.get("labels", {}),
        }
    )


@dataclass
class ActionBlock:
    id: str
    block_id: str
    name: str
    description: str
    icon: str
    enabled: bool = True
    selector: str = ""
    label_selector: str = ""
    match_text: str = ""
    match_mode: str = "contains"
    click_enabled: bool = True
    click_selector: str = ""
    fallback_selector: str = ""
    fallback_text: str = ""
    highlight_enabled: bool = True
    color: str = "#FF0000"
    timeout_ms: int = 10000
    required: bool = False
    category: str = "action"
    custom_name: str = ""
    pre_delay_ms: int = 200
    highlight_ms: int = 2000
    confirm_pause_ms: int = 700
    highlight_duration_ms: int = 2000
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["highlight_duration_ms"] = self.highlight_ms
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionBlock":
        data = _migrate_block_dict(data)
        return cls(**_block_kwargs(data))

    @property
    def display_name(self) -> str:
        return self.custom_name.strip() if self.custom_name.strip() else self.name

    def config_schema(self) -> Dict[str, Any]:
        defn = BLOCK_DEFINITIONS.get(self.block_id, {})
        labels = defn.get("labels", {})
        schema = {
            "custom_name": {"type": "text", "default": "", "label": labels.get("custom_name", "Custom name")},
            "selector": {"type": "text", "default": defn.get("default_selector", ""), "label": labels.get("selector", "Selector")},
            "label_selector": {"type": "text", "default": "", "label": labels.get("label_selector", "Label selector")},
            "match_text": {"type": "text", "default": "", "label": labels.get("match_text", "Match text")},
            "match_mode": {"type": "select", "default": "contains", "options": ["contains", "exact"], "label": "Match mode"},
            "click_enabled": {"type": "checkbox", "default": True, "label": "Click enabled"},
            "click_selector": {"type": "text", "default": "", "label": "Click selector"},
            "highlight_enabled": {"type": "checkbox", "default": True, "label": "Highlight enabled"},
            "color": {"type": "text", "default": "#FF0000", "label": "Color"},
            "pre_delay_ms": {"type": "number", "default": 200, "label": "Pre-delay (ms)"},
            "confirm_pause_ms": {"type": "number", "default": 700, "label": "Confirm pause (ms)"},
            "highlight_ms": {"type": "number", "default": 2000, "label": "Highlight duration (ms)"},
            "timeout_ms": {"type": "number", "default": 10000, "label": "Timeout (ms)"},
            "enabled": {"type": "checkbox", "default": True, "label": "Enabled"},
        }
        return schema


def create_default_block(block_type: str, custom_id: str = None) -> "ActionBlock":
    defn = BLOCK_DEFINITIONS.get(block_type, {})
    extra = dict(defn.get("extra_defaults", {}))
    return ActionBlock(
        id=custom_id or f"{block_type.lower()}_{uuid.uuid4().hex[:8]}",
        block_id=block_type,
        name=defn.get("name", block_type),
        description=defn.get("description", ""),
        icon=defn.get("icon", "extension"),
        enabled=defn.get("default_enabled", True),
        selector=defn.get("default_selector", ""),
        label_selector=defn.get("default_label_selector", ""),
        match_text=defn.get("default_match_text", ""),
        match_mode=defn.get("default_match_mode", "contains"),
        click_enabled=defn.get("default_click_enabled", True),
        click_selector=defn.get("default_click_selector", ""),
        fallback_selector=defn.get("default_fallback_selector", ""),
        fallback_text=defn.get("default_fallback_text", ""),
        highlight_enabled=defn.get("default_highlight_enabled", True),
        color=defn.get("default_color", "#FF0000"),
        required=defn.get("required", False),
        category=defn.get("category", "action"),
        timeout_ms=defn.get("default_timeout_ms", 10000),
        highlight_ms=defn.get("default_highlight_ms", 2000),
        highlight_duration_ms=defn.get("default_highlight_ms", 2000),
        pre_delay_ms=defn.get("default_pre_delay_ms", 200),
        confirm_pause_ms=defn.get("default_confirm_pause_ms", 700),
        extra=extra,
    )


def default_stack() -> List[ActionBlock]:
    return [create_default_block(bt) for bt in DEFAULT_STACK_ORDER]


def load_stack_from_dicts(dicts: List[Dict[str, Any]]) -> List[ActionBlock]:
    blocks = _blocks_from_dicts(dicts)
    _ensure_required_blocks(blocks)
    return blocks


def _blocks_from_dicts(dicts: List[Dict[str, Any]]) -> List[ActionBlock]:
    """Valid persisted dicts -> ActionBlocks (invalid entries skipped)."""
    blocks: List[ActionBlock] = []
    for d in dicts:
        try:
            block = _block_from_persisted(d)
            if block is not None:
                blocks.append(block)
        except Exception:
            continue
    return blocks


def _block_from_persisted(d: Any) -> "ActionBlock | None":
    """One persisted entry -> block (None for non-dicts)."""
    if not isinstance(d, dict):
        return None
    for rk in RETIRED_KEYS:
        d.pop(rk, None)
    if "block_id" in d:
        return ActionBlock.from_dict(d)
    bt = d.get("id") or d.get("block_id") or ""
    if bt in BLOCK_DEFINITIONS:
        return create_default_block(bt, custom_id=d.get("id"))
    return ActionBlock.from_dict(d)


def _ensure_required_blocks(blocks: List[ActionBlock]) -> None:
    """Append missing required blocks (in-place)."""
    existing_types = {b.block_id for b in blocks}
    for req_type, defn in BLOCK_DEFINITIONS.items():
        if defn.get("required") and req_type not in existing_types:
            blocks.append(create_default_block(req_type))


def stack_to_dicts(stack: List[ActionBlock]) -> List[Dict[str, Any]]:
    return [b.to_dict() for b in stack]


def validate_stack(stack: List[ActionBlock]) -> tuple[bool, str]:
    if not stack:
        return False, "Stack empty"
    types = {b.block_id: b for b in stack}
    for bt, defn in BLOCK_DEFINITIONS.items():
        if defn.get("required"):
            if bt not in types:
                return False, f"Required block {bt} missing"
            if not types[bt].enabled:
                return False, f"Required block {bt} disabled"
    return True, ""


def get_default_stack_json() -> str:
    return json.dumps(stack_to_dicts(default_stack()), ensure_ascii=False, indent=2)


def parse_stack_json(payload: str) -> List[ActionBlock]:
    try:
        data = json.loads(payload or "[]")
        if isinstance(data, list):
            return load_stack_from_dicts(data)
    except Exception:
        pass
    return default_stack()


def get_builtin_blocks_json() -> str:
    return json.dumps(BUILTIN_BLOCKS, ensure_ascii=False, indent=2)
def _is_other_preset(entry, clean: str) -> bool:
    """True for dict presets whose name survives an upsert."""
    return isinstance(entry, dict) and entry.get("name") != clean


def upsert_stack_preset(presets, name: str, blocks: list) -> list:
    """Upsert a named full-stack snapshot; latest save moves to the end."""
    clean = (name or "").strip()
    if not clean:
        raise ValueError("preset name required")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("stack must be a non-empty list")
    kept = [p for p in (presets or []) if _is_other_preset(p, clean)]
    kept.append({"name": clean, "blocks": copy.deepcopy(blocks)})
    return kept


def remove_stack_preset(presets, name: str) -> tuple:
    """Remove a named stack snapshot; (kept, removed?)."""
    kept = [p for p in (presets or []) if not (isinstance(p, dict) and p.get("name") == name)]
    before = len(presets) if isinstance(presets, list) else 0
    return kept, len(kept) != before



def _migrate_block_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a persisted block dict: retired keys, defaults, legacy rename."""
    for rk in RETIRED_KEYS:
        data.pop(rk, None)
    if "highlight_duration_ms" in data and "highlight_ms" not in data:
        data["highlight_ms"] = data.get("highlight_duration_ms", 2000)
    bid = data.get("block_id", "")
    defn = BLOCK_DEFINITIONS.get(bid, {})
    for key, def_key, default in _BLOCK_DEFAULT_FIELDS:
        data.setdefault(key, defn.get(def_key, default))
    data.setdefault("color", BLOCK_DEFINITIONS.get(data.get("block_id", ""), {}).get(
        "default_color", BLOCK_DEFINITIONS.get(data.get("block_id", ""), {}).get("color", "#FF0000")))
    data.setdefault("highlight_duration_ms", data.get("highlight_ms", 2000))
    data.setdefault("extra", {})
    if not data.get("id"):
        data["id"] = f"{bid.lower()}_{uuid.uuid4().hex[:8]}"
    return data


# (field, definition key, fallback default) — mirrors pre-W3 from_dict defaults
_BLOCK_DEFAULT_FIELDS = [
    ("label_selector", "default_label_selector", ""),
    ("match_text", "default_match_text", ""),
    ("match_mode", "default_match_mode", "contains"),
    ("click_enabled", "default_click_enabled", True),
    ("click_selector", "default_click_selector", ""),
    ("fallback_selector", "default_fallback_selector", ""),
    ("fallback_text", "default_fallback_text", ""),
    ("highlight_enabled", "default_highlight_enabled", True),
    ("timeout_ms", "default_timeout_ms", 10000),
    ("pre_delay_ms", "default_pre_delay_ms", 200),
    ("highlight_ms", "default_highlight_ms", 2000),
    ("confirm_pause_ms", "default_confirm_pause_ms", 700),
]


def _block_kwargs(data: Dict[str, Any]) -> Dict[str, Any]:
    """Constructor kwargs for ActionBlock from a migrated dict."""
    bid = data.get("block_id", "")
    defn = BLOCK_DEFINITIONS.get(bid, {})
    kwargs = dict(
        id=data.get("id", str(uuid.uuid4())),
        block_id=data.get("block_id", ""),
        name=data.get("name", defn.get("name", "")),
        description=data.get("description", defn.get("description", "")),
        icon=data.get("icon", defn.get("icon", "")),
        enabled=data.get("enabled", True),
        selector=data.get("selector", ""),
        extra=data.get("extra", {}),
    )
    kwargs.update(_block_behavior_kwargs(data, defn))
    return kwargs


def _block_behavior_kwargs(data: Dict[str, Any], defn: Dict[str, Any]) -> Dict[str, Any]:
    """Behavior/definition-backed kwargs (matching, fallbacks, timings)."""
    return dict(
        label_selector=data.get("label_selector", ""),
        match_text=data.get("match_text", ""),
        match_mode=data.get("match_mode", "contains"),
        click_enabled=data.get("click_enabled", True),
        click_selector=data.get("click_selector", ""),
        fallback_selector=data.get("fallback_selector", ""),
        fallback_text=data.get("fallback_text", ""),
        highlight_enabled=data.get("highlight_enabled", True),
        color=data.get("color", "#FF0000"),
        timeout_ms=data.get("timeout_ms", 10000),
        required=data.get("required", defn.get("required", False)),
        category=data.get("category", defn.get("category", "action")),
        custom_name=data.get("custom_name", ""),
        pre_delay_ms=data.get("pre_delay_ms", 200),
        highlight_ms=data.get("highlight_ms", 2000),
        confirm_pause_ms=data.get("confirm_pause_ms", 700),
        highlight_duration_ms=data.get("highlight_duration_ms", data.get("highlight_ms", 2000)),
    )
