# Data Model and Persistence Plan

## No DB Requirement
All persistence via JSON files, atomic writes, human-readable. No SQLite.

## Files

### `config/app_state.json` (or `presets.json`)
Single file containing all storable UI parameters and job history.

Structure:
```json
{
  "version": "1.0.0",
  "urls": [
    {
      "id": "url_abc123",
      "url": "https://arena.ai/c/01a0a4f3-b60a-7169-8e15-aa3f099d8e4e",
      "enabled": true,
      "last_status": "ready",
      "last_checked": "2026-09-15T14:25:30Z",
      "error": null
    }
  ],
  "folder": {
    "root_path": "/home/user/images",
    "supported_types": [".png", ".jpg", ".jpeg", ".webp"],
    "ignore_ai_suffix": true
  },
  "prompt": {
    "user_prompt": "Transform low-resolution...",
    "preview_with_token": "[JOB-ID: 20260915-142530-A7F3]\nTransform..."
  },
  "settings": {
    "timeouts": {
      "page_load": 30,
      "selector": 10,
      "attachment": 15,
      "generation": 180,
      "download": 30
    },
    "retries": {
      "max_attempts": 3,
      "backoff_seconds": [1, 3, 5]
    },
    "output": {
      "suffix": "_AI",
      "preserve_format": true,
      "overwrite": false,
      "unique_suffix_template": "{base}_AI_{n}{ext}"
    },
    "highlight": {
      "enabled": true,
      "duration_seconds": 2,
      "color": "#FF0000",
      "border_width": 2
    },
    "browser": {
      "user_data_dir": "./browser_profile",
      "headless": false,
      "slow_mo": 0
    },
    "scheduling": "round-robin",
    "concurrency": 1
  },
  "images": [
    {
      "id": "img_hash_or_path",
      "relative_path": "subfolder/02-a.jpeg",
      "absolute_path": "/home/user/images/subfolder/02-a.jpeg",
      "filename": "02-a.jpeg",
      "base_name": "02-a",
      "extension": ".jpeg",
      "size": 12345,
      "mtime": 1720000000,
      "content_hash": "optional_sha256",
      "status": "pending",
      "selected": true,
      "assigned_url_id": "url_abc123",
      "attempt_count": 0,
      "output_path": null,
      "error": null,
      "fingerprint": "path+size+mtime"
    }
  ],
  "jobs": [
    {
      "job_id": "20260915-142530-A7F3",
      "image_id": "img_...",
      "image_path": "/home/user/images/subfolder/02-a.jpeg",
      "url_id": "url_abc123",
      "url": "https://arena.ai/c/...",
      "correlation_id": "20260915-142530-A7F3",
      "attempt": 1,
      "status": "completed",
      "created_at": "2026-09-15T14:25:30Z",
      "baseline": {
        "output_count_before": 5,
        "output_srcs_before": ["https://..."],
        "timestamp": "2026-09-15T14:25:31Z"
      },
      "attachment_verified": true,
      "prompt": "[JOB-ID: 20260915-142530-A7F3]\nTransform...",
      "prompt_verified": true,
      "submitted_at": "2026-09-15T14:25:35Z",
      "output_detected_at": "2026-09-15T14:27:00Z",
      "output_src": "https://messages-prod.../image.png",
      "output_metadata": {
        "width": 1024,
        "height": 1024,
        "size": 1234567,
        "hash": "sha256..."
      },
      "saved_path": "/home/user/images/subfolder/02-a_AI.png",
      "error": null,
      "needs_review": false,
      "logs": []
    }
  ],
  "progress": {
    "total": 100,
    "selected": 80,
    "pending": 30,
    "processing": 1,
    "completed": 45,
    "skipped": 5,
    "failed": 4,
    "needs_review": 1
  },
  "run_state": "idle",
  "last_run": "2026-09-15T14:30:00Z"
}
```

### Persistence Implementation
- `app/core/persistence.py` provides:
  - `load_state(path) -> AppState`
  - `save_state(state, path)` atomic: write to temp file then rename
  - `reconcile_with_filesystem(state, root_path)` updates image list vs disk
  - Versioning and migration (if version mismatch, migrate or warn)

- All UI parameters storable: any change in UI immediately persists (or on explicit Save Preset button).
- Preset file: user can save multiple presets as separate JSON files, e.g., `config/presets/my_preset.json`. All parameters in UI are storable, so preset = full app_state snapshot minus job history? Or include job history? For simplicity, preset includes urls, prompt, settings, folder, but not image queue or jobs. However requirement says "save preset in json file. all parameter in UI is storable." So we will make preset = urls + prompt + settings + folder.

- Job history and image queue are part of main app_state.json, not preset, to allow resume.

- Atomic write: use `tempfile` + `os.replace`

- No DB: fingerprints for completed files stored in JSON to avoid reprocessing: `completed_fingerprints` list of hashes or path+mtime.

### Core Models (Python dataclasses)

```python
@dataclass
class UrlRow:
    id: str
    url: str
    enabled: bool
    last_status: str  # unchecked, checking, ready, unavailable, auth_required, captcha_required, unsupported, error
    last_checked: Optional[datetime]
    error: Optional[str]

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
    content_hash: Optional[str]
    status: str  # pending, selected, deselected, processing, completed, failed, skipped, needs_review
    selected: bool
    assigned_url_id: Optional[str]
    attempt_count: int
    output_path: Optional[str]
    error: Optional[str]

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
    created_at: datetime
    baseline: dict
    prompt: str
    submitted_at: Optional[datetime]
    output_src: Optional[str]
    saved_path: Optional[str]
    error: Optional[str]
    needs_review: bool

@dataclass
class Settings:
    timeouts: dict
    retries: dict
    output: dict
    highlight: dict
    browser: dict
    scheduling: str
    concurrency: int

@dataclass
class AppState:
    version: str
    urls: List[UrlRow]
    folder: dict
    prompt: dict
    settings: Settings
    images: List[ImageItem]
    jobs: List[JobRecord]
    progress: dict
    run_state: str
```

### Scanning Logic
- `scanner.py`: `scan_folder(root, supported_exts, ignore_ai_suffix) -> List[ImageItem]`
- Preserves folder structure, returns relative paths
- Ignores `*_AI.*` by default: regex `r'_AI(\.\w+)?$'` before extension, case-insensitive check if base ends with _AI
- Uses `pathlib.Path.rglob`
- For each file: stat size, mtime, optional hash (if enabled)
- ID: `hashlib.sha256(f"{relative_path}|{size}|{mtime}".encode()).hexdigest()[:16]` or content hash if available

### Naming Logic
- `naming.py`: `get_output_path(source_path, suffix="_AI", preserve_format=True, overwrite=False, downloaded_ext=None) -> Path`
- Save beside source: `source.parent / f"{source.stem}{suffix}{ext}"`
- If preserve_format and downloaded_ext provided, use downloaded_ext else source ext
- If exists and overwrite False, iterate `n=2,3,...` -> `f"{stem}{suffix}_{n}{ext}"`
- Write to temp partial file first: `output_path.with_suffix(f".partial{ext}")`, validate, then atomic rename

### Correlation ID
- `utils/correlation.py`: `generate_correlation_id() -> str` format `YYYYMMDD-HHMMSS-XXXX` where XXXX random hex uppercase
- Unique per attempt, stored in job record

### State Reconciliation on Startup
- Load saved state
- Check if root folder still exists
- Re-scan folder, compare with saved images:
  - New files -> add as pending
  - Missing files -> mark as skipped with error "source missing"
  - Changed files (mtime/size changed) -> if previously completed, mark as pending again? Or keep completed but note changed? For safety, if completed file's source changed, reset to pending (needs reprocessing)
- For jobs with status PROCESSING or SUBMITTED etc. that were active during crash: mark INTERRUPTED, do not auto-resubmit, require user confirmation
- Check if output files still exist for completed jobs; if not, keep completed state but warn

### Logging
- Structured logs: timestamp, job_id, url_id, image_path, state, attempt, result
- Human-readable activity log in UI + file log `logs/app.log`
- No secrets in logs (no credentials, no full signed URLs — truncate or hash)

### Testing Strategy for Persistence
- Unit tests for naming (no overwrite, unique suffix, preserve format)
- Scanner (ignore _AI, recursive, supported types)
- Persistence atomic write and load
- Reconciliation logic
- Correlation uniqueness
```

