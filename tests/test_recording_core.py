"""Recording sanitizer/session/diff — redaction, header round-trip, diffs.

RULE 8: real functions exercised; a deleted function fails these loudly.
"""

import pytest

from app.services.recording import sanitizer as san
from app.services.recording.diffview import snapshot_diff, timeline_summary
from app.services.recording.session import LABELS, OUTCOMES, RecordingSession


@pytest.mark.unit
def test_redact_dom_blanks_recaptcha_fields():
    html = ('<div><textarea name="g-recaptcha-response" id="g-recaptcha-response-12">'
            'SECRET-TOKEN-VALUE</textarea>'
            '<input name="g-recaptcha-response" value="ANOTHER-SECRET"/></div>')
    out = san.redact_dom_html(html)
    assert "SECRET-TOKEN-VALUE" not in out
    assert "ANOTHER-SECRET" not in out
    assert out.count("[REDACTED]") == 2


@pytest.mark.unit
def test_redact_dom_leaves_clean_html():
    html = "<div>hello</div>"
    assert san.redact_dom_html(html) == html
    assert san.redact_dom_html("") == ""


@pytest.mark.unit
def test_redact_url_recaptcha_keeps_param_names_only():
    url = ("https://www.google.com/recaptcha/enterprise/anchor"
           "?ar=1&k=6Le3SECRETSITEKEY&bft=0dAFBIGSECRETTOKEN&hl=en")
    out = san.redact_url(url)
    assert "6Le3SECRETSITEKEY" not in out and "0dAFBIGSECRETTOKEN" not in out
    # recaptcha-family: ALL values masked, names kept (host/path readable)
    assert "k=*" in out and "bft=*" in out and "hl=*" in out and "ar=*" in out
    assert out.startswith("https://www.google.com/recaptcha/enterprise/anchor?")


@pytest.mark.unit
def test_redact_url_other_host_keeps_path_strips_secret_params():
    url = "https://arena.ai/api/chat?model=x&token=VERYSECRET&page=2"
    out = san.redact_url(url)
    assert "VERYSECRET" not in out and "token=*" in out
    assert "model=x" in out and "page=2" in out


@pytest.mark.unit
def test_bound_str_clips_and_flattens():
    assert san.bound_str("a\nb" * 500, 10) == "a ba ba ba"
    assert san.bound_str(None) == ""


@pytest.mark.unit
def test_session_header_round_trip():
    s = RecordingSession.create("TAB123456", {
        "url": "https://arena.ai/c/1", "trigger": "check-security",
        "kind": "recaptcha_enterprise", "sitekey": "6Le3key"})
    s.bump("events"); s.bump("mutations", 3)
    restored, err = RecordingSession.from_header(s.to_header())
    assert err == "" and restored is not None
    assert restored.id == s.id and restored.trigger == "check-security"
    assert restored.counters["events"] == 1 and restored.counters["mutations"] == 3
    s.finalize("solved", "auto")
    restored2, err2 = RecordingSession.from_header(s.to_header())
    assert err2 == "" and restored2.outcome == "solved" and restored2.status == "stopped"


@pytest.mark.unit
def test_session_header_rejects_corrupt():
    assert RecordingSession.from_header("nope")[1]
    assert RecordingSession.from_header({"v": 99, "id": "x"})[1]
    assert RecordingSession.from_header({"v": 1, "id": "../evil"})[1]
    ok, err = RecordingSession.from_header({"v": 1, "id": "20260918-120000-ABC123"})
    assert err == "" and ok.id.startswith("2026")
    assert RecordingSession.from_header({"v": 1, "id": "x"*5, "label": "hax"})[0].label == ""


@pytest.mark.unit
def test_finalize_maps_unknown_outcome_to_none():
    s = RecordingSession.create("T", {"url": "u", "trigger": "job"})
    s.finalize("bogus-outcome")
    assert s.outcome == "none" and s.outcome != "bogus-outcome"
    assert "none" in OUTCOMES and "" in LABELS


@pytest.mark.unit
def test_snapshot_diff_bounded_and_identical():
    a = "<html>\n<body>\n<p>same</p>\n</body>\n</html>"
    assert snapshot_diff(a, a)["identical"] is True
    b = "<html>\n<body>\n<p>changed</p>\n<div>bot extra</div>\n</body>\n</html>"
    d = snapshot_diff(a, b)
    assert d["identical"] is False and d["total"] > 0
    assert any("bot extra" in l for l in d["lines"])


@pytest.mark.unit
def test_timeline_summary_counts():
    events = [{"ts": "2026-09-18T13:23:15Z", "kind": "mutation"},
              {"ts": "2026-09-18T13:23:16Z", "kind": "mutation"},
              {"ts": "2026-09-18T13:23:17Z", "kind": "network", "host": "arena.ai"},
              {"ts": "2026-09-18T13:24:01Z", "kind": "state"}]
    s = timeline_summary(events)
    assert s["total"] == 4 and s["by_kind"]["mutation"] == 2
    assert s["network_hosts"] == {"arena.ai": 1}
    assert s["by_minute"]["2026-09-18T13:23"] == 3
    assert timeline_summary([])["total"] == 0
