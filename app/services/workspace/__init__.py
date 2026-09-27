"""Workspace save/restore services — provider registry + meta/save/restore/apply.

Import direction: `app/services/workspace` never imports `app.ui*`
(`tests/test_workspace_architecture.py` pins this). Providers own their
native formats (one small class per domain — design §B table); the
meta owns identity/env; save owns the SAVE side; apply owns the RESTORE side;
recovery backup. No giant AppState, no second schema (task rules 1–2).
"""
