"""D5 mutation triage: naming + cooldown primitives, branch-complete.

Targets naming (get_output_path 11, atomic_write_bytes 12) and
core cooldown (config_from_dict 18, config_to_dict 5, cooldown_total 4,
clamp_seconds 4, is_cooling 3, remaining_seconds 2, format_remaining 2).
"""

import os

from pathlib import Path

from app.core import naming
from app.core.naming import OutputSpec
from app.core.cooldown import (
    DAY_SECONDS,
    CooldownConfig,
    clamp_seconds,
    cooldown_total,
    config_from_dict,
    config_to_dict,
    format_remaining,
    is_cooling,
    remaining_seconds,
)


class TestGetOutputPath:
    def test_basic_new_target(self, tmp_path):
        src = tmp_path / "img.png"
        out = naming.get_output_path(src)
        assert out == tmp_path / "img_AI.png"

    def test_custom_suffix(self, tmp_path):
        src = tmp_path / "img.png"
        out = naming.get_output_path(src, OutputSpec(suffix="_X"))
        assert out.name == "img_X.png"

    def test_existing_target_gets_unique_number(self, tmp_path):
        src = tmp_path / "img.png"
        (tmp_path / "img_AI.png").write_bytes(b"x")
        out = naming.get_output_path(src)
        assert out.name == "img_AI_2.png"

    def test_existing_unique_increments(self, tmp_path):
        src = tmp_path / "img.png"
        (tmp_path / "img_AI.png").write_bytes(b"x")
        (tmp_path / "img_AI_2.png").write_bytes(b"x")
        out = naming.get_output_path(src)
        assert out.name == "img_AI_3.png"

    def test_overwrite_returns_existing_target(self, tmp_path):
        src = tmp_path / "img.png"
        (tmp_path / "img_AI.png").write_bytes(b"x")
        out = naming.get_output_path(src, OutputSpec(overwrite=True))
        assert out.name == "img_AI.png"

    def test_downloaded_ext_with_dot(self, tmp_path):
        src = tmp_path / "img.png"
        out = naming.get_output_path(src, OutputSpec(downloaded_ext=".jpg"))
        assert out.name == "img_AI.jpg"

    def test_downloaded_ext_without_dot(self, tmp_path):
        src = tmp_path / "img.png"
        out = naming.get_output_path(src, OutputSpec(downloaded_ext="webp"))
        assert out.name == "img_AI.webp"

    def test_downloaded_ext_ignored_when_not_preserving(self, tmp_path):
        src = tmp_path / "img.png"
        out = naming.get_output_path(src, OutputSpec(downloaded_ext=".jpg", preserve_format=False))
        assert out.name == "img_AI.png"

    def test_source_without_suffix(self, tmp_path):
        src = tmp_path / "archive"
        out = naming.get_output_path(src)
        assert out.name == "archive_AI"

    def test_bad_unique_template_falls_back(self, tmp_path):
        src = tmp_path / "img.png"
        (tmp_path / "img_AI.png").write_bytes(b"x")
        out = naming.get_output_path(src, OutputSpec(unique_template="{bogus}"))
        assert out.name == "img_AI_2.png"

    def test_custom_template(self, tmp_path):
        src = tmp_path / "img.png"
        (tmp_path / "img_AI.png").write_bytes(b"x")
        out = naming.get_output_path(src, OutputSpec(unique_template="{base}-out-{n}{ext}"))
        assert out.name == "img-out-2.png"


class TestAtomicWriteBytes:
    def test_writes_and_returns_final(self, tmp_path):
        final = tmp_path / "out.bin"
        result = naming.atomic_write_bytes(tmp_path / "tmp", final, b"hello")
        assert result == final
        assert final.read_bytes() == b"hello"
        assert not list(tmp_path.glob("*.partial_*"))

    def test_empty_data_rejected(self, tmp_path):
        final = tmp_path / "out.bin"
        try:
            naming.atomic_write_bytes(tmp_path / "tmp", final, b"")
            assert False, "expected ValueError"
        except ValueError:
            pass
        assert not final.exists()

    def test_temp_dir_param_created_but_ignored(self, tmp_path):
        # Characterization (D5): temp_dir IS created, but the partial file is
        # actually placed in final_path.parent — the param is currently unused.
        final = tmp_path / "out.bin"
        naming.atomic_write_bytes(tmp_path / "newtmp", final, b"x")
        assert (tmp_path / "newtmp").is_dir()
        assert final.read_bytes() == b"x"


class TestIsAiGeneratedFilename:
    def test_exact_suffix(self):
        assert naming.is_ai_generated_filename("image_AI.png") is True
        assert naming.is_ai_generated_filename(Path("x/image_AI.jpg")) is True

    def test_suffix_with_number(self):
        assert naming.is_ai_generated_filename("image_AI_2.png") is True
        assert naming.is_ai_generated_filename("image_AI_10.png") is True

    def test_not_generated(self):
        assert naming.is_ai_generated_filename("image.png") is False
        assert naming.is_ai_generated_filename("imageAI.png") is False
        assert naming.is_ai_generated_filename("image_ai_2.png") is False
        assert naming.is_ai_generated_filename("image_AI_2_backup.png") is False

    def test_custom_suffix(self):
        assert naming.is_ai_generated_filename("image_X_1.png", suffix="_X") is True
        assert naming.is_ai_generated_filename("image_X.png", suffix="_X") is True


class TestClampSeconds:
    def test_in_range(self):
        assert clamp_seconds(5) == 5
        assert clamp_seconds(0) == 0
        assert clamp_seconds(DAY_SECONDS) == DAY_SECONDS

    def test_out_of_range(self):
        assert clamp_seconds(-1) == 0
        assert clamp_seconds(DAY_SECONDS + 1) == DAY_SECONDS
        assert clamp_seconds(-100, limit=10) == 0
        assert clamp_seconds(100, limit=10) == 10

    def test_bad_types_return_default(self):
        assert clamp_seconds(None) == 0
        assert clamp_seconds(None, default=7) == 7
        assert clamp_seconds("abc") == 0
        assert clamp_seconds("abc", default=9) == 9
        assert clamp_seconds("12.9", default=4) == 4
        assert clamp_seconds(12.9) == 12

    def test_numeric_string(self):
        assert clamp_seconds("42") == 42


class TestConfigRoundTrip:
    def test_none_and_empty_get_defaults(self):
        for data in (None, {}):
            cfg = config_from_dict(data)
            assert cfg.enabled is True
            assert cfg.min_seconds == 300
            assert cfg.captcha_penalty_seconds == 900
            assert cfg.rate_limit_penalty_seconds == 1800

    def test_non_dict_gets_defaults(self):
        cfg = config_from_dict("junk")
        assert cfg.min_seconds == 300

    def test_explicit_values(self):
        cfg = config_from_dict({
            "enabled": False,
            "min_seconds": 60,
            "captcha_penalty_seconds": 120,
            "rate_limit_penalty_seconds": 30,
        })
        assert cfg.enabled is False
        assert cfg.min_seconds == 60
        assert cfg.captcha_penalty_seconds == 120
        assert cfg.rate_limit_penalty_seconds == 30

    def test_bad_values_clamped_or_defaulted(self):
        cfg = config_from_dict({
            "enabled": "1",
            "min_seconds": -5,
            "captcha_penalty_seconds": "junk",
            "rate_limit_penalty_seconds": 999999,
        })
        assert cfg.enabled is True
        assert cfg.min_seconds == 0
        assert cfg.captcha_penalty_seconds == 900
        assert cfg.rate_limit_penalty_seconds == DAY_SECONDS

    def test_to_dict_shape(self):
        d = config_to_dict(CooldownConfig(
            enabled=False, min_seconds=120, captcha_penalty_seconds=1800,
            rate_limit_penalty_seconds=3600))
        assert d == {
            "enabled": False,
            "min_seconds": 120,
            "captcha_penalty_seconds": 1800,
            "rate_limit_penalty_seconds": 3600,
            "min_minutes": 2,
            "captcha_penalty_minutes": 30,
            "rate_limit_penalty_minutes": 60,
        }

    def test_round_trip(self):
        cfg = config_from_dict({"min_seconds": 61, "captcha_penalty_seconds": 91})
        back = config_from_dict(config_to_dict(cfg))
        assert back.min_seconds == 61
        assert back.captcha_penalty_seconds == 91
        assert back.rate_limit_penalty_seconds == 1800


class TestRemaining:
    def test_future(self):
        assert remaining_seconds(100, now=50) == 50
        assert remaining_seconds(100.9, now=50.2) == 50

    def test_expired_and_exact(self):
        assert remaining_seconds(50, now=50) == 0
        assert remaining_seconds(10, now=50) == 0

    def test_is_cooling_boundaries(self):
        assert is_cooling(100, now=50) is True
        assert is_cooling(50, now=50) is False
        assert is_cooling(10, now=50) is False


class TestCooldownTotal:
    def test_sum(self):
        assert cooldown_total(300, 900) == 1200

    def test_negatives_zeroed(self):
        assert cooldown_total(-5, 100) == 100
        assert cooldown_total(300, -5) == 300
        assert cooldown_total(-5, -5) == 0
        assert cooldown_total(0, 0) == 0


class TestFormatRemaining:
    def test_zero_and_negative(self):
        assert format_remaining(0) == "00:00"
        assert format_remaining(-1) == "00:00"

    def test_under_hour(self):
        assert format_remaining(59) == "00:59"
        assert format_remaining(60) == "01:00"
        assert format_remaining(3599) == "59:59"

    def test_over_hour(self):
        assert format_remaining(3600) == "1:00:00"
        assert format_remaining(3661) == "1:01:01"
        assert format_remaining(90000) == "25:00:00"
