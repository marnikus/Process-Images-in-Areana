# CAPTCHA watcher isolation — audit and implementation plan

Date: 2026-09-19

## Scope

This change separates CAPTCHA handling from image processing. The Watcher is
now the only runtime owner of CAPTCHA detection, provider calls, token
injection, and per-page status. The image job pipeline remains responsible
for attachment, prompt, submission, output verification, and persistence; it
does not inspect or solve CAPTCHA.

## Audit findings

| Area | Finding | Change |
|---|---|---|
| Runtime ownership | `single_job_runner.py` called `handle_captcha` at the security block, submit, download, and generation-wait boundaries. Recovery could also resubmit after a CAPTCHA. | Remove those runtime call paths. The security block remains a restorable, informational block and never solves. |
| Provider | `app/services/captcha/api_client.py` speaks the 2Captcha HTTP API directly and the old service owns the full-chain flow. | Add a Watcher-owned adapter around the official `2captcha-python` SDK (`twocaptcha.TwoCaptcha`). Keep the old package only as a compatibility surface for existing persisted data/tests; no production image path imports it. |
| Watcher | Watcher detects a boolean CAPTCHA but only pauses; it has no provider integration and is not guarded by an explicit enabled gate in `check_once`. | Detect a structured signal, invoke the SDK only from an enabled Watcher, inject through the Watcher CDP boundary, and fail open to a visible manual state. Disabled Watcher performs no CAPTCHA work. |
| Action Blocks | The web renderer queried legacy IDs (`ab-block-list`, `ab-stack-presets`, etc.), while the HTML uses `actionBlocksStack`, `stackPresetChips`, etc. This made the whole block surface appear empty. | Align renderer IDs and make backend default loading repair empty/corrupt saved stacks. |
| URL/folder actions | URL and folder slots exist, but UI state was initialized before/without reliable bridge refresh in several surfaces. The folder browser also silently did nothing when a bridge method was unavailable. | Rebind state after bridge readiness, return explicit UI errors, refresh rows after URL add, and preserve the Qt existing-directory dialog path. |
| Prompt presets | The JS dynamically created controls with IDs different from the current Arena Presets markup; Save/Load/Delete controls were therefore absent or bound to duplicate IDs. | Use the existing Arena Presets controls, render one row per preset with Load and Remove actions, and load lists after the bridge handshake. |

## Runtime contract

1. `WatcherConfig.enabled == False` is a hard gate. `check_once` returns an
   idle/watching status without a CAPTCHA probe or provider call.
2. Only `WatcherHandlers` may call `WatcherCaptchaService.solve`.
3. A provider failure, missing SDK, missing sitekey, timeout, or injection
   error produces a logged manual-required state; it never raises into an
   image job.
4. Provider credentials remain in `config/2captcha.json`; only masked status
   crosses the WebChannel. The obsolete multi-provider `captcha_solvers.json`
   format is not read.
5. The official SDK is synchronous, so its call runs in `asyncio.to_thread`.
   The watcher event loop remains responsive and the task is deduplicated per
   tab.
6. The watcher may solve only a visible, user-authorized page signal. It does
   not navigate, submit an image job, or retry a generation request.

## UI repair contract

* Action Blocks always have a backend reset path and a visible default stack.
* The URL Add button accepts a new valid HTTP(S) URL, persists it, and the
  state signal refreshes the table immediately.
* Browse calls `pick_folder(start_dir)` and reports cancellation, missing
  bridge, and provider errors distinctly.
* Prompt presets expose Save, Load, and Remove in the Arena Presets window.

## Verification plan

* Unit tests: Watcher disabled gate, SDK adapter success/failure/stop,
  default-stack repair, URL add, folder dialog, and prompt preset CRUD.
* JS tests: execute the real block/preset modules in the existing harness and
  assert the actual DOM IDs receive controls.
* Static checks: `py_compile`, `python tools/verify_quality.py --changed
  --allow-legacy`, and the repository's JS lane.
* Manual: start with Watcher off and confirm no CAPTCHA probe/provider log;
  enable Watcher for two connected pages and confirm independent detection,
  status, and manual fallback; exercise URL Add, Browse, block Reset, and all
  prompt preset actions.
