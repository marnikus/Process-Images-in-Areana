"""Models — queue rows (`UrlRow`, `ImageItem`), job records, settings and `AppState`.

Progress counting lives in `core/progress.py`; imports go core -> core only.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime
from .enums import UrlStatus, ImageStatus, JobStatus, RunState
from .progress import build_progress_counts
import uuid

def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

@dataclass
class UrlRow:
    id: str
    url: str
    enabled: bool = True
    last_status: str = UrlStatus.UNCHECKED.value
    last_checked: Optional[str] = None
    error: Optional[str] = None
    tab_id: str = ""
    receiver: bool = False  # S7: can receive a job now (one owner: live/url_policy.mark_receivers)
    typed: bool = False     # I-64: the user typed/edited this URL — never auto-removed, only unlinked

    @staticmethod
    def from_dict(d: dict) -> "UrlRow":
        """Tolerant dict→row funnel: keys this row does not have are ignored (RULE 13).

        Persisted states from older versions still carry a `browser` key on each
        url row; loading must not break on a field that no longer exists.
        """
        known = {f.name for f in fields(UrlRow)}
        return UrlRow(**{k: v for k, v in dict(d or {}).items() if k in known})

    @staticmethod
    def create(url: str, enabled: bool = True, tab_id: str = "") -> "UrlRow":
        return UrlRow(
            id=f"url_{uuid.uuid4().hex[:8]}",
            url=url,
            enabled=enabled,
            last_status=UrlStatus.UNCHECKED.value,
            last_checked=None,
            error=None,
            tab_id=tab_id,
        )

    def link_tab(self, tab_id: str) -> bool:
        if not tab_id:
            return False
        self.tab_id = tab_id
        return True


def _discovered_status(selected: bool, existing_output: str | None) -> str:
    """Discovered with an `_AI` sibling → completed (I-46); else pending / selected."""
    if existing_output:
        return ImageStatus.COMPLETED.value
    return ImageStatus.SELECTED.value if selected else ImageStatus.PENDING.value


@dataclass
class ImageItem:
    id: str
    relative_path: str
    absolute_path: str
    filename: str
    base_name: str
    extension: str
    size: int
    mtime: float
    fingerprint: str
    status: str = ImageStatus.PENDING.value
    selected: bool = False
    assigned_url_id: Optional[str] = None
    attempt_count: int = 0
    output_path: Optional[str] = None
    error: Optional[str] = None
    content_hash: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_scan_dict(d: dict, selected: bool = False) -> "ImageItem":
        output = d.get("existing_output")  # `_AI` sibling already on disk → completed (I-46)
        return ImageItem(
            id=d.get("id") or d.get("fingerprint"),
            relative_path=d["relative_path"],
            absolute_path=d["absolute_path"],
            filename=d["filename"],
            base_name=d["base_name"],
            extension=d["extension"],
            size=d["size"],
            mtime=d["mtime"],
            fingerprint=d["fingerprint"],
            status=_discovered_status(selected, output),
            selected=bool(selected and not output),
            assigned_url_id=None,
            attempt_count=0,
            output_path=output,
            error=None,
            content_hash=d.get("content_hash"),
        )

@dataclass
class JobRequest:
    """Param object for JobRecord.create (C6 spec pattern — keeps factory ≤4 params)."""
    image: ImageItem
    url: UrlRow
    correlation_id: str
    prompt: str
    attempt: int = 1


@dataclass
class JobRecord:
    job_id: str
    image_id: str
    image_path: str
    url_id: str
    url: str
    correlation_id: str
    attempt: int
    status: str
    created_at: str
    baseline: Dict[str, Any] = field(default_factory=dict)
    prompt: Optional[str] = None
    submitted_at: Optional[str] = None
    output_src: Optional[str] = None
    output_metadata: Dict[str, Any] = field(default_factory=dict)
    saved_path: Optional[str] = None
    error: Optional[str] = None
    needs_review: bool = False
    logs: List[Dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def create(req: JobRequest) -> "JobRecord":
        return JobRecord(
            job_id=req.correlation_id,
            image_id=req.image.id,
            image_path=req.image.absolute_path,
            url_id=req.url.id,
            url=req.url.url,
            correlation_id=req.correlation_id,
            attempt=req.attempt,
            status=JobStatus.CREATED.value,
            created_at=now_iso(),
            baseline={},
            prompt=req.prompt,
            submitted_at=None,
            output_src=None,
            output_metadata={},
            saved_path=None,
            error=None,
            needs_review=False,
            logs=[],
        )

@dataclass
class AppSettings:
    timeouts: Dict[str, int] = field(default_factory=lambda: {
        "page_load": 30,
        "selector": 10,
        "attachment": 15,
        "generation": 180,
        "download": 30,
    })
    retries: Dict[str, Any] = field(default_factory=lambda: {
        "max_attempts": 3,
        "backoff_seconds": [1, 3, 5],
    })
    output: Dict[str, Any] = field(default_factory=lambda: {
        "suffix": "_AI",
        "preserve_format": True,
        "overwrite": False,
        "unique_suffix_template": "{base}_AI_{n}{ext}",
    })
    highlight: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "duration_seconds": 2,
        "color": "#FF0000",
        "border_width": 3,
    })
    browser: Dict[str, Any] = field(default_factory=lambda: {
        "user_data_dir": "./browser_profile",
        "headless": False,
        "slow_mo": 0,
    })
    scheduling: str = "round-robin"
    concurrency: int = 1
    supported_types: List[str] = field(default_factory=lambda: [".png", ".jpg", ".jpeg", ".webp"])
    ignore_ai_suffix: bool = True


def _folder_from_saved(value: Any) -> Dict[str, Any]:
    """Saved `folder` → dict (null / bare path string in legacy files never brick the picker)."""
    folder: Dict[str, Any] = {"root_path": "", "supported_types": [".png", ".jpg", ".jpeg", ".webp"],
                              "ignore_ai_suffix": True}
    if isinstance(value, dict):
        folder.update(value)
    elif isinstance(value, str):
        folder["root_path"] = value.strip()
    return folder


@dataclass
class AppState:
    version: str = "1.0.0"
    urls: List[UrlRow] = field(default_factory=list)
    folder: Dict[str, Any] = field(default_factory=lambda: {
        "root_path": "",
        "supported_types": [".png", ".jpg", ".jpeg", ".webp"],
        "ignore_ai_suffix": True,
    })
    prompt: Dict[str, str] = field(default_factory=lambda: {
        "user_prompt": "",
        "preview_with_token": "",
    })
    settings: AppSettings = field(default_factory=AppSettings)
    images: List[ImageItem] = field(default_factory=list)
    jobs: List[JobRecord] = field(default_factory=list)
    progress: Dict[str, int] = field(default_factory=lambda: {
        "total": 0,
        "selected": 0,
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "skipped": 0,
        "failed": 0,
        "needs_review": 0,
    })
    run_state: str = RunState.IDLE.value
    last_run: Optional[str] = None

    def recalculate_progress(self):
        self.progress = build_progress_counts(self.images)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "urls": [asdict(u) for u in self.urls],
            "folder": self.folder,
            "prompt": self.prompt,
            "settings": asdict(self.settings),
            "images": [asdict(i) for i in self.images],
            "jobs": [asdict(j) for j in self.jobs],
            "progress": self.progress,
            "run_state": self.run_state,
            "last_run": self.last_run,
        }

    @staticmethod
    def from_dict(d: dict) -> "AppState":
        urls = [UrlRow.from_dict(u) for u in d.get("urls", [])]
        images = [ImageItem(**i) for i in d.get("images", [])]
        jobs = [JobRecord(**j) for j in d.get("jobs", [])]
        settings_dict = d.get("settings", {})
        settings = AppSettings(
            timeouts=settings_dict.get("timeouts", AppSettings().timeouts),
            retries=settings_dict.get("retries", AppSettings().retries),
            output=settings_dict.get("output", AppSettings().output),
            highlight=settings_dict.get("highlight", AppSettings().highlight),
            browser=settings_dict.get("browser", AppSettings().browser),
            scheduling=settings_dict.get("scheduling", "round-robin"),
            concurrency=settings_dict.get("concurrency", 1),
            supported_types=settings_dict.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"]),
            ignore_ai_suffix=settings_dict.get("ignore_ai_suffix", True),
        )
        return AppState(
            version=d.get("version", "1.0.0"),
            urls=urls,
            folder=_folder_from_saved(d.get("folder")),
            prompt=d.get("prompt", {"user_prompt": "", "preview_with_token": ""}),
            settings=settings,
            images=images,
            jobs=jobs,
            progress=d.get("progress", {"total":0,"selected":0,"pending":0,"processing":0,"completed":0,"skipped":0,"failed":0,"needs_review":0}),
            run_state=d.get("run_state", RunState.IDLE.value),
            last_run=d.get("last_run"),
        )
