# Image Queue

A local desktop image-processing rebuild retaining the previous **dark drag/drop workspace, layouts, global undo/redo, presets/variables, Chrome/CDP connection, and visual click rectangles**. No database is planned.

**Current implementation: Steps 1–6 (manual exit gates pending).** The retained dark
workspace supports global JSON undo, seven preset families, templates/variables,
stack drag/typed block editing, explicit checks of user-opened debug Chrome, and
folder scanning with thumbnails and fingerprint-bound selection. Upload, submission
and image generation remain disabled. Real Qt/WebChannel and automated transport/DOM
tests pass; native WebEngine rendering and live Windows Chrome are still unverified.
See [current results](docs/IMPLEMENTATION-STATUS.md) and [Steps 4–6 usage](docs/STEPS-4-6.md).

```sh
python -m pip install --upgrade pip
python -m pip install -e '.[dev,desktop]'
python -m image_queue desktop
```

Use `".[dev,desktop]"` in Windows Command Prompt. See [workspace instructions](docs/WORKSPACE.md)
for data directories, recovery, keyboard behavior and Linux system dependencies.

## Plan and status

- [Twelve approximately four-hour steps](docs/rebuild/09-FOUR-HOUR-STEPS.md) — ~48 hours initial engineering estimate, not a deadline.
- [Implementation status and measured checks](docs/IMPLEMENTATION-STATUS.md).
- [Reviewed requirements/research map](docs/rebuild/README.md).
- [Coding rules](AGENTS.md) and [testing](docs/TESTING.md).

## Install for development

Python 3.11+ is required. Node.js 22+ is needed for retained JavaScript regression tests, not for the offline CLI. Run these commands from repository root.

Windows Command Prompt:

```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,desktop]"
```

Linux/macOS shell:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,desktop]'
```

The desktop extra installs Qt/WebEngine. Runtime dependencies include filelock/platformdirs, retained aiohttp/websockets transport, and Pillow for validated thumbnails. Linux installation and checks were executed here; Windows/macOS installation and desktop packaging have not yet been manually validated. The Linux/Windows/native CI template is preserved at `tools/ci/quality.yml`, but is inactive: the GitHub integration lacks workflow-write permission. No remote CI run is claimed.

## Run offline checks

```sh
python -m image_queue --version
python -m image_queue check-url "https://arena.ai/c/example"
python -m image_queue check-preset examples/connection-preset.json
npm ci --ignore-scripts
python tools/check.py
```

A valid URL means syntax only, **not** reachable/authenticated/connected/ready. The example URL is a disabled placeholder, not a real tested conversation. The offline validation commands do not modify files or contact a website (the desktop command stores workspace state). Invalid input returns exit code 2 with a non-secret-bearing error. Avoid passing secrets on command lines (shell history may retain them).

The example JSON is a **connection preset subset**: schema version, loopback Chrome endpoint, inherited highlight controls, exact URL rows and enabled flags. It neither replaces nor migrates the full legacy layout/stack/template/variable libraries; those are implemented as separate libraries in Step 4. The pure codec rejects unknown fields/versions instead of losing them, duplicate keys, malformed types/ranges, duplicate row IDs and files larger than 1 MiB. The separate workspace store supplies atomic persistence and global undo; this connection codec does not own job state.

## Connect to existing Chrome

The chosen strategy reuses existing user-opened debug Chrome. Example Windows command:

```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\arena-images-chrome"
```

Open your authorized pages there and log in manually. Use **Discover existing Chrome**, then explicitly choose **Check this tab**. Checks use the retained CDP approach without launching a second browser or silently choosing another conversation. Connection verification is not site readiness; no generation is enabled. Keep remote debugging on loopback and profile contents out of this repository. The app must run locally on the same computer as Chrome.

## Safety and preservation

No legacy production code or reference captures were removed. A small legacy test-loader repair now loads the real split JS files in shipped order; its assertions were preserved and a missing-preset negative case added. Tests used synthetic images and a loopback CDP peer, not credentials/accounts or live Chrome. Missing reviewed idle/upload/completion/download evidence still blocks the concrete Arena adapter.
