# Known Limitations and Maintenance Guidance

## Known Limitations — MVP

1. **Manual Login Required:** First run requires manual login to arena.ai in persistent browser profile. Session stored in `./browser_profile`, not automated.
2. **Selector Fragility:** arena.ai uses Tailwind utility classes and generated Radix IDs that change frequently. We mitigate with semantic selectors and fallbacks, but DOM changes will break readiness checks. Requires manual update of `app/browser/site_adapter.py`.
3. **Attachment Preview Not Fully Verified:** Saved HTML evidence does not contain a state with attached file preview. Our selector `div.flex.flex-wrap.gap-2 img[alt]` and blob fallback is based on spec, not confirmed HTML. May need adjustment after observing real preview.
4. **Output Detection Heuristic:** Output image host pattern `.r2.cloudflarestorage.com` observed from JS bundles, not from actual output HTML. If host changes, detection fails. Fallback to `img.aspect-square` may pick wrong images.
5. **Sign-in / Error Detection Heuristic:** Detection of sign-in, access-denied, rate-limit uses text search, not stable selectors. May miss localized or new error pages.
6. **Sequential Only:** MVP processes one image at a time, round-robin URLs. No concurrent processing across independent URLs (optional enhancement).
7. **No Thumbnails:** Image queue shows filename and size, not actual image thumbnail. Thumbnail generation with Pillow is possible but not implemented to keep MVP simple.
8. **No Watch-Folder Mode:** User must click Scan to detect new files. No automatic filesystem watcher.
9. **No CSV/JSON Export:** Job history is in `config/app_state.json`, but no exportable CSV/JSON report button yet (optional enhancement).
10. **No Visual Comparison:** No side-by-side source vs result viewer (optional enhancement).
11. **Download via Fetch:** Download uses page's `fetch()` to preserve auth. If site uses blob URLs or requires special headers, download may fail. Needs fallback to Playwright request with storage state.
12. **No Dry-Run Selector Testing:** No UI button to test selectors without submission (optional enhancement, but useful for maintenance).
13. **Highlight Overlay:** Rect drawing uses absolute positioned div appended to body. May be hidden by page's own overlays or not scroll correctly if page uses transformed containers. Configurable but not perfect.
14. **No Notification:** No desktop notification when user action required or batch finishes (optional enhancement).
15. **Limited Image Format Validation:** Validates via magic bytes and Pillow, but does not check dimensions or corruption deeply.
16. **No Per-Image Prompts:** Single prompt for whole batch. Per-image prompt template is optional enhancement.

## Maintenance Guidance for Webpage Changes

### When to Update Selectors
- URL test fails with "Not ready: ..." — check which required element missing
- Attachment verification fails consistently — preview selector changed
- Output detection never finds new image — host pattern or container changed
- Security dialog not detected — role or text changed
- Send button not found — aria-label changed

### How to Update

1. **Save New Evidence:**
   - Open arena.ai in browser profile
   - For each state (empty, with attachment, generating, completed, security dialog), save full HTML (right-click Save As, or via Playwright `page.content()` to file)
   - Save screenshot

2. **Inspect Elements:**
   - Use DevTools to find stable attributes: `aria-label`, `name`, `role`, `placeholder`, `alt`, `data-*`
   - Avoid: full class chains, generated IDs (`radix-...`), signed URLs with query params, dimensions

3. **Update Site Adapter:**
   - Edit `app/browser/site_adapter.py`
   - For each element, update primary selector, add fallbacks in order
   - Update `evidence` and `lastVerified` fields
   - Keep old selectors as fallbacks if still plausible

4. **Test Readiness:**
   - Run app, add URL, click Test — should become READY
   - Check logs for which selector succeeded (add debug logging if needed)

5. **Test Full Flow:**
   - Pick small folder with 1 image
   - Enter prompt, Start
   - Verify each step: attachment verified, prompt verified, submission confirmed, new output detected, saved as _AI

6. **Document:**
   - Update `docs/selector_map.md` with new evidence
   - Update `docs/research_summary.md` with new findings

### Selector Priority (from spec)
1. Primary: role, accessible name, label, name, type, stable data attribute, stable visible text
2. Secondary: stable structural relationship inside verified container
3. Fallback: short class fragment + semantic attributes
4. Never alone: generated IDs, complete utility-class chains, temporary blob URLs, signed image URLs, dimensions, nth-child

### Diagnostic Evidence on Failure
- When selector not found, `BrowserController` logs attempted selectors
- Optionally save sanitized screenshot and limited HTML snapshot to `logs/diagnostics/` (if user consents)
- Logs contain timestamp, job ID, URL ID, image path, workflow state, attempt, result — no secrets

### Versioning
- Keep `SELECTORS` dict versioned with `lastVerified` date
- When major DOM change detected, bump app version in `app/__init__.py` and `AppState.version`

### Future-Proofing
- Consider adding dry-run mode: test selectors without submission, show which selectors matched
- Consider adding visual selector tester in UI: user can click "Test Selectors" and see highlighted elements
- Keep site_adapter replaceable — could support multiple site adapters (e.g., different arena.ai modes: direct, battle, side-by-side) via strategy pattern

## Compliance Maintenance
- Always keep CAPTCHA detection and manual pause logic
- Never add auto-solve
- Keep credentials out of logs
- Keep atomic writes and no overwrite of source

## Performance
- For large folders (1000+ images), scanning may be slow if content hash enabled. Keep hash optional (currently disabled by default, uses path+size+mtime fingerprint)
- Thumbnail generation would add overhead — keep optional

## Security
- Browser profile contains session cookies — keep `./browser_profile` out of git, protect permissions
- Preset JSON does not contain session, only URLs and prompts
- Logs should not contain full signed URLs — truncate or hash if needed (currently logs src but could be sensitive — consider truncating in future)
