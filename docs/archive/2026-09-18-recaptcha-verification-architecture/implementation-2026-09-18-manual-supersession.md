# Manual-supersession correction

The previous live interpretation was incorrect: no automatic CAPTCHA solve has yet produced a proven end-to-end generation. The successful output lines were associated with a page where the CAPTCHA dialog had already disappeared before the API token arrived. That means manual/user resolution or another page transition may have cleared the challenge; the later API injection was not evidence that the API path passed.

## Correct rule

A provider token arriving while `dialog_at_token == gone` is never an automatic success. The solver must:

1. refuse to inject the token;
2. delete the provider task best effort;
3. report `token_stale` with reason `dialog_gone_before_token_injection`;
4. apply no CAPTCHA penalty for the API attempt;
5. allow the existing page/job flow to continue if the page has already been cleared manually.

A token is an automatic acceptance candidate only when the dialog is still present at token arrival, the current page/challenge identity matches, injection/callback succeeds, and no page error appears. Final generation output remains the authoritative job result.

This correction prevents a manual pass from being falsely attributed to the API solver.
