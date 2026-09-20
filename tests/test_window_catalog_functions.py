"""S8 function unit; cross-language registry/migration contracts stay separate."""
import pytest

from app.core.window_catalog import default_grid_tree

pytestmark = pytest.mark.unit


@pytest.mark.target('app.core.window_catalog:default_grid_tree')
def test_default_grid_tree():
    first, second = default_grid_tree(), default_grid_tree()
    assert first == second and first is not second
    leaves = []
    stack = [first]
    while stack:
        node = stack.pop()
        if node['t'] == 'leaf':
            leaves.append(node['id'])
        else:
            assert len(node['children']) == len(node['sizes'])
            assert sum(node['sizes']) == pytest.approx(100)
            stack.extend(node['children'])
    assert len(leaves) == len(set(leaves)) == 16
    assert 'live_debug' in leaves and 'recordings' in leaves
    first.clear()
    assert second and default_grid_tree() == second
