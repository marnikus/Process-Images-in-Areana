"""Protect test-loader alignment with actual UI script order after the legacy splits."""

import json
import re
import subprocess
from pathlib import Path

LEGACY = Path(__file__).parents[1] / "Process Images in Areana" / "Old App"


def test_retained_families_use_shipped_script_order():
    result = subprocess.run(
        ["node", "-e", "console.log(JSON.stringify(require('./tests/js_family').FAMILIES))"],
        cwd=LEGACY,
        capture_output=True,
        text=True,
        check=True,
    )
    families = json.loads(result.stdout)
    html = (LEGACY / "ui/index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="js/([^"]+)"', html)
    for family in families.values():
        positions = [scripts.index(name) for name in family]
        assert positions == sorted(positions), family
    # The formerly empty facade must never substitute for its real implementation.
    assert {"sash-grid-drag-core.js", "sash-grid-drag-spec.js", "sash-grid-drag-resize.js"} <= set(
        families["sashGrid"]
    )
    assert {"stack-drag-core.js", "stack-drag-visual.js", "stack-drag-scroll.js"} <= set(
        families["stackDnd"]
    )
