/* The retained grid registers its initializer; the authoritative state loads first. */
"use strict";
window.GridInitializers = [];
window.BridgeReady = { ready: (fn) => GridInitializers.push(fn) };
window.App = { bridge: null };
window.LogConsole = {
  log(message) {
    const log = document.getElementById("activity");
    if (log) log.textContent = String(message);
  },
};
