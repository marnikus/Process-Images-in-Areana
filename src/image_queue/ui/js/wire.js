/* Bounded Qt callback boundary. Lost acknowledgements lock editing, never replay a write. */
"use strict";
const WorkspaceWire = {
  invoke(bridge, request, timeout = 15000) {
    return new Promise((resolve) => {
      const requestId = crypto.randomUUID();
      const failed = {
        ok: false,
        faulted: true,
        error:
          "Persistence acknowledgement unavailable. Reopen to inspect saved state.",
      };
      let complete = false;
      const finish = (response) => {
        if (complete) return;
        complete = true;
        clearTimeout(timer);
        try {
          bridge.completed.disconnect(receive);
        } catch {
          /* channel may be gone */
        }
        resolve(response);
      };
      const receive = (id, raw) => {
        if (id !== requestId) return;
        try {
          const response = JSON.parse(raw);
          const valid =
            response &&
            typeof response.ok === "boolean" &&
            (!response.ok ||
              (response.state && Number.isInteger(response.state.revision)));
          finish(valid ? response : failed);
        } catch {
          finish(failed);
        }
      };
      const timer = setTimeout(() => finish(failed), timeout);
      try {
        bridge.completed.connect(receive);
        bridge.command(requestId, JSON.stringify(request));
      } catch {
        finish(failed);
      }
    });
  },
};
