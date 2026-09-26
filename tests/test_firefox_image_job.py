"""Firefox image job — the Chrome phases, driven by Ui.Vision macros (I-65).

A scripted transport stands in for the desktop. The tests fail if a phase is
skipped, a second Send is clicked, a bad file is marked completed, or a miss
is counted.
"""

from __future__ import annotations

import errno
import json
from pathlib import Path

import pytest

from app.browser.page_status import PageStatus
from app.browser.uivision import autorun, job_macro, launch, macro
from app.core.enums import ImageStatus
from app.core.models import ImageItem
from app.services import multi_page_dispatcher as mpd
from app.services.firefox_image import checkpoint, runner, save, steps
from app.services.firefox_image.reset import reset_firefox_chat
from app.services.firefox_image.runner import RunOptions
from app.services.firefox_image.settle import emit_review
from app.services.firefox_image.transport import PhaseCall, parse_job_reply, run_phase
from tests.test_firefox_dispatch import FakeBridge, firefox_pool, make_img

pytestmark = pytest.mark.unit

PNG = __import__("base64").b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PROMPT = "line1\nline2 café 🦊"
CORR = "20260925-000000-ABCD"


class Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    async def sleep(self, seconds):
        self.t += float(seconds)


class Script:
    def __init__(self, replies):
        self.replies = {k: (v if isinstance(v, list) else [v]) for k, v in replies.items()}
        self.calls = []

    async def act(self, phase, payload):
        self.calls.append((phase, dict(payload or {})))
        queue = self.replies.get(phase) or [{"kind": "error", "message": f"unexpected {phase}", "data": {}}]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(item):
            item = item(payload)
        return item

    def count(self, phase):
        return sum(1 for name, _ in self.calls if name == phase)


def _png(tmp: Path, name="a.png") -> Path:
    path = tmp / name
    path.write_bytes(PNG)
    return path


def _img(path: Path) -> ImageItem:
    img = make_img(path.name)
    img.absolute_path = str(path)
    img.id = "img-" + path.stem
    return img


def _bridge(tmp: Path) -> FakeBridge:
    bridge = FakeBridge()
    bridge.config.dir = str(tmp / "cfg")
    return bridge


def _snap(**kw):
    data = {"attachment": {"found": False, "name": "", "src": ""}, "prompt": "",
            "send": {"found": True, "enabled": True}, "security": False,
            "generating": False, "composer_empty": True, "page_ready": True, "results": []}
    data.update(kw)
    return {"kind": "ok", "message": "", "data": data}


def _result(src="https://cdn.example/new.png", corr=CORR):
    return {"src": src, "text": f"[JOB-ID: {corr}]", "job_id": corr, "alt": ""}


def _happy(name="a.png", png=PNG):
    return {
        "probe": [_snap(results=[{"src": "https://cdn.example/old.png", "text": "", "job_id": ""}]),
                  _snap(results=[_result()])],
        "upload": {"kind": "ok", "data": {"attachment": {"found": True, "name": name, "src": "blob:fresh"}}},
        "prompt": lambda payload: {"kind": "ok", "data": {"ok": True, "actual": payload.get("prompt")}},
        "submit": {"kind": "ok", "data": {}},
        "download": {"kind": "ok", "data": {"started": True, "partial": False, "name": "out.png", "raw": png}},
    }


async def _run(img, bridge, pool, script, **kw):
    page = pool.get_page("9THrgpBc.Profile1_tab1")
    clock = kw.pop("clock", None) or Clock()
    await runner.run_firefox_image(img_job(img, bridge, pool), page, RunOptions(
        corr_id=kw.get("corr", CORR), prompt=kw.get("prompt", PROMPT), transport=script,
        clock=clock, sleep=kw.get("sleep") or clock.sleep, timeout=kw.get("timeout", 2)))
    return page


def img_job(img, bridge, pool):
    from types import SimpleNamespace as NS
    return NS(img=img, bridge=bridge, pool=pool, tab_id="9THrgpBc.Profile1_tab1", urls=[])


def _logs(bridge):
    return "\n".join(message for _level, message in bridge.logs)


# ---- macros: native clicks, the preexisting tab survives --------------------

def test_every_phase_reuses_the_tab_and_never_closes_it():
    for phase in ("probe", "clear", "upload", "prompt", "submit", "download", "new_chat"):
        commands = job_macro.build_commands(phase, {"path": "/tmp/a.png", "prompt": PROMPT,
                                                    "src": "https://cdn.example/a.png"})
        names = [row["Command"].lower() for row in commands]
        assert "close" not in names and "closewindow" not in names
        opened = [row for row in commands if row["Command"] == "selectWindow"]
        assert opened and all(row["Value"] == "" for row in opened)
        assert "click" not in names


def _stored(rows) -> str:
    return next(row["Target"] for row in rows if row["Value"] == "!clipboard")


def test_submit_clicks_send_exactly_once_and_upload_does_not_type_the_path():
    submit = job_macro.build_commands("submit")
    assert job_macro.xclick_targets(submit) == [job_macro.send_target()]
    upload = job_macro.build_commands("upload", {"path": "/tmp/café.png"})
    assert job_macro.xclick_targets(upload) == [job_macro.add_files_target()]
    assert not any(row["Command"] == "XType" and "café" in row["Target"] for row in upload)
    assert _stored(upload) == "/tmp/café.png"


def test_windows_dialog_pastes_a_quoted_path_and_never_uses_locale_keys(monkeypatch):
    monkeypatch.setattr(job_macro, "_dialog_system", lambda: "windows")
    path = "C:\\Users\\Jiří Novák\\icon-location-pin.png"
    commands = job_macro.build_commands("upload", {"path": path})
    assert _stored(commands) == '"C:/Users/Jiří Novák/icon-location-pin.png"'
    targets = [row["Target"] for row in commands]
    assert "${KEY_CTRL+KEY_L}" not in targets
    assert not any("KEY_ALT" in target for target in targets)
    assert not any(row["Command"] == "XType" and "icon-location-pin" in row["Target"] for row in commands)
    click = targets.index(job_macro.add_files_target())
    assert click < targets.index("1000") < targets.index("${KEY_CTRL+KEY_V}") < targets.index("${KEY_ENTER}")
    assert targets.index("${KEY_ENTER}") < targets.index("2000")
    stores = [row for row in commands if row["Command"] == "store"]
    assert stores[0]["Value"] == "!stringescape" and stores[0]["Target"] == "false"
    loaded = json.loads(macro.to_json(job_macro.build_job_macro("upload", {"path": path})))
    assert _stored(loaded["Commands"]) == '"C:/Users/Jiří Novák/icon-location-pin.png"'


def test_linux_dialog_opens_the_location_bar_before_the_paste():
    rows = job_macro.file_dialog_rows("/tmp/café.png", "linux")
    targets = [row["Target"] for row in rows]
    assert _stored(rows) == "/tmp/café.png"
    assert targets.index("${KEY_CTRL+KEY_L}") < targets.index("${KEY_CTRL+KEY_V}")
    assert targets.count("${KEY_ENTER}") == 1


def test_mac_dialog_goes_to_the_folder_then_opens():
    rows = job_macro.file_dialog_rows("/Users/me/a.png", "mac")
    targets = [row["Target"] for row in rows]
    assert "${KEY_CMD+KEY_SHIFT+KEY_G}" in targets
    assert "${KEY_CMD+KEY_V}" in targets
    assert targets.count("${KEY_ENTER}") == 2
    go = targets.index("${KEY_ENTER}")
    assert targets.index("${KEY_CMD+KEY_V}") < go < targets.index("${KEY_ENTER}", go + 1)


def test_windows_unc_path_keeps_backslashes_inside_quotes():
    rows = job_macro.file_dialog_rows("\\\\server\\share\\icon-location-pin.png", "windows")
    assert _stored(rows) == '"\\\\server\\share\\icon-location-pin.png"'


def test_empty_or_multiline_upload_path_is_refused():
    with pytest.raises(ValueError):
        job_macro.build_commands("upload", {"path": ""})
    with pytest.raises(ValueError):
        job_macro.build_commands("upload", {"path": "a\nb.png"})


def test_unknown_dialog_system_is_refused():
    with pytest.raises(ValueError):
        job_macro.file_dialog_rows("/tmp/a.png", "freebsd")


def test_launch_url_does_not_close_the_existing_tab():
    url = autorun.launch_url(autorun.LaunchSpec(
        page_path="/tmp/ui.vision.html", macro=job_macro.MACRO_NAME, storage="xfile",
        log_path="/tmp/log.txt", pause_ms=500, target=job_macro.send_target(), tab="title=*A*"))
    assert "continueInLastUsedTab=0" in url
    assert "macro=Arena_ImageJob" in url


def test_prompt_is_baked_as_json_so_newlines_and_unicode_survive():
    js = __import__("app.browser.uivision.job_probe", fromlist=["build_insert_js"]).build_insert_js(PROMPT)
    assert json.dumps(PROMPT) in js


def test_phase_macro_is_the_image_job_not_the_demo(tmp_path):
    from types import SimpleNamespace as NS
    from app.services.firefox_image import transport
    spec = NS(home=str(tmp_path), config_dir=str(tmp_path / "cfg"))
    page = transport.provision_phase(spec, "submit", {})
    written = tmp_path / "macros" / "Arena_ImageJob.json"
    doc = json.loads(written.read_text(encoding="utf-8"))
    assert doc["Name"] == "Arena_ImageJob"
    assert any(row["Command"] == "XClick" for row in doc["Commands"])
    assert "Python_XClick_Demo" not in written.read_text(encoding="utf-8")
    assert page.endswith("ui.vision.html")


def test_image_phase_does_not_call_the_demo_provision():
    import inspect
    from app.services.firefox_image import transport
    body = inspect.getsource(transport._execute_phase) + inspect.getsource(transport.provision_phase)
    assert "runner.provision" not in body
    assert "uv_runner" not in body


# ---- pure decisions --------------------------------------------------------

def test_checkpoint_restore_overwrites_a_later_edit(tmp_path):
    saved = {"phase": "prompt_verified", "prompt": "All"}
    live = steps.restore_book(saved)
    live["prompt"] = "save1"
    live["extra"] = 1
    assert steps.restore_book(saved) == {"phase": "prompt_verified", "prompt": "All"}
    bridge = _bridge(tmp_path)
    checkpoint.save_book(bridge, "img", {"phase": "prompt_verified", "prompt": "All"})
    checkpoint.save_book(bridge, "img", {"phase": "attachment_verified"})
    assert checkpoint.load_book(bridge, "img") == {"phase": "attachment_verified"}


@pytest.mark.parametrize("name,data,expected", [
    ("missing.png", None, "missing source file"),
    ("empty.png", b"", "empty source file"),
    ("note.gif", b"GIF89a", "unsupported source file"),
])
def test_source_problems_are_named(tmp_path, name, data, expected):
    path = tmp_path / name
    if data is not None:
        path.write_bytes(data)
    assert steps.source_problem(str(path) if data is not None else str(tmp_path / "nope.png")) == expected


def test_png_jpeg_and_webp_sources_are_uploadable(tmp_path):
    (tmp_path / "a.png").write_bytes(PNG)
    (tmp_path / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (tmp_path / "a.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
    for name in ("a.png", "a.jpg", "a.webp"):
        assert steps.source_problem(str(tmp_path / name)) == ""


def test_correlation_names_old_wrong_and_multiple():
    base = ["https://old"]
    assert steps.correlate(base, [{"src": "https://old", "text": ""}], CORR).kind == "rejected"
    wrong = steps.correlate(base, [{"src": "https://new", "text": "other", "job_id": "nope"}], CORR)
    assert wrong.kind == "rejected" and "not the current job" in wrong.reason
    many = steps.correlate(base, [{"src": "https://a", "job_id": CORR, "text": ""},
                                  {"src": "https://b", "job_id": CORR, "text": ""}], CORR)
    assert many.kind == "review" and many.reason == "multiple result candidates"
    one = steps.correlate(base, [{"src": "https://new", "text": f"[JOB-ID: {CORR}]", "job_id": ""}], CORR)
    assert one.kind == "ok" and one.src == "https://new"


def test_download_and_save_errors_are_named():
    assert steps.download_problem({"started": False}) == "download does not start"
    assert "partial" in steps.download_problem({"started": True, "partial": True, "name": "a.crdownload"})
    assert "HTML" in steps.download_problem({"started": True, "error": "html", "name": "x.html"})
    assert save.image_problem(b"<!DOCTYPE html><html></html>") == "Downloaded file is HTML, not image"
    assert save.image_problem(b"this is not an image") != ""
    assert save.save_error_name(OSError(errno.ENOSPC, "full")) == "disk full"
    assert save.save_error_name(OSError(errno.EACCES, "denied")) == "access denied"
    assert save.save_error_name(OSError(errno.EIO, "rename")) == "atomic rename failure"


def test_an_old_sibling_is_not_a_completed_job(tmp_path):
    source = _png(tmp_path)
    sibling = tmp_path / "a_AI.png"
    sibling.write_bytes(PNG)
    assert steps.sibling_output(str(source)) == sibling
    assert steps.should_reconcile("processing", "", False, sibling) is False
    assert steps.should_reconcile("pending", "", False, sibling) is False
    assert steps.should_reconcile("processing", "saving", False, sibling) is True
    assert steps.should_reconcile("processing", "", True, sibling) is True
    assert steps.claim_block(None, set()) == "removed"


# ---- the job ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_saves_beside_the_source_and_submits_once(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    script = Script(_happy())
    img = _img(source)
    await _run(img, bridge, pool, script)
    assert script.count("submit") == 1
    assert script.count("new_chat") == 0
    assert img.status == ImageStatus.COMPLETED.value
    assert Path(img.output_path).read_bytes() == PNG
    assert Path(img.output_path).name == "a_AI.png"
    sent = [payload["prompt"] for name, payload in script.calls if name == "prompt"]
    assert sent == [PROMPT]
    text = _logs(bridge)
    for token in ("worker/job/attempt", "Attach started", "Attachment verified", "Inserted",
                  "Verified", "Submit intent", "Clicked send", "Waiting for generation",
                  "correlated", "Downloaded", "Saved", "pool BUSY"):
        assert token in text


@pytest.mark.asyncio
async def test_stale_attachment_is_cleared_and_a_stuck_one_is_not_uploaded(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    def stale():
        return _snap(attachment={"found": True, "name": "old.png", "src": "blob:old"})

    script = Script({"probe": [stale(), _snap(), _snap(results=[_result()])],
                     "clear": {"kind": "ok", "data": {}}, **{k: v for k, v in _happy().items() if k != "probe"}})
    img = _img(source)
    await _run(img, bridge, pool, script)
    assert script.count("clear") == 1 and script.count("upload") == 1
    assert img.status == ImageStatus.COMPLETED.value

    stuck = Script({"probe": [stale(), stale()], "clear": {"kind": "ok", "data": {}}})
    img2 = _img(_png(tmp_path, "b.png"))
    await _run(img2, bridge, pool, stuck)
    assert stuck.count("upload") == 0
    assert img2.status == ImageStatus.FAILED.value
    assert "stale" in img2.error


@pytest.mark.asyncio
async def test_prompt_readback_must_match_before_send(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    script = Script({"probe": [_snap()],
                     "upload": _happy()["upload"],
                     "prompt": {"kind": "ok", "data": {"actual": "line1\nline2"}}})
    img = _img(source)
    await _run(img, bridge, pool, script)
    assert script.count("submit") == 0
    assert img.status == ImageStatus.FAILED.value
    assert "truncated" in img.error


@pytest.mark.asyncio
async def test_lost_ack_does_not_click_again_and_is_not_completed(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    clock = Clock()
    script = Script({"probe": [_snap(), _snap()], "upload": _happy()["upload"],
                     "prompt": _happy()["prompt"], "submit": {"kind": "timeout", "message": "no ack"}})
    img = _img(source)
    await _run(img, bridge, pool, script, clock=clock, timeout=0.2)
    assert script.count("submit") == 1
    assert script.count("download") == 0
    assert img.status == ImageStatus.NEEDS_REVIEW.value
    assert "uncertain" in (img.error or "")
    book = checkpoint.load_book(bridge, img.id)
    assert book["submitted"] is True and book["submit_uncertain"] is True


@pytest.mark.asyncio
async def test_old_result_times_out_and_a_wrong_job_is_not_downloaded(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    clock = Clock()
    old = Script({"probe": [_snap(results=[{"src": "https://old", "text": "", "job_id": ""}]),
                            _snap(results=[{"src": "https://old", "text": "stale", "job_id": ""}])],
                  "upload": _happy()["upload"], "prompt": _happy()["prompt"],
                  "submit": {"kind": "ok", "data": {}}})
    img = _img(source)
    await _run(img, bridge, pool, old, clock=clock, timeout=0.2)
    assert img.status == ImageStatus.FAILED.value
    assert img.error == "generation timed out"
    assert "rejected" in _logs(bridge)
    assert old.count("download") == 0

    clock2 = Clock()
    wrong = Script({"probe": [_snap(), _snap(results=[{"src": "https://new", "text": "other", "job_id": "nope"}])],
                    "upload": _happy()["upload"], "prompt": _happy()["prompt"],
                    "submit": {"kind": "ok", "data": {}}})
    img2 = _img(_png(tmp_path, "c.png"))
    await _run(img2, bridge, pool, wrong, clock=clock2, timeout=0.2)
    assert img2.status == ImageStatus.NEEDS_REVIEW.value
    assert wrong.count("download") == 0


@pytest.mark.asyncio
async def test_multiple_candidates_are_review_immediately(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    fresh = [{"src": "https://a", "job_id": CORR, "text": ""}, {"src": "https://b", "job_id": CORR, "text": ""}]
    script = Script({"probe": [_snap(), _snap(results=fresh)], "upload": _happy()["upload"],
                     "prompt": _happy()["prompt"], "submit": {"kind": "ok", "data": {}}})
    img = _img(source)
    await _run(img, bridge, pool, script, timeout=30)
    assert img.status == ImageStatus.NEEDS_REVIEW.value
    assert img.error == "multiple result candidates"
    assert script.count("download") == 0
    assert script.count("submit") == 1


@pytest.mark.asyncio
async def test_a_delayed_result_is_downloaded_without_a_second_send(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    clock = Clock()
    first = Script({"probe": [_snap(), _snap()], "upload": _happy()["upload"],
                    "prompt": _happy()["prompt"], "submit": {"kind": "ok", "data": {}}})
    img = _img(source)
    await _run(img, bridge, pool, first, clock=clock, timeout=0.2)
    assert img.status == ImageStatus.FAILED.value and first.count("submit") == 1
    second = Script({"probe": [_snap(results=[_result()])],
                     "download": _happy()["download"]})
    await _run(img, bridge, pool, second, timeout=30)
    assert second.count("submit") == 0 and second.count("upload") == 0
    assert img.status == ImageStatus.COMPLETED.value
    assert Path(img.output_path).is_file()


@pytest.mark.asyncio
@pytest.mark.parametrize("offer,needle", [
    ({"started": False}, "does not start"),
    ({"started": True, "partial": True, "name": "a.crdownload"}, "partial"),
    ({"started": True, "name": "page.html", "raw": b"<!DOCTYPE html><html></html>"}, "HTML"),
    ({"started": True, "name": "bad.bin", "raw": b"not an image at all"}, "invalid"),
])
async def test_invalid_downloads_are_not_completed(tmp_path, offer, needle):
    source = _png(tmp_path, f"{needle[:4]}.png")
    bridge, pool = _bridge(tmp_path), firefox_pool()
    script = Script({"probe": _happy()["probe"], "upload": _happy()["upload"],
                     "prompt": _happy()["prompt"], "submit": {"kind": "ok", "data": {}},
                     "download": {"kind": "ok", "data": offer}})
    img = _img(source)
    await _run(img, bridge, pool, script)
    assert img.status != ImageStatus.COMPLETED.value
    assert img.output_path in (None, "")
    assert needle.lower() in (img.error or "").lower() or needle.lower() in _logs(bridge).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("code,needle", [
    (errno.ENOSPC, "disk full"),
    (errno.EACCES, "access denied"),
    (errno.EIO, "atomic rename failure"),
])
async def test_save_failures_are_named_and_not_completed(tmp_path, monkeypatch, code, needle):
    source = _png(tmp_path, f"s{code}.png")
    bridge, pool = _bridge(tmp_path), firefox_pool()

    def boom(*_a, **_k):
        raise OSError(code, needle)

    monkeypatch.setattr(save, "write_output", boom)
    script = Script(_happy())
    img = _img(source)
    await _run(img, bridge, pool, script)
    assert img.status == ImageStatus.FAILED.value
    assert img.error == needle
    assert not (tmp_path / f"s{code}_AI.png").exists()


@pytest.mark.asyncio
async def test_interrupted_save_is_reconciled_and_a_bare_sibling_is_not(tmp_path):
    source = _png(tmp_path)
    sibling = tmp_path / "a_AI.png"
    sibling.write_bytes(PNG)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    checkpoint.mark_saving(str(source))
    img = _img(source)
    img.status = ImageStatus.PROCESSING.value
    script = Script({})
    await _run(img, bridge, pool, script)
    assert script.calls == []
    assert img.status == ImageStatus.COMPLETED.value
    assert img.output_path == str(sibling)

    other = _png(tmp_path, "b.png")
    (tmp_path / "b_AI.png").write_bytes(PNG)
    img2 = _img(other)
    img2.status = ImageStatus.PROCESSING.value
    script2 = Script({"probe": [_snap()], "upload": {"kind": "error", "message": "stop"}})
    await _run(img2, bridge, pool, script2)
    assert script2.count("upload") == 1
    assert img2.status == ImageStatus.FAILED.value


@pytest.mark.asyncio
async def test_cancel_before_submit_sends_nothing(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    bridge._cancel_requested = True
    script = Script({"probe": [_snap()]})
    img = _img(source)
    await _run(img, bridge, pool, script)
    assert script.count("submit") == 0 and script.count("upload") == 0
    assert img.status == ImageStatus.FAILED.value and img.error == "Cancelled"


@pytest.mark.asyncio
async def test_cancel_after_submit_is_review_and_does_not_resend(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    def arm(_payload):
        bridge._cancel_requested = True
        return _snap()
    script = Script({"probe": [_snap(), arm], "upload": _happy()["upload"],
                     "prompt": _happy()["prompt"], "submit": {"kind": "ok", "data": {}}})
    img = _img(source)
    await _run(img, bridge, pool, script, timeout=30)
    assert script.count("submit") == 1 and script.count("download") == 0
    assert img.status == ImageStatus.NEEDS_REVIEW.value


@pytest.mark.asyncio
async def test_pause_waits_and_a_verified_phase_is_not_repeated(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    bridge._pause_requested = True

    async def nap(seconds):
        bridge._pause_requested = False

    script = Script(_happy())
    img = _img(source)
    await _run(img, bridge, pool, script, sleep=nap, timeout=5)
    assert script.count("upload") == 1
    assert img.status == ImageStatus.COMPLETED.value

    img2 = _img(_png(tmp_path, "d.png"))
    checkpoint.save_book(bridge, img2.id, {"phase": "attachment_verified", "baseline": []})
    script2 = Script({"prompt": _happy()["prompt"], "submit": {"kind": "ok", "data": {}},
                      "probe": [_snap(results=[_result()])], "download": _happy()["download"]})
    await _run(img2, bridge, pool, script2, clock=Clock(), timeout=1)
    assert script2.count("upload") == 0
    assert img2.status == ImageStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_security_waits_for_the_user_then_finishes(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    seen = []
    page = pool.get_page("9THrgpBc.Profile1_tab1")

    def result(_payload):
        seen.append(str(page.status))
        return _snap(results=[_result()])

    script = Script({"probe": [_snap(), _snap(security=True), result],
                     "upload": _happy()["upload"], "prompt": _happy()["prompt"],
                     "submit": {"kind": "ok", "data": {}}, "download": _happy()["download"]})
    img = _img(source)
    await _run(img, bridge, pool, script, clock=Clock(), timeout=2)
    assert img.status == ImageStatus.COMPLETED.value
    assert "waiting_user" in _logs(bridge)
    assert "pool waiting_captcha" in _logs(bridge)
    assert seen  # generation resumed after the challenge, it did not stay stuck


@pytest.mark.asyncio
async def test_stop_after_current_still_finishes_this_job(tmp_path):
    source = _png(tmp_path)
    bridge, pool = _bridge(tmp_path), firefox_pool()
    bridge._stop_after = True
    script = Script(_happy())
    img = _img(source)
    await _run(img, bridge, pool, script)
    assert img.status == ImageStatus.COMPLETED.value
    assert mpd._feeding(bridge) is False


def test_disabled_busy_cooling_and_removed_workers_are_not_claimed():
    pool = firefox_pool()
    tab = "9THrgpBc.Profile1_tab1"
    page = pool.get_page(tab)
    assert steps.claim_block(page, set()) == "disabled"
    assert mpd._acquire_free_in(pool, set(), "job") is None
    pool.mark_busy(tab, "other")
    assert steps.claim_block(pool.get_page(tab), {tab}) == "busy"
    assert mpd._acquire_free_in(pool, {tab}, "job") is None
    pool.mark_steady(tab)
    page = pool.get_page(tab)
    page.status = PageStatus.COOLDOWN
    page.cooldown_until = __import__("time").time() + 100
    assert steps.claim_block(page, {tab}) == "cooling"
    pool.remove_page(tab)
    assert steps.claim_block(pool.get_page(tab), {tab}) == "removed"
    assert mpd._acquire_free_in(pool, {tab}, "job") is None


@pytest.mark.asyncio
async def test_missing_firefox_does_not_write_desktop_macros(monkeypatch, tmp_path):
    monkeypatch.setattr(launch, "binary_exists", lambda _binary: False)
    wrote = []
    monkeypatch.setattr("app.services.firefox_image.transport.provision_phase",
                        lambda *a, **k: wrote.append(1))
    bridge, pool = _bridge(tmp_path), firefox_pool()
    desktop = Path.home() / "Desktop" / "uivision" / "macros" / "Arena_ImageJob.json"
    before = desktop.exists()
    ok, reason = await reset_firefox_chat(pool, "9THrgpBc.Profile1_tab1", bridge)
    assert ok is False and "firefox" in reason
    assert wrote == []
    assert desktop.exists() == before


@pytest.mark.asyncio
async def test_browser_storage_is_blocked_before_a_write(monkeypatch, tmp_path):
    wrote = []
    monkeypatch.setattr("app.services.firefox_image.transport.provision_phase",
                        lambda *a, **k: wrote.append(1))
    bridge = _bridge(tmp_path)
    bridge.config.get_state = lambda key, default=None: (
        {"storage": "browser", "macro": "Python_XClick_Demo"} if key == "firefox_auto" else default)
    page = firefox_pool().get_page("9THrgpBc.Profile1_tab1")
    reply = await run_phase(PhaseCall(bridge, page, "probe", {}))
    assert reply["kind"] == "blocked" and "xfile" in reply["message"]
    assert wrote == []


def test_savelog_echo_is_the_phase_answer():
    lines = ["Executing: echo ARENA_JOB=${arenaJob}", 'echo ARENA_JOB={"ok": true, "actual": "hi"}']
    assert parse_job_reply(lines) == {"ok": True, "actual": "hi"}
    assert parse_job_reply(["no answer"]) == {}


@pytest.mark.asyncio
async def test_a_lost_submit_ack_from_the_macro_is_uncertain():
    async def execute(_call):
        return "timeout", "no ack", ()

    bridge = FakeBridge()
    page = firefox_pool().get_page("9THrgpBc.Profile1_tab1")
    reply = await run_phase(PhaseCall(bridge, page, "submit", {}), execute=execute)
    assert reply["kind"] == "uncertain"


def test_needs_review_history_is_not_completed(tmp_path):
    from app.services.job_history import store_of
    bridge, pool = _bridge(tmp_path), firefox_pool()
    img = _img(_png(tmp_path))
    img.status = ImageStatus.NEEDS_REVIEW.value
    job = img_job(img, bridge, pool)
    job.corr_id = CORR
    job.lane_job_id = CORR
    emit_review(job, "multiple result candidates")
    row = store_of(bridge).recent(1)[0]
    assert row["status"] == "failed"
    assert row["status"] != "completed"
    payload = json.loads(bridge.job_finished.calls[-1][1])
    assert payload["status"] == "needs_review"
    assert payload["message"] == "multiple result candidates"
    assert payload["error"] == ""
