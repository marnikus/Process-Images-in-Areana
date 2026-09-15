"""Action Blocks for Arena — stacking jobs with visual confirmations.

Inspired by old app's configurable action-block constructor (Find & Click),
but simplified for Arena's image-to-image workflow.

Each job (image processing) is a stack of blocks:
- OBSERVE_BASELINE: capture existing outputs
- CHECK_SECURITY: check for CAPTCHA/security dialog
- HIGHLIGHT_ATTACH: visual confirmation of file input
- ATTACH_IMAGE: attach image via CDP
- HIGHLIGHT_PROMPT: visual confirmation of prompt textarea
- INSERT_PROMPT: insert prompt with JOB-ID token
- VERIFY_PROMPT: read back and verify
- HIGHLIGHT_SUBMIT: visual confirmation of send button
- SUBMIT: click send once
- WAIT_OUTPUT: wait for new output (baseline comparison)
- DOWNLOAD: download highest-quality image
- VALIDATE: validate image bytes
- SAVE: atomic save beside source with _AI suffix
- ADVANCE: mark completed and persist

Each block can be enabled/disabled, reordered (some have dependencies),
has configurable selector, timeout, highlight color/duration.

Persistence: stored in config/session.json as action_blocks stack,
and in arena presets (urls, prompt, settings, blocks).

UI: drag & drop reorder, enable toggle, config panel per block,
visual rect confirmation when block executes.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
import json
import uuid
from datetime import datetime

BLOCK_DEFINITIONS = {
    "OBSERVE_BASELINE": {
        "name": "Observe Baseline",
        "description": "Capture existing outputs count before generation",
        "icon": "visibility",
        "default_enabled": True,
        "default_selector": "",
        "color": "#888888",
        "required": True,
        "category": "observe",
    },
    "CHECK_SECURITY": {
        "name": "Check Security Dialog",
        "description": "Detect CAPTCHA / security verification, pause for manual solve",
        "icon": "security",
        "default_enabled": True,
        "default_selector": "div[role=\"dialog\"][data-state=\"open\"]",
        "color": "#FF6B6B",
        "required": False,
        "category": "observe",
    },
    "HIGHLIGHT_ATTACH": {
        "name": "Highlight Attach Input",
        "description": "Visual rect over file input before attaching",
        "icon": "highlight",
        "default_enabled": True,
        "default_selector": "input[type=\"file\"]",
        "color": "#00FF00",
        "required": False,
        "category": "visual",
    },
    "ATTACH_IMAGE": {
        "name": "Attach Image",
        "description": "Attach image via CDP DOM.setFileInputFiles, verify preview",
        "icon": "attach_file",
        "default_enabled": True,
        "default_selector": "input[type=\"file\"]",
        "color": "#00FF00",
        "required": True,
        "category": "action",
    },
    "HIGHLIGHT_PROMPT": {
        "name": "Highlight Prompt",
        "description": "Visual rect over prompt textarea",
        "icon": "highlight",
        "default_enabled": True,
        "default_selector": "textarea[name=\"message\"]",
        "color": "#00AAFF",
        "required": False,
        "category": "visual",
    },
    "INSERT_PROMPT": {
        "name": "Insert Prompt",
        "description": "Insert final prompt with [JOB-ID] token",
        "icon": "edit",
        "default_enabled": True,
        "default_selector": "textarea[name=\"message\"]",
        "color": "#00AAFF",
        "required": True,
        "category": "action",
    },
    "VERIFY_PROMPT": {
        "name": "Verify Prompt",
        "description": "Read back textarea value and verify exact match",
        "icon": "fact_check",
        "default_enabled": True,
        "default_selector": "textarea[name=\"message\"]",
        "color": "#00AAFF",
        "required": False,
        "category": "verify",
    },
    "HIGHLIGHT_SUBMIT": {
        "name": "Highlight Submit",
        "description": "Visual rect over Send button",
        "icon": "highlight",
        "default_enabled": True,
        "default_selector": "button[aria-label=\"Send message\"]",
        "color": "#FFAA00",
        "required": False,
        "category": "visual",
    },
    "SUBMIT": {
        "name": "Submit Once",
        "description": "Click Send button once, confirm processing state",
        "icon": "send",
        "default_enabled": True,
        "default_selector": "button[aria-label=\"Send message\"]",
        "color": "#FFAA00",
        "required": True,
        "category": "action",
    },
    "WAIT_OUTPUT": {
        "name": "Wait New Output",
        "description": "Wait for genuinely new output image (baseline comparison)",
        "icon": "hourglass_top",
        "default_enabled": True,
        "default_selector": "div.no-scrollbar img, div[data-testid=\"output\"] img",
        "color": "#AA00FF",
        "required": True,
        "category": "wait",
    },
    "DOWNLOAD": {
        "name": "Download Highest Quality",
        "description": "Download new output image, pick highest quality",
        "icon": "download",
        "default_enabled": True,
        "default_selector": "",
        "color": "#00FFAA",
        "required": True,
        "category": "action",
    },
    "VALIDATE": {
        "name": "Validate Image",
        "description": "Validate downloaded bytes is valid image, not HTML",
        "icon": "verified",
        "default_enabled": True,
        "default_selector": "",
        "color": "#00FFAA",
        "required": True,
        "category": "verify",
    },
    "SAVE": {
        "name": "Save *_AI.ext Atomically",
        "description": "Save beside source with _AI suffix, unique if exists, atomic write",
        "icon": "save",
        "default_enabled": True,
        "default_selector": "",
        "color": "#4ADE80",
        "required": True,
        "category": "persist",
    },
    "ADVANCE": {
        "name": "Advance & Persist",
        "description": "Mark job completed, recalculate progress, persist state",
        "icon": "check_circle",
        "default_enabled": True,
        "default_selector": "",
        "color": "#4ADE80",
        "required": True,
        "category": "persist",
    },
}

DEFAULT_STACK_ORDER = [
    "OBSERVE_BASELINE",
    "CHECK_SECURITY",
    "HIGHLIGHT_ATTACH",
    "ATTACH_IMAGE",
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

@dataclass
class ActionBlock:
    id: str
    block_id: str  # type from BLOCK_DEFINITIONS
    name: str
    description: str
    icon: str
    enabled: bool = True
    selector: str = ""
    color: str = "#FF0000"
    timeout_ms: int = 30000
    required: bool = False
    category: str = "action"
    custom_name: str = ""
    pre_delay_ms: int = 200
    highlight_duration_ms: int = 2000
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionBlock":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            block_id=data.get("block_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            icon=data.get("icon", ""),
            enabled=data.get("enabled", True),
            selector=data.get("selector", ""),
            color=data.get("color", "#FF0000"),
            timeout_ms=data.get("timeout_ms", 30000),
            required=data.get("required", False),
            category=data.get("category", "action"),
            custom_name=data.get("custom_name", ""),
            pre_delay_ms=data.get("pre_delay_ms", 200),
            highlight_duration_ms=data.get("highlight_duration_ms", 2000),
            extra=data.get("extra", {}),
        )

    @property
    def display_name(self) -> str:
        return self.custom_name.strip() if self.custom_name.strip() else self.name

def create_default_block(block_type: str, custom_id: str = None) -> ActionBlock:
    defn = BLOCK_DEFINITIONS.get(block_type, {})
    return ActionBlock(
        id=custom_id or f"{block_type.lower()}_{uuid.uuid4().hex[:8]}",
        block_id=block_type,
        name=defn.get("name", block_type),
        description=defn.get("description", ""),
        icon=defn.get("icon", ""),
        enabled=defn.get("default_enabled", True),
        selector=defn.get("default_selector", ""),
        color=defn.get("color", "#FF0000"),
        required=defn.get("required", False),
        category=defn.get("category", "action"),
        timeout_ms=30000 if defn.get("category") in ("wait", "action") else 5000,
        highlight_duration_ms=2000,
        pre_delay_ms=200,
    )

def default_stack() -> List[ActionBlock]:
    return [create_default_block(bt) for bt in DEFAULT_STACK_ORDER]

def load_stack_from_dicts(dicts: List[Dict[str, Any]]) -> List[ActionBlock]:
    blocks = []
    for d in dicts:
        try:
            # If dict has block_id, use it, otherwise try to infer
            if "block_id" in d:
                blocks.append(ActionBlock.from_dict(d))
            else:
                # Old format: maybe just string id
                bt = d.get("id") or d.get("block_id") or ""
                if bt in BLOCK_DEFINITIONS:
                    blocks.append(create_default_block(bt, custom_id=d.get("id")))
                else:
                    blocks.append(ActionBlock.from_dict(d))
        except Exception:
            continue
    # Ensure required blocks exist
    existing_types = {b.block_id for b in blocks}
    for req_type, defn in BLOCK_DEFINITIONS.items():
        if defn.get("required") and req_type not in existing_types:
            blocks.append(create_default_block(req_type))
    return blocks

def stack_to_dicts(stack: List[ActionBlock]) -> List[Dict[str, Any]]:
    return [b.to_dict() for b in stack]

def validate_stack(stack: List[ActionBlock]) -> tuple[bool, str]:
    if not stack:
        return False, "Stack empty"
    # Check required blocks present and enabled
    types = {b.block_id: b for b in stack}
    for bt, defn in BLOCK_DEFINITIONS.items():
        if defn.get("required"):
            if bt not in types:
                return False, f"Required block {bt} missing"
            if not types[bt].enabled:
                return False, f"Required block {bt} disabled"
    return True, ""

# For persistence and UI
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
