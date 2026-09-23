"""D5 mutation triage: layout_service grid-tree logic, branch-complete.

Targets normalize_grid_tree (24), canonical_grid_payload (20),
leaf_ids (5), _default_payload (5), _parse_grid_payload (3), _migrate_grid_tree (3).
"""

import json

from app.core import layout_service as ls


def valid_tree():
    return json.loads(ls.default_payload())["tree"]


def payload(tree):
    return json.dumps({"v": ls.GRID_VERSION, "tree": tree})


class TestDefaults:
    def test_default_tree_window_set(self):
        assert sorted(ls.leaf_ids(ls.default_grid_tree())) == sorted(ls.WINDOW_IDS)

    def test_default_tree_splits_sum_100(self):
        def walk(node):
            if node["t"] == "split":
                assert abs(sum(node["sizes"]) - 100) < 0.01, node["sizes"]
                for kid in node["children"]:
                    walk(kid)
        walk(ls.default_grid_tree())

    def test_default_payload(self):
        data = json.loads(ls.default_payload())
        assert data["v"] == ls.GRID_VERSION
        assert data["tree"]["t"] == "split"

    def test_window_titles_cover_ids(self):
        assert set(ls.WINDOW_TITLES) == set(ls.WINDOW_IDS)
        assert ls.WINDOW_TITLES["url_list"] == "URL List"


class TestNormalizeSizes:
    def test_unchanged_when_sums_100(self):
        assert ls._normalize_sizes([50, 50]) == [50.0, 50.0]

    def test_scaled_to_100(self):
        out = ls._normalize_sizes([1, 1])
        assert out == [50.0, 50.0]

    def test_bad_values_clamped_to_min(self):
        out = ls._normalize_sizes(["junk", 0, -5, None])
        assert out == [25.0, 25.0, 25.0, 25.0]

    def test_tiny_slice_redistributed(self):
        out = ls._normalize_sizes([1, 99])
        assert min(out) >= ls.MIN_GRID_SIZE
        assert abs(sum(out) - 100) < 0.01

    def test_floor_exceeds_100_equal_share(self):
        out = ls._normalize_sizes([1] * 40)
        assert abs(sum(out) - 100) < 0.01
        assert all(abs(x - 100 / 40) < 1e-9 for x in out)


class TestNormalizeGridTree:
    def test_leaf_ok(self):
        node, err = ls.normalize_grid_tree({"t": "leaf", "id": "a"})
        assert err is None
        assert node == {"t": "leaf", "id": "a"}

    def test_leaf_without_id(self):
        node, err = ls.normalize_grid_tree({"t": "leaf"})
        assert node is None
        assert err == "leaf without id"

    def test_leaf_non_string_id(self):
        for bad in (5, None, ["x"], ""):
            node, err = ls.normalize_grid_tree({"t": "leaf", "id": bad})
            assert err == "leaf without id", bad

    def test_type_alias(self):
        node, err = ls.normalize_grid_tree({"type": "leaf", "id": "a"})
        assert err is None

    def test_unknown_type(self):
        node, err = ls.normalize_grid_tree({"t": "mystery", "id": "a"})
        assert err == "unknown node type"

    def test_non_dict(self):
        for bad in (None, "x", 3, ["a"]):
            node, err = ls.normalize_grid_tree(bad)
            assert err == "node must be object", bad

    def test_bad_dir(self):
        tree = {"t": "split", "dir": "diagonal", "children": [
            {"t": "leaf", "id": "a"}, {"t": "leaf", "id": "b"}], "sizes": [50, 50]}
        node, err = ls.normalize_grid_tree(tree)
        assert err == "bad dir"

    def test_one_child_rejected(self):
        tree = {"t": "split", "dir": "row", "children": [{"t": "leaf", "id": "a"}], "sizes": [100]}
        node, err = ls.normalize_grid_tree(tree)
        assert err == "split needs >=2 children"

    def test_no_children(self):
        tree = {"t": "split", "dir": "row", "sizes": [50, 50]}
        node, err = ls.normalize_grid_tree(tree)
        assert err == "split needs >=2 children"

    def test_sizes_mismatch(self):
        tree = {"t": "split", "dir": "row", "children": [
            {"t": "leaf", "id": "a"}, {"t": "leaf", "id": "b"}], "sizes": [50]}
        node, err = ls.normalize_grid_tree(tree)
        assert err == "sizes must match children"

    def test_bad_size_values(self):
        for bad in (True, "50", 1, -1, None):
            tree = {"t": "split", "dir": "row", "children": [
                {"t": "leaf", "id": "a"}, {"t": "leaf", "id": "b"}], "sizes": [bad, 50]}
            node, err = ls.normalize_grid_tree(tree)
            assert err == "bad size value", bad

    def test_sizes_not_100(self):
        tree = {"t": "split", "dir": "row", "children": [
            {"t": "leaf", "id": "a"}, {"t": "leaf", "id": "b"}], "sizes": [40, 50]}
        node, err = ls.normalize_grid_tree(tree)
        assert err == "sizes must sum to 100"

    def test_nested_error_propagates(self):
        tree = {"t": "split", "dir": "row", "children": [
            {"t": "split", "dir": "nope", "children": [
                {"t": "leaf", "id": "a"}, {"t": "leaf", "id": "b"}], "sizes": [50, 50]},
            {"t": "leaf", "id": "c"}], "sizes": [50, 50]}
        node, err = ls.normalize_grid_tree(tree)
        assert err == "bad dir"

    def test_too_deep(self):
        node = {"t": "leaf", "id": "deep"}
        for _ in range(13):
            node = {"t": "split", "dir": "row", "children": [node, {"t": "leaf", "id": "s"}],
                    "sizes": [50, 50]}
        out, err = ls.normalize_grid_tree(node)
        assert out is None
        assert "too deep" in err

    def test_valid_split_roundtrip(self):
        node, err = ls.normalize_grid_tree(valid_tree())
        assert err is None
        assert sorted(ls.leaf_ids(node)) == sorted(ls.WINDOW_IDS)


class TestLeafIds:
    def test_nested(self):
        tree = {"t": "split", "dir": "row", "children": [
            {"t": "leaf", "id": "a"},
            {"t": "split", "dir": "col", "children": [
                {"t": "leaf", "id": "b"}, {"t": "leaf", "id": "c"}], "sizes": [50, 50]}], "sizes": [50, 50]}
        assert ls.leaf_ids(tree) == ["a", "b", "c"]

    def test_non_dict(self):
        assert ls.leaf_ids(None) == []
        assert ls.leaf_ids("x") == []

    def test_split_without_children(self):
        assert ls.leaf_ids({"t": "split", "dir": "row"}) == []

    def test_custom_out(self):
        out = ["seed"]
        ls.leaf_ids({"t": "leaf", "id": "a"}, out)
        assert out == ["seed", "a"]


class TestValidate:
    def test_error_strings(self):
        assert ls.validate_grid_tree({"t": "leaf", "id": "a"}) is None
        assert ls.validate_grid_tree({"t": "leaf"}) == "leaf without id"
        assert ls.validate_grid_tree(None) == "node must be object"


class TestParsePayload:
    def test_bad_json(self):
        tree, err = ls.parse_grid_payload("{nope")
        assert tree is None
        assert err.startswith("bad JSON")

    def test_non_object(self):
        tree, err = ls.parse_grid_payload("[1,2]")
        assert err == "payload must be object"

    def test_bad_versions(self):
        for v in (0, ls.GRID_VERSION + 1, "5", None):
            tree, err = ls.parse_grid_payload(json.dumps({"v": v, "tree": valid_tree()}))
            assert tree is None, v
            assert "unsupported version" in err

    def test_valid(self):
        tree, err = ls.parse_grid_payload(payload(valid_tree()))
        assert err is None
        assert tree["t"] == "split"

    def test_window_mismatch(self):
        tree = valid_tree()
        # rename a leaf -> window set mismatch (log missing, bogus extra)
        tree["children"][2]["id"] = "bogus"
        tree, err = ls.parse_grid_payload(payload(tree))
        assert tree is None
        assert err == "window set mismatch"


class TestCanonicalPayload:
    def test_valid_compact(self):
        out, err = ls.canonical_grid_payload(payload(valid_tree()))
        assert err is None
        data = json.loads(out)
        assert data["v"] == ls.GRID_VERSION
        assert ", " not in out and ": " not in out

    def test_hard_error(self):
        out, err = ls.canonical_grid_payload(payload(
            {"t": "split", "dir": "bad", "children": [
                {"t": "leaf", "id": "a"}, {"t": "leaf", "id": "b"}], "sizes": [50, 50]}))
        assert out is None
        assert err == "bad dir"

    def test_bad_json_rejected(self):
        out, err = ls.canonical_grid_payload("{broken")
        assert out is None
        assert "bad JSON" in err

    def test_missing_windows_migrate(self):
        # valid 2-leaf tree (sums to 100) missing 13 windows -> migrate re-adds
        raw_tree = {"t": "split", "dir": "row", "children": [
            {"t": "leaf", "id": "url_list"}, {"t": "leaf", "id": "folder"}], "sizes": [50, 50]}
        out, err = ls.canonical_grid_payload(payload(raw_tree))
        assert err is None, err
        data = json.loads(out)
        assert sorted(ls.leaf_ids(data["tree"])) == sorted(ls.WINDOW_IDS)

    def test_renamed_window_rejected_after_migration(self):
        # structure valid but one id unknown -> migration adds missing,
        # re-parse still mismatches -> rejected (never silently defaulted)
        tree = json.loads(json.dumps(valid_tree()))
        tree["children"][2]["id"] = "legacy_log"
        out, err = ls.canonical_grid_payload(payload(tree))
        assert out is None
        assert err == "window set mismatch"

    def test_non_dict_raw_no_migration(self):
        out, err = ls.canonical_grid_payload("[1]")
        assert out is None
        assert err == "payload must be object"


class TestMigrate:
    def test_no_missing_returns_same(self):
        tree = valid_tree()
        out = ls.migrate_grid_tree(tree)
        assert out is tree

    def test_single_missing_appended(self):
        tree = json.loads(json.dumps(valid_tree()))
        tree["children"].pop()  # lose 'log'
        out = ls.migrate_grid_tree(tree)
        assert sorted(ls.leaf_ids(out)) == sorted(ls.WINDOW_IDS)
        assert abs(sum(out["sizes"]) - 100) < 0.01
        assert out["sizes"][1] == min(40, max(ls.MIN_GRID_SIZE, 9))

    def test_multiple_missing_split_row(self):
        tree = json.loads(json.dumps(valid_tree()))
        for _ in range(3):
            tree["children"].pop()
        missing = [w for w in ls.WINDOW_IDS if w not in set(ls.leaf_ids(tree))]
        out = ls.migrate_grid_tree(tree)
        assert sorted(ls.leaf_ids(out)) == sorted(ls.WINDOW_IDS)
        extra = out["children"][1]
        assert extra["t"] == "split"
        assert extra["dir"] == "row"
        assert abs(sum(extra["sizes"]) - 100) < 0.01
        room = min(40, max(ls.MIN_GRID_SIZE, len(missing) * 9))
        assert out["sizes"] == [100 - room, room]

    def test_share_rounding(self):
        tree = {"t": "leaf", "id": "only"}  # 'only' is not a window: all 15 missing
        out = ls.migrate_grid_tree(tree)
        sizes = out["children"][1]["sizes"]
        assert abs(sum(sizes) - 100) < 0.01
        assert len(sizes) == len(ls.WINDOW_IDS)
        share = round(100 / len(ls.WINDOW_IDS), 4)
        assert sizes[0] == round(100 - share * (len(ls.WINDOW_IDS) - 1), 4)
        assert all(abs(s - share) < 1e-9 for s in sizes[1:])


class TestNodeType:
    def test_variants(self):
        assert ls.node_type({"t": "leaf"}) == "leaf"
        assert ls.node_type({"type": "split"}) == "split"
        assert ls.node_type({}) is None
        assert ls.node_type(None) is None
        assert ls.node_type("x") is None


class TestLegacyWindowMigration:
    """`captcha_records` → `recordings`: stored layouts must follow the rename."""

    def test_stored_legacy_leaf_is_migrated(self):
        tree = valid_tree()

        def rename(node):
            if node.get("t") == "leaf" and node.get("id") == "recordings":
                node["id"] = "captcha_records"
            for kid in node.get("children", []):
                rename(kid)
            return node

        payload, err = ls.canonical_grid_payload(json.dumps({"v": ls.GRID_VERSION,
                                                             "tree": rename(tree)}))
        assert err is None
        ids = ls.leaf_ids(json.loads(payload)["tree"])
        assert "recordings" in ids and "captcha_records" not in ids

    def test_rename_helpers_are_identity_without_a_legacy_id(self):
        leaf = {"t": "leaf", "id": "recordings"}
        assert ls._rename_legacy_windows(leaf) is leaf           # nothing to rename
        assert ls._rename_legacy_windows(["not", "a", "node"]) == ["not", "a", "node"]
        assert ls._rename_legacy_windows({"t": "leaf"}) == {"t": "leaf"}

    def test_malformed_json_in_the_migration_path_is_rejected(self):
        assert ls._try_migrate("{not json", "window set mismatch") == \
            (None, "window set mismatch")

    def test_unmigratable_tree_reports_the_migration_error(self):
        tree = {"t": "split", "sizes": [50, 50], "children": [
            {"t": "leaf", "id": "captcha_records"},
            {"t": "leaf", "id": "ghost_window"},
        ]}
        payload, err = ls.canonical_grid_payload(json.dumps({"v": ls.GRID_VERSION, "tree": tree}))
        assert payload is None
        assert err  # the migration's own reason wins over "window set mismatch"

    def test_migration_path_edge_branches(self):
        # a payload whose tree is not a dict cannot be migrated → the original error stands (L207)
        assert ls._try_migrate(json.dumps({"v": ls.GRID_VERSION, "tree": [1, 2]}), "window set mismatch") == \
            (None, "window set mismatch")
        # a v5 tree already at max depth cannot take another leaf → the migration's own reason is reported
        ids = [i for i in ls.WINDOW_IDS if i not in ("live_debug", "job_history", "firefox_auto")]
        tree = {"t": "split", "dir": "row", "children": [{"t": "leaf", "id": i} for i in ids[:4]], "sizes": [25] * 4}
        for i in ids[4:]:
            tree = {"t": "split", "dir": "col", "children": [tree, {"t": "leaf", "id": i}], "sizes": [50, 50]}
        assert ls.parse_grid_payload(json.dumps({"v": 5, "tree": tree}))[1] == "window set mismatch"
        assert ls.canonical_grid_payload(json.dumps({"v": 5, "tree": tree})) == (None, "tree too deep")
        # a split node with a non-list `children` is left untouched by the rename pass (L236)
        odd = {"t": "split", "children": "nope"}
        assert ls._rename_legacy_windows(odd) is odd
