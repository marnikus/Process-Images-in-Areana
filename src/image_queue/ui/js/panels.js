/* Explicit retained ID -> image workspace mapping. No old content/data is imported. */
"use strict";
const PanelRegistry = [
  [
    "stats",
    "winStats",
    "Progress",
    '<p class="big-number">0 <span>images</span></p><p class="muted">The image queue arrives in Step 6.</p>',
  ],
  [
    "filters",
    "winFilters",
    "Source folder",
    '<label for="folder">Root folder</label><input id="folder" placeholder="Local folder path"><button id="chooseFolderBtn">Choose folder…</button><p class="muted">Path is saved; scanning is not available yet.</p>',
  ],
  [
    "stack",
    "winStack",
    "Workflow",
    '<div class="workflow-step"><b>01</b> Observe baseline</div><div class="workflow-step"><b>02</b> Attach & verify image</div><div class="workflow-step"><b>03</b> Verify prompt · submit once</div><div class="workflow-step"><b>04</b> Correlate · validate · save</div><p class="muted">Execution and editable block libraries arrive in later steps. These safety gates cannot be skipped.</p>',
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
    '<label for="prompt">Your exact prompt</label><textarea id="prompt" placeholder="Describe how you want to transform each image…" spellcheck="false"></textarea><p class="muted">Literal text · job marker will be added by the future workflow.</p>',
  ],
  [
    "people",
    "winPeople",
    "Image queue",
    '<div class="empty-state"><span>▧</span><h2>Your images will appear here</h2><p>The workspace is ready. Folder scanning and queue controls are the next processing milestones.</p></div>',
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
    '<p class="muted">Filesystem reconciliation arrives with scanning. No background collector runs.</p>',
  ],
  [
    "labels",
    "winLabels",
    "Variables",
    '<p class="muted">The existing variable/template system will be extracted in Step 4. Saved legacy files remain untouched.</p>',
  ],
  [
    "dbconn",
    "winDbconn",
    "Chrome URLs",
    '<label for="urls">Exact page URLs · one per line</label><textarea id="urls" placeholder="https://arena.ai/c/your-conversation" spellcheck="false"></textarea><div class="input-row"><button disabled>Connect existing Chrome</button><span class="muted">Step 5</span></div><p class="muted">Chrome must already be open with remote debugging. URL rows save here; no connection is claimed.</p>',
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
    '<p class="muted">Full template and variable libraries arrive in Step 4. Layout presets already work in the Layouts menu.</p>',
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
