import pytest
from app.browser.site_adapter import SELECTORS, get_selector

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
        assert sel.tier in ("semantic", "structural", "class-fragment")  # RULE 21

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
