"""Workspace save/restore services — provider registry + thin coordinator.

Import direction: `app/services/workspace` never imports `app.ui*`
(`tests/test_workspace_architecture.py` pins this). Providers own their
native formats (one small class per domain — design §B table); the
coordinator owns the folder, manifest, ordering, integrity, reports and
recovery backup. No giant AppState, no second schema (task rules 1–2).
"""
