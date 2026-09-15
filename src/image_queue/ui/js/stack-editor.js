/* Actual retained StackDrag with global undo; imported scripts/selectors are inert data. */
"use strict";
const StackEditor = {
  selected: null,
  wire() {
    document.getElementById("addBlockBtn").onclick = () =>
      Features.edit("Add block", (data) =>
        data.workflow.push({ block_id: "UNCONFIGURED", enabled: false }),
      );
    document.getElementById("saveBlockBtn").onclick = () => {
      const block = Features.parse("blockJson"),
        index = this.selected;
      if (block === undefined || this.selected === null) return;
      Features.edit("Edit block parameters", (data) => {
        data.workflow[index] = block;
      });
    };
    StackDrag.attach({
      container: document.getElementById("workflowBlocks"),
      itemSelector: ".workflow-block",
      handleSelector: ".block-grip",
      onReorder: (from, to) => this.reorder(from, to),
    });
  },
  reorder(from, to) {
    return Features.edit("Reorder workflow blocks", (data) => {
      const [block] = data.workflow.splice(from, 1);
      data.workflow.splice(to, 0, block);
    });
  },
  render(blocks) {
    const serialized = JSON.stringify(blocks);
    if (this.rendered === serialized) return;
    const selected = this.retainedSelection(blocks);
    this.rendered = serialized;
    const container = document.getElementById("workflowBlocks");
    container.replaceChildren();
    blocks.forEach((block, index) => {
      const row = window.UIHelpers.el("div", "workflow-block");
      row.dataset.idx = index;
      row.appendChild(window.UIHelpers.el("span", "block-grip", "⠿"));
      const label = window.UIHelpers.el(
        "button",
        "",
        block.custom_name || block.block_id || "Unconfigured block",
      );
      label.onclick = () => this.select(index);
      const remove = window.UIHelpers.el("button", "", "Delete");
      remove.onclick = () =>
        Features.edit("Delete block", (data) => data.workflow.splice(index, 1));
      row.append(label, remove);
      container.appendChild(row);
    });
    this.selected = null;
    document.getElementById("blockConfigFields").replaceChildren();
    document.getElementById("blockJson").value = "";
    if (selected !== null) this.select(selected);
  },
  retainedSelection(blocks) {
    if (this.selected === null) return null;
    const old = JSON.parse(this.rendered || "[]");
    if (old.length !== blocks.length) return null;
    const others = (items) =>
      JSON.stringify(items.filter((_, index) => index !== this.selected));
    return others(old) === others(blocks) ? this.selected : null;
  },
  select(index) {
    this.selected = index;
    const block = Workspace.state.workspace.workflow[index];
    BlockFields.render(block, index);
    document.getElementById("blockJson").value = JSON.stringify(block, null, 2);
  },
};
