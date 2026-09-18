# Acceptance-gated CAPTCHA implementation record

This follow-up implements the remaining live-run correctness slice from the architecture document:

- compare the page/document identity at detection and token arrival;
- compare the challenge identity/sitekey before injection;
- classify a changed page/challenge as `token_stale`;
- never inject a late token into a new page state;
- preserve the final output/job result as authoritative;
- add reports and tests for identity evidence.

The implementation deliberately does not attempt to read Google’s private risk score from the browser. Backend assessment remains observable only through the actual Arena generation/output result. No proxy, cookie, user-agent, fingerprint, or telemetry spoofing is added (RULE 20).

## Architecture slice implemented

```text
initial detect.js evidence
  -> SolvePlan identity snapshot
  -> provider polling
  -> fresh detect.js evidence before token injection
  -> page/challenge/sitekey comparison
  -> token_stale + delete provider task on mismatch
  -> otherwise inject/callback candidate
  -> existing output verification decides CAPTCHA_JOB completion
```

`page_identity` uses the page URL plus browser `performance.timeOrigin`, which changes across document navigations while remaining stable across evaluations in the same document. `challenge_identity` is a bounded public frame identity made from the challenge frame name/title and safe host/path; query values are not logged.

## Test/quality plan

- real node probe tests assert page and challenge identities;
- solver tests assert a changed identity prevents injection and deletes the task;
- existing full pytest/node suites remain green;
- quality gate and radon run after production changes;
- RULE 18 recheck keeps identity extraction in the probe and comparison in solver helpers rather than expanding the service/runner functions.
