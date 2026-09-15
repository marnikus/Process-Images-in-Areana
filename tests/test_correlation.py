from app.utils.correlation import generate_correlation_id, build_final_prompt, extract_job_id_from_prompt
from datetime import datetime

def test_correlation_format():
    cid = generate_correlation_id()
    # Format YYYYMMDD-HHMMSS-XXXX
    assert len(cid) == 15 + 4 + 1  # 8+1+6+1+4 = 20? Let's check: YYYYMMDD (8) + - (1) + HHMMSS (6) + - (1) + XXXX (4) = 20
    assert len(cid) == 20
    parts = cid.split("-")
    assert len(parts) == 3
    assert len(parts[0]) == 8
    assert len(parts[1]) == 6
    assert len(parts[2]) == 4

def test_correlation_uniqueness():
    ids = {generate_correlation_id() for _ in range(100)}
    # With random 4 chars, collisions possible but very unlikely for 100
    assert len(ids) >= 95  # allow some collision but should be mostly unique

def test_build_final_prompt():
    cid = "20260915-142530-A7F3"
    user_prompt = "Transform this image"
    final = build_final_prompt(cid, user_prompt)
    assert final.startswith(f"[JOB-ID: {cid}]")
    assert user_prompt in final

def test_extract_job_id():
    prompt = "[JOB-ID: 20260915-142530-A7F3]\nTransform this image"
    extracted = extract_job_id_from_prompt(prompt)
    assert extracted == "20260915-142530-A7F3"

def test_extract_job_id_missing():
    prompt = "No job id here"
    assert extract_job_id_from_prompt(prompt) is None

def test_correlation_with_fixed_datetime():
    dt = datetime(2026, 9, 15, 14, 25, 30)
    cid = generate_correlation_id(dt)
    assert cid.startswith("20260915-142530-")
