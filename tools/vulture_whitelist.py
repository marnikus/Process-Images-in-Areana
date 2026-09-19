"""Vulture whitelist — protocol signatures that must keep their unused args.

RULE 16 §16.4: "Unused args on protocol/callback signatures may stay."
These names are parameters of Qt `except ImportError` fallback shims that
mirror the real PySide6 signal/slot signatures, so headless imports work
without Qt installed. Renaming or removing them would change the shim
contract for no benefit.

Run:  vulture app tools/vulture_whitelist.py --min-confidence 90   -> 0 findings
"""

# cdp_client.py / bridge.py — Signal/Object fallback shims (*a, **kw)
a

# captcha_recordings_bridge.py — Slot fallback shim (*args, **kwargs)
args
