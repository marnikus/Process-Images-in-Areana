from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, ClassVar, Dict
import uuid

from .definitions import BLOCK_DEFINITIONS, RETIRED_KEYS

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
    use_preset: bool = False
    preset_name: str = ""
    overwrite: bool = False
    include_prompt: bool = True
    include_job_id: bool = True
    suffix: str = "_AI"
    duration_ms: int = 1000
    load_from_preset: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["highlight_duration_ms"] = self.highlight_ms
        return d

    _DEFN_DEFAULTS: ClassVar[tuple] = (
        ("label_selector","default_label_selector",""),("match_text","default_match_text",""),
        ("match_mode","default_match_mode","contains"),("click_enabled","default_click_enabled",True),
        ("click_selector","default_click_selector",""),("fallback_selector","default_fallback_selector",""),
        ("fallback_text","default_fallback_text",""),("highlight_enabled","default_highlight_enabled",True),
        ("timeout_ms","default_timeout_ms",10000),("pre_delay_ms","default_pre_delay_ms",200),
        ("highlight_ms","default_highlight_ms",2000),("confirm_pause_ms","default_confirm_pause_ms",700),
    )
    _CTOR_RAW: ClassVar[tuple] = (
        ("enabled",True),("selector",""),("label_selector",""),("match_text",""),("match_mode","contains"),
        ("click_enabled",True),("click_selector",""),("fallback_selector",""),("fallback_text",""),
        ("highlight_enabled",True),("color","#FF0000"),("timeout_ms",10000),("pre_delay_ms",200),
        ("highlight_ms",2000),("confirm_pause_ms",700),("custom_name",""),("use_preset",False),
        ("preset_name",""),("overwrite",False),("include_prompt",True),("include_job_id",True),
        ("suffix","_AI"),("duration_ms",1000),("load_from_preset",False),("extra",{}),
    )
    _CTOR_FROM_DEFN: ClassVar[tuple] = (("name","name",""),("description","description",""),("icon","icon",""),("required","required",False),("category","category","action"),)

    @staticmethod
    def _apply_definition_defaults(data: Dict[str, Any], defn: Dict[str, Any]) -> None:
        for attr, key, fb in ActionBlock._DEFN_DEFAULTS:
            data.setdefault(attr, defn.get(key, fb))
        data.setdefault("color", defn.get("default_color", defn.get("color", "#FF0000")))
        data.setdefault("highlight_duration_ms", data.get("highlight_ms", 2000))
        data.setdefault("extra", {})

    @staticmethod
    def _ctor_kwargs(data: Dict[str, Any], defn: Dict[str, Any]) -> Dict[str, Any]:
        kw = {"id": data.get("id", str(uuid.uuid4())),"block_id": data.get("block_id", ""),"highlight_duration_ms": data.get("highlight_duration_ms", data.get("highlight_ms", 2000)),}
        kw.update({attr: data.get(attr, fb) for attr, fb in ActionBlock._CTOR_RAW})
        kw.update({attr: data.get(attr, defn.get(dkey, dfb)) for attr, dkey, dfb in ActionBlock._CTOR_FROM_DEFN})
        return kw

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionBlock":
        for rk in RETIRED_KEYS:
            data.pop(rk, None)
        if "highlight_duration_ms" in data and "highlight_ms" not in data:
            data["highlight_ms"] = data.get("highlight_duration_ms", 2000)
        extra = data.get("extra", {}) if isinstance(data.get("extra"), dict) else {}
        for key in ("use_preset","preset_name","overwrite","include_prompt","include_job_id","suffix","duration_ms","load_from_preset"):
            if key in extra and key not in data:
                data[key] = extra[key]
        bid = data.get("block_id", "")
        defn = BLOCK_DEFINITIONS.get(bid, {})
        cls._apply_definition_defaults(data, defn)
        for k, v in defn.get("extra_defaults", {}).items():
            data.setdefault(k, v)
        if not data.get("id"):
            data["id"] = f"{bid.lower()}_{uuid.uuid4().hex[:8]}"
        return cls(**cls._ctor_kwargs(data, defn))

    @property
    def display_name(self) -> str:
        return self.custom_name.strip() if self.custom_name.strip() else self.name

    def config_schema(self) -> Dict[str, Any]:
        defn = BLOCK_DEFINITIONS.get(self.block_id, {})
        labels = defn.get("labels", {})
        return {
            "custom_name": {"type":"text","default":"","label":labels.get("custom_name","Custom name")},
            "selector": {"type":"text","default":defn.get("default_selector",""),"label":labels.get("selector","Selector")},
            "label_selector": {"type":"text","default":"","label":labels.get("label_selector","Label selector")},
            "match_text": {"type":"text","default":"","label":labels.get("match_text","Match text")},
            "match_mode": {"type":"select","default":"contains","options":["contains","exact"],"label":"Match mode"},
            "click_enabled": {"type":"checkbox","default":True,"label":"Click enabled"},
            "click_selector": {"type":"text","default":"","label":"Click selector"},
            "highlight_enabled": {"type":"checkbox","default":True,"label":"Highlight enabled"},
            "color": {"type":"text","default":"#FF0000","label":"Color"},
            "pre_delay_ms": {"type":"number","default":200,"label":"Pre-delay (ms)"},
            "confirm_pause_ms": {"type":"number","default":700,"label":"Confirm pause (ms)"},
            "highlight_ms": {"type":"number","default":2000,"label":"Highlight duration (ms)"},
            "timeout_ms": {"type":"number","default":10000,"label":"Timeout (ms)"},
            "enabled": {"type":"checkbox","default":True,"label":"Enabled"},
        }
