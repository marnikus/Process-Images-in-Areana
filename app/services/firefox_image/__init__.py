"""Firefox image job — Ui.Vision phases, Chrome's save and cooldown rules (I-65).

Services → browser only. `run_firefox_image` is the dispatcher entry.
"""

from .runner import run_firefox_image

__all__ = ["run_firefox_image"]
