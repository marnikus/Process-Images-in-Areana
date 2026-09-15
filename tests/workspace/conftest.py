"""Real default tree and clean service state; no GUI/database fixtures."""

import json
from pathlib import Path

import pytest

from image_queue.workspace.history import initial_state
from image_queue.workspace.schema import default_workspace


@pytest.fixture
def workspace():
    path = Path(__file__).parents[2] / "src/image_queue/ui/default-tree.json"
    return default_workspace(json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def state(workspace):
    return initial_state(workspace)
