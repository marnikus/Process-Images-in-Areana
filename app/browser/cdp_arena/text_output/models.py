from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

@dataclass
class PollContextText:
    old_texts: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None
    old_outputs: List[Any] = field(default_factory=list)
    err_base: str = ""

@dataclass
class WaitSpecText:
    baseline: Dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 180000
    correlation_id: Optional[str] = None
    cancel_check: Optional[Callable] = None
    log_cb: Optional[Callable] = None
    ctrl: Any = None
