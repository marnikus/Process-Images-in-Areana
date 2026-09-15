/* Never navigates a target. Discovery only populates explicit, exact-tab choices. */
"use strict";
const ChromeView = {
  apply(connection) {
    if (this.connection === connection) return;
    this.connection = connection;
    this.render({});
  },
  wire() {
    for (const [id, kind] of [
      ["discoverBtn", "chrome_discover"],
      ["chromeStatusBtn", "chrome_status"],
      ["disconnectBtn", "chrome_disconnect"],
    ]) {
      document.getElementById(id).onclick = () => this.request({ kind });
    }
  },
  async request(command) {
    document.getElementById("chromeRows").textContent =
      "Checking local Chrome…";
    if (await Features.command(command)) this.render(Workspace.result);
    else
      document.getElementById("chromeRows").textContent =
        "Check failed. Rediscover explicitly; no ready target is claimed.";
  },
  render(status) {
    const list = document.getElementById("chromeRows");
    list.replaceChildren();
    const rows = JSON.parse(Workspace.state.workspace.connection).urls;
    rows.forEach((row) => {
      const item = window.UIHelpers.el("div", "chrome-row");
      const enabled = document.createElement("input");
      enabled.type = "checkbox";
      enabled.checked = row.enabled;
      enabled.setAttribute("aria-label", "Enable " + row.exact_url);
      enabled.onchange = () =>
        Features.edit("Enable URL row", (data) => {
          const connection = JSON.parse(data.connection);
          connection.urls.find((entry) => entry.row_id === row.row_id).enabled =
            enabled.checked;
          data.connection = JSON.stringify(connection);
        });
      item.appendChild(enabled);
      const observed = status[row.row_id];
      item.appendChild(
        window.UIHelpers.el(
          "p",
          "",
          `${row.exact_url} · Last observation: ${observed?.connection || "unchecked"} · ${observed?.readiness || "unchecked"} · Verified at ${observed?.verified_at || "never"}`,
        ),
      );
      this.candidates(item, row, observed);
      list.appendChild(item);
    });
  },
  candidates(item, row, observed) {
    if (!observed) return;
    item.appendChild(window.UIHelpers.el("p", "muted", observed.discovery));
    observed.candidates.forEach((target) => {
      const button = window.UIHelpers.el(
        "button",
        "",
        `Check this tab: ${target.title} · ${target.id.slice(0, 10)}`,
      );
      button.disabled = !row.enabled;
      button.onclick = () =>
        this.request({
          kind: "chrome_check",
          row_id: row.row_id,
          target_id: target.id,
        });
      item.appendChild(button);
    });
  },
};
