/* Real extracted DOM + real Python service/store. Qt channel is the only replaced wire. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const vm = require("node:vm");
const readline = require("node:readline");
const { spawn } = require("node:child_process");
const { once } = require("node:events");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "../.."),
  ui = path.join(root, "src/image_queue/ui");

async function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "image-workspace-"));
  const python =
    process.env.PYTHON ||
    path.join(
      root,
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    );
  const child = spawn(
    python,
    [path.join(root, "tools/workspace_test_backend.py"), directory],
    { stdio: ["pipe", "pipe", "inherit"] },
  );
  const waiting = [];
  readline
    .createInterface({ input: child.stdout })
    .on("line", (line) => waiting.shift()(line));
  const request = (data) =>
    new Promise((resolve) => {
      waiting.push(resolve);
      child.stdin.write(JSON.stringify(data) + "\n");
    });
  const raw = await request({ kind: "read" });
  const dom = new JSDOM(fs.readFileSync(path.join(ui, "index.html"), "utf8"), {
    runScripts: "outside-only",
    pretendToBeVisual: true,
    url: "https://local-workspace.test/",
  });
  dom.window.structuredClone = structuredClone;
  const context = dom.getInternalVMContext();
  for (const match of dom.window.document.querySelectorAll("script[src]")) {
    const name = match.getAttribute("src");
    if (name.startsWith("qrc:") || name === "js/connect.js") continue;
    vm.runInContext(fs.readFileSync(path.join(ui, name), "utf8"), context, {
      filename: name,
    });
  }
  const listeners = new Set();
  const bridge = {
    completed: {
      connect(fn) {
        listeners.add(fn);
      },
      disconnect(fn) {
        listeners.delete(fn);
      },
    },
    command(id, raw) {
      request(JSON.parse(raw)).then((response) =>
        listeners.forEach((fn) => fn(id, response)),
      );
    },
    ready_to_close() {},
    choose_folder(callback) {
      callback("");
    },
  };
  context.testBridge = bridge;
  context.testState = JSON.parse(raw).state;
  vm.runInContext("Workspace.initialize(testBridge,testState)", context);
  t.after(async () => {
    dom.window.close();
    const exited = once(child, "exit");
    child.stdin.end();
    await exited;
    fs.rmSync(directory, { recursive: true, force: true });
  });
  return {
    dom,
    context,
    directory,
    request,
    run: (code) => vm.runInContext(code, context),
  };
}

test("extracted shell has all 14 retained windows and no automatic browser action", async (t) => {
  const f = await fixture(t);
  assert.equal(f.dom.window.document.querySelectorAll(".panel").length, 14);
  assert.equal(f.dom.window.document.getElementById("startBtn").disabled, true);
  assert.match(
    f.dom.window.document.getElementById("connectionNotice").textContent,
    /not implemented/,
  );
  assert.equal(f.run("SashCore.validate(SashGrid.root)"), null);
});

test("prompt and real drag/drop are globally undoable and durable", async (t) => {
  const f = await fixture(t);
  f.dom.window.document.getElementById("prompt").value =
    "exact prompt\nsecond line";
  await f.run("Workspace.schedule('Prompt edit');Workspace.flush()");
  const first = f.run("JSON.stringify(Workspace.state.workspace)");
  assert.equal(f.run("Workspace.state.history.length"), 1);
  await f.run(
    "SashGrid.simulateDrop('composer','people','right');Workspace.flush()",
  );
  assert.equal(f.run("Workspace.state.history.length"), 2);
  await f.run("Workspace.travel('undo')");
  assert.equal(f.run("JSON.stringify(Workspace.state.workspace)"), first);
  await f.run("Workspace.travel('undo')");
  assert.equal(f.dom.window.document.getElementById("prompt").value, "");
  await f.run("Workspace.travel('redo')");
  assert.equal(
    f.dom.window.document.getElementById("prompt").value,
    "exact prompt\nsecond line",
  );
  const saved = JSON.parse(
    fs.readFileSync(path.join(f.directory, "state.json"), "utf8"),
  ).state;
  assert.equal(saved.cursor, 0);
  assert.equal(saved.workspace.prompt, "exact prompt\nsecond line");
});

test("minimize restore named layout and resize each commit one gesture", async (t) => {
  const f = await fixture(t);
  await f.run("SashGrid.minimizeWindow('composer');Workspace.flush()");
  assert.equal(
    f.run("Workspace.state.workspace.layout.minimized.includes('composer')"),
    true,
  );
  assert.equal(
    f.dom.window.document.querySelectorAll(".sash-min-chip").length,
    1,
  );
  f.dom.window.document.getElementById("layoutName").value = "My desk";
  await f.run("Workspace.saveLayout()");
  await f.run("SashGrid.restoreMinimized('composer');Workspace.flush()");
  const resizeBefore = f.run("Workspace.state.history.length");
  await f.run("SashGrid.simulateResize('',35);Workspace.flush()");
  assert.equal(f.run("Workspace.state.history.length"), resizeBefore + 1);
  assert.equal(f.run("Workspace.state.workspace.layout.tree.sizes[0]"), 35);
  const length = f.run("Workspace.state.history.length");
  await f.run("Workspace.applyLayout('My desk')");
  assert.equal(f.run("Workspace.state.history.length"), length + 1);
  assert.equal(
    f.run("Workspace.state.workspace.layout.minimized.includes('composer')"),
    true,
  );
  await f.run("Workspace.travel('undo')");
  assert.equal(
    f.run("Workspace.state.workspace.layout.minimized.includes('composer')"),
    false,
  );
  await f.run("Workspace.deleteLayout('My desk')");
  assert.equal(
    f.run("Object.keys(Workspace.state.workspace.layouts).length"),
    0,
  );
  await f.run("Workspace.travel('undo')");
  assert.equal(
    f.run("Object.keys(Workspace.state.workspace.layouts).length"),
    1,
  );
});

test("invalid edits roll back without a false saved revision", async (t) => {
  const f = await fixture(t);
  const before = f.run("Workspace.state.revision");
  f.dom.window.document.getElementById("chromePort").value = "0";
  const okay = await f.run(
    "Workspace.schedule('Settings edit');Workspace.flush()",
  );
  assert.equal(okay, false);
  assert.equal(f.run("Workspace.state.revision"), before);
  assert.equal(
    f.dom.window.document.getElementById("chromePort").value,
    "9222",
  );
  assert.equal(
    f.dom.window.document
      .getElementById("saveStatus")
      .classList.contains("error"),
    true,
  );
});

test("layout names render as text rather than executable HTML", async (t) => {
  const f = await fixture(t);
  f.dom.window.document.getElementById("layoutName").value =
    "<img src=x onerror=alert(1)>";
  await f.run("Workspace.saveLayout()");
  assert.equal(
    f.dom.window.document.querySelectorAll("#namedLayouts img").length,
    0,
  );
  assert.match(
    f.dom.window.document.getElementById("namedLayouts").textContent,
    /<img/,
  );
});

test("lost acknowledgement is bounded and never automatically retried", async (t) => {
  const f = await fixture(t);
  const result = await f.run(
    `WorkspaceWire.invoke({completed:{connect(){},disconnect(){}},command(){}},{kind:'edit'},5)`,
  );
  assert.equal(result.ok, false);
  assert.equal(result.faulted, true);
  assert.match(result.error, /Reopen/);
});

test("malformed wire response locks editing and prevents another command", async (t) => {
  const f = await fixture(t);
  f.run(
    `window.invocations=0;const handlers=new Set();Workspace.bridge={completed:{connect(fn){handlers.add(fn)},disconnect(fn){handlers.delete(fn)}},command(id){window.invocations++;handlers.forEach(fn=>fn(id,'bad json'))}}`,
  );
  const result = await f.run(
    `document.getElementById('prompt').value='unsaved';Workspace.schedule('Prompt');Workspace.flush()`,
  );
  assert.equal(result, false);
  assert.equal(f.run("Workspace.blocked"), true);
  assert.equal(f.dom.window.document.getElementById("prompt").value, "");
  await f.run(`Workspace.send({kind:'undo'})`);
  assert.equal(f.run("window.invocations"), 1);
});

test("all-family libraries use retained chips; previews, invalid import and global undo", async (t) => {
  const f = await fixture(t), doc = f.dom.window.document;
  doc.getElementById("prompt").value = "Keep {tone}\r\nexact";
  doc.getElementById("prompt").dispatchEvent(new f.dom.window.Event("input"));
  await f.run("Libraries.capture()");
  assert.equal(JSON.parse(doc.getElementById("presetJson").value).body, "Keep {tone}\nexact");
  doc.getElementById("presetName").value = '<img src=x onerror="alert(1)">';
  await f.run('Libraries.change("create")');
  assert.equal(doc.querySelectorAll("#templateChips .chip").length, 1);
  assert.equal(doc.querySelectorAll("#templateChips img").length, 0);
  const before = f.run("Workspace.state.revision");
  doc.getElementById("importJson").value = '{"bad":';
  await f.run("Libraries.previewImport()");
  assert.equal(f.run("Workspace.state.revision"), before);
  assert.equal(doc.getElementById("confirmImportBtn").disabled, true);
  await f.run("Features.command({kind:'library_export'})");
  const backup = f.run("Workspace.result");
  assert.ok(JSON.parse(backup).libraries.templates['<img src=x onerror="alert(1)">']);
  await f.run("Workspace.travel('undo')");
  assert.equal(doc.querySelectorAll("#templateChips .chip").length, 0);
  doc.getElementById("importJson").value = backup;
  await f.run("Libraries.previewImport()");
  assert.equal(doc.getElementById("confirmImportBtn").disabled, false);
  await f.run("Libraries.importReviewed()");
  assert.equal(doc.querySelectorAll("#templateChips .chip").length, 1);
  assert.equal(doc.getElementById("confirmImportBtn").disabled, true);
});

test("literal/template modes preserve raw text and invalid variable JSON never saves", async (t) => {
  const f = await fixture(t), doc = f.dom.window.document;
  doc.getElementById("prompt").value = "{tone} and {missing}";
  doc.getElementById("variablesJson").value = '{"tone":"{nested}","nested":"never recursively rendered"}';
  await f.run("Workspace.schedule('variables'); Workspace.flush()");
  await f.run("Features.command({kind:'prompt_preview'})");
  assert.equal(f.run("Workspace.result.text"), "{tone} and {missing}");
  doc.getElementById("promptMode").value = "template";
  await f.run("Workspace.schedule('mode'); Workspace.flush()");
  await f.run("Features.command({kind:'prompt_preview'})");
  assert.equal(f.run("Workspace.result.text"), "{nested} and {missing}");
  assert.equal(f.run("Workspace.result.ok"), false);
  const before = f.run("Workspace.state.revision");
  doc.getElementById("variablesJson").value = '{invalid';
  assert.equal(await f.run("Workspace.schedule('invalid variables'); Workspace.flush()"), false);
  assert.equal(f.run("Workspace.state.revision"), before);
  assert.equal(doc.getElementById("variablesJson").value, '{invalid');
});

test("real retained stack pointer drag commits one global undo operation", async (t) => {
  const f = await fixture(t), doc = f.dom.window.document;
  await f.run("Features.edit('blocks', data => { data.workflow = [{block_id:'first', extra:{kept:true}}, {block_id:'second'}]; })");
  const before = f.run("Workspace.state.revision");
  const list = doc.getElementById("workflowBlocks");
  list.getBoundingClientRect = () => ({left:0, top:0, bottom:300, width:300, height:300});
  [...list.children].forEach((row,index) => {
    row.getBoundingClientRect = () => ({left:0, top:index*60, bottom:index*60+50, width:300, height:50});
  });
  const event = (type, y) => new f.dom.window.MouseEvent(type, {bubbles:true, button:0, clientX:10, clientY:y});
  list.querySelector(".block-grip").dispatchEvent(event("pointerdown",10));
  doc.dispatchEvent(event("pointermove",100));
  doc.dispatchEvent(event("pointerup",100));
  await new Promise(resolve => setTimeout(resolve, 160));
  if (f.run("Workspace.pending")) await f.run("Workspace.pending");
  assert.equal(f.run("Workspace.state.workspace.workflow[0].block_id"), "second");
  assert.equal(f.run("Workspace.state.revision"), before+1);
  await f.run("Workspace.travel('undo')");
  assert.equal(f.run("Workspace.state.workspace.workflow[0].extra.kept"), true);
  assert.equal(doc.getElementById("startBtn").disabled, true);
});

test("scanner thumbnails and explicit selection persist; missing sources never selected", async (t) => {
  const f = await fixture(t), doc = f.dom.window.document;
  const sourceDir = path.join(f.directory, "images"); fs.mkdirSync(sourceDir);
  // Synthetic PNG created by Pillow; no real user media in fixtures.
  const {spawnSync} = require("node:child_process");
  const python = process.env.PYTHON || path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
  const result = spawnSync(python, ['-c','from PIL import Image; import sys; Image.new("RGB",(8,8),"red").save(sys.argv[1])', path.join(sourceDir,'input.png')]);
  assert.equal(result.status,0);
  doc.getElementById("folder").value = sourceDir;
  await f.run("Workspace.schedule('source folder'); Workspace.flush()");
  await f.run("Features.command({kind:'scan'})");
  assert.equal(doc.querySelectorAll("#imageRows img").length, 1);
  assert.equal(doc.querySelector("#imageRows input").checked, false);
  await f.run("Features.command({kind:'select', ids:Object.keys(Workspace.state.jobs.sources), decision:'selected'})");
  assert.equal(doc.querySelector("#imageRows input").checked, true);
  await f.run("Workspace.travel('undo')");
  assert.equal(doc.querySelector("#imageRows input").checked, false);
  await f.run("Workspace.travel('redo')");
  fs.unlinkSync(path.join(sourceDir,'input.png'));
  await f.run("Features.command({kind:'scan'})");
  assert.equal(doc.querySelector("#imageRows input").disabled, true);
  assert.equal(doc.querySelector("#imageRows input").checked, false);
  const saved = JSON.parse(fs.readFileSync(path.join(f.directory,'state.json'),'utf8')).state;
  assert.equal(Object.values(saved.jobs.sources)[0].status,'missing');
});

test("Chrome duplicate choices render safe text and persist per-row enable state", async (t) => {
  const f = await fixture(t), doc = f.dom.window.document;
  doc.getElementById('urls').value = 'https://arena.ai/c/exact';
  await f.run("Workspace.schedule('URL'); Workspace.flush()");
  f.run(`ChromeView.render({[JSON.parse(Workspace.state.workspace.connection).urls[0].row_id]: {discovery:'choose_tab', connection:'not_attached', readiness:'unchecked', candidates:[{id:'one',title:'<img src=x>',url:'https://arena.ai/c/exact'},{id:'two',title:'second',url:'https://arena.ai/c/exact'}]}})`);
  assert.equal(doc.querySelectorAll('#chromeRows button').length,2);
  assert.equal(doc.querySelectorAll('#chromeRows img').length,0);
  const enabled = doc.querySelector('#chromeRows input'); enabled.checked = false;
  await enabled.onchange();
  assert.equal(f.run('JSON.parse(Workspace.state.workspace.connection).urls[0].enabled'),false);
});

test("retained typed block controls preserve fields and escape imported text", async (t) => {
  const f = await fixture(t), doc = f.dom.window.document;
  await f.run(`Features.edit('block fields',data => {data.workflow=[{block_id:'CUSTOM_FIND',enabled:false,highlight_ms:1200,message:'<img src=x>&quot;',nested:{keep:true}}]})`);
  doc.querySelector('#workflowBlocks button').click();
  assert.equal(doc.querySelectorAll('#blockConfigFields img').length,0);
  assert.equal(doc.querySelector('[aria-label="Block parameter message"]').value,'<img src=x>&quot;');
  const input = doc.querySelector('[aria-label="Block parameter highlight_ms"]'); input.value='3000';
  await input.onchange();
  assert.equal(f.run('Workspace.state.workspace.workflow[0].highlight_ms'),3000);
  assert.equal(f.run('Workspace.state.workspace.workflow[0].nested.keep'),true);
  await f.run("Workspace.travel('undo')");
  assert.equal(f.run('Workspace.state.workspace.workflow[0].highlight_ms'),1200);
});

test("unchanged prompt line endings survive layout/settings transactions", async (t) => {
  const f = await fixture(t);
  await f.run(`Features.edit('import exact prompt', data => {data.prompt='line one\\r\\nline two';})`);
  await f.run("Workspace.schedule('unrelated layout'); Workspace.flush()");
  assert.equal(f.run('Workspace.state.workspace.prompt'),'line one\r\nline two');
});

test("prototype-like layout names survive save and full portable backup", async (t) => {
  const f = await fixture(t), doc = f.dom.window.document;
  doc.getElementById('layoutName').value='__proto__';
  await f.run('Workspace.saveLayout()');
  assert.equal(f.run("Object.hasOwn(Workspace.state.workspace.layouts,'__proto__')"),true);
  await f.run("Features.command({kind:'library_export'})");
  assert.ok(JSON.parse(f.run('Workspace.result')).libraries.windows.__proto__.tree);
});

test("offline evidence renders truthful saved/review counts without interpreting HTML", async (t) => {
  const f = await fixture(t), doc = f.dom.window.document;
  f.run(`QueueView.render({workspace: {selection: {}}, jobs: {execution: {
    paused: true, stop_after: false, attempts: {
      a: {inputs: {source: {name: '<img src=x onerror=alert(1)>'}}, events: [
        {phase: 'submitted'}, {phase: 'saved', evidence: {path: '<b>output.png</b>', sha256: 'abc'}}]},
      b: {inputs: {source: {name: 'review.png'}}, events: [{phase: 'needs_review'}]}
    }}}})`);
  assert.match(doc.getElementById('queueSummary').textContent, /1 recorded submissions/);
  assert.match(doc.getElementById('executionStatus').textContent, /Live processing disabled.*paused: true/);
  assert.match(doc.getElementById('executionRows').textContent, /needs_review/);
  assert.equal(doc.querySelectorAll('#executionRows img, #outputRows b').length, 0);
  assert.match(doc.getElementById('outputRows').textContent, /<b>output.png<\/b>/);
  f.run('QueueView.render(Workspace.state)');
  assert.equal(doc.getElementById('outputRows').textContent, '');
});
