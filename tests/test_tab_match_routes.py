"""The owner's model query must not tie with the Agent tab."""
import pytest
from app.browser.tab_matcher import best_matches, score_tab


def test_model_query_prefers_image_route_regardless_of_listing_order():
    urls = ['https://arena.ai/agent/abc', 'https://arena.ai/c/abc',
            'https://arena.ai/image/direct']
    matches = best_matches('https://arena.ai/image/direct?model_a=max',
                           [{'id': str(i), 'url': u} for i, u in enumerate(urls)])
    assert [m['id'] for m in matches] == ['2']
    assert matches[0]['kind'] == 'url_path'


@pytest.mark.parametrize('url', ['https://arena.ai/agent/abc',
    'https://arena.ai/image/directly', 'https://other.example/image/direct'])
def test_explicit_route_never_falls_back_to_unrelated_tab(url):
    assert score_tab('https://arena.ai/image/direct?model_a=max', url)[0] == 0


@pytest.mark.parametrize('query,url,kind', [
    ('https://arena.ai/image/direct?model_a=max', 'https://arena.ai/image/direct?model_a=max', 'url_exact'),
    ('arena.ai/image/direct?model_a=max#x', 'https://arena.ai/image/direct/', 'url_path'),
    ('arena.ai', 'https://arena.ai/agent/a', 'host'),
    ('frontier', 'https://arena.ai/image/direct', 'keyword'),
])
def test_exact_host_and_keyword_modes_remain(query, url, kind):
    assert score_tab(query, url, 'Frontier Images')[1] == kind
