"""Executable S10 acceptance; archive history is not rewritten to pass these."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_current_docs_name_all_chain_invariants_and_live_owners():
    sor = (ROOT / 'docs/current/SYSTEM_OF_RECORD.md').read_text()
    for number in range(47, 55):
        assert f'| I-{number} |' in sor, f'missing current I-{number}'
    assert '`batch_orchestrator.run_batch`' not in sor
    assert '`app/services/batch_orchestrator.run_batch`' not in sor
    assert 'every 15 s' not in sor
    assert 'plans only, not landed' not in sor
    assert 'url_reconcile_interval_ms' in sor


def test_title_fit_is_in_the_default_test_command():
    command = json.loads((ROOT / 'package.json').read_text())['scripts']['test:js']
    assert 'tests/js/test_title_fit.mjs' in command.split()


def test_private_fixture_suite_has_an_explicit_opt_in_command_and_limit():
    scripts = json.loads((ROOT / 'package.json').read_text())['scripts']
    assert 'tests/js/test_captcha_saved_page.mjs' in scripts.get('test:js:saved-page', '').split()
    quality = (ROOT / 'docs/current/QUALITY_RECHECK.md').read_text()
    assert 'test:js:saved-page' in quality
    assert 'private HTML fixtures' in quality


def test_current_readme_marks_the_chain_integrated():
    readme = (ROOT / 'docs/README.md').read_text()
    for line in readme.splitlines():
        if line.startswith('- `archive/2026-09-20-'):
            assert 'planning only' not in line
            assert 'no production code yet' not in line
    assert 'S10' in readme


def test_invariant_enforcement_files_exist_and_window_count_matches_code():
    import re
    from app.core.window_catalog import WINDOW_IDS
    sor = (ROOT / 'docs/current/SYSTEM_OF_RECORD.md').read_text()
    assert f'{len(WINDOW_IDS)} windows:' in sor
    for number in range(47, 55):
        line = next(line for line in sor.splitlines() if line.startswith(f'| I-{number} |'))
        paths = re.findall(r'`((?:tests|app)/[^`]+\.(?:py|mjs))(?::[^`]*)?`', line)
        assert paths, f'I-{number} needs executable enforcement pointers'
        for path in paths:
            assert (ROOT / path).is_file(), (number, path)
