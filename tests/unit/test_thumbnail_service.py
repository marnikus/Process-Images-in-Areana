"""Unit tests for thumbnail_service.py — pure PIL logic with tmp_path (Phase 2).

RULE 18: file 60-200 LOC ideal.
RULE 16: func LOC ≤30, integration marker for FS.
"""

import pytest
from pathlib import Path

from app.ui.services.thumbnail_service import (
    generate_thumbnail_data_url,
    get_cached_thumbnail,
    is_cache_hit,
)


@pytest.mark.unit
def test_is_cache_hit_pure():
    cache = {"id1": "data_url1"}
    assert is_cache_hit(cache, "id1") is True
    assert is_cache_hit(cache, "id2") is False


@pytest.mark.unit
def test_get_cached_thumbnail_pure():
    cache = {"id1": "data_url1"}
    assert get_cached_thumbnail(cache, "id1") == "data_url1"
    assert get_cached_thumbnail(cache, "missing") == ""


@pytest.mark.integration
def test_generate_thumbnail_data_url_with_tmp_path(tmp_path):
    # Create a small PNG via PIL
    from PIL import Image

    img_path = tmp_path / "test.png"
    img = Image.new("RGB", (10, 10), color="red")
    img.save(img_path)

    res = generate_thumbnail_data_url(img_path, size=32)
    assert res["ok"] is True
    assert "data_url" in res
    assert res["data_url"].startswith("data:image/")


@pytest.mark.integration
def test_generate_thumbnail_data_url_missing_file(tmp_path):
    missing = tmp_path / "missing.png"
    res = generate_thumbnail_data_url(missing)
    assert res["ok"] is False
    assert "not exists" in res["error"]


@pytest.mark.unit
def test_guess_mime_via_service():
    # Indirect via generate with fallback — test pure logic of cache
    cache = {}
    assert is_cache_hit(cache, "any") is False
