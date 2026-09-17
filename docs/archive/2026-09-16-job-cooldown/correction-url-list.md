# Correction 2026-09-16 — Cooldown Controls on URL List Win

User correction to the JOB CYCLE & COOLDOWN spec: the cooldown controls and
per-tab countdown must live on the **URL List win** (not only Page Pool /
Settings):

- 02: minimum-pause control → URL List win bar.
- 03: countdown display → each URL row; reset/edit → each URL row.
- 04: captcha-penalty control → URL List win bar.
- Tabs stay independent sessions; image queue stays single/shared (unchanged).

## Implementation (JS + HTML only, no Python changes)

- `app/ui/web/index.html` — URL win gains a cooldown bar (pause minutes,
  penalty minutes, on/off, Save → existing `get/set_cooldown_config` slots)
  and a `Cooldown` table column.
- `app/ui/web/js/panels/url-list.js`:
  - `matchPoolPage(url)` matches each URL row to its pool tab with the same
    exact → prefix → host logic as the Conn column (`findBestTabForUrl`).
  - `_fillCoolCell` renders per-row state (🔵 busy / `MM:SS / total` / pending
    `+MM:SS` / ✅ ready / 🛡 captcha count) on each fresh pool snapshot;
    1s tick decrements locally between snapshots.
  - Row ♻️/✎ buttons delegate to `PagePoolPanel.resetCooldown/editCooldown`
    (same slots, same logs); disabled with hint while the tab is not pooled.

No backend/selector/state-machine change; `pytest` + quality gate unaffected.
