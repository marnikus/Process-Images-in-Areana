"""D5 mutation triage: core models full round-trip + progress tests.

Targets AppState.from_dict (188), recalculate_progress (43),
ImageItem.from_scan_dict (32), AppState.to_dict (18), UrlRow.create (7).
"""

from datetime import datetime

from app.core.enums import ImageStatus, JobStatus, RunState, UrlStatus
from app.core.models import (
    JobRequest,
    AppSettings,
    AppState,
    ImageItem,
    JobRecord,
    UrlRow,
    now_iso,
)


def scan_dict(**over):
    d = {
        "id": "img1",
        "relative_path": "a/b.png",
        "absolute_path": "/x/a/b.png",
        "filename": "b.png",
        "base_name": "b",
        "extension": ".png",
        "size": 12,
        "mtime": 1.0,
        "fingerprint": "fp1",
    }
    d.update(over)
    return d


class TestNowIso:
    def test_format(self):
        s = now_iso()
        assert s.endswith("Z")
        datetime.fromisoformat(s[:-1])  # parseable


class TestUrlRow:
    def test_create_defaults(self):
        r = UrlRow.create("http://x.test")
        assert r.id.startswith("url_")
        assert r.url == "http://x.test"
        assert r.enabled is True
        assert r.last_status == UrlStatus.UNCHECKED.value
        assert r.last_checked is None
        assert r.error is None
        assert r.tab_id == ""

    def test_create_options(self):
        r = UrlRow.create("http://y.test", enabled=False, tab_id="T1")
        assert r.enabled is False
        assert r.tab_id == "T1"

    def test_link_tab_sets(self):
        r = UrlRow.create("http://x.test")
        assert r.link_tab("T9") is True
        assert r.tab_id == "T9"

    def test_link_tab_empty_never_clears(self):
        r = UrlRow.create("http://x.test", tab_id="T1")
        assert r.link_tab("") is False
        assert r.tab_id == "T1"
        assert r.link_tab(None) is False
        assert r.tab_id == "T1"


class TestImageItem:
    def test_from_scan_dict_base(self):
        i = ImageItem.from_scan_dict(scan_dict())
        assert i.id == "img1"
        assert i.relative_path == "a/b.png"
        assert i.status == ImageStatus.PENDING.value
        assert i.selected is False
        assert i.assigned_url_id is None
        assert i.attempt_count == 0
        assert i.output_path is None
        assert i.error is None
        assert i.content_hash is None

    def test_from_scan_dict_fallback_id_from_fingerprint(self):
        d = scan_dict()
        del d["id"]
        i = ImageItem.from_scan_dict(d)
        assert i.id == "fp1"

    def test_from_scan_dict_selected(self):
        i = ImageItem.from_scan_dict(scan_dict(), selected=True)
        assert i.selected is True
        assert i.status == ImageStatus.SELECTED.value

    def test_from_scan_dict_content_hash(self):
        i = ImageItem.from_scan_dict(scan_dict(content_hash="abc"))
        assert i.content_hash == "abc"

    def test_to_dict(self):
        i = ImageItem.from_scan_dict(scan_dict())
        d = i.to_dict()
        assert d["fingerprint"] == "fp1"
        assert d["size"] == 12


class TestJobRecord:
    def test_create(self):
        img = ImageItem.from_scan_dict(scan_dict())
        url = UrlRow.create("http://x.test")
        j = JobRecord.create(JobRequest(image=img, url=url, correlation_id="corr-1",
                                        prompt="p t"))
        assert j.job_id == "corr-1"
        assert j.correlation_id == "corr-1"
        assert j.image_id == "img1"
        assert j.image_path == "/x/a/b.png"
        assert j.url_id == url.id
        assert j.url == "http://x.test"
        assert j.attempt == 1
        assert j.status == JobStatus.CREATED.value
        assert j.prompt == "p t"
        assert j.baseline == {}
        assert j.logs == []
        assert j.needs_review is False
        assert j.saved_path is None

    def test_create_custom_attempt(self):
        img = ImageItem.from_scan_dict(scan_dict())
        url = UrlRow.create("http://x.test")
        j = JobRecord.create(JobRequest(image=img, url=url, correlation_id="corr-1",
                                        prompt="p", attempt=4))
        assert j.attempt == 4


class TestAppSettings:
    def test_defaults(self):
        s = AppSettings()
        assert s.timeouts == {"page_load": 30, "selector": 10, "attachment": 15,
                              "generation": 180, "download": 30}
        assert s.retries == {"max_attempts": 3, "backoff_seconds": [1, 3, 5]}
        assert s.output["suffix"] == "_AI"
        assert s.output["preserve_format"] is True
        assert s.output["overwrite"] is False
        assert s.output["unique_suffix_template"] == "{base}_AI_{n}{ext}"
        assert s.highlight == {"enabled": True, "duration_seconds": 2,
                               "color": "#FF0000", "border_width": 3}
        assert s.browser == {"user_data_dir": "./browser_profile",
                             "headless": False, "slow_mo": 0}
        assert s.scheduling == "round-robin"
        assert s.concurrency == 1
        assert s.supported_types == [".png", ".jpg", ".jpeg", ".webp"]
        assert s.ignore_ai_suffix is True

    def test_default_instances_not_shared(self):
        a, b = AppSettings(), AppSettings()
        a.timeouts["page_load"] = 99
        assert b.timeouts["page_load"] == 30


def make_image(status, selected=False):
    return ImageItem(
        id=f"i-{status}",
        relative_path="r.png",
        absolute_path="/r.png",
        filename="r.png",
        base_name="r",
        extension=".png",
        size=1,
        mtime=0.0,
        fingerprint=f"f-{status}",
        status=status,
        selected=selected,
    )


class TestRecomputeProgress:
    def test_mixed_statuses(self):
        state = AppState()
        state.images = [
            make_image(ImageStatus.PENDING.value, selected=True),   # pending (selected)
            make_image(ImageStatus.PENDING.value),                   # not selected: nothing
            make_image(ImageStatus.SELECTED.value, selected=True),   # pending (selected)
            make_image(ImageStatus.PROCESSING.value, selected=True), # processing
            make_image(ImageStatus.COMPLETED.value, selected=True),  # completed
            make_image(ImageStatus.SKIPPED.value, selected=True),    # skipped
            make_image(ImageStatus.FAILED.value, selected=True),     # failed
            make_image(ImageStatus.NEEDS_REVIEW.value, selected=True),  # needs_review
        ]
        state.recalculate_progress()
        p = state.progress
        assert p["total"] == 8
        assert p["selected"] == 7
        assert p["pending"] == 2
        assert p["processing"] == 1
        assert p["completed"] == 1
        assert p["skipped"] == 1
        assert p["failed"] == 1
        assert p["needs_review"] == 1

    def test_empty_state(self):
        state = AppState()
        state.recalculate_progress()
        assert state.progress["total"] == 0
        assert state.progress["selected"] == 0
        assert state.progress["pending"] == 0


class TestAppStateRoundTrip:
    def test_from_dict_empty(self):
        s = AppState.from_dict({})
        assert s.version == "1.0.0"
        assert s.urls == []
        assert s.images == []
        assert s.jobs == []
        assert s.folder["root_path"] == ""
        assert s.folder["supported_types"] == [".png", ".jpg", ".jpeg", ".webp"]
        assert s.folder["ignore_ai_suffix"] is True
        assert s.prompt == {"user_prompt": "", "preview_with_token": ""}
        assert s.settings.scheduling == "round-robin"
        assert s.settings.concurrency == 1
        assert s.settings.ignore_ai_suffix is True
        assert s.progress == {"total": 0, "selected": 0, "pending": 0, "processing": 0,
                              "completed": 0, "skipped": 0, "failed": 0, "needs_review": 0}
        assert s.run_state == RunState.IDLE.value
        assert s.last_run is None

    def test_from_dict_partial_settings(self):
        s = AppState.from_dict({"settings": {"concurrency": 2, "scheduling": "ff"}})
        assert s.settings.concurrency == 2
        assert s.settings.scheduling == "ff"
        assert s.settings.timeouts["page_load"] == 30  # defaults for missing

    def test_full_round_trip(self):
        original = AppState()
        original.version = "2.0.0"
        original.urls = [UrlRow.create("http://a.test", tab_id="T1")]
        original.folder = {"root_path": "/tmp", "supported_types": [".png"], "ignore_ai_suffix": False}
        original.prompt = {"user_prompt": "hi", "preview_with_token": "hi {{token}}"}
        original.settings = AppSettings(concurrency=3)
        original.images = [ImageItem.from_scan_dict(scan_dict(), selected=True)]
        url = original.urls[0]
        original.jobs = [JobRecord.create(JobRequest(image=original.images[0], url=url,
                                                   correlation_id="c1", prompt="prompt"))]
        original.progress = {"total": 1, "selected": 1, "pending": 0, "processing": 0,
                             "completed": 0, "skipped": 0, "failed": 0, "needs_review": 0}
        original.run_state = RunState.RUNNING.value
        original.last_run = "2026-09-19T00:00:00Z"

        d = original.to_dict()
        back = AppState.from_dict(d)
        assert back.version == "2.0.0"
        assert back.urls[0].url == "http://a.test"
        assert back.urls[0].tab_id == "T1"
        assert back.urls[0].last_status == UrlStatus.UNCHECKED.value
        assert back.folder["root_path"] == "/tmp"
        assert back.prompt["user_prompt"] == "hi"
        assert back.settings.concurrency == 3
        assert back.images[0].id == "img1"
        assert back.images[0].selected is True
        assert back.jobs[0].job_id == "c1"
        assert back.jobs[0].attempt == 1
        assert back.progress["total"] == 1
        assert back.run_state == RunState.RUNNING.value
        assert back.last_run == "2026-09-19T00:00:00Z"

    def test_to_dict_shape(self):
        s = AppState()
        d = s.to_dict()
        assert set(d) == {"version", "urls", "folder", "prompt", "settings",
                          "images", "jobs", "progress", "run_state", "last_run"}
        assert d["urls"] == []
        assert "timeouts" in d["settings"]
