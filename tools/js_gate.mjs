#!/usr/bin/env node
// RULE 16 JS gate (design.md D6) — acorn-based size/complexity checks for
// production JS under app/ui/web/js/**.
//
// Fail: function >30 LOC, >4 params, nesting >4, rough CC >10
// Warn: file >300 lines
// Grandfathering (baseline v2 "js" section, per-symbol):
//   changed file, symbol in baseline, regressed on any metric  -> FAIL
//   changed file, symbol in baseline, within baseline but over -> WARN
//   changed file, symbol new-to-baseline over a hard limit     -> FAIL
//
// Usage:
//   node tools/js_gate.mjs --root DIR --changed f1.js f2.js [more]   # push gate
//   node tools/js_gate.mjs --root DIR --all                          # full audit
//   node tools/js_gate.mjs --root DIR --emit-baseline                # baseline JSON to stdout
//   node tools/js_gate.mjs --root DIR --json                         # machine-readable
//
// Exit 1 on any fail.

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import * as acorn from "acorn";
import * as walk from "acorn-walk";

const LIMITS = { loc: 30, params: 4, nesting: 4, cc: 10 };
const FILE_WARN_LINES = 300;

function parseArgs(argv) {
  const args = { root: null, changed: null, all: false, baseline: null, json: false, emitBaseline: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--root") args.root = argv[++i];
    else if (a === "--changed") {
      args.changed = [];
      while (i + 1 < argv.length && !argv[i + 1].startsWith("--")) args.changed.push(argv[++i]);
    } else if (a === "--all") args.all = true;
    else if (a === "--baseline") args.baseline = argv[++i];
    else if (a === "--json") args.json = true;
    else if (a === "--emit-baseline") args.emitBaseline = true;
  }
  if (!args.root) { console.error("--root required"); process.exit(2); }
  return args;
}

function readdirSorted(d) { try { return readdirSync(d).sort(); } catch { return []; } }
function statSafe(p) { try { return statSync(p); } catch { return null; } }

function jsFiles(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSorted(dir)) {
    const p = join(dir, entry);
    const st = statSafe(p);
    if (!st) continue;
    if (st.isDirectory()) {
      if (entry === "node_modules" || entry === "__pycache__") continue;
      jsFiles(p, out);
    } else if (entry.endsWith(".js")) {
      out.push(p);
    }
  }
  return out;
}

const BRANCH_NODES = new Set(["IfStatement", "ForStatement", "ForInStatement", "ForOfStatement",
  "WhileStatement", "DoWhileStatement", "WithStatement", "TryStatement", "CatchClause", "SwitchStatement"]);

function childNodesOf(n) {
  const kids = [];
  for (const key of Object.keys(n)) {
    if (key === "type" || key === "start" || key === "end" || key === "loc" || key === "range") continue;
    const v = n[key];
    if (Array.isArray(v)) v.forEach((c) => { if (c && typeof c === "object" && c.type) kids.push(c); });
    else if (v && typeof v === "object" && v.type) kids.push(v);
  }
  return kids;
}

function funcMetrics(node) {
  const loc = node.loc.end.line - node.loc.start.line + 1; // source lines
  const params = node.params.length;
  let maxNest = 0;
  (function rec(n, depth) {
    let d = depth;
    if (BRANCH_NODES.has(n.type)) d = depth + 1;
    maxNest = Math.max(maxNest, d);
    for (const c of childNodesOf(n)) rec(c, d);
  })(node, 0);
  let cc = 1;
  walk.full(node, (n) => {
    if (BRANCH_NODES.has(n.type)) cc += 1;
    else if (n.type === "LogicalExpression") cc += 1;
    else if (n.type === "ConditionalExpression") cc += 1;
    else if (n.type === "CaseClause") cc += 1;
  });
  return { loc, params, nesting: maxNest, cc };
}

function collectFunctions(tree, out) {
  const seen = new Map();
  const add = (name, node) => {
    let key = name || "anonymous";
    if (seen.has(key)) {
      seen.get(key) += 1;
      key = `${name}#${seen.get(key)}`;
    } else {
      seen.set(key, 1);
    }
    out.push({ name: key, metrics: funcMetrics(node),
               startLine: node.loc.start.line, endLine: node.loc.end.line });
  };
  walk.full(tree, (node, key, parent) => {
    if (node.type === "FunctionDeclaration") add(node.id?.name, node);
    else if (node.type === "ObjectMethod") add(node.key?.name || node.key?.value, node);
    else if (node.type === "FunctionExpression" || node.type === "ArrowFunctionExpression") {
      let name = null;
      if (parent?.type === "VariableDeclarator" && parent.id?.type === "Identifier" && key === "init") name = parent.id.name;
      else if (parent?.type === "AssignmentExpression" && parent.left?.type === "Identifier" && key === "right") name = parent.left.name;
      else if (parent?.type === "Property" && key === "value" && parent.key?.type === "Identifier") name = parent.key.name;
      if (name) add(name, node);
    }
  });
  return out;
}

function analyzeJsFile(path, root) {
  const source = readFileSync(path, "utf-8");
  const tree = acorn.parse(source, { ecmaVersion: "latest", sourceType: "module", locations: true });
  return {
    rel: relative(root, path).split("\\").join("/"),
    fileLines: source.split("\n").length,
    functions: collectFunctions(tree, []),
  };
}

function checkFile(info, baseEntry) {
  const fails = [];
  const warns = [];
  const baseFns = (baseEntry && baseEntry.functions) || {};
  for (const fn of info.functions) {
    const base = baseFns[fn.name] || null;
    for (const metric of Object.keys(LIMITS)) {
      const cur = fn.metrics[metric];
      if (base === null) {
        if (cur > LIMITS[metric]) fails.push({ file: info.rel, name: fn.name, metric, value: cur, limit: LIMITS[metric], message: `JS function ${fn.name} NEW ${metric} ${cur} > ${LIMITS[metric]}` });
      } else if (cur > base[metric]) {
        fails.push({ file: info.rel, name: fn.name, metric, value: cur, limit: base[metric], message: `JS function ${fn.name} ${metric} regressed ${base[metric]} -> ${cur} (baseline ratchet)` });
      } else if (cur > LIMITS[metric]) {
        warns.push({ file: info.rel, name: fn.name, metric, value: cur, limit: LIMITS[metric], message: `[LEGACY] JS function ${fn.name} ${metric} ${cur} > ${LIMITS[metric]} (within baseline ${base[metric]})` });
      }
    }
  }
  if (info.fileLines > FILE_WARN_LINES) warns.push({ file: info.rel, metric: "file-lines", value: info.fileLines, limit: FILE_WARN_LINES, message: `JS file ${info.fileLines} lines > ${FILE_WARN_LINES} (warn)` });
  return { fails, warns };
}

function main() {
  const args = parseArgs(process.argv);
  const root = args.root.replace(/\/+$/, "");
  const jsRoot = join(root, "app", "ui", "web", "js");
  const allFiles = jsFiles(jsRoot);

  if (args.emitBaseline) {
    const js = {};
    for (const f of allFiles) {
      try {
        const info = analyzeJsFile(f, root);
        js[info.rel] = { fileLines: info.fileLines,
          functions: Object.fromEntries(info.functions.map((x) => [x.name, x.metrics])) };
      } catch (e) {
        console.error(`warning: skipping ${f}: ${e.message}`);
      }
    }
    process.stdout.write(JSON.stringify({ js }, null, 1) + "\n");
    return;
  }

  let files = allFiles;
  if (args.changed) {
    files = allFiles.filter((f) => args.changed.includes(relative(root, f).split("\\").join("/")));
  } else if (!args.all) {
    console.error("need --changed <files> or --all");
    process.exit(2);
  }

  const baselinePath = args.baseline ? join(root, args.baseline) : join(root, "tools", "quality_baseline.json");
  let baseline = {};
  if (existsSync(baselinePath)) {
    try { baseline = JSON.parse(readFileSync(baselinePath, "utf-8")); } catch { baseline = {}; }
  }
  const jsBase = baseline.js || {};

  const fails = [];
  const warns = [];
  let parsed = 0;
  for (const f of files) {
    let info;
    try { info = analyzeJsFile(f, root); parsed++; }
    catch (e) { fails.push({ file: relative(root, f), metric: "parse", message: `JS parse error: ${e.message}` }); continue; }
    const r = checkFile(info, jsBase[info.rel] || null);
    fails.push(...r.fails); warns.push(...r.warns);
  }

  if (args.json) {
    process.stdout.write(JSON.stringify({ filesChecked: parsed, fails, warns }, null, 1) + "\n");
  } else {
    console.log(`Checked ${parsed} JS files`);
    console.log(`Found ${fails.length} fail(s), ${warns.length} warn(s)`);
    if (fails.length) {
      console.log("\n=== FAILS (must fix before push) ===");
      for (const b of fails) console.log(`${b.file} [${b.metric}] ${b.message}`);
    }
    if (warns.length) {
      console.log("\n=== WARNS (should fix, not blocking) ===");
      for (const b of warns) console.log(`${b.file} [${b.metric}] ${b.message}`);
    }
    if (!fails.length) console.log("\n✅ JS gate PASSED — no fails");
  }
  process.exit(fails.length ? 1 : 0);
}

main();
