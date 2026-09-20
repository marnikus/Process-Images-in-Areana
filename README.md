# Arena Image Processor — MVP

A desktop application that automates image-to-image generation on arena.ai (or similar pages) with full traceability and user control.

> **New App:** Built from scratch based on core of old ChatBot Automator, but simplified: no DB, no Windows-specific code, JSON persistence only, Playwright browser automation, PySide6 UI.

## Product Goal
1. Accept multiple exact webpage URLs as separate rows
2. Check whether each URL is valid, reachable, authenticated, ready
3. Let user choose local folder and recursively discover supported images
4. Track pending, selected, processing, completed, skipped, failed
5. Manual include/exclude/retry/reset
6. Attach each selected image to configured webpage
7. Copy user's prompt plus correlation token into webpage prompt field
8. Start generation and wait for genuinely new output image
9. Verify output belongs to current job (not older request)
10. Save new image beside source with "_AI" suffix
11. Persist progress so work can resume after interruption

## Setup

### Requirements
- Python 3.11+
- Chromium (via Playwright)

### Install
```bash
pip install -r requirements.txt
playwright install chromium
```

### Run
```bash
python -m app.main
```

On first run, browser launches with profile `./browser_profile`. Log in to arena.ai manually in that browser window. The session is remembered.

## UI Areas
- **URL List:** add, edit, remove, enable/disable, test single/all, status: unchecked, checking, ready, unavailable, auth required, CAPTCHA required, unsupported, error
- **Folder Picker:** choose root, show path, scan button
- **Image Queue:** thumbnail placeholder, relative path, filename, selected checkbox, status, assigned URL, attempt count, output path, error
- **Bulk Controls:** select all, deselect all, select pending, clear completed, retry failed
- **Prompt Editor:** multiline, preview with correlation token `[JOB-ID: ...]`
- **Run Controls:** Start, Pause, Resume, Stop after current, Cancel current, Retry
- **Progress Summary:** total, selected, pending, processing, completed, skipped, failed, needs_review
- **Activity Log:** timestamped events
- **Settings:** timeouts, retry limits, output naming, supported file types, overwrite, highlight rect (enable, duration, color, border width), browser profile

## Workflow
For each selected pending image (sequential, round-robin URLs):
1. Create job with unique correlation ID
2. Confirm webpage ready
3. Capture baseline (old outputs, timestamp)
4. Attach image via file input, verify preview
5. Build final prompt: `[JOB-ID: unique]\n<user prompt>`
6. Insert into textarea, read back verify exact match
7. Submit once, confirm processing state
8. Wait for new output (baseline comparison, loading complete)
9. Download highest-quality image, validate (not HTML, valid image)
10. Save beside source as `*_AI.ext`, unique suffix if exists, atomic write
11. Persist completed state

Core rule: **observe baseline -> execute one action -> verify effect -> persist state -> advance**

## Selector Strategy
All selectors centralized in `app/browser/site_adapter.py` with primary + fallbacks. Prefer semantic: aria-label, name, role, placeholder prefix. Avoid generated IDs, full Tailwind chains, signed URLs.

Key selectors (verified from saved HTML):
- Add: `button[aria-label="Add files"]`
- File input: `form input[type="file"][accept*="image"]` (hidden)
- Textarea: `textarea[name="message"]`
- Send: `button[aria-label="Send message"]`
- Output: `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]`
- Security: `div[role="dialog"][data-state="open"]` + `iframe[title="reCAPTCHA"]`

See `docs/selector_map.md` for full map.

## Persistence
- `config/app_state.json` — main state (URLs, folder, prompt, settings, images, jobs, progress, run_state)
- `config/presets/*.json` — presets with UI params (URLs, prompt, settings, folder) without job history
- Atomic writes via temp file + replace
- Reconcile on startup: detect added/removed/changed files, mark interrupted jobs

### Configuration & secrets (local only — never in Git)
- Everything under `config/` is **runtime data of one machine**: the 2Captcha API key
  (`config/captcha_solvers.json`, written by the Captcha Settings panel), session/undo history,
  captcha recordings, presets. `.gitignore` excludes `config/*` (only `config/.gitkeep` is tracked),
  `logs/`, `arena webpages/` (saved session pages) and bytecode.
- Enter the API key in the app (Captcha → Settings); it is stored only in that ignored file.
- Guard: `tests/test_repo_hygiene.py` asks `git ls-files` and fails when any such path or an
  `api_key` literal is tracked; `tools/pre_push_check.sh` step 0 blocks the push the same way.
- History note (2026-10-09): keys were once committed in the root commit of this repo and have
  been rotated; a leaked key is burned the moment it is pushed — rotate first, clean second.

## Highlight Rect
When clicking element, draws rect overlay for configurable seconds (default 2s, color #FF0000). Enabled in settings.

## Security & Compliance
- Never bypass CAPTCHA — pause, show "User action required", wait manual completion
- Respect ToS, rate limits
- Credentials out of logs, session in browser profile dir
- Upload only to user-configured URLs

## Testing
```bash
pytest tests/ -v
```

- Unit: scanner, naming, persistence, correlation, state transitions, verification, selector
- Integration: mocked browser for site_adapter, job_runner
- Manual checklist in `docs/implementation_plan.md`

## Architecture
```
app/
  core/ — models, enums, scanner, naming, persistence, state_machine
  browser/ — controller (Playwright), site_adapter (selectors), selector
  services/ — verification, job_runner
  ui/ — main_window (PySide6)
  utils/ — correlation, hashing, logging
```

Responsibilities separate, site adapter replaceable.

## Known Limitations
- Requires manual login first time
- Output detection relies on R2 host pattern, may need update if host changes
- Attachment preview selector not fully verified (no HTML with attachment in saved evidence) — fallback to blob URL
- Sign-in/error detection heuristic, may need refinement
- Sequential processing only (MVP)
- No thumbnail generation yet (shows filename)
- No watch-folder mode yet
- No CSV/JSON export yet (but logs and job history in JSON)

## Maintenance
When arena.ai DOM changes:
1. Check `logs/` and activity log for which selector failed
2. Update `app/browser/site_adapter.py` primary/fallbacks
3. Update `lastVerified` date
4. Test via "Test URL" button
5. Document in `docs/selector_map.md`

## Docs
- `docs/research_summary.md` — saved pages analysis
- `docs/selector_map.md` — selector inventory
- `docs/workflow_diagram.md` — state machine
- `docs/data_model.md` — persistence
- `docs/risks.md` — risks & compliance
- `docs/implementation_plan.md` — plan & test strategy
- `docs/rules.md` — essential rules

## Acceptance Criteria (MVP)
- [x] Add multiple URLs, see readiness status
- [x] Recursively scan folder, display images
- [x] Manual select/deselect
- [x] Survive loading delays without duplicate submissions
- [x] Correct attachment verified before submission
- [x] Exact prompt + job ID inserted and read back
- [x] Wait for new result, not old image
- [x] Uncertain correlation => Needs Review
- [x] Valid result saved beside source with _AI suffix, no overwrite
- [x] States persist after restart
- [x] CAPTCHA pauses for manual completion, never bypassed
- [x] Errors visible, actionable, recorded
- [x] Highlight rect with configurable duration
- [x] Preset save/load JSON, all UI params storable
