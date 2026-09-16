"""Run production admission JavaScript, including the hidden-file-input case."""
import json
import subprocess
from pathlib import Path

import pytest
from app.browser.page_availability import PAGE_AVAILABILITY_JS


@pytest.mark.parametrize('fixture,expected', [
    ({}, 'steady'),
    ({'send': {'disabled': True}}, 'steady'),
    ({'prompt': False}, 'not_ready'),
    ({'prompt': {'disabled': True}}, 'not_ready'),
    ({'prompt': {'offsetParent': None}}, 'not_ready'),
    ({'send': False}, 'not_ready'),
    ({'file': False}, 'not_ready'),
    ({'activity': [{}]}, 'busy'),
    ({'outputs': [{'complete': False}]}, 'busy'),
    ({'outputs': [{'complete': True}]}, 'steady'),
    ({'outputs': [{'complete': False, 'offsetParent': None}]}, 'steady'),
    ({'activity': [{'offsetParent': None}]}, 'steady'),
    ({'captcha': [{}]}, 'waiting_captcha'),
    ({'captcha': [{'offsetParent': None}]}, 'steady'),
    ({'activity': [{}], 'captcha': [{}]}, 'waiting_captcha'),
    ({'dialogs': [{'innerText': 'Security Verification'}]}, 'waiting_captcha'),
    ({'dialogs': [{'innerText': 'Security Verification', 'offsetParent': None}]}, 'steady'),
    ({'dialogs': [{'innerText': 'Other dialog'}]}, 'steady'),
])
def test_real_availability_probe(fixture, expected):
    harness = Path(__file__).with_name('js_harness.js')
    result = subprocess.run(['node', str(harness)], input=json.dumps({
        'probe': PAGE_AVAILABILITY_JS, 'fixture': fixture,
    }), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == {'status': expected}
