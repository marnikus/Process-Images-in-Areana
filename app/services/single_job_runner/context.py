from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("arena")

@dataclass
class JobCtx:
    """Context to keep params ≤4."""

    bridge: Any
    ctrl: Any
    client: Any
    tab_id: str
    img: Any
    urls: List[Any]
    job_id: str
    corr_id: str
    final_prompt: str
    baseline: Dict[str, Any] = field(default_factory=dict)
    text_baseline: Dict[str, Any] = field(default_factory=dict)
    new_src: Optional[str] = None
    file_bytes: Optional[bytes] = None
    ctype: Optional[str] = None
    ext: Optional[str] = None
    old_srcs: List[str] = field(default_factory=list)
    text_output: Optional[str] = None

_OUTPUT_BLOCKS = ("DOWNLOAD", "SAVE", "SAVE_DESCRIPTION_JSON")
