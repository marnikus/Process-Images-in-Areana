# 02 — Refactor & Fix Plan

Order is deliberate: contracts first, then the captcha isolation, then the
six bugs. Each phase is independently shippable and independently testable.

---

## Phase 0 — Freeze the contracts (blocks everything else)

| # | Step | Deliverable | Done when |
|---|---|---|---|
| 0.1 | Declare the JS-facing slot list | `app/ui/bridge_slots.py` → `REQUIRED_SLOTS` | list covers every slot JS calls |
| 0.2 | Add startup audit | `audit_slots()` + `log_slot_audit()` | boot log prints exposed / fallback / missing |
| 0.3 | Add `invoke(name, args_json)` + `slot_audit()` **in the Bridge class body** | `BridgeDispatchMixin` | a mix-in slot is reachable even if the meta-object misses it |
| 0.4 | Single JS call path | `js/core/bridge-call.js` | no panel calls `App.bridge.x` directly |
| 0.5 | CI check: every `getElementById` id exists in `index.html` | `tools/check_dom_ids.py` (gate) | build fails on a dead id |

## Phase 1 — Captcha watcher isolation (REFACTOR 02)

| # | Step | Deliverable | Done when |
|---|---|---|---|
| 1.1 | One gate owns the decision | `app/services/captcha/watcher_gate.py` | `solve_if_watcher_on()` is the only entry |
| 1.2 | Swap the transport to the official SDK | `app/services/captcha/sdk_client.py` | `api_client.py` + solver transport deleted |
| 1.3 | Per-page passive step | `app/services/watcher_pkg/captcha_step.py` | detect → gate → inject → verify, per `tab_id` |
| 1.4 | Cut the chain call sites | see `docs/03` removal map | `grep -rn captcha app/services/single_job_runner.py` is empty |
| 1.5 | One captcha UI | `js/panels/watcher/captcha-watch.js` | `#winCaptcha` controls retired |
| 1.6 | Off means off | gate returns `skipped(watcher_off)` | no network call when the Watcher is off |

## Phase 2 — Restore the broken windows (BUGS 03)

| # | Bug | Step | Deliverable |
|---|---|---|---|
| 2.1 | URL window cannot add pages | bind through `BridgeCall`, validate client-side, show the reason | `js/panels/url-list/add-url.js` |
| 2.2 | Action blocks vanished | self-healing load + always-available restore | `app/ui/panels/blocks_defaults.py`, `js/panels/action-blocks/block-defaults.js` |
| 2.3 | Defaults must always be restorable | `REQUIRED_BLOCK_IDS` + `merge_missing_defaults()` | same pair |
| 2.4 | Browse folder opens nothing | real parent window + native→Qt fallback chain | `app/ui/panels/folder_browse.py`, `js/panels/folder-picker-browse.js` |
| 2.5 | Buttons/dialogs do nothing | fault-isolated boot + visible errors | `js/core/panel-boot.js`, `js/core/bridge-call.js` |
| 2.6 | Prompt presets gone | bind the static markup, stop injecting duplicates | `js/panels/arena-presets/prompt-presets.js` |

## Phase 3 — Wire-up (edits to existing files)

```
index.html
  + <script src="js/core/bridge-call.js"></script>        (after bridge-ready.js)
  + <script src="js/core/panel-boot.js"></script>
  + <script src="js/panels/url-list/add-url.js"></script>
  + <script src="js/panels/folder-picker-browse.js"></script>
  + <script src="js/panels/action-blocks/block-defaults.js"></script>
  + <script src="js/panels/arena-presets/prompt-presets.js"></script>
  + <script src="js/panels/watcher/captcha-watch.js"></script>

arena-app.js
  - _PANEL_INITS.forEach(_initIfExists);
  + PanelBoot.bootAll(_PANEL_INITS);
  + _PANEL_INITS adds: 'UrlAdd','FolderBrowse','BlockDefaults','PromptPresets','CaptchaWatch'

bridge.py
  + from app.ui import bridge_slots
  + from app.ui.panels.blocks_defaults import BlocksDefaultsMixin
  + from app.ui.panels.folder_browse import FolderBrowseMixin
  + class Bridge(QObject, …, BlocksDefaultsMixin, FolderBrowseMixin, bridge_slots.BridgeDispatchMixin)
  + @Slot(str, str, result=str) def invoke(self, name, args_json="[]"): …
  + @Slot(result=str)          def slot_audit(self): …
  + @Slot(bool, result=str)    def restore_default_blocks(self, merge_missing=False): …
  + @Slot(str, result=str)     def pick_folder(self, start_dir=""): …
  + bridge_slots.log_slot_audit(self) at the end of __init__

blocks_stack.py
  - def get_action_blocks(bridge): …            (empty-list bug)
  + from app.ui.panels.blocks_defaults import load_blocks as get_action_blocks

bridge_context.py
  + gate = CaptchaGate(watcher_enabled=…, settings_getter=…, logger=bridge._log)
  + captcha_watcher_gate.install_gate(gate)
```

## Phase 4 — Verification

| Check | Command / action | Pass |
|---|---|---|
| DOM ids | `python tools/check_dom_ids.py` | 0 missing |
| Slot contract | start app, read the boot banner | `✅ Bridge contract OK` |
| Panel boot | devtools `PanelBoot.report()` | no `failed` |
| URL add | type URL → Add | row appears, log line, error text on a bad URL |
| Blocks | delete all → **Restore defaults** | 16 blocks return |
| Browse | click Browse | dialog opens in front of the window |
| Prompt presets | Save → Restore → Remove | list updates each time |
| Watcher off | captcha page open | no network call, log says `watcher_off` |
| Watcher on | captcha page open | solved per page, `✅ Captcha cleared` |
| Unit | `pytest tests/ -v` | green |

## Removal list (dead after this refactor)

```
app/services/captcha/api_client.py        → sdk_client.py
app/services/captcha/solver.py            → sdk_client.py (transport half)
app/services/captcha/recovery.py          → watcher_gate + captcha_step
app/services/captcha_recording/*          → optional, behind a debug flag
CHECK_SECURITY block execution            → pause only, never solve
```
