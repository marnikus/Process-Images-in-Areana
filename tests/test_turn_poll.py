"""Poll order + thumbnail guard + wait status (2026-09-27 D-2/D-3).

RULE 8: the real `_read_output` / `_poll_output_diag` / wait loop run; only
`evaluate` is scripted. The turn payload is told apart from the v4 check by
its own marker (`engine: 'turn'`). What the turn probe *returns* on the real
arena DOM is proven in Chromium (design §5) and in tests/js/test_turn_probe.mjs.
"""

import time

import pytest

from app.browser import output_wait_status as ows
from app.browser import turn_probe as tp
from app.browser.cdp_arena import output as out
from app.browser.output_wait import WaitSpec, wait_for_new_output_with_spec
from app.browser.probe_selectors import chat_chrome_selectors, generating_status, spinner_selector

JOB = "20260927-090424-RLHW"
THUMB = "https://x.r2.cloudflarestorage.com/att/thumb.png"


class FakeCDP:
    def __init__(self, turn=None, legacy=None, last_error=""):
        self.turn, self.legacy, self.last_error = turn, legacy, last_error
        self.calls = []

    async def evaluate(self, js, await_promise=True):
        kind = "turn" if "engine: 'turn'" in js else "legacy"
        self.calls.append(kind)
        answer = self.turn if kind == "turn" else self.legacy
        if isinstance(answer, Exception):
            raise answer
        return answer


def _ctx(corr=JOB):
    return out.PollContext(correlation_id=corr)


def _turn(**kw):
    base = {"engine": "turn", "ready": False, "turn_found": True, "generating": False,
            "reason": "turn_no_image", "candidates": [], "refs": [THUMB]}
    base.update(kw)
    return base


@pytest.mark.unit
def test_turn_payload_is_wired_to_site_adapter_lists():
    js = tp.build_turn_js(JOB)
    for piece in (JOB, chat_chrome_selectors(), spinner_selector(), generating_status(), tp.MIN_SHOWN):
        assert __import__("json").dumps(piece) in js
    assert "engine: 'turn'" in js and "document.createTreeWalker" in js


@pytest.mark.unit
async def test_turn_ready_wins_and_the_v4_check_is_not_run():
    ready = _turn(ready=True, reason="", src="blob:https://arena.ai/1b2c", width=1024, height=1024)
    cdp = FakeCDP(turn=ready, legacy={"ready": False, "reason": "no_new"})
    diag = await out._read_output(cdp, _ctx())
    assert diag["src"].startswith("blob:") and cdp.calls == ["turn"]


@pytest.mark.unit
async def test_turn_generating_stands_even_when_v4_would_say_ready():
    cdp = FakeCDP(turn=_turn(generating=True, spinning=True, reason="turn_generating"),
                  legacy={"ready": True, "src": THUMB})
    diag = await out._read_output(cdp, _ctx())
    assert not diag["ready"] and diag["reason"] == "turn_generating" and cdp.calls == ["turn"]


@pytest.mark.unit
async def test_v4_ready_on_the_attachment_thumbnail_is_refused():
    cdp = FakeCDP(turn=_turn(), legacy={"ready": True, "src": THUMB, "expectedJobId": JOB})
    diag = await out._read_output(cdp, _ctx())
    assert diag["ready"] is False and diag["reason"] == "thumbnail_rejected"
    assert diag["turn"]["found"] is True and diag["turn"]["refs"] == 1


@pytest.mark.unit
async def test_v4_ready_on_another_image_passes_with_the_turn_summary():
    real = "https://x.r2.cloudflarestorage.com/out/final.png"
    cdp = FakeCDP(turn=_turn(found=False, turn_found=False, reason="turn_not_found"),
                  legacy={"ready": True, "src": real})
    diag = await out._read_output(cdp, _ctx())
    assert diag["ready"] and diag["src"] == real and diag["turn"]["found"] is False


@pytest.mark.unit
async def test_no_job_id_or_a_broken_turn_probe_falls_back_to_v4_untouched():
    legacy = {"ready": False, "reason": "no_new"}
    for cdp, ctx in ((FakeCDP(turn=_turn(), legacy=legacy), _ctx(None)),
                     (FakeCDP(turn=RuntimeError("socket"), legacy=legacy), _ctx()),
                     (FakeCDP(turn="garbage", legacy=legacy), _ctx())):
        diag = await out._read_output(cdp, ctx)
        assert diag["reason"] == "no_new" and "turn" not in diag and cdp.calls[-1] == "legacy"


@pytest.mark.unit
async def test_an_empty_page_answer_carries_the_transport_reason():
    cdp = FakeCDP(turn=None, legacy=None, last_error="TimeoutError: CDP command Runtime.evaluate timed out after 30s")
    diag = await out._read_output(cdp, _ctx())
    assert diag == {"ready": False, "reason": "no_result",
                    "error": "TimeoutError: CDP command Runtime.evaluate timed out after 30s"}
    assert "the page did not answer the check (TimeoutError" in ows.status_text(diag)


# ── status words, throttle, timeout detail ─────────────────────────────


@pytest.mark.unit
def test_status_words_name_the_turn_evidence():
    loading = _turn(reason="turn_image_loading",
                    candidates=[{"scheme": "blob", "w": 0, "h": 0, "complete": False}])
    assert ows.status_text(loading) == ("this job's image is still loading "
                                        "(job prompt found, 1 image(s): blob 0x0 loading)")
    lost = {"ready": False, "reason": "no_new", "turn": {"found": False}}
    assert ows.status_text(lost) == "no new image on the page yet (this job's prompt is not visible in the chat)"
    assert ows.status_text({"reason": "Boom: x"}) == "check said: Boom: x"
    assert ows.status_text(None) == "check said: unknown"


@pytest.mark.unit
def test_status_line_logs_on_change_every_20s_and_on_slow_checks(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(ows.time, "monotonic", lambda: now[0])
    lines = []
    st = ows.WaitStatus(lines.append, 120.0, 100.0)
    no_new = {"ready": False, "reason": "no_new"}
    st.note(no_new, 0.1)
    now[0] = 110.0
    st.note(no_new, 0.1)                       # same words, not due → silent
    st.note({"ready": True, "src": "x"}, 0.1)  # ready answers log themselves
    now[0] = 121.0
    st.note(no_new, 0.1)                       # due (≥ 20 s)
    st.note({"ready": False, "reason": "turn_generating"}, 0.2)   # changed
    st.note({"ready": False, "reason": "turn_generating"}, 7.5)   # slow page check
    assert lines == [
        "⏳ Output check 0s/120s: no new image on the page yet",
        "⏳ Output check 21s/120s: no new image on the page yet",
        "⏳ Output check 21s/120s: the image is still being generated",
        "⏳ Output check 21s/120s: the image is still being generated · slow page check 7.5s",
    ]


@pytest.mark.unit
def test_timeout_text_says_what_the_last_check_saw():
    result = {"reason": "timeout", "last": {"ready": False, "reason": "turn_no_image", "engine": "turn",
                                            "turn_found": True, "candidates": []}}
    assert out._timeout_text(result, 120000) == (
        "Timeout after 120000ms — last check: no finished image in this job's answer yet "
        "(job prompt found, no large image under it)")
    assert out._timeout_text({"reason": "timeout"}, 5) == "Timeout after 5ms"


@pytest.mark.unit
async def test_wait_loop_emits_status_lines_and_keeps_its_timeout_contract():
    lines = []

    async def check():
        return {"ready": False, "reason": "turn_no_image", "engine": "turn", "turn_found": True}

    t0 = time.monotonic()
    res = await wait_for_new_output_with_spec(check, lines.append, None, WaitSpec(timeout=0.05, poll_interval=0.01))
    assert res["reason"] == "timeout" and res["last"]["reason"] == "turn_no_image"
    assert lines[0].startswith("⏳ Output check 0s/0s: no finished image in this job's answer yet")
    assert len([l for l in lines if l.startswith("⏳ Output check")]) == 1   # throttled
    assert time.monotonic() - t0 < 2
