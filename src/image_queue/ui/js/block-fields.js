/* Reuse retained form row builders, with safe keys/text and a single global writer. */
"use strict";
const BlockFields = {
  render(block, index) {
    const form = document.getElementById("blockConfigFields");
    form.replaceChildren();
    Object.entries(block).forEach(([key, value]) => {
      const wrapper = document.createElement("div");
      const input = this.control(wrapper, key, value);
      input.setAttribute("aria-label", "Block parameter " + key);
      input.onchange = async () => {
        let edited;
        try {
          edited = this.value(input, value);
        } catch {
          WorkspaceView.status(
            "Invalid block parameter JSON; nothing saved",
            true,
          );
          return;
        }
        await Features.edit("Edit block parameter", (data) => {
          data.workflow[index][key] = edited;
        });
      };
      form.appendChild(wrapper);
    });
  },
  control(wrapper, key, value) {
    const safe = window.UIHelpers.esc(key),
      rows = StackDnDConfigRows;
    if (typeof value === "boolean") {
      wrapper.innerHTML = rows._checkboxRowHtml(safe, safe, value, "");
      return wrapper.querySelector("input");
    }
    if (typeof value === "number") {
      wrapper.innerHTML = rows._inputRowHtml(safe, safe, value, "", {});
      return wrapper.querySelector("input");
    }
    const text =
      typeof value === "string" ? value : JSON.stringify(value, null, 2);
    wrapper.innerHTML = rows._messageRowHtml.call(
      { _esc: window.UIHelpers.esc },
      safe,
      text,
      {},
      "",
    );
    const input = wrapper.querySelector("textarea");
    input.dataset.key = key;
    return input;
  },
  value(input, previous) {
    if (typeof previous === "boolean") return input.checked;
    if (typeof previous === "number") return Number(input.value);
    if (typeof previous === "string") return input.value;
    return JSON.parse(input.value);
  },
};
