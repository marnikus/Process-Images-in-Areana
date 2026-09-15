/* Pure-ish view adapter. Never owns history; renders only acknowledged snapshots. */
"use strict";
const WorkspaceView = {
  apply(state) {
    const data = state.workspace,
      layout = data.layout;
    SashGrid.root = structuredClone(layout.tree);
    SashGrid.closedWindows = new Set(layout.closed);
    SashGrid.minimizedWindows = new Set(layout.minimized);
    Object.values(SashGrid.winEls).forEach((panel) => {
      panel.classList.remove("hidden");
      panel.style.display = "";
    });
    SashGrid.render();
    const connection = JSON.parse(data.connection);
    const values = {
      prompt: data.prompt,
      folder: data.folder,
      urls: connection.urls.map((row) => row.exact_url).join("\n"),
      chromeHost: connection.endpoint.host,
      chromePort: connection.endpoint.port,
      highlightMs: connection.highlight.highlight_ms,
      confirmMs: connection.highlight.confirm_pause_ms,
    };
    Object.entries(values).forEach(([id, value]) => {
      document.getElementById(id).value = value;
    });
    document.getElementById("highlightEnabled").checked =
      connection.highlight.highlight_enabled;
    this.history(state);
    this.layouts(data.layouts);
    Features.apply(state);
  },
  history(state) {
    const undo = state.history[state.cursor],
      redo = state.history[state.cursor + 1];
    for (const [kind, entry, arrow] of [
      ["undo", undo, "↶"],
      ["redo", redo, "↷"],
    ]) {
      const button = document.getElementById(kind + "Btn");
      button.disabled = !entry;
      button.textContent = `${arrow} ${kind === "undo" ? "Undo" : "Redo"}${entry ? ": " + entry.label : ""}`;
    }
    document.getElementById("revisionLabel").textContent =
      `Revision ${state.revision} · ${state.cursor + 1}/${state.history.length} edits`;
  },
  layouts(layouts) {
    const list = document.getElementById("namedLayouts");
    list.replaceChildren();
    for (const name of Object.keys(layouts)) {
      const row = document.createElement("div");
      row.className = "input-row";
      for (const [text, action] of [
        [name, () => Workspace.applyLayout(name)],
        ["Delete", () => Workspace.deleteLayout(name)],
      ]) {
        const button = document.createElement("button");
        button.textContent = text;
        button.onclick = action;
        row.appendChild(button);
      }
      list.appendChild(row);
    }
  },
  capture(state) {
    const data = structuredClone(state.workspace),
      connection = JSON.parse(data.connection);
    data.layout = { tree: SashGrid.getTree(), ...SashGrid.getWindowStates() };
    const promptValue = document.getElementById("prompt").value;
    if (promptValue !== data.prompt.replace(/\r\n?/g, "\n"))
      data.prompt = promptValue;
    data.folder = document.getElementById("folder").value;
    const text = document.getElementById("urls").value;
    const lines = text === "" ? [] : text.split("\n");
    connection.urls = lines.map((url, index) => {
      const old = connection.urls[index];
      return {
        row_id: old?.row_id || crypto.randomUUID(),
        exact_url: url,
        enabled: old?.enabled ?? true,
      };
    });
    connection.endpoint = {
      host: document.getElementById("chromeHost").value,
      port: Number(document.getElementById("chromePort").value),
    };
    connection.highlight = {
      highlight_enabled: document.getElementById("highlightEnabled").checked,
      highlight_ms: Number(document.getElementById("highlightMs").value),
      confirm_pause_ms: Number(document.getElementById("confirmMs").value),
    };
    data.connection = JSON.stringify(connection);
    Features.capture(data);
    return data;
  },
  status(message, error = false) {
    const element = document.getElementById("saveStatus");
    element.textContent = message;
    element.classList.toggle("error", error);
  },
};
