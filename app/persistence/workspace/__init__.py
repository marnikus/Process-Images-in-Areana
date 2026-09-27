"""Workspace save core — failure vocabulary, integrity, manifest, folder IO.

Pure + stdlib only: no Qt, no bridge, no app.services imports
(`tests/test_workspace_architecture.py` pins this). The services-layer
the services own ordering and reports; this package owns the file-level
contracts: one stage vocabulary (`errors`), deterministic bytes + safe
paths (`integrity`), the manifest schema (`manifest`), and the
temp-folder → manifest-last → atomic-publish protocol (`fsio`).
"""
