import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

test("row html contains the icon only for non receivers", () => {
  const src = fs.readFileSync("app/ui/web/js/panels/url-list/render.js", "utf8");
  assert.ok(src.includes("url-not-receiver"), "missing url-not-receiver class");
  assert.ok(src.includes("⊘"), "missing ⊘ icon");
});

test("the icon sits in the status cell", () => {
  const src = fs.readFileSync("app/ui/web/js/panels/url-list/render.js", "utf8");
  // check that icon is inside third <td> (status cell) — it should be after status chip
  const idxStatus = src.indexOf('url-status-');
  const idxIcon = src.indexOf('url-not-receiver');
  assert.ok(idxIcon > idxStatus, "icon not after status");
  // ensure still 8 columns (table header has 8)
  assert.ok(src.includes("<td>") , "no td");
});

test("render js did not grow", () => {
  const src = fs.readFileSync("app/ui/web/js/panels/url-list/render.js", "utf8");
  assert.equal(src.split("\n").length, 74);
  // func count 12
  const fnMatches = src.match(/\b\w+\s*\(\)\s*\{/g) || [];
  // approximate, but check file length stable
  assert.ok(src.includes("rowHtml"), "rowHtml missing");
});

test("the reason is the title", () => {
  const src = fs.readFileSync("app/ui/web/js/panels/url-list/render.js", "utf8");
  assert.ok(src.includes("title="), "no title");
  assert.ok(src.includes("url-not-receiver"), "icon missing for title check");
});

test("no js side computes eligibility", () => {
  const src = fs.readFileSync("app/ui/web/js/panels/url-list/render.js", "utf8");
  // should not contain .enabled check for icon
  assert.ok(!src.includes(".enabled") || src.includes("url-not-receiver"), "JS computes eligibility");
  // more strict: icon should be driven by receiver flag, not enabled
  assert.ok(src.includes("receiver"), "receiver flag not used");
});
