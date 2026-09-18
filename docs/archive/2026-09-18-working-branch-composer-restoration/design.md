# Restore the proven image-and-prompt composer interaction

Date: 2026-09-18

## User validation

Two replacement implementations were rejected after testing against the live Arena composer:

1. active-form input marking plus `DOM.setFileInputFiles`;
2. synthetic `File`/`DataTransfer` paste plus marked-input fallback and delayed prompt verification.

Neither replacement visibly added the reference image or prompt. Unit and JSDOM success therefore did not represent the live page.

The user identified Git branch `befor-merge---working-past-job-to-web-page` as the last known working implementation. The branch is inspected at commit `032dfc61c45030be1a3e3821f52814513ff54aa3` without switching away from the Arena session branch.

## Proven path found in the working branch

The working branch uses this exact interaction:

1. `CDPClient.attach_image_cdp()` gets the document root.
2. It queries file inputs in this order:
   - `form input[type="file"][accept*="image"]`
   - `input[type="file"][accept*="image"]`
   - `input[type="file"]`
3. It passes the first matching node and absolute image path to `DOM.setFileInputFiles`.
4. `CDPArenaController.attach_image()` waits one second, checks the established visible preview selectors, and retries verification after another two seconds.
5. `JS_INSERT_PROMPT` finds the visible textarea in semantic selector order, invokes the native `HTMLTextAreaElement.value` setter, emits bubbling `input` and `change` events, and performs the final direct value assignment used by the working page.

The multi-page dispatcher and `single_job_runner` already existed on the working branch and call these controller methods. The regression is therefore in replacement of the proven browser interaction, not in dispatcher selection.

## Replacement decision

Remove the unvalidated paste/marked-active-form/composer-probe replacement and restore the proven working-branch transport and JavaScript verbatim where interaction behavior matters.

Retain only safety changes that do not alter that browser interaction:

- reject explicit or malformed CDP protocol failures instead of treating every reply as success;
- preserve the required-block failure gate, so attachment or prompt failure prevents Submit and generation waiting;
- retain tests proving the exact production JavaScript and selector order are used.

Do not combine the failed synthetic paste with the proven path. Do not add another selector abstraction around it. This is a find-and-replace restoration, not a third speculative composer implementation.

## Verification

- Compare restored constants and selector order directly with commit `032dfc6`.
- Run production JavaScript tests extracted from `cdp_arena.py`.
- Test first-match file-input selection, absolute path transport, explicit protocol failure, preview retry, prompt insertion, and required-block stop behavior.
- Run full Python and JavaScript suites and RULE 16/18 checks.
- Treat live user validation as the final acceptance gate.
