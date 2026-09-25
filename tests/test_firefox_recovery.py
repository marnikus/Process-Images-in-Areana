"""Crash recovery: what the evidence on disk says the job must do next (step 16).

One row per bullet of the owner's brief, in the order the evidence is trusted —
the file first, the journal second, the page last. The table is pure (files +
journal in, an action out), so it can be driven with a tmpdir and a dict here;
the page probe is `firefox_job`'s job, and it is asked only when the page is the
only witness left.

RED at base: `app/services/firefox_recovery.py` did not exist.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from app.services import firefox_recovery as rec
from app.services import firefox_result as fr

pytestmark = pytest.mark.unit


def settings():
    return NS(output={"suffix": "_AI", "preserve_format": True, "overwrite": False})


def image_bytes(fmt="PNG", size=(64, 64)):
    buf = io.BytesIO()
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(buf, format=fmt)
    return buf.getvalue()


def evidence(tmp_path, journal=None, final_name="pic_AI.png") -> rec.Evidence:
    return rec.Evidence(journal=dict(journal or {}), final_path=tmp_path / final_name,
                        source_path=tmp_path / "pic.png", settings=settings())


def test_nothing_on_disk_is_a_first_try():
    import tempfile
    ev = evidence(Path(tempfile.mkdtemp()))
    plan = rec.plan(ev)
    assert plan.action == rec.FRESH and "no journal" in plan.note


def test_the_final_file_means_completed_never_resubmitted():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    (tmp / "pic_AI.png").write_bytes(image_bytes())
    plan = rec.plan(evidence(tmp))
    assert plan.action == rec.DONE and "already on disk" in plan.note


def test_an_ai_sibling_from_this_jobs_own_window_is_its_output():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    started = datetime.now(timezone.utc).isoformat()
    fresh = tmp / "pic_AI_2.jpg"
    fresh.write_bytes(image_bytes("JPEG"))
    os.utime(fresh, (fr.timestamp_of(started) + 5, fr.timestamp_of(started) + 5))
    plan = rec.plan(evidence(tmp, {"phase": "downloaded", "started_at": started}))
    assert plan.action == rec.DONE and str(fresh) == plan.final_path
    # …but a file from before the job started is somebody else's and proves nothing:
    # a submitted job moves on to the page probe, a prepared one may start fresh
    os.utime(fresh, (fr.timestamp_of(started) - 60, fr.timestamp_of(started) - 60))
    assert rec.plan(evidence(
        tmp, {"phase": "downloaded", "started_at": started})).action == rec.PROBE
    assert rec.plan(evidence(
        tmp, {"phase": "prepared", "started_at": started})).action == rec.FRESH


def test_a_staged_download_is_finished_without_touching_the_page():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    final = tmp / "pic_AI.png"
    data = image_bytes()
    fr.store_staging(final, data)
    plan = rec.plan(evidence(tmp))
    assert plan.action == rec.FINALIZE and plan.data == data
    assert "staged download" in plan.note


def test_a_torn_staging_file_is_dropped_and_never_promoted():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    final = tmp / "pic_AI.png"
    fr.store_staging(final, b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    plan = rec.plan(evidence(tmp))
    assert plan.action == rec.FRESH
    assert not fr.staging_path(final).exists()      # the torn bytes are gone


def test_a_recorded_submit_with_a_correlated_src_is_collected_never_resubmitted():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    plan = rec.plan(evidence(tmp, {"phase": "submitted", "submit_clicks": 1,
                                   "src": "https://x/1.png"}))
    assert plan.action == rec.COLLECT and plan.src == "https://x/1.png"
    assert "never resubmitting" in plan.note
    # a lost acknowledgement (clicks unknown) still counts as submitted when the phase says so
    plan = rec.plan(evidence(tmp, {"phase": "correlated", "src": "https://x/2.png"}))
    assert plan.action == rec.COLLECT and plan.src == "https://x/2.png"


def test_a_recorded_submit_without_a_src_asks_the_page_first():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    plan = rec.plan(evidence(tmp, {"phase": "submitted", "submit_clicks": 1}))
    assert plan.action == rec.PROBE and "never resubmitting" in plan.note
    # clicks recorded but the phase never advanced (the macro died after the click)
    assert rec.plan(evidence(tmp, {"submit_clicks": 1})).action == rec.PROBE


def test_a_journal_without_a_submit_is_a_safe_fresh_retry():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    for journal in ({}, {"phase": "baseline"}, {"phase": "prepared", "submit_clicks": 0}):
        plan = rec.plan(evidence(tmp, journal))
        assert plan.action == rec.FRESH, journal
        assert "nothing was submitted" in plan.note or "no journal" in plan.note


def test_the_page_probe_decides_the_last_row_and_doubt_becomes_review():
    import tempfile
    ev = evidence(Path(tempfile.mkdtemp()))
    ready = rec.after_probe(ev, {"result": {"candidates": [
        {"src": "https://x/1.png", "after": True, "in_user": False, "large": True}]}},
        correlate=lambda reply: ("ready", "https://x/1.png", "one large candidate after this job's token"))
    assert ready.action == rec.COLLECT and ready.src == "https://x/1.png"

    for status, reason, needle in (("ambiguous", "2 candidate(s) after the token", "human must choose"),
                                   ("rejected", "3 new image(s) exist but none after", "other jobs"),
                                   ("uncertain", "generation still running", "no result"),
                                   ("missing", "no result answer", "no result")):
        plan = rec.after_probe(ev, {"result": {}}, correlate=lambda _r, s=status, r=reason: (s, "", r))
        assert plan.action == rec.REVIEW, status
        assert needle in plan.note, plan.note


def test_review_paths_never_carry_bytes_or_a_source():
    import tempfile
    ev = evidence(Path(tempfile.mkdtemp()))
    plan = rec.after_probe(ev, {"result": {}}, correlate=lambda _r: ("ambiguous", "https://x/1.png", "2"))
    assert plan.data == b"" and plan.src == ""       # nothing to save, nothing to fetch
