"""
Site Adapter — centralized selectors for arena.ai image generation.
Replaceable because webpage structure will change.
"""
from .selector import SelectorObject
from typing import Dict, List

# Define selectors per spec and research

SELECTORS: Dict[str, SelectorObject] = {
    "model_label": SelectorObject(
        name="model_label",
        primary="span.truncate",
        fallbacks=["span.font-mono.text-sm"],
        scope="div.flex.min-w-0.flex-1.items-center.gap-2",
        mustBeVisible=True,
        mustBeEnabled=False,
        expectedCount=1,
        textCondition="Max",
        textConditionType="equals",
        verification="visible span.truncate with text Max indicates model row",
        evidence="Directly Chat...html + spec A",
        lastVerified="2026-09-15",
    ),
    "processing_spinner": SelectorObject(
        name="processing_spinner",
        primary="div.animate-spin",
        fallbacks=[
            "div.h-5.w-5.flex-shrink-0.animate-spin",
            "div.animate-spin > canvas",
            "div.flex.min-w-0.flex-1.items-center.gap-2 div.animate-spin",
            "div.flex.min-w-0.flex-1.items-center.gap-2:has(div.animate-spin)",
            "div:has(> div.animate-spin)",
            "canvas[width=\"28\"][height=\"28\"]",
        ],
        scope=None,
        mustBeVisible=True,
        mustBeEnabled=False,
        expectedCount=0,
        verification="spinner visible near model label indicates processing. User provided HTML: <div class=\"flex min-w-0 flex-1 items-center gap-2\"><div class=\"h-5 w-5 flex-shrink-0 animate-spin\"><canvas></canvas></div><span><span class=\"truncate\">Response A</span></span></div> — indicates generating. Wait for spinner to disappear + new output image to appear.",
        evidence="spec A + user report 2026-09-16 with Response A/B spinner",
        lastVerified="2026-09-16",
    ),
    "add_files_button": SelectorObject(
        name="add_files_button",
        primary='button[aria-label="Add files"]',
        fallbacks=[
            'button[aria-label*="add" i][aria-label*="file" i]',
            'button[aria-label*="attach" i]',
            'button[aria-label*="upload" i]',
            'button[title*="attach" i]',
        ],
        scope='form:has(textarea[name="message"])',
        mustBeVisible=True,
        mustBeEnabled=True,
        expectedCount=1,
        verification="click triggers file chooser or file input",
        evidence="Directly Chat...html confirmed",
        lastVerified="2026-09-15",
    ),
    "file_input": SelectorObject(
        name="file_input",
        primary='form input[type="file"][accept*="image"]',
        fallbacks=[
            'input[type="file"][accept*="image"]',
            'input[type="file"]',
        ],
        scope='form',
        mustBeVisible=False,  # hidden
        mustBeEnabled=True,
        expectedCount=1,
        verification="can set files via playwright",
        evidence="Directly Chat...html confirmed hidden input",
        lastVerified="2026-09-15",
    ),
    "attachment_preview_container": SelectorObject(
        name="attachment_preview_container",
        primary="div.flex.flex-wrap.gap-2",
        fallbacks=[],
        scope="form",
        mustBeVisible=True,
        mustBeEnabled=False,
        expectedCount=1,
        verification="container exists above textarea",
        evidence="spec C",
        lastVerified="2026-09-15",
    ),
    "attachment_preview_image": SelectorObject(
        name="attachment_preview_image",
        primary='div.flex.flex-wrap.gap-2 img[alt]',
        fallbacks=[
            'div.flex.flex-wrap.gap-2 img[src^="blob:"]',
            'div.group.relative.overflow-hidden.rounded-lg.h-16.w-16 img',
        ],
        scope="form",
        mustBeVisible=True,
        mustBeEnabled=False,
        expectedCount=1,
        textCondition=None,
        verification="preview is new, visible, inside active input area and matches expected filename when available",
        evidence="spec C",
        lastVerified="2026-09-15",
    ),
    "remove_file_button": SelectorObject(
        name="remove_file_button",
        primary='button[aria-label="Remove file"]',
        fallbacks=[
            'div.flex.flex-wrap.gap-2 button[aria-label="Remove file"]',
            'button[type="button"][aria-label="Remove file"]',
        ],
        scope="div.flex.flex-wrap.gap-2",
        mustBeVisible=True,
        mustBeEnabled=True,
        expectedCount=1,
        verification="click removes preview",
        evidence="spec D",
        lastVerified="2026-09-15",
    ),
    "prompt_textarea": SelectorObject(
        name="prompt_textarea",
        primary='textarea[name="message"]',
        fallbacks=[
            'textarea[name="message"][autocomplete="off"]',
            'textarea[placeholder^="Describe how you want to edit"]',
            'textarea[placeholder^="Describe the image you want to generate"]',
            'textarea[placeholder^="Describe"]',
            'textarea[rows="1"]',
        ],
        scope="form",
        mustBeVisible=True,
        mustBeEnabled=True,
        expectedCount=1,
        verification="after insertion, textarea.value equals expected prompt exactly",
        evidence="Directly Chat...html confirmed",
        lastVerified="2026-09-15",
    ),
    "send_button": SelectorObject(
        name="send_button",
        primary='button[aria-label="Send message"]:not([disabled])',
        fallbacks=[
            'button[aria-label="Send message"]',
            'form button[aria-label="Send message"]:not([disabled])',
            'form:has(textarea[name="message"]) button[aria-label="Send message"]:not([disabled])',
            'div.flex.items-center.gap-2 button[aria-label="Send message"]:not([disabled])',
            'button[type="button"][aria-label="Send message"]:not([disabled])',
            'button[type="submit"][aria-label="Send message"]',
            'form div.flex.items-center.gap-2 button:last-child:not([disabled])',
            'form button:has(svg):not([disabled])',
            'button.inline-flex.h-8.w-8[aria-label="Send message"]',
        ],
        scope="form",
        mustBeVisible=True,
        mustBeEnabled=True,
        expectedCount=1,
        verification="click once, confirm processing/loading state, prevent duplicate. Must be enabled after prompt insertion; wait for disabled->enabled transition. User log shows 0 nodes when disabled, need :not([disabled]) primary + wait.",
        evidence="Directly Chat...html confirmed disabled has opacity-50 pointer-events-none; improved 2026-09-16 after failed submit log",
        lastVerified="2026-09-16",
    ),
    "output_region": SelectorObject(
        name="output_region",
        primary="div.no-scrollbar.relative.flex.w-full.flex-1.flex-col.overflow-x-auto",
        fallbacks=[
            "div.no-scrollbar",
            "main div.flex.flex-col.gap-3",
        ],
        scope=None,
        mustBeVisible=True,
        mustBeEnabled=False,
        expectedCount=1,
        verification="output observation container exists",
        evidence="spec G",
        lastVerified="2026-09-15",
    ),
    "output_image": SelectorObject(
        name="output_image",
        primary='div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]',
        fallbacks=[
            'div.no-scrollbar img[src*="messages-prod."]',
            'div.no-scrollbar img[loading="lazy"].aspect-square',
            'img.aspect-square.cursor-pointer',
            'img.cursor-pointer',
            'img[loading="lazy"]',
            'div.flex img[src*=".r2.cloudflarestorage.com/"]',
            'div.flex img.aspect-square',
            'img.aspect-square.w-full',
            'div.no-scrollbar img[src^="https://"]',
            'main img[src*=".r2.cloudflarestorage.com/"]',
            'main img.aspect-square',
        ],
        scope=None,
        mustBeVisible=True,
        mustBeEnabled=False,
        expectedCount=0,  # 0..n
        verification="capture all matching nodes and src before submission, result must be newly inserted or new source after submission, appear after current prompt, finish loading, nonzero natural dimensions. Wait for processing spinner to disappear first.",
        evidence="spec G + user report 2026-09-16 image created but download failed",
        lastVerified="2026-09-16",
    ),
    "security_dialog": SelectorObject(
        name="security_dialog",
        primary='div[role="dialog"][data-state="open"]',
        fallbacks=[],
        scope=None,
        mustBeVisible=True,
        mustBeEnabled=False,
        expectedCount=0,
        textCondition="Security Verification",
        textConditionType="contains",
        verification="if visible, set USER_ACTION_REQUIRED, pause, show page to user",
        evidence="spec H",
        lastVerified="2026-09-15",
    ),
    "recaptcha_iframe": SelectorObject(
        name="recaptcha_iframe",
        primary='iframe[title="reCAPTCHA"]',
        fallbacks=[
            'iframe[src*="google.com/recaptcha/"]',
            'iframe[src*="/recaptcha/enterprise/anchor"]',
            '#recaptcha-v2-container',
        ],
        scope=None,
        mustBeVisible=True,
        mustBeEnabled=False,
        expectedCount=0,
        verification="if visible, pause for manual completion",
        evidence="Directly Chat...html contains grecaptcha badge",
        lastVerified="2026-09-15",
    ),
    "composer_form": SelectorObject(
        name="composer_form",
        primary='form:has(textarea[name="message"])',
        fallbacks=[
            'form.flex.w-full.flex-col',
        ],
        scope=None,
        mustBeVisible=True,
        mustBeEnabled=False,
        expectedCount=1,
        verification="contains file input, textarea, send button",
        evidence="Directly Chat...html",
        lastVerified="2026-09-15",
    ),
    "new_chat_button": SelectorObject(
        name="new_chat_button",
        primary='a[href="/image/direct"]',
        fallbacks=[
            'li[data-sidebar="menu-item"] a[href="/image/direct"]',
            'a[data-sidebar="menu-button"][href="/image/direct"]',
        ],
        scope='li[data-sidebar="menu-item"]',
        mustBeVisible=True,
        mustBeEnabled=True,
        expectedCount=1,
        textCondition="New Chat",
        textConditionType="contains",
        verification="click returns to clean new chat; wait readyState complete + page ready + empty composer",
        evidence="user HTML 2026-09-16: li[data-sidebar=menu-item] > a[href=/image/direct] > span New Chat",
        lastVerified="2026-09-16",
    ),
}

# Composite readiness check
def get_readiness_requirements() -> List[str]:
    return [
        "prompt_textarea",
        "send_button",
        "file_input",
        "output_region",
        # add_files_button is alternative to file_input, but we check both
    ]

def get_selector(name: str) -> SelectorObject:
    if name not in SELECTORS:
        raise KeyError(f"Selector {name} not found")
    return SELECTORS[name]

def list_selectors() -> Dict[str, SelectorObject]:
    return SELECTORS

# Helper to generate JS for finding element with fallbacks
def build_js_find(selector_obj: SelectorObject) -> str:
    """
    Build JS snippet that tries primary then fallbacks, returns element or null.
    This is used for browser controller to evaluate.
    """
    selectors = selector_obj.all_selectors()
    # Escape for JS string
    js_array = "[" + ", ".join(f'"{s}"' for s in selectors) + "]"
    js = f"""
    (function() {{
        const selectors = {js_array};
        const mustBeVisible = {str(selector_obj.mustBeVisible).lower()};
        const mustBeEnabled = {str(selector_obj.mustBeEnabled).lower()};
        function isVisible(el) {{
            if (!el) return false;
            const style = window.getComputedStyle(el);
            return style && style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
        }}
        function isEnabled(el) {{
            return !el.disabled && el.getAttribute('aria-disabled') !== 'true';
        }}
        for (const sel of selectors) {{
            try {{
                const els = document.querySelectorAll(sel);
                for (const el of els) {{
                    if (mustBeVisible && !isVisible(el)) continue;
                    if (mustBeEnabled && !isEnabled(el)) continue;
                    return el;
                }}
            }} catch (e) {{
                continue;
            }}
        }}
        return null;
    }})()
    """
    return js
