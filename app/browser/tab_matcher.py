"""URL → Chrome-tab matching (from Old App backend/tab_matcher.py)"""

from urllib.parse import unquote, urlparse
from typing import Iterable

_SITE_ROOTS = ("virt-chat.com",)

def _normalize_url(url: str) -> str:
    url = (url or "").strip().lower()
    if not url:
        return ""
    for p in ("https://", "http://"):
        if url.startswith(p):
            url = url[len(p):]
    url = url.split("#", 1)[0]
    while url.endswith("/"):
        url = url[:-1]
    try:
        url = unquote(url)
    except Exception:
        pass
    return url

def _parse(query: str):
    q = _normalize_url(query)
    if not q:
        return "", "", False
    if "/" in q or "." in q:
        path = ""
        host = q
        if "/" in q:
            host, path = q.split("/", 1)
            path = "/" + path
        if ":" in host:
            host = host.split(":", 1)[0]
        return host, path, True
    return "", "", False

def _site_key(host: str) -> str:
    host = (host or "").lower()
    for root in _SITE_ROOTS:
        if host == root or host.endswith("." + root):
            return root
    return host

def _parsed_target(tab_url: str):
    try:
        parsed = urlparse(tab_url)
        return (parsed.hostname or "").lower(), unquote(parsed.path or "")
    except Exception:
        return "", ""

def _score_url_like(query_parts, q_norm, tab_parts):
    q_host, q_path = query_parts
    tab_host, tab_path = tab_parts
    if _site_key(tab_host) != _site_key(q_host):
        if q_norm in f"{tab_host}{tab_path}":
            return 60, "keyword"
        return None
    if q_path and tab_path.startswith(q_path):
        return 300, "url_path"
    if not q_path:
        return 200, "host"
    return 60, "keyword"

def _score_keyword(q_norm, url_norm, tab_title):
    if q_norm and (q_norm in url_norm or q_norm in (tab_title or "").lower()):
        return 60, "keyword"
    return 0, ""

def score_tab(query: str, tab_url: str, tab_title: str = ""):
    query = (query or "").strip()
    if not query or not tab_url:
        return 0, ""
    q_norm = _normalize_url(query)
    url_norm = _normalize_url(tab_url)
    if q_norm and url_norm == q_norm:
        return 500, "url_exact"
    q_host, q_path, is_url_like = _parse(query)
    if is_url_like and q_host:
        verdict = _score_url_like((q_host, q_path), q_norm, _parsed_target(tab_url))
        if verdict is not None:
            return verdict
    return _score_keyword(q_norm, url_norm, tab_title)

def _tab_url(tab: dict):
    return tab.get("url") or tab.get("ws_url") or ""

def best_matches(query: str, tabs: Iterable[dict], top_n: int = 5):
    scored = []
    for tab in tabs or []:
        score, _kind = score_tab(query, _tab_url(tab), tab.get("title") or "")
        if score > 0:
            scored.append((score, tab))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, tab in scored[: max(1, int(top_n))]:
        _sc, kind = score_tab(query, _tab_url(tab), tab.get("title") or "")
        out.append({"id": tab.get("id", ""), "title": tab.get("title", ""),
                    "url": tab.get("url", ""), "ws_url": tab.get("ws_url", ""),
                    "score": score, "kind": kind})
    return out
