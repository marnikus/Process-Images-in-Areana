"""Vulture whitelist — protocol signatures that must keep their unused args.

RULE 16 §16.4: "Unused args on protocol/callback signatures may stay."
These names are parameters of Qt `except ImportError` fallback shims that
mirror the real PySide6 signal/slot signatures, so headless imports work
without Qt installed. Removing them would change the shim contract.

Every name is `*_shim_*`-suffixed on purpose (finding F-2): the old bare
`a`/`args` entries whitelisted those names PROJECT-WIDE and could have
silenced a genuinely unused variable in production code. The distinctive
names can only ever match the shims themselves.

Run:  vulture app tools/vulture_whitelist.py --min-confidence 90   -> 0 findings
"""

# cdp_client.py / bridge.py — QObject / Signal / _Sig fallback shims
qt_shim_args
qt_shim_kwargs
sig_shim_args
sig_shim_kwargs
emit_shim_args
emit_shim_kwargs
connect_shim_args
connect_shim_kwargs

# bridge.py / captcha_recordings_bridge.py — Slot fallback shims
slot_shim_args
slot_shim_kwargs
