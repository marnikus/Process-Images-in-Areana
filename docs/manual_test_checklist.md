# Manual Test Checklist

## Authentication
- [ ] Launch app, browser opens with profile ./browser_profile
- [ ] Navigate to arena.ai, log in manually with Google
- [ ] Close app, reopen, verify session persists (no need to log in again)
- [ ] Test URL that requires auth — should mark AUTH_REQUIRED

## URL Management
- [ ] Add valid URL https://arena.ai/image or https://arena.ai/c/...
- [ ] Add invalid URL (syntax error) — should mark ERROR
- [ ] Add unreachable URL — should mark UNAVAILABLE
- [ ] Test single URL — status changes to CHECKING then READY or error
- [ ] Test all URLs — each enabled URL checked
- [ ] Disable URL — should not be used for jobs, shows ✗
- [ ] Enable URL — should be used again
- [ ] Edit URL — status resets to UNCHECKED
- [ ] Remove URL — disappears from list

## Folder and Image Queue
- [ ] Pick root folder with nested images (png, jpg, jpeg, webp)
- [ ] Scan — verify recursive discovery, ignore _AI suffix
- [ ] Verify relative paths preserved
- [ ] Add new file to folder, rescan — detects added
- [ ] Remove file, rescan — marks as skipped or removed
- [ ] Select all / deselect all / select pending / clear completed — verify counts
- [ ] Manual checkbox per image — include/exclude
- [ ] Verify file size, attempt count displayed

## Attachment
- [ ] Start job with one image, verify file input set
- [ ] Verify preview appears in page (blob URL or filename)
- [ ] Verify correct filename matched
- [ ] Test remove file button — preview disappears
- [ ] Test attachment failure (invalid file) — should fail gracefully

## Prompt
- [ ] Enter user prompt, verify preview shows [JOB-ID: ...] + prompt
- [ ] Verify prompt inserted into textarea
- [ ] Verify read-back exact match
- [ ] Test prompt mismatch correction — clears and retries

## Submission
- [ ] Submit once — verify processing state (spinner or textarea cleared)
- [ ] Verify no duplicate submission on slow network
- [ ] Verify submission timestamp recorded

## Generation Wait
- [ ] Wait for new output — verify baseline comparison
- [ ] Verify new image appears after current job in DOM order
- [ ] Verify image loading complete (naturalWidth >0)
- [ ] Test timeout — generation timeout after configured seconds marks FAILED

## Download and Save
- [ ] Download output via src URL — verify valid image bytes, not HTML
- [ ] Save beside source as *_AI.ext — verify file exists
- [ ] Verify source not overwritten
- [ ] If target exists and overwrite disabled — creates _AI_2, _AI_3 etc.
- [ ] Verify atomic write (no partial files left)
- [ ] Verify output metadata (size, format, hash) stored in job record

## CAPTCHA / Security
- [ ] Trigger security verification if possible (or simulate by injecting dialog)
- [ ] Verify app pauses, shows USER_ACTION_REQUIRED, brings browser to front
- [ ] Complete challenge manually
- [ ] Verify app detects dialog gone and continues

## Restart Recovery
- [ ] Start batch, kill app during processing (PROCESSING state)
- [ ] Restart app — verify interrupted job marked INTERRUPTED, not auto-resubmitted
- [ ] Verify image marked FAILED with interrupted error
- [ ] Retry failed — should re-queue

## Error Handling
- [ ] Delete source file mid-batch — should mark SKIPPED or FAILED with clear error
- [ ] Make output folder read-only — should fail with permission denied, logged
- [ ] Simulate disk full — graceful error
- [ ] Invalid URL during batch — skip, mark UNAVAILABLE, continue with other URLs
- [ ] Network timeout — bounded retry, then FAILED

## Highlight Rect
- [ ] Enable highlight in settings, set duration 2s
- [ ] Start job — verify red rect drawn above element being clicked (Add files, textarea, Send)
- [ ] Change duration to 5s — verify longer visible
- [ ] Disable highlight — no rect

## Preset
- [ ] Save preset JSON — verify file contains URLs, prompt, settings, folder, not images/jobs
- [ ] Load preset — verify all UI params restored
- [ ] All parameters in UI storable — change each setting, restart app, verify persisted

## Logging and Observability
- [ ] Verify structured logs in logs/app.log with timestamp, job_id, url_id, image_path, state, attempt
- [ ] Verify activity log in UI shows human-readable events
- [ ] Verify no secrets in logs (no full signed URLs, no credentials)
- [ ] On failure, optional screenshot saved to logs/diagnostics/ if enabled
- [ ] Verify current workflow step shown in UI (status bar or progress)

## Progress Summary
- [ ] Verify totals: total, selected, pending, processing, completed, skipped, failed, needs_review update correctly during batch

## Final Acceptance
- [ ] User can add multiple exact URLs and see reliable readiness status
- [ ] App can recursively scan selected folder and display supported images
- [ ] User can manually select/deselect any image
- [ ] Processing survives ordinary page loading delays without duplicate submissions
- [ ] Correct image attached and verified before submission
- [ ] Exact user prompt + unique job ID inserted and read back
- [ ] App waits for and identifies new result rather than reusing old image
- [ ] Uncertain correlation produces NEEDS REVIEW, not false success
- [ ] Valid result saved beside source using _AI suffix without overwriting
- [ ] Completed/failed/skipped/pending states persist after restart
- [ ] CAPTCHA/security checks pause for manual completion and never bypassed
- [ ] Errors visible, actionable, recorded in job history
