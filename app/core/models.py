from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime
from .enums import UrlStatus, ImageStatus, JobStatus, RunState
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

    @staticmethod
    def create(url: str, enabled: bool = True) -> "UrlRow":
        return UrlRow(
            id=f"url_{uuid.uuid4().hex[:8]}",
            url=url,
            enabled=enabled,
            last_status=UrlStatus.UNCHECKED.value,
            last_checked=None,
            error=None,
        )

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
            status=ImageStatus.PENDING.value if not selected else ImageStatus.SELECTED.value,
            selected=selected,
            assigned_url_id=None,
            attempt_count=0,
            output_path=None,
            error=None,
            content_hash=d.get("content_hash"),
        )

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
    def create(image: ImageItem, url: UrlRow, correlation_id: str, prompt: str, attempt: int = 1) -> "JobRecord":
        return JobRecord(
            job_id=correlation_id,  # use correlation as job_id for simplicity
            image_id=image.id,
            image_path=image.absolute_path,
            url_id=url.id,
            url=url.url,
            correlation_id=correlation_id,
            attempt=attempt,
            status=JobStatus.CREATED.value,
            created_at=now_iso(),
            baseline={},
            prompt=prompt,
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
        total = len(self.images)
        selected = sum(1 for img in self.images if img.selected)
        pending = sum(1 for img in self.images if img.status == ImageStatus.PENDING.value and img.selected)
        # Also count selected that are pending status? Let's treat SELECTED as pending if not processed
        # For simplicity, pending includes both PENDING and SELECTED
        pending_selected = sum(1 for img in self.images if img.selected and img.status in [ImageStatus.PENDING.value, ImageStatus.SELECTED.value])
        processing = sum(1 for img in self.images if img.status == ImageStatus.PROCESSING.value)
        completed = sum(1 for img in self.images if img.status == ImageStatus.COMPLETED.value)
        skipped = sum(1 for img in self.images if img.status == ImageStatus.SKIPPED.value)
        failed = sum(1 for img in self.images if img.status == ImageStatus.FAILED.value)
        needs_review = sum(1 for img in self.images if img.status == ImageStatus.NEEDS_REVIEW.value)

        self.progress = {
            "total": total,
            "selected": selected,
            "pending": pending_selected,
            "processing": processing,
            "completed": completed,
            "skipped": skipped,
            "failed": failed,
            "needs_review": needs_review,
        }

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
        urls = [UrlRow(**u) for u in d.get("urls", [])]
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
            folder=d.get("folder", {"root_path": "", "supported_types": [".png", ".jpg", ".jpeg", ".webp"], "ignore_ai_suffix": True}),
            prompt=d.get("prompt", {"user_prompt": "", "preview_with_token": ""}),
            settings=settings,
            images=images,
            jobs=jobs,
            progress=d.get("progress", {"total":0,"selected":0,"pending":0,"processing":0,"completed":0,"skipped":0,"failed":0,"needs_review":0}),
            run_state=d.get("run_state", RunState.IDLE.value),
            last_run=d.get("last_run"),
        )
