# Risk List, Compliance Assumptions, Unresolved Questions

## Risks

### 1. Selector Fragility
- **Risk:** arena.ai uses Tailwind with utility classes that change on deploy; generated IDs (radix) change every session.
- **Impact:** Page readiness fails, attachment fails, output detection fails.
- **Mitigation:** Prefer semantic selectors (aria-label, name, role, placeholder prefix). Centralize selectors in site_adapter with fallback chains. Structured logging of selector failures. Provide dry-run selector testing without submission (optional enhancement). Document last verified date.
- **Likelihood:** High
- **Severity:** High

### 2. Attachment Preview Not Observed
- **Risk:** No HTML evidence of preview after attachment; our selector `div.flex.flex-wrap.gap-2 img[alt]` may be inaccurate.
- **Impact:** Attachment verification fails, jobs never submit.
- **Mitigation:** Implement multiple fallbacks, log actual DOM when preview not found, capture sanitized snapshot for debugging, allow user to inspect page manually. Request additional saved states with attachment.
- **Likelihood:** Medium
- **Severity:** High

### 3. Output Detection Ambiguity
- **Risk:** Output image host pattern may change, or multiple images appear (old + new). Correlation uncertain.
- **Impact:** False success (saving old image) or Needs Review flood.
- **Mitigation:** Baseline capture before submission, timestamp, DOM order check, wait for new src, validate loading complete, mark Needs Review when uncertain rather than false success. Log evidence.
- **Likelihood:** High
- **Severity:** High

### 4. CAPTCHA / Security Verification
- **Risk:** reCAPTCHA appears unpredictably, blocks automation.
- **Impact:** Jobs stuck, user not notified.
- **Mitigation:** Detect dialog via role and iframe, pause affected job, bring browser to front, show "User action required" in UI, wait for manual completion, detect readiness again. Never attempt to bypass or solve.
- **Likelihood:** Medium
- **Severity:** Medium (compliance critical)

### 5. Session Expiry / Authentication
- **Risk:** User session expires, page redirects to sign-in.
- **Impact:** All URLs marked unavailable, jobs fail.
- **Mitigation:** Detect sign-in pages via URL and text heuristics, mark AUTH_REQUIRED, pause, notify user to log in manually, retest.
- **Likelihood:** Medium
- **Severity:** Medium

### 6. Rate Limit / Paid Work Duplication
- **Risk:** Automatic retries could create duplicate paid generations or hit rate limits.
- **Impact:** Financial cost, account ban.
- **Mitigation:** Bounded retries, never retry submission automatically when duplicate risk exists (i.e., after submit confirmed). Require manual retry. Log all submissions.
- **Likelihood:** Medium
- **Severity:** High

### 7. File System Issues
- **Risk:** Source file disappears, output path permission denied, disk full.
- **Impact:** Job fails, possible data loss.
- **Mitigation:** Check source exists before each job, validate output path writable, handle disk full gracefully, write to temp then atomic rename, never overwrite source.
- **Likelihood:** Low
- **Severity:** Medium

### 8. Browser Automation Flakiness
- **Risk:** Playwright/CDP timing issues, page loading delays, element not interactable.
- **Impact:** False failures, duplicate clicks.
- **Mitigation:** Explicit waits, verification after each action, prevent duplicate submission, use slow_mo config, structured retries with backoff.
- **Likelihood:** Medium
- **Severity:** Medium

### 9. Large Image Files / Memory
- **Risk:** Very large images may exceed upload limit or cause OOM.
- **Impact:** Attachment fails, browser crashes.
- **Mitigation:** Check file size against max (configurable, default 25MB), skip with clear error, log.
- **Likelihood:** Low
- **Severity:** Low

### 10. Concurrency & Scheduling
- **Risk:** MVP says sequential processing unless concurrency approved. If user configures multiple URLs, round-robin scheduling must be visible and safe.
- **Impact:** Race conditions, wrong URL assignment.
- **Mitigation:** MVP single job at a time, round-robin URL assignment, log assignment, UI shows assigned URL per image.
- **Likelihood:** Low (if concurrency=1)
- **Severity:** Medium

## Compliance Assumptions

1. **User Authorization:** User is authorized to access all configured URLs and accounts. App does not bypass authentication.
2. **Terms of Service:** Target site (arena.ai) permits this automation for user's own account. If ToS forbids automation, user assumes risk. App respects rate limits and does not circumvent protections.
3. **No CAPTCHA Bypass:** App never attempts to bypass, defeat, outsource, or automatically solve CAPTCHA. Manual user completion only.
4. **No Credential Logging:** Credentials and session data not stored in logs. Sensitive data stored securely and minimally (browser profile dir, not in JSON).
5. **Upload Scope:** Files are uploaded only to URLs explicitly configured and approved by user.
6. **Data Privacy:** Screenshots and page snapshots for debugging are optional, sanitized, subject to user consent.
7. **Output Ownership:** Generated images belong to user; app only saves beside source.
8. **OS Support:** Windows, macOS, Linux (Playwright supports all). Tested on Linux first.
9. **Browser:** Chromium via Playwright persistent context, user data dir isolated.
10. **Image Formats:** Source png, jpg, jpeg, webp; output preserves downloaded format.

## Unresolved Questions

1. **Supported OS:** Confirm Windows/macOS/Linux all required? MVP Linux OK?
2. **Browser Profile:** Dedicated profile vs attaching to user-opened Chrome? We propose Playwright persistent context with dedicated profile `./browser_profile`, user logs in manually once.
3. **Authentication Storage:** Store session in browser profile dir, not in JSON. Acceptable?
4. **Max File Size:** What is max source image size allowed by arena.ai? Assume 25MB.
5. **Sequential vs Concurrent:** MVP sequential, but UI allows multiple URLs with round-robin. Confirm sequential is OK.
6. **ToS Permission:** Does arena.ai explicitly permit automation? Need user confirmation.
7. **Saved Page States:** We have only empty chat state. Need states with attachment, generating, completed, security dialog, sign-in.
8. **DOM Change Handling:** When webpage changes, how should app notify user? We propose readiness check fails with diagnostic and selector update guide.
9. **Output Folder:** Should outputs remain beside sources or optionally use separate output folder? MVP beside source, optional subfolder later.
10. **Review Before Submit:** Does user want review/approval before each submission or only on errors? MVP auto-submit after verification, but allow Pause/Stop.
11. **Highlight Duration:** User-configurable seconds for rect drawing — default 2s, confirm.
12. **Preset Scope:** Preset includes URLs, prompt, settings, folder? Or also image selections? We propose preset = UI params without job history.
13. **Overwrite Behavior:** Default overwrite disabled, create unique name. Confirm.

## Mitigation Plan for Unknowns

- Implement diagnostic mode: on selector failure, save sanitized HTML snippet (remove sensitive) and screenshot (if consented) to `logs/diagnostics/`
- Provide manual test checklist covering auth, upload, generation, CAPTCHA pause/resume, download, restart recovery, common failures
- Make site_adapter replaceable and versioned, with clear docs on how to update selectors
- Log all automatic decisions inspectably, especially why output considered new and correlated
