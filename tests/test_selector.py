from app.browser.site_adapter import SELECTORS, get_selector, get_readiness_requirements

def test_selectors_exist():
    required = ["prompt_textarea", "send_button", "file_input", "output_region", "output_image", "add_files_button"]
    for name in required:
        assert name in SELECTORS, f"Selector {name} missing"

def test_selector_structure():
    for name, sel in SELECTORS.items():
        assert sel.name == name
        assert sel.primary
        assert isinstance(sel.fallbacks, list)
        assert sel.expectedCount >= 0

def test_readiness_requirements():
    reqs = get_readiness_requirements()
    assert "prompt_textarea" in reqs
    assert "send_button" in reqs
    assert "file_input" in reqs

def test_get_selector():
    sel = get_selector("prompt_textarea")
    assert sel.primary == 'textarea[name="message"]'

def test_selector_fallbacks():
    sel = get_selector("prompt_textarea")
    all_sels = sel.all_selectors()
    assert len(all_sels) >= 1
    assert all_sels[0] == sel.primary
