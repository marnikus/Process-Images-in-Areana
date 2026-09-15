/* Controls share one durable command queue; only explicit user actions scan/connect. */
"use strict";
const Features = {
  async command(command) {
    if (!(await Workspace.flush())) return false;
    return Workspace.send(command);
  },
  async edit(label, change) {
    if (!(await Workspace.flush())) return false;
    const data = structuredClone(Workspace.state.workspace);
    change(data);
    return Workspace.send({ kind: "edit", workspace: data, label });
  },
  parse(id) {
    try {
      return JSON.parse(document.getElementById(id).value);
    } catch {
      WorkspaceView.status("Invalid JSON; nothing saved", true);
      return undefined;
    }
  },
  wire() {
    Libraries.wire();
    StackEditor.wire();
    QueueView.wire();
    ChromeView.wire();
    document.getElementById("promptPreviewBtn").onclick = async () => {
      if (await this.command({ kind: "prompt_preview" })) {
        const result = Workspace.result;
        document.getElementById("promptPreview").textContent =
          result.text +
          (result.ok
            ? ""
            : "\nUNRESOLVED: " +
              [...result.unknown, ...result.malformed].join(", "));
      }
    };
  },
  apply(state) {
    const data = state.workspace;
    document.getElementById("variablesJson").value = JSON.stringify(
      data.variables,
      null,
      2,
    );
    document.getElementById("promptMode").value = data.prompt_mode;
    document.getElementById("scanRecursive").checked =
      data.scan_options.recursive;
    document.getElementById("scanMax").value = data.scan_options.max_bytes;
    document.getElementById("outputFolder").value =
      data.scan_options.output_folder;
    ChromeView.apply(data.connection);
    Libraries.render();
    StackEditor.render(data.workflow);
    QueueView.render(state);
  },
  capture(data) {
    data.variables = JSON.parse(document.getElementById("variablesJson").value);
    data.prompt_mode = document.getElementById("promptMode").value;
    data.scan_options = {
      recursive: document.getElementById("scanRecursive").checked,
      max_bytes: Number(document.getElementById("scanMax").value),
      output_folder: document.getElementById("outputFolder").value,
    };
  },
};
