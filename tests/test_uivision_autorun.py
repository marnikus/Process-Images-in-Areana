"""Ui.Vision autorun helpers — the 2026-09-23 "Can't find macro" fix.

RED: `app.browser.uivision_autorun` did not exist; the external runner sent raw
spaces in the file:/// URL and query, an unknown `tab=` key the extension
ignores, and matched window titles exactly — tabs matched while windows
reported 0. Every test here fails if its helper is deleted (RULE 8, RULE 16.3).
"""

import json
import os
from urllib.parse import parse_qsl, urlsplit

import pytest

from app.browser import uivision_autorun as ua

pytestmark = pytest.mark.unit


def test_page_path_with_spaces_is_percent_encoded_not_raw():
    url = ua.page_file_url("D:\\Google Drive\\Py\\Process Images in Areana\\ui.vision.html")
    assert url.startswith("file:///")
    assert " " not in url and "\\" not in url
    assert "Google%20Drive" in url and "Process%20Images%20in%20Areana" in url


def test_page_path_drive_and_posix_shapes():
    assert ua.page_file_url("C:\\Users\\marni\\Desktop\\uivision\\ui.vision.html") == (
        "file:///C:/Users/marni/Desktop/uivision/ui.vision.html"
    )
    assert ua.page_file_url("/home/u/uivision/ui.vision.html") == (
        "file:///home/u/uivision/ui.vision.html"
    )


def test_query_values_use_percent20_never_plus_or_raw_space():
    query = ua.autorun_query("Python_XClick_Demo", "D:\\Google Drive\\logs\\run 1.txt")
    url = ua.build_autorun_url("C:\\uivision\\ui.vision.html", query)
    assert " " not in url
    assert "savelog=D%3A%5CGoogle%20Drive%5Clogs%5Crun%201.txt" in url
    assert "+" not in urlsplit(url).query, "quote_plus + breaks Ui.Vision's own parser"
    back = dict(parse_qsl(urlsplit(url).query))
    assert back["savelog"] == "D:\\Google Drive\\logs\\run 1.txt"
    assert back["macro"] == "Python_XClick_Demo" and back["direct"] == "1"


def test_empty_savelog_is_omitted_not_sent_blank():
    assert "savelog" not in ua.autorun_query("Demo")
    assert ua.autorun_query("Demo")["storage"] == "xfile"


def test_unknown_keys_flags_tab_param_but_keeps_documented_ones():
    query = {"macro": "Demo", "storage": "xfile", "direct": "1",
             "tab": "title=*Arena*", "cmd_var1": "hello world"}
    assert ua.unknown_query_keys(query) == ["tab"]


def test_macro_file_maps_simple_folder_and_json_suffixed_names():
    home = os.path.join("C:\\Users\\marni", "Desktop", "uivision")
    assert ua.macro_file(home, "Python_XClick_Demo") == os.path.join(
        home, "macros", "Python_XClick_Demo.json")
    assert ua.macro_file(home, "a/sap-2") == os.path.join(home, "macros", "a", "sap-2.json")
    assert ua.macro_file(home, "Demo.json") == os.path.join(home, "macros", "Demo.json")


def test_macro_status_distinguishes_missing_invalid_and_ok(tmp_path):
    home = str(tmp_path)
    assert ua.macro_status(home, "Python_XClick_Demo") == "missing", "RULE 4: empty ≠ broken"
    macros = tmp_path / "macros"
    macros.mkdir()
    (macros / "Bad.json").write_text("{not json", encoding="utf-8")
    assert ua.macro_status(home, "Bad") == "invalid"
    (macros / "Shape.json").write_text(json.dumps({"Name": "Shape"}), encoding="utf-8")
    assert ua.macro_status(home, "Shape") == "invalid", "no Commands list, not runnable"
    good = {"Name": "Python_XClick_Demo", "Commands": [
        {"Command": "selectWindow", "Target": "title=*Arena*", "Value": ""}]}
    (macros / "Python_XClick_Demo.json").write_text(json.dumps(good), encoding="utf-8")
    assert ua.macro_status(home, "Python_XClick_Demo") == "ok"


def test_window_title_matches_substring_case_and_entities():
    title = "Arena | Benchmark & Compare the Best AI Models — Mozilla Firefox"
    assert ua.window_title_matches("Arena", title)
    assert ua.window_title_matches("arena", title), "case-insensitive"
    assert ua.window_title_matches("Compare", "Arena | Benchmark &amp; Compare")
    assert ua.window_title_matches("Arena", "Arena | Benchmark &amp; Compare")
    assert not ua.window_title_matches("Arena", "YouTube — Mozilla Firefox")
    assert not ua.window_title_matches("", title), "empty pattern never matches"
    assert not ua.window_title_matches("Arena", "")


def test_select_window_command_reuses_tab_by_title_wildcard():
    assert ua.select_window_command("Arena") == {
        "Command": "selectWindow", "Target": "title=*Arena*", "Value": ""}
