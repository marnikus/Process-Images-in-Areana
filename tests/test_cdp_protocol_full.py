"""D5 mutation triage: cdp_protocol full pure-logic tests.

Targets _item_to_tab (30), is_devtools_url (19), _is_valid_tab_item (19),
parse_tabs (4), filter_real_tabs (3).
"""

from app.browser.cdp_protocol import (
    TabInfo,
    deduplicate_tabs_by_id,
    filter_real_tabs,
    is_devtools_url,
    normalize_ws_url,
    parse_tabs,
)


class TestIsDevtoolsUrl:
    def test_empty_url_is_devtools(self):
        assert is_devtools_url("") is True

    def test_prefixes(self):
        for u in ("devtools://devtools/bundled/inspector.html",
                  "chrome://extensions",
                  "chrome-extension://abc/popup.html",
                  "about:blank",
                  "edge://settings"):
            assert is_devtools_url(u) is True, u

    def test_case_insensitive(self):
        assert is_devtools_url("DEVTOOLS://x") is True
        assert is_devtools_url("Chrome://newtab") is True

    def test_embedded_markers(self):
        assert is_devtools_url("https://x.test/devtools/bundled/panel") is True
        assert is_devtools_url("chrome://inspect#device_mode_emulation_frame") is True

    def test_title_devtools(self):
        assert is_devtools_url("https://x.test", title="DevTools") is True
        assert is_devtools_url("https://x.test", title="devtools whatever") is True

    def test_normal_url(self):
        assert is_devtools_url("https://arena.example.com/app", title="Arena") is False
        assert is_devtools_url("https://arena.example.com/app") is False


class TestNormalizeWsUrl:
    def test_empty_unchanged(self):
        assert normalize_ws_url("", "h", 1) == ""

    def test_host_port_replaced(self):
        out = normalize_ws_url("ws://127.0.0.1:9222/devtools/page/1", "0.0.0.0", 1234)
        assert out == "ws://0.0.0.0:1234/devtools/page/1"

    def test_missing_port(self):
        out = normalize_ws_url("ws://localhost/devtools/page/2", "host2", 44)
        assert out == "ws://host2:44/devtools/page/2"

    def test_non_ws_scheme_unchanged(self):
        u = "http://127.0.0.1:9222/json"
        assert normalize_ws_url(u, "h", 1) == u

    def test_no_path_unchanged(self):
        u = "ws://127.0.0.1:9222"
        assert normalize_ws_url(u, "h", 1) == u


class TestIsValidTabItem:
    def test_non_dict(self):
        from app.browser.cdp_protocol import _is_valid_tab_item
        assert _is_valid_tab_item("x", True) is False
        assert _is_valid_tab_item(None, True) is False
        assert _is_valid_tab_item(3, True) is False

    def test_non_page_type_rejected(self):
        from app.browser.cdp_protocol import _is_valid_tab_item
        for t in ("service_worker", "shared_worker", "iframe", "other"):
            assert _is_valid_tab_item({"type": t, "url": "https://x.test"}, True) is False

    def test_missing_type_ok(self):
        from app.browser.cdp_protocol import _is_valid_tab_item
        assert _is_valid_tab_item({"url": "https://x.test"}, True) is True

    def test_page_type_ok(self):
        from app.browser.cdp_protocol import _is_valid_tab_item
        assert _is_valid_tab_item({"type": "page", "url": "https://x.test"}, True) is True

    def test_empty_url_rejected(self):
        from app.browser.cdp_protocol import _is_valid_tab_item
        assert _is_valid_tab_item({"type": "page", "url": ""}, True) is False
        assert _is_valid_tab_item({"type": "page"}, True) is False

    def test_devtools_filtering(self):
        from app.browser.cdp_protocol import _is_valid_tab_item
        dev = {"type": "page", "url": "devtools://x", "title": "t"}
        assert _is_valid_tab_item(dev, True) is True
        assert _is_valid_tab_item(dev, False) is False


class TestItemToTab:
    def test_full_item(self):
        from app.browser.cdp_protocol import _item_to_tab
        t = _item_to_tab({"id": "a", "title": "T", "url": "https://x.test",
                          "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/a",
                          "type": "page"}, "0.0.0.0", 1)
        assert t.id == "a"
        assert t.title == "T"
        assert t.url == "https://x.test"
        assert t.ws_url == "ws://0.0.0.0:1/devtools/page/a"
        assert t.type == "page"

    def test_missing_fields(self):
        from app.browser.cdp_protocol import _item_to_tab
        t = _item_to_tab({"url": "https://x.test"}, "h", 1)
        assert t.id == ""
        assert t.title == ""
        assert t.ws_url == ""
        assert t.type == "page"


class TestParseTabs:
    def test_none_and_empty(self):
        assert parse_tabs(None) == []
        assert parse_tabs([]) == []

    def test_mixed_list(self):
        items = [
            {"id": "1", "type": "page", "title": "A", "url": "https://a.test",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1"},
            "junk",
            {"id": "2", "type": "service_worker", "url": "https://b.test"},
            {"id": "3", "title": "NoUrl"},
            {"id": "4", "type": "page", "url": "chrome://newtab"},
        ]
        tabs = parse_tabs(items, include_devtools=False)
        assert [t.id for t in tabs] == ["1"]
        tabs_all = parse_tabs(items)
        assert "4" in [t.id for t in tabs_all]

    def test_host_port_prefers(self):
        tabs = parse_tabs([{"id": "1", "url": "https://a.test",
                            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1"}],
                          preferred_host="9.9.9.9", preferred_port=77)
        assert tabs[0].ws_url == "ws://9.9.9.9:77/devtools/page/1"


class TestFilterRealTabs:
    def test_removes_devtools(self):
        tabs = [
            TabInfo(id="1", title="A", url="https://a.test", ws_url=""),
            TabInfo(id="2", title="d", url="devtools://x", ws_url=""),
            TabInfo(id="3", title="Chrome", url="chrome://newtab", ws_url=""),
            TabInfo(id="4", title="DevTools panel", url="https://a.test", ws_url=""),
        ]
        out = filter_real_tabs(tabs)
        assert [t.id for t in out] == ["1"]


class TestDeduplicate:
    def test_empty(self):
        assert deduplicate_tabs_by_id([]) == []

    def test_no_key_skipped(self):
        assert deduplicate_tabs_by_id([TabInfo("", "t", "", "")]) == []

    def test_prefers_one_with_ws(self):
        a = TabInfo("x", "t", "https://a.test", "")
        b = TabInfo("x", "t", "https://a.test", "ws://1.2.3.4:9/devtools/page/x")
        out = deduplicate_tabs_by_id([a, b])
        assert len(out) == 1
        assert out[0].ws_url == b.ws_url
        out_rev = deduplicate_tabs_by_id([b, a])
        assert len(out_rev) == 1

    def test_prefers_preferred_host(self):
        a = TabInfo("x", "t", "https://a.test", "ws://1.1.1.1:9/devtools/page/x")
        b = TabInfo("x", "t", "https://a.test", "ws://2.2.2.2:9/devtools/page/x")
        out = deduplicate_tabs_by_id([a, b], preferred_host="2.2.2.2")
        assert out[0].ws_url == b.ws_url
        out2 = deduplicate_tabs_by_id([b, a], preferred_host="2.2.2.2")
        assert out2[0].ws_url == b.ws_url

    def test_distinct_ids_kept(self):
        tabs = [TabInfo("1", "t", "https://a.test", "ws://1:9/1"),
                TabInfo("2", "t", "https://b.test", "ws://1:9/2")]
        assert len(deduplicate_tabs_by_id(tabs)) == 2
