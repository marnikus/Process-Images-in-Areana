import copy
import json
import math

import pytest

from image_queue.domain.validation import ContractError
from image_queue.workspace.layout import validate_layout, validate_tree
from image_queue.workspace.schema import validate_workspace


@pytest.mark.parametrize(
    "tree",
    [
        None,
        {},
        {"t": "leaf", "id": "unknown"},
        {"t": "leaf", "id": "stats"},
        {"t": "leaf", "id": []},
        {"t": "split", "dir": "bad", "children": [], "sizes": []},
    ],
)
def test_invalid_trees(tree):
    with pytest.raises(ContractError):
        validate_tree(tree)


@pytest.mark.parametrize("sizes", [None, [100], [99, 99], [float("nan"), 50], [True, 99], [3, 97]])
def test_invalid_split_allocations(workspace, sizes):
    tree = workspace["layout"]["tree"]
    tree["sizes"] = sizes
    with pytest.raises(ContractError):
        validate_tree(tree)


def test_tree_depth_and_duplicate_leaf_guard(workspace):
    leaf = {"t": "leaf", "id": "stats"}
    tree = leaf
    for _ in range(15):
        tree = {"t": "split", "dir": "row", "children": [tree, leaf], "sizes": [50, 50]}
    with pytest.raises(ContractError, match="nesting"):
        validate_tree(tree)
    tree = workspace["layout"]["tree"]
    tree["children"][0] = copy.deepcopy(tree["children"][1])
    with pytest.raises(ContractError):
        validate_tree(tree)


@pytest.mark.parametrize(
    "patch",
    [
        {"closed": ["unknown"]},
        {"closed": ["stats", "stats"]},
        {"closed": [None]},
        {"closed": {}},
        {"closed": ["stats"], "minimized": ["stats"]},
    ],
)
def test_invalid_window_states(workspace, patch):
    with pytest.raises(ContractError):
        validate_layout({**workspace["layout"], **patch})


@pytest.mark.parametrize(
    "patch",
    [
        {"prompt": "a" * 64001},
        {"folder": "a\x00b"},
        {"layouts": []},
        {"layouts": {" ": {}}},
        {"layouts": {str(i): {} for i in range(31)}},
        {"geometry": []},
        {"geometry": [0, 0, 100, 100]},
        {"geometry": [True, 0, 1000, 800]},
        {"geometry": [100001, 0, 1000, 800]},
        {"connection": "{}"},
    ],
)
def test_invalid_workspace_rejected_without_silent_defaults(workspace, patch):
    with pytest.raises(ContractError):
        validate_workspace({**workspace, **patch})


def test_named_layout_and_full_workspace_roundtrip(workspace):
    workspace["layouts"]["Editing desk"] = copy.deepcopy(workspace["layout"])
    validate_workspace(json.loads(json.dumps(workspace)))
    assert math.isclose(sum(workspace["layout"]["tree"]["sizes"]), 100)


@pytest.mark.parametrize(
    "sizes,message", [([float("nan"), 50], "finite"), ([3, 97], "finite"), ([51, 50], "sum")]
)
def test_size_value_errors_not_only_child_count(sizes, message):
    tree = {
        "t": "split",
        "dir": "row",
        "children": [{"t": "leaf", "id": "stats"}, {"t": "leaf", "id": "config"}],
        "sizes": sizes,
    }
    with pytest.raises(ContractError, match=message):
        validate_tree(tree)


def test_split_child_count_must_be_supported():
    with pytest.raises(ContractError, match="2–14"):
        validate_tree({"t": "split", "dir": "row", "children": [], "sizes": []})
