/* Explicit retained ID -> image workspace mapping. No old content/data is imported. */
"use strict";
const PanelRegistry = [
  [
    "stats",
    "winStats",
    "Progress",
    '<p id="queueSummary">No scan yet</p><p class="muted">Selection is not permission to submit. Processing remains disabled.</p>',
  ],
  [
    "filters",
    "winFilters",
    "Source folder",
    '<label for="folder">Root folder</label><input id="folder" placeholder="Local folder path"><button id="chooseFolderBtn">Choose folder…</button><label class="check"><input id="scanRecursive" type="checkbox"> Include subfolders</label><label for="scanMax">Max source bytes</label><input id="scanMax" type="number" min="1" max="67108864"><label for="outputFolder">Exclude output folder (optional)</label><input id="outputFolder"><button id="scanBtn">Scan / reconcile</button><p class="muted">PNG, JPEG, WebP, BMP, TIFF · no links or generated _AI files. New/changed files require selection.</p>',
  ],
  [
    "stack",
    "winStack",
    "Workflow",
    '<div class="workflow-step"><b>01</b> Observe baseline</div><div class="workflow-step"><b>02</b> Attach & verify image</div><div class="workflow-step"><b>03</b> Verify prompt · submit once</div><div class="workflow-step"><b>04</b> Correlate · validate · save</div><p class="muted">Stored blocks are editable plans, never executable in this build. Mandatory verification gates cannot be bypassed by a preset.</p><div id="workflowBlocks"></div><button id="addBlockBtn">Add inert block</button><div id="blockConfigFields"></div><label for="blockJson">Selected block · all parameters (JSON)</label><textarea id="blockJson"></textarea><button id="saveBlockBtn">Save block parameters</button>',
  ],
  [
    "config",
    "blockConfigPanel",
    "Settings",
    '<label for="chromeHost">Chrome host</label><select id="chromeHost"><option>127.0.0.1</option><option>localhost</option><option>::1</option></select><label for="chromePort">Debug port</label><input id="chromePort" type="number" min="1" max="65535"><label class="check"><input id="highlightEnabled" type="checkbox"> Highlight click target</label><label for="highlightMs">Rectangle duration (ms)</label><input id="highlightMs" type="number" min="0" max="30000"><label for="confirmMs">Before-click pause (ms)</label><input id="confirmMs" type="number" min="0" max="30000">',
  ],
  [
    "composer",
    "winComposer",
    "Prompt",
    '<label for="prompt">Your exact prompt</label><textarea id="prompt" placeholder="Describe how you want to transform each image…" spellcheck="false"></textarea><label for="promptMode">Prompt mode</label><select id="promptMode"><option value="literal">Literal (unchanged)</option><option value="template">Render saved variables</option></select><button id="promptPreviewBtn">Preview final text</button><pre id="promptPreview"></pre>',
  ],
  [
    "people",
    "winPeople",
    "Image queue",
    '<div class="input-row"><button id="selectAllBtn">Select valid</button><button id="skipAllBtn">Skip valid</button><button id="reviewAllBtn">Require review</button></div><div id="imageRows">Choose a folder and scan. Nothing runs automatically.</div>',
  ],
  [
    "log",
    "winLog",
    "Activity",
    '<p id="activity">Workspace ready. No files uploaded or remote actions performed.</p><p class="muted">Save errors are shown in the status bar and never reported as success.</p>',
  ],
  [
    "history",
    "winHistory",
    "Job history",
    '<p class="muted">No jobs submitted. Future job evidence is immutable and excluded from workspace undo.</p>',
  ],
  [
    "userdb",
    "winUserDb",
    "Saved outputs",
    '<p class="muted">No generated outputs. This panel will show validated files, not a database.</p>',
  ],
  [
    "collector",
    "winCollector",
    "File changes",
    '<p id="scanChanges">Scan explicitly to reconcile changed and missing files. No background collector runs.</p>',
  ],
  [
    "labels",
    "winLabels",
    "Variables",
    '<label for="variablesJson">Saved variables (JSON object of text values)</label><textarea id="variablesJson" spellcheck="false"></textarea><p class="muted">Use {name}. One-pass substitution only; unknown variables remain visible. Literal mode never substitutes.</p>',
  ],
  [
    "dbconn",
    "winDbconn",
    "Chrome URLs",
    '<label for="urls">Exact page URLs · one per line</label><textarea id="urls" placeholder="https://arena.ai/c/your-conversation" spellcheck="false"></textarea><div class="input-row"><button id="discoverBtn">Discover existing Chrome</button><button id="chromeStatusBtn">Refresh status</button><button id="disconnectBtn">Disconnect</button></div><div id="chromeRows"></div><p class="muted">Only exact, user-opened tabs. Checks are observations, never site readiness. No automatic reconnect or browser launch.</p>',
  ],
  [
    "botchat",
    "winBotChat",
    "Job inspector",
    '<p class="muted">Correlation evidence will appear here. Processing is unavailable in this build.</p>',
  ],
  [
    "botprompt",
    "winBotPrompt",
    "Prompt templates",
    '<label for="libraryFamily">Library family</label><select id="libraryFamily"><option value="templates">Templates</option><option value="prompts">Prompts</option><option value="variables">Variables</option><option value="stacks">Stacks</option><option value="blocks">Blocks</option><option value="connections">Connections</option><option value="windows">Windows</option><option value="archives">Legacy backups (inert)</option></select><div id="templateChips"></div><label for="presetName">Preset name</label><input id="presetName" maxlength="80"><label for="presetJson">All preset fields (JSON)</label><textarea id="presetJson" spellcheck="false"></textarea><div class="input-row"><button id="capturePresetBtn">Capture current</button><button id="createPresetBtn">Create</button><button id="updatePresetBtn">Update</button><button id="applyPresetBtn">Apply reviewed entry</button></div><label for="libraryFile">Import JSON file (preview first)</label><input id="libraryFile" type="file" accept=".json,application/json"><label for="importJson">Import / exported backup JSON</label><textarea id="importJson"></textarea><button id="previewImportBtn">Preview import</button><button id="confirmImportBtn" disabled>Import reviewed data</button><button id="exportLibraryBtn">Export full backup</button><pre id="libraryPreview"></pre>',
  ],
];
for (const [key, id, title, content] of PanelRegistry) {
  const panel = document.createElement("section");
  panel.id = id;
  panel.className = "panel";
  panel.dataset.window = key;
  panel.innerHTML = `<h3 class="win-title"><span class="win-grip" aria-hidden="true">⠿</span>${title}</h3><div class="panel-body">${content}</div>`;
  document.getElementById("sashGrid").appendChild(panel);
}
