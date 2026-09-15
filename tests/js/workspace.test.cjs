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
