# 02 — Old project removal and retention map

## What exists

`Process Images in Areana/Old App/` is ChatBot Automator: Python 3.11+, PySide6/Qt WebEngine HTML+JS UI, qasync, custom CDP/websocket transport, aiohttp, and aiosqlite. Bootstrap creates user memory/database, criteria, run engine and history services. This is not an existing folder-to-Arena-image pipeline. The retained core includes **the existing dark UI workspace, layout/drag-drop mechanics, global undo/redo, preset libraries and variable/template editing**, plus audited persistence and browser helpers. The chat execution engine is not retained as-is.

The old tree is approximately 106 MB on disk, including roughly 45 MB of unrelated chat assets and 48 MB of saved Arena development-page evidence. These are local size observations, not promised distribution savings. No deletion occurs in this phase.

## Explicit disposition map

All paths below are relative to `Process Images in Areana/Old App/` unless noted. “Remove” means after approval and extraction—not now. The old directory can leave the active checkout only after retained systems and their regression tests have been extracted successfully; Git history retains tracked legacy source.

| Existing path/family | Disposition | New replacement / reason |
|---|---|---|
| `app/`, `main.py` | Adapt shell/lifecycle; replace domain wiring | Retain Qt/WebEngine desktop workspace, remove DB/history/criteria bootstrap dependencies |
| `ui/index.html`, `ui/css/`, `ui/js/` | Retain/adapt existing dark shell and shared components | Replace chat panel content with image panels; keep WebEngine, visual style, workspace interactions |
| `ui/js/sash-*`, `window-presets-*`, `stack-*`, `presets-ui-*` | KEEP and adapt with existing tests | Drag/drop, split/resize, named window/layout presets, stack/block libraries and import/export remain |
| `ui/js/db-*`, chat-only `history-*` (exclude global editing history), `labels-*`, `user-table-*`, `collector-panel.js`, `criteria-editor.js` | Remove | No DB browser, people/labels, harvested chats, provider bot; keep reusable prompt/template/variable editor |
| `bridge/`, `backend/bridge.py` | Selective retention/adaptation | Keep layout/preset/stack/undo bridge contracts; remove chat/DB slots and add typed image commands |
| `actions/` registry/base/config and block library | Retain authoring/serialization; replace chat actions | Image-safe blocks feed a validated mandatory state machine; no arbitrary skip of verification or duplicate Send |
| `backend/db_manager.py`, `history_*`, `user_memory.py`, `label_store.py`, `criteria_engine.py`, `person_filter.py` | Remove | No SQL, people, labels, history queries or chat criteria |
| `backend/chat_*`, `collector.py`, `scroll_parser*`, `message_injector*`, `media_*` | Remove/replace | Image-specific adapter, exact URL mapping and output writer; chat selectors/media harvesting are wrong domain |
| `backend/cdp_client*.py`, `services/cdp_service.py`, CDP bridge/UI | KEEP/adapt existing system | Attach to already-open debug Chrome; discover targets, verify live per-row connections and revalidate after reconnect; no Playwright replacement |
| `backend/tab_matcher.py` | Adapt matching policy, retain discovery UI | Exact approved URLs only for execution; old normalized/host/path/keyword scoring cannot silently select a job destination |
| `backend/visual_click.py`, `dom_highlight.py`, `dom_probe.py`, `probe_requests.py`, `actions/cancellation.py` | KEEP/adapt implementation and paired tests | Reuse existing FIND/red and CLICK/orange runner, same-target logic, user-configurable timing and cancellation; adjust dependencies and researched image selectors, not a fresh replacement |
| `backend/config_manager*`, `preset_store.py`, `logger.py` | Reference then replace | Small typed settings/preset repository and privacy-safe diagnostics |
| `services/bot_*` except retained template/variable/preset modules, `collector_*`, `db_*`, `people_service.py`, `world_events.py` | Remove | No bots, collector or DB lifecycle; undo is retained separately |
| `services/layout_*`, `window_preset_*`, `undo_*` | KEEP/adapt | Preserve layout validation, named presets and global undo; remove only people/DB-world undo delegates |
| `services/run/`, `run_service/` | Replace chat execution internals | Sequential image coordinator; retain compatible stack configuration/normalization contracts |
| `services/preset_io.py`, `service_log.py`; `core/` | Keep preset IO; audit remaining helpers | Retain useful validated import/export, result/error/event patterns if genuinely independent; do not copy container/event framework wholesale |
| `stores/history_*`, `user_*`, `label*`, `media_*`, chat/DB portions of `migration.py`, `world_lock.py`, `bookmark_store.py` | Remove | JSON job state and presets, no chat database/media cache; retain/adapt preset migration separately |
| `stores/atomic.py`, `jsonio.py`, `json_store.py`, `outcome.py` | Audit; adapt or rewrite minimally | Atomic-write/result ideas retained. Existing corrupt-JSON-to-empty behavior is **unsafe for job history** and must not carry over |
| `stores/undo_store.py`, `block_store.py`, `window_preset_store.py`, `preset_store.py`, settings/session modules | KEEP/adapt | JSON global undo, layout/session, all preset families and variables; explicit validated compatibility migration, never destructive auto-import |
| `config/` old settings, blocks, presets, session, undo and window presets | Preserve for compatibility audit; do not delete user configurations | Migrate supported data with backup/preview; separate private runtime data from shipped defaults. Remove unrelated bookmarks only after review |
| `start-chatflow-chrome.bat` | Remove | Hard-coded old target/profile; new OS-specific launch docs only after OS approval |
| `requirements.txt` | Replace | Drop aiosqlite; keep PySide6 WebEngine/WebChannel and qasync where used by retained shell; keep aiohttp/websockets for existing CDP; add image validation |
| `tests/` | KEEP retained-system regression suites; replace chat/DB-only suites | Preserve testing standards, not thousands of chat/DB/window assumptions; paired tests required for any ported helper |
| `tools/metrics/`, `tools/build_stubs.py`, `tools/ci/quality-gate.yml` | Simplify/retarget after audit | Retain real size/complexity/coverage/behavior checks; discard old store-family inventories, debt baselines, permissive Qt stubs; retain JS DOM harness coverage for real workspace behavior. Existing CI YAML under tools is not proof of active root CI |
| `.pre-commit-config.yaml`, `pytest.ini`, `setup.cfg`, `requirements-dev.txt` | Replace configuration, retain standards | Root-scoped gates/tests for new paths; no DB markers, legacy mutation target or blanket warning suppression |
| `logs/`, `reports/`, `coverage.json` | Remove tracked generated/history artifacts | Fresh measured reports ignored or emitted by CI; never use legacy numbers as new coverage |
| `README.md`, `docs/` old manuals, current docs, archive and window/stack designs | Replace after principles extracted | New documentation map below; Git history is sufficient for unrelated old design history |
| `Вирт чат*.html`, `Вирт чат*_files/` | Remove after approval | Unrelated private chat evidence; no need in new fixtures or distribution |
| `Restore/From Webpage Code saved/` | Preserve temporarily, then remove from active app tree after research signoff | Agent Mode capture is not image workflow evidence; retain only relevant sanitized negative fixtures if needed |
| Root `Directly Chat with Frontier Image Generation AI Models.html` and `_files/` | Preserve until research complete; later sanitize/archive outside runtime | Only substantive image-page capture; never delete before missing states are supplied and fixtures approved |
| Root `.gitattributes`, repository root and `.git/` | Keep | Repository identity/history unchanged; update ignore rules later to exclude state/profile/output/secrets |

Any unlisted old module is **not implicitly approved for reuse**. Default: retire with old app. An extraction must name new owner, dependencies and tests before copying. Do not leave a renamed old backend connected to the new UI.

## Documentation replacement map

| Old documentation | New current document planned | Retained substance / discarded substance |
|---|---|---|
| Old `README.md` | Root `README.md` | Tested install, run, manual browser login and safety; discard Virt-Chat tours/flags |
| `docs/README.md` + archive index | `docs/README.md` | Short current-document index; no unrelated inherited 100+ topic archive; preserve relevant retained-feature design evidence |
| `current/SYSTEM_OF_RECORD.md` | `docs/PRODUCT.md`, `docs/ARCHITECTURE.md` | New image invariants, state ownership and workflow; no people/DB world; global editable-workspace undo remains |
| `current/AGENT_RULES.md` | Root `AGENTS.md` plus `docs/TESTING.md` | Essential adapted rules in proposal 05; no old frozen surfaces/debt exceptions |
| `current/DOM_SELECTORS.md` | `docs/SITE-ADAPTER.md` + sanitized `tests/fixtures/arena/` evidence manifest | Evidence-backed new selectors and maintenance; no old chat selectors |
| Window/stack preset designs | `docs/CONFIGURATION.md`, `docs/WORKSPACE.md` | Preserve layout/tree, stack/block and template/variable contracts, named libraries and validated import/export |
| DB/collector/bot-runtime archives | No counterpart | Unrelated product features removed, retained only in Git history |
| Undo/workspace/preset/template design records | `docs/WORKSPACE.md`, `docs/CONFIGURATION.md` | Retain relevant contracts/evidence until migrated; do not delete as unrelated |
| Quality reports/test instructions | `docs/TESTING.md` | Actual new commands, acceptance IDs, test tiers and manual checklist |
| Old troubleshooting scattered across archive | `docs/OPERATIONS.md` | Authentication, CAPTCHA manual action, review/interruption recovery, output failures, diagnostics and known limits |

These current docs are **planned**, not created as misleading implemented documentation in this phase. `docs/rebuild/` contains the nine review documents now. Keep current guides concise, single-owned and linked; historical proposals are not operational truth.

## Safe cleanup order

1. Owner reviews this map; confirm OS coverage and compatibility mappings; existing debug-Chrome attachment and old visual-click reuse are owner requirements; retaining dark windows, undo and preset/variable systems is now an owner requirement.
2. Identify/sanitize required evidence, preserve undo/layout/preset/variable source and paired tests, and retain all essential engineering rules; review dependencies of any selected helper and paired tests.
3. Build isolated new package after approval; no runtime import from `Old App`.
4. Once new skeleton and gates run, remove old feature families in a separately reviewable deletion change. Do not execute old database deletion services against user data.
5. Search for remaining Virt-Chat domains, chatbot names, SQL dependencies, obsolete paths/imports and dead documentation links. Inspect exceptions such as this historical proposal rather than demanding zero historical mentions.
6. Remove obsolete evidence/assets only after evidence review; remove old app folder once no selected work depends on it. Never remove repository root or `.git`.
7. Validate fresh installation, dependency list, tests and packaging; ensure no browser profile, user state, raw capture, generated output or private media ships.
