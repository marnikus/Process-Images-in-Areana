"use strict";
const QueueView = {
  sources: {},
  wire() {
    document.getElementById("scanBtn").onclick = () =>
      Features.command({ kind: "scan" });
    for (const [id, decision] of [
      ["selectAllBtn", "selected"],
      ["skipAllBtn", "skipped"],
      ["reviewAllBtn", "review"],
    ]) {
      document.getElementById(id).onclick = () => {
        const ids = Object.keys(this.sources).filter((id) =>
          ["available", "changed"].includes(this.sources[id].status),
        );
        return Features.command({ kind: "select", ids, decision });
      };
    }
  },
  render(state) {
    this.sources = state.jobs.sources || {};
    const list = document.getElementById("imageRows");
    list.replaceChildren();
    let selected = 0,
      changed = 0;
    Object.entries(this.sources).forEach(([id, source]) => {
      const choice = state.workspace.selection[id];
      const current = choice?.sha256 === source.sha256 && !!source.sha256;
      const valid = ["available", "changed"].includes(source.status);
      const checked = current && choice.decision === "selected" && valid;
      selected += checked ? 1 : 0;
      changed += source.status !== "available" ? 1 : 0;
      this.row(
        list,
        { id, source, checked, valid },
        current ? choice.decision : "needs review",
      );
    });
    document.getElementById("queueSummary").textContent =
      `${Object.keys(this.sources).length} sources · ${selected} selected · 0 submitted`;
    document.getElementById("scanChanges").textContent =
      `${changed} changed, missing or invalid records. Rescan after restart before processing. No completion is inferred from a file name.`;
  },
  row(list, item, decision) {
    const { id, source, checked, valid } = item;
    const row = window.UIHelpers.el("div", "image-row");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = checked;
    checkbox.disabled = !valid;
    checkbox.setAttribute("aria-label", "Select " + source.relative);
    checkbox.onchange = () =>
      Features.command({
        kind: "select",
        ids: [id],
        decision: checkbox.checked ? "selected" : "skipped",
      });
    row.appendChild(checkbox);
    if (source.thumbnail) {
      const image = document.createElement("img");
      image.src = source.thumbnail;
      image.alt = "";
      image.width = 64;
      row.appendChild(image);
    }
    row.appendChild(
      window.UIHelpers.el(
        "span",
        "",
        `${source.relative} · ${source.status} · ${decision}`,
      ),
    );
    list.appendChild(row);
  },
};
