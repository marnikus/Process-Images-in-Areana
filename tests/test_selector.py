import pytest
from app.browser.site_adapter import SELECTORS, get_selector, get_readiness_requirements

@pytest.mark.unit
def test_selectors_exist():
    required = ["prompt_textarea", "send_button", "file_input", "output_region", "output_image", "add_files_button"]
    for name in required:
        assert name in SELECTORS, f"Selector {name} missing"

@pytest.mark.unit
def test_selector_structure():
    for name, sel in SELECTORS.items():
        assert sel.name == name
        assert sel.primary
        assert isinstance(sel.fallbacks, list)
        assert sel.expectedCount >= 0

@pytest.mark.unit
def test_readiness_requirements():
    reqs = get_readiness_requirements()
    assert "prompt_textarea" in reqs
    assert "send_button" in reqs
    assert "file_input" in reqs

@pytest.mark.unit
def test_get_selector():
    sel = get_selector("prompt_textarea")
    assert sel.primary == 'textarea[name="message"]'

@pytest.mark.unit
def test_selector_fallbacks():
    sel = get_selector("prompt_textarea")
    all_sels = sel.all_selectors()
    assert len(all_sels) >= 1
    assert all_sels[0] == sel.primary

@pytest.mark.unit
def test_get_selector_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        get_selector("no_such_element")

@pytest.mark.unit
def test_presence_selector_and_round_trip():
    send = get_selector("send_button")
    # broad form matches disabled instances (state scans), differs from primary
    assert send.presence() == 'button[aria-label="Send message"]'
    assert send.presence() != send.primary
    file_input = get_selector("file_input")
    assert file_input.presence() == 'input[type="file"]'
    # to_dict round-trips the presence field (docs/§I shape)
    as_dict = send.to_dict()
    assert as_dict["presenceSelector"] == 'button[aria-label="Send message"]'
    assert as_dict["primary"] == send.primary
