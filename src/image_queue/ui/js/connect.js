"use strict";
if (typeof qt === "undefined" || typeof QWebChannel === "undefined") {
  document.getElementById("connectionNotice").textContent =
    "Desktop bridge unavailable. Open with “image-queue desktop”; this standalone page cannot save or connect to Chrome.";
  WorkspaceView.status("Not connected to local persistence", true);
} else {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    const bridge = channel.objects.workspaceBridge;
    bridge.read((raw) => {
      const response = JSON.parse(raw);
      if (response.ok) {
        Workspace.dialogs = channel.objects.dialogBridge;
        Workspace.initialize(bridge, response.state);
        bridge.ready();
      } else {
        WorkspaceView.status(response.error, true);
      }
    });
  });
}
