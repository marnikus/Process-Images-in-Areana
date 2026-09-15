/* Retained preset chips/picker semantics, now backed by the single JSON undo authority. */
"use strict";
const Libraries = {
  preview: null,
  family() {
    return document.getElementById("libraryFamily").value;
  },
  render() {
    const entries = Workspace.state.workspace.libraries[this.family()];
    PresetsUITemplates.renderTemplateChips.call({
      templatePresets: Object.entries(entries).map(([name, value]) => ({
        name,
        len: JSON.stringify(value).length,
      })),
      _makeChip(title, meta, onLoad, onDelete) {
        return window.UIHelpers.chip({ title, meta, onLoad, onDelete });
      },
      loadTemplate: (name) => this.load(name),
      deleteTemplate: (name) => this.change("delete", name),
    });
  },
  load(name) {
    document.getElementById("presetName").value = name;
    document.getElementById("presetJson").value = JSON.stringify(
      Workspace.state.workspace.libraries[this.family()][name],
      null,
      2,
    );
  },
  async change(operation, name = document.getElementById("presetName").value) {
    const value = operation === "delete" ? null : Features.parse("presetJson");
    if (value === undefined) return;
    await Features.command({
      kind: "library_change",
      change: { family: this.family(), name, value, operation },
    });
  },
  async capture() {
    if (!(await Workspace.flush())) return;
    const data = Workspace.state.workspace,
      family = this.family();
    const values = {
      templates: { body: data.prompt },
      prompts: {
        body: data.prompt,
        mode: data.prompt_mode,
        variables: data.variables,
      },
      variables: data.variables,
      stacks: { blocks: data.workflow },
      blocks: {},
      connections: JSON.parse(data.connection),
      windows: data.layout,
      archives: {},
    };
    document.getElementById("presetJson").value = JSON.stringify(
      values[family],
      null,
      2,
    );
  },
  async apply() {
    const name = document.getElementById("presetName").value;
    const entries = Workspace.state.workspace.libraries[this.family()];
    const entry = Object.hasOwn(entries, name) ? entries[name] : null;
    if (this.family() === "archives") {
      WorkspaceView.status(
        "Lossless archive only; inspect/export without applying",
        true,
      );
      return;
    }
    if (!entry) {
      WorkspaceView.status("Choose a saved entry first", true);
      return;
    }
    await Features.edit("Apply " + this.family(), (data) =>
      this.applyEntry(data, entry),
    );
  },
  applyEntry(data, entry) {
    const family = this.family();
    const setters = {
      templates: () => {
        data.prompt = entry.body;
      },
      prompts: () => {
        data.prompt = entry.body;
        data.prompt_mode = entry.mode || "literal";
        data.variables = entry.variables || {};
      },
      variables: () => {
        data.variables = structuredClone(entry);
      },
      stacks: () => {
        data.workflow = structuredClone(entry.blocks);
      },
      blocks: () => {
        data.workflow.push(structuredClone(entry.block || entry));
      },
      connections: () => {
        data.connection = JSON.stringify(entry);
      },
      windows: () => {
        data.layout = structuredClone(entry.layout || entry);
      },
    };
    setters[family]();
  },
  async previewImport() {
    const text = document.getElementById("importJson").value;
    this.preview = null;
    document.getElementById("confirmImportBtn").disabled = true;
    if (await Features.command({ kind: "library_preview", text })) {
      this.preview = { text, sha256: Workspace.result.sha256 };
      document.getElementById("libraryPreview").textContent = JSON.stringify(
        Workspace.result,
        null,
        2,
      );
      document.getElementById("confirmImportBtn").disabled = false;
    }
  },
  async importReviewed() {
    if (
      !this.preview ||
      this.preview.text !== document.getElementById("importJson").value
    )
      return;
    if (await Features.command({ kind: "library_import", ...this.preview })) {
      this.preview = null;
      document.getElementById("confirmImportBtn").disabled = true;
    }
  },
  wire() {
    const actions = {
      capturePresetBtn: () => this.capture(),
      createPresetBtn: () => this.change("create"),
      updatePresetBtn: () => this.change("update"),
      applyPresetBtn: () => this.apply(),
      previewImportBtn: () => this.previewImport(),
      confirmImportBtn: () => this.importReviewed(),
      exportLibraryBtn: () => this.export(),
    };
    Object.entries(actions).forEach(([id, fn]) => {
      document.getElementById(id).onclick = fn;
    });
    document.getElementById("libraryFamily").onchange = () => this.render();
    document.getElementById("importJson").oninput = () => {
      this.preview = null;
      document.getElementById("confirmImportBtn").disabled = true;
    };
    document.getElementById("libraryFile").onchange = async (event) => {
      const file = event.target.files[0];
      if (!file || file.size > 1000000) {
        WorkspaceView.status("Choose JSON under 1 MB", true);
        return;
      }
      document.getElementById("importJson").value = await file.text();
      await this.previewImport();
    };
  },
  async export() {
    if (!(await Features.command({ kind: "library_export" }))) return;
    document.getElementById("importJson").value = Workspace.result;
    document.getElementById("libraryPreview").textContent =
      "Full portable backup above. Save to a new JSON file; it may contain private prompt/connection data.";
    Workspace.dialogs?.save_library_file?.(Workspace.result, (result) =>
      WorkspaceView.status(result),
    );
  },
};
