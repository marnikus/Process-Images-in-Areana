# Arena Image Processor — MVP

A desktop application that automates image-to-image generation on arena.ai (or similar pages) with full traceability and user control.

> **New App:** Built from scratch based on core of old ChatBot Automator, but simplified: no DB, no Windows-specific code, JSON persistence only, Playwright browser automation, PySide6 UI.

## Product Goal
0. Discover and link matching webpages automatically — no manual URL connection
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

### Auto-connect (no manual URL connection)
Start Chrome with a debug port (for arena: `9223`), open your arena.ai pages, then start the app:

```bash
./start-arena-chrome.sh 9223 ~/.arena-9223 https://arena.ai   # or start-arena-chrome.bat 9223
python -m app.main
```

The app scans **only** `CDP Host:CDP Port` from Settings, links every page whose URL
contains the stored **URL pattern** (default `arena.ai`, comma separated list and `*`
wildcards allowed), re-scans every `interval` ms and on Chrome new-tab events, and
drops pages that closed or stopped matching. Two tabs on the same URL are two pages —
identity is the unique CDP page id, never the URL. Settings → *Auto-Connect & URL
Parsing*; live status in the Auto-Connect toolbar and the Page Pool window.
See `docs/archive/2026-09-16-auto-connect-url-parsing/design.md`.

## UI Areas
- **URL List:** add, edit, remove, enable/disable, test single/all, status: unchecked, checking, ready, unavailable, auth required, CAPTCHA required, unsupported, error
- **Folder Picker:** choose root, show path, scan button
- **Image Queue:** thumbnail placeholder, relative path, filename, selected checkbox, status, assigned URL, attempt count, output path, error
- **Bulk Controls:** select all, deselect all, select pending, clear completed, retry failed
- **Prompt Editor:** multiline, preview with correlation token `[JOB-ID: ...]`
- **Run Controls:** Start, Pause, Resume, Stop after current, Cancel current, Retry
- **Progress Summary:** total, selected, pending, processing, completed, skipped, failed, needs_review
- **Activity Log:** timestamped events
- **Settings:** timeouts, retry limits, output naming, supported file types, overwrite, highlight rect (enable, duration, color, border width), browser profile, CDP host/port/user-data-dir, **Auto-Connect & URL Parsing** (enable, URL pattern, re-scan interval, max pages, primary session, Scan Now)
- **Auto-Connect toolbar:** badge (watching / off / port unreachable), pattern + endpoint + interval, scanned/matched/linked counts, Scan Now, On/Off

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
  browser/ — cdp_client (transport), cdp_arena, site_adapter (selectors), page_pool,
             autoconnect_match / _config / _linker / _service / _report, tab_events
  services/ — verification, job_runner, multi_page_dispatcher, cooldown_service, watcher
  ui/ — main_window (PySide6), bridge (+ bridge_autoconnect mixin), autoconnect_pages,
        autoconnect_settings, web/js panels
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
- [x] Auto-connect: pages on the configured CDP port discovered, filtered by storable URL pattern, linked automatically on start / timer / new-tab events
- [x] Duplicate URLs distinguished by unique page id, not URL
- [x] CDP host + port user-configurable (arena: 9223)
