"""Repo hygiene — runtime data and secrets never reach Git.

2026-10-09 (B13): two 2Captcha API keys, the whole `config/` tree (session,
undo history, captcha recordings, presets), `logs/`, 50 `.pyc` files and the
saved arena.ai pages (with account e-mails) were tracked in a PUBLIC repo
although `.gitignore` listed them — they had been committed before the rule
existed, so the ignore never applied. This lane asks git itself (RULE 8) and
fails the moment any such path is tracked again; `tools/pre_push_check.sh`
step 0 runs the same check before every push.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Directories that hold runtime/user data — nothing under them may be tracked
# except the placeholders in ALLOWED.
RUNTIME_PREFIXES = ("config/", "logs/", "arena webpages/")
ALLOWED = frozenset({"config/.gitkeep"})

# `"api_key": "<hex>"` as the captcha key stores write it (20+ hex chars so
# short placeholders in docs/tests never trip it).
API_KEY_RE = re.compile(r'"api_key"\s*:\s*"[0-9a-f]{20,}"', re.IGNORECASE)
MAX_SCAN_BYTES = 2_000_000


def is_runtime_artifact(rel: str) -> bool:
    """True for a path that must never be tracked (runtime data or bytecode)."""
    if rel in ALLOWED:
        return False
    if rel.startswith(RUNTIME_PREFIXES):
        return True
    return rel.endswith(".pyc") or "__pycache__/" in rel


def tracked_files() -> list[str]:
    """`git ls-files` of this checkout; skips the lane outside a git repo."""
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run([git, "ls-files", "-z"], cwd=ROOT, check=True,
                         capture_output=True).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def files_with_api_key(paths: list[str], root: Path = ROOT) -> list[str]:
    """Tracked text files (relative to root) that contain an api_key literal."""
    hits = []
    for rel in paths:
        path = root / rel
        if not path.is_file() or path.stat().st_size > MAX_SCAN_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if API_KEY_RE.search(text):
            hits.append(rel)
    return hits


@pytest.mark.parametrize("rel", [
    "config/2captcha.json",
    "config/captcha_solvers.json",
    "config/captcha_recordings/20260918T153914/events.jsonl",
    "logs/2026-09-16.log",
    "arena webpages/state/page.html",
    "app/core/__pycache__/models.cpython-310.pyc",
    "tests/__pycache__/x.pyc",
])
def test_predicate_flags_every_runtime_class(rel):
    assert is_runtime_artifact(rel) is True


@pytest.mark.parametrize("rel", ["config/.gitkeep", "app/core/models.py",
                                 "docs/current/SYSTEM_OF_RECORD.md", "tests/test_repo_hygiene.py"])
def test_predicate_keeps_source_and_placeholder(rel):
    assert is_runtime_artifact(rel) is False


def test_api_key_regex_matches_store_format_only():
    assert API_KEY_RE.search('{"api_key": "00000000000000000000000000000000"}')
    assert API_KEY_RE.search('"api_key":"ABCDEF0123456789ABCDEF01"')
    assert not API_KEY_RE.search('"api_key": ""')
    assert not API_KEY_RE.search('"api_key": "<your key>"')
    assert not API_KEY_RE.search('api_key = load()')


def test_no_runtime_data_is_tracked():
    leaked = sorted(p for p in tracked_files() if is_runtime_artifact(p))
    assert leaked == [], f"runtime data tracked — `git rm --cached` it: {leaked[:10]}"


def test_no_api_key_literal_is_tracked():
    assert files_with_api_key(tracked_files()) == []


def test_api_key_scanner_finds_a_planted_key(tmp_path):
    """The scanner itself must be live, not vacuously green (RULE 8)."""
    (tmp_path / "leak.json").write_text(
        '{"api_key": "0123456789abcdef0123456789abcdef"}', encoding="utf-8")
    (tmp_path / "clean.json").write_text('{"api_key": ""}', encoding="utf-8")
    assert files_with_api_key(["leak.json", "clean.json", "missing.json"], tmp_path) == ["leak.json"]
