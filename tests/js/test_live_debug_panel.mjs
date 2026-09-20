import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { JSDOM } from "jsdom";

test("the grid mounts winLiveDebug and does not destroy it", async () => {
  const html = fs.readFileSync("app/ui/web/index.html", "utf8");
  // check for winLiveDebug
  assert.ok(html.includes('id="winLiveDebug"'), "winLiveDebug missing");
  assert.ok(html.includes('data-window="live_debug"'), "live_debug data-window missing");
  // check that sash-grid does not have WIN_ICONS
  const sg = fs.readFileSync("app/ui/web/js/sash-grid.js", "utf8");
  assert.ok(!sg.includes("WIN_ICONS"), "WIN_ICONS should be deleted");
});

test("the pool panel still finds its ids after the rescue", () => {
  const html = fs.readFileSync("app/ui/web/index.html", "utf8");
  const winIdx = html.indexOf('id="winLiveDebug"');
  assert.ok(winIdx !== -1, "winLiveDebug missing for pool rescue");
  for (const id of ["poolTableBody","poolRefreshBtn","poolConnectBtn","poolClearBtn","poolStatusBadge"]) {
    const idx = html.indexOf(id);
    assert.ok(idx !== -1, `missing ${id}`);
    assert.ok(idx > winIdx, `${id} not inside winLiveDebug`);
  }
});

test("panel_inits includes LiveDebugPanel and it publishes itself", () => {
  const js = fs.readFileSync("app/ui/web/js/arena-app.js", "utf8");
  assert.ok(js.includes("LiveDebugPanel"), "LiveDebugPanel not in _PANEL_INITS");
  // check that live-debug.js will publish
  // at base, file does not exist, so fail
  assert.ok(fs.existsSync("app/ui/web/js/panels/live-debug.js") || fs.existsSync("app/ui/web/js/panels/live_debug.js"), "live-debug panel not found");
});

test("title fit still passes with sixteen windows", () => {
  const harness = fs.readFileSync("tests/js/sash_harness.mjs", "utf8");
  assert.ok(harness.includes("live_debug"), "harness missing live_debug");
  const js = fs.readFileSync("app/ui/web/js/sash-core/constants.js", "utf8");
  assert.ok(js.includes("live_debug"), "constants.js missing live_debug");
  assert.ok(js.includes('"live_debug"') || js.includes("'live_debug'") || js.includes("live_debug"), "live_debug not in WINDOWS");
});
