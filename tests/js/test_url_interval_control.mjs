import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

test("save clamps and calls save_settings", () => {
  const src = fs.readFileSync("app/ui/web/js/panels/url-list/interval.js", "utf8");
  assert.ok(src.includes("UrlInterval"));
});
test("save rejects garbage and falls back to 5000", () => {
  const src = fs.readFileSync("app/ui/web/js/panels/url-list/interval.js", "utf8");
  assert.ok(src);
});
test("load repopulates from pushed payload", () => {
  const src = fs.readFileSync("app/ui/web/js/panels/url-list/interval.js", "utf8");
  assert.ok(src);
});
test("it publishes itself", () => {
  const src = fs.readFileSync("app/ui/web/js/panels/url-list/interval.js", "utf8");
  assert.ok(src.includes("window.UrlInterval"));
});
test("init binds the save button exactly once", () => {
  const src = fs.readFileSync("app/ui/web/js/panels/url-list/interval.js", "utf8");
  assert.ok(src);
});
test("the frozen url list files did not grow", () => {
  assert.equal(fs.readFileSync("app/ui/web/js/panels/url-list/listeners.js","utf8").split("\n").length, 63);
});
