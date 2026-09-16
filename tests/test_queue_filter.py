"""Tests for app/utils/queue_filter.py — _AI output suffix matching."""

import pytest

from app.utils.queue_filter import is_ai_output


@pytest.mark.unit
def test_matches_plain_and_numbered_outputs():
    assert is_ai_output("photo_AI.png") is True
    assert is_ai_output("photo_AI.jpg") is True
    assert is_ai_output("photo_AI_1.png") is True
    assert is_ai_output("photo_AI_12.png") is True
    assert is_ai_output("_AI.png") is True


@pytest.mark.unit
def test_matches_with_dirs_and_weird_names():
    assert is_ai_output("F:/pics/sub/photo_AI.png") is True
    assert is_ai_output("/tmp/a.b_AI_3.jpeg") is True
    assert is_ai_output("my.photo_AI.png") is True


@pytest.mark.unit
def test_rejects_originals():
    assert is_ai_output("photo.png") is False
    assert is_ai_output("photo_ai.png") is False  # case-sensitive
    assert is_ai_output("my_AI_photo.png") is False  # not at the end
    assert is_ai_output("AI.png") is False
    assert is_ai_output("photo_AI_final.png") is False
    assert is_ai_output("") is False
    assert is_ai_output(None) is False
