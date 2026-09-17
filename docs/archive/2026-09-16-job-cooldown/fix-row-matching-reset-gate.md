# Fix 2026-09-16 — Cooldown Visible on URL Rows + Fresh-Chat Reset Gate

User report (with log): after first job, URL rows still showed "ready".
Log proved the backend worked (`Page 154FBF… cooling 05:00`) — the rows
just never displayed it.

## Root cause 1: first-match-wins row→tab matching

With 2 similar URLs + 2 pooled tabs, both rows matched the same steady tab
and the cooling tab was shown nowhere on the URL win.

Fix (`url-list.js`, no Python change): greedy 1:1 assignment —
`scorePoolPage` (exact 500 / prefix 300 / host 200, same vocabulary as the
Conn column), `assignPoolPages` claims each page once, best score first.
Unclaimed rows fall back to shared best-match (1 tab still shows on N rows
in single mode). Verified in node: bare-URL ties split 1:1 (cooling always
visible), exact URLs attribute correctly.

## Root cause 2 (from the same log): reset gate too strict for fresh chat

Every job burned 30s + error noise: `ready=False reasons=['file not
visible', 'output not found']` — but a fresh new chat correctly HAS no
output yet.

Fix (`new_chat._fresh_chat_ready`, tested): file/output absence is
tolerated; prompt/send absence and Security dialog still block; empty
composer still required. Reset now succeeds in ~1s on a clean new chat.

`pytest 136 passed`, `verify_quality --changed --allow-legacy` 0 fails.
