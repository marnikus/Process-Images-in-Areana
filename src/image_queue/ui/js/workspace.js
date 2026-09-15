/* Serialized command UI. Retained grid gestures become ONE durable global history edit. */
"use strict";
const Workspace = {
  state: null,
  bridge: null,
  dirty: false,
  label: "Workspace change",
  timer: null,
  pending: null,
  blocked: false,
  initialize(bridge, state) {
    this.bridge = bridge;
    this.state = state;
    SashGrid._loadTree = () =>
      structuredClone(this.state.workspace.layout.tree);
    SashGrid._loadWindowStates = () => {};
    SashGrid._loadFromBackend = () => {};
    SashGrid._save = () => this.schedule("Layout change");
    SashGrid._saveWindowStates = () => this.schedule("Window arrangement");
    SashGrid.flushPersistence = () => false; // shutdown uses the awaited workspace transaction instead
    GridInitializers.forEach((fn) => fn());
    WorkspaceView.apply(state);
    this.wire();
    Features.wire();
    document.getElementById("connectionNotice").textContent =
      "Workspace editing is active. Chrome checks and folder scans run only on request. Image processing is not implemented yet.";
    WorkspaceView.status("Saved locally · changes are undoable");
  },
  schedule(label) {
    if (this.blocked) return;
    this.dirty = true;
    this.label = label;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), 0);
  },
  async flush() {
    clearTimeout(this.timer);
    if (this.pending) await this.pending;
    if (this.blocked) return false;
    if (!this.dirty) return true;
    this.dirty = false;
    try {
      return this.send({
        kind: "edit",
        workspace: WorkspaceView.capture(this.state),
        label: this.label,
      });
    } catch {
      this.dirty = true;
      WorkspaceView.status("Invalid settings JSON; fix before saving", true);
      return false;
    }
  },
  async send(command) {
    if (this.pending) await this.pending;
    if (this.blocked) return false;
    document.getElementById("busyShield").hidden = false;
    document.activeElement?.blur();
    const request = { ...command, revision: this.state.revision };
    this.pending = WorkspaceWire.invoke(
      this.bridge,
      request,
      request.kind === "scan" ? 120000 : 15000,
    );
    let response;
    try {
      response = await this.pending;
    } finally {
      this.pending = null;
      document.getElementById("busyShield").hidden = true;
    }
    if (!response.ok) {
      this.dirty = false;
      this.blocked = response.faulted;
      WorkspaceView.apply(this.state);
      WorkspaceView.status(response.error, true);
      if (this.blocked)
        document.getElementById("connectionNotice").textContent =
          "Persistence fault. Editing locked; close and reopen to inspect durable state.";
      return false;
    }
    this.result = response.result;
    this.state = response.state;
    WorkspaceView.apply(this.state);
    WorkspaceView.status("Saved locally · verified JSON checkpoint");
    return true;
  },
  async travel(kind) {
    if (await this.flush()) await this.send({ kind });
  },
  async saveLayout() {
    if (!(await this.flush())) return;
    const name = document.getElementById("layoutName").value;
    if (!name.trim()) {
      WorkspaceView.status("Enter a layout name", true);
      return;
    }
    const data = structuredClone(this.state.workspace);
    data.layouts = { ...data.layouts, [name]: structuredClone(data.layout) };
    await this.send({ kind: "edit", workspace: data, label: "Save layout" });
  },
  async applyLayout(name) {
    if (!(await this.flush())) return;
    const data = structuredClone(this.state.workspace);
    data.layout = structuredClone(data.layouts[name]);
    await this.send({ kind: "edit", workspace: data, label: "Apply layout" });
  },
  async deleteLayout(name) {
    if (!(await this.flush())) return;
    const data = structuredClone(this.state.workspace);
    delete data.layouts[name];
    await this.send({ kind: "edit", workspace: data, label: "Delete layout" });
  },
  async close(geometry) {
    document.activeElement?.blur();
    if (!(await this.flush())) return;
    const data = structuredClone(this.state.workspace);
    data.geometry = geometry;
    if (
      await this.send({
        kind: "edit",
        workspace: data,
        label: "Window geometry",
      })
    )
      this.bridge.ready_to_close();
  },
  wire() {
    for (const id of [
      "prompt",
      "variablesJson",
      "promptMode",
      "scanRecursive",
      "scanMax",
      "outputFolder",
      "folder",
      "urls",
      "chromeHost",
      "chromePort",
      "highlightMs",
      "confirmMs",
      "highlightEnabled",
    ]) {
      document
        .getElementById(id)
        .addEventListener("change", () =>
          this.schedule(id === "prompt" ? "Prompt edit" : "Settings edit"),
        );
      document.getElementById(id).addEventListener("input", () => {
        this.dirty = true;
        this.label = id === "prompt" ? "Prompt edit" : "Settings edit";
      });
    }
    document.getElementById("undoBtn").onclick = () => this.travel("undo");
    document.getElementById("redoBtn").onclick = () => this.travel("redo");
    document.getElementById("saveLayoutBtn").onclick = () => this.saveLayout();
    document.getElementById("chooseFolderBtn").onclick = () =>
      this.dialogs.choose_folder((path) => {
        if (path) {
          document.getElementById("folder").value = path;
          this.schedule("Source folder");
        }
      });
    document.addEventListener("keydown", (event) => {
      const editor = event.target.closest("input,textarea,[contenteditable]");
      if (editor || !(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === "z") {
        event.preventDefault();
        this.travel(event.shiftKey ? "redo" : "undo");
      }
      if (event.key.toLowerCase() === "y") {
        event.preventDefault();
        this.travel("redo");
      }
    });
  },
};
