"""The Firefox job's bridge seams (audit R3, 2026-09-26).

RULE 5: a UI / persist callback never kills the pipeline — and a failure is
never silent either: it reaches the `arena` logger as a warning.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services import firefox_job_host as host

pytestmark = pytest.mark.unit


class Raising:
    def __getattr__(self, name):
        raise RuntimeError(f"{name} down")


def test_say_passes_text_and_level_to_the_bridge():
    seen = []
    host.say(NS(_log=lambda text, level: seen.append((level, text))), "hello", "warn")
    assert seen == [("warn", "hello")]


def test_a_failing_seam_is_logged_never_raised(caplog):
    with caplog.at_level(logging.WARNING, logger="arena"):
        host.say(Raising(), "hello")
        host.persist(Raising())
        assert host.call("pool push", lambda: 1 / 0) is False
    text = caplog.text
    assert "log line failed" in text and "state save failed" in text and "pool push failed" in text


def test_call_reports_success():
    assert host.call("noop", lambda: None) is True


def test_persist_recalculates_then_saves():
    order = []
    bridge = NS(state=NS(recalculate_progress=lambda: order.append("progress")),
                _save_arena=lambda: order.append("save"))
    host.persist(bridge)
    assert order == ["progress", "save"]


@pytest.mark.parametrize("bridge, fallback, expected", [
    (NS(config=NS(dir="/cfg")), Path("."), Path("/cfg")),
    (NS(config=NS(dir=Path("/cfg"))), None, Path("/cfg")),
    (NS(config=NS(dir=None)), Path("."), Path(".")),
    (NS(), None, None),
    (NS(config=NS(dir=object())), None, None),        # a MagicMock-ish dir is not a path
])
def test_config_dir(bridge, fallback, expected):
    assert host.config_dir(bridge, fallback) == expected


def test_config_dir_defaults_to_the_working_folder():
    assert host.config_dir(NS()) == Path(".")


def test_settings_of_tolerates_a_bare_bridge():
    settings = NS(timeouts={})
    assert host.settings_of(NS(state=NS(settings=settings))) is settings
    assert host.settings_of(NS()) is None


@pytest.mark.parametrize("timeouts, expected", [
    ({"download": 7}, 7), ({"download": "9"}, 9), ({}, 60), ({"download": "soon"}, 60),
])
def test_timeout_s_reads_the_chrome_knobs(timeouts, expected):
    bridge = NS(state=NS(settings=NS(timeouts=timeouts)))
    assert host.timeout_s(bridge, "download", 60) == expected


def test_timeout_s_without_settings_is_the_default():
    assert host.timeout_s(NS(), "generation", 180) == 180
