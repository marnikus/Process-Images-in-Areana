#!/usr/bin/env node
/**
 * R0.2 — JS metrics via acorn, same fail lines as Python
 * Usage: node tools/js_metrics.js app/ui/web [--json]
 * Outputs JSON array of {file, line, name, loc, params, depth, cc}
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..');

let acorn, walk;
try {
  acorn = await import('acorn');
  walk = await import('acorn-walk');
} catch (e) {
  console.error(JSON.stringify({error: 'acorn not installed, run npm ci', details: String(e)}));
  process.exit(0);
}

const targetDir = process.argv[2] ? path.resolve(process.argv[2]) : path.resolve(ROOT, 'app/ui/web');
const jsonOut = process.argv.includes('--json');

function collectJsFiles(dir) {
  const res = [];
  function walkDir(d) {
    const entries = fs.readdirSync(d, { withFileTypes: true });
    for (const ent of entries) {
      const p = path.join(d, ent.name);
      if (ent.isDirectory()) walkDir(p);
      else if (ent.isFile() && p.endsWith('.js')) res.push(p);
    }
  }
  walkDir(dir);
  return res;
}

function computeNesting(node, depth = 0, max = 0) {
  const inc = ['IfStatement', 'ForStatement', 'ForInStatement', 'ForOfStatement', 'WhileStatement', 'DoWhileStatement', 'WithStatement', 'SwitchStatement'].includes(node.type) ? 1 : 0;
  const nd = depth + inc;
  max = Math.max(max, nd);
  for (const key in node) {
    const child = node[key];
    if (Array.isArray(child)) {
      for (const c of child) {
        if (c && typeof c.type === 'string') {
          max = computeNesting(c, nd, max);
        }
      }
    } else if (child && typeof child.type === 'string') {
      max = computeNesting(child, nd, max);
    }
  }
  return max;
}

function computeCC(node) {
  let cc = 1;
  function visit(n) {
    if (!n || typeof n.type !== 'string') return;
    if (['IfStatement', 'ForStatement', 'ForInStatement', 'ForOfStatement', 'WhileStatement', 'DoWhileStatement', 'CatchClause', 'ConditionalExpression'].includes(n.type)) cc += 1;
    if (n.type === 'LogicalExpression' && (n.operator === '&&' || n.operator === '||')) cc += 1;
    if (n.type === 'SwitchCase' && n.test) cc += 1;
    for (const k in n) {
      const ch = n[k];
      if (Array.isArray(ch)) ch.forEach(visit);
      else if (ch && typeof ch.type === 'string') visit(ch);
    }
  }
  visit(node);
  return cc;
}

function getFuncName(node, parent) {
  if (node.id && node.id.name) return node.id.name;
  if (parent && parent.type === 'VariableDeclarator' && parent.id && parent.id.name) return parent.id.name;
  if (parent && parent.type === 'Property' && parent.key) return parent.key.name || parent.key.value || 'anon';
  if (parent && parent.type === 'AssignmentExpression' && parent.left) return parent.left.property?.name || parent.left.name || 'anon';
  return 'anon';
}

const files = collectJsFiles(targetDir);
const results = [];

for (const file of files) {
  let code;
  try {
    code = fs.readFileSync(file, 'utf8');
  } catch {
    continue;
  }
  let ast;
  try {
    ast = acorn.parse(code, { ecmaVersion: 'latest', sourceType: 'module', locations: true });
  } catch (e) {
    results.push({ file: path.relative(ROOT, file), error: String(e.message || e), line: e.loc?.line || 0 });
    continue;
  }
  const fileLines = code.split('\n').length;
  // file-level entry
  results.push({ file: path.relative(ROOT, file), fileLines, isFile: true });

  try {
    walk.ancestor(ast, {
      FunctionDeclaration(node, ancestors) {
        const parent = ancestors[ancestors.length - 2];
        const name = getFuncName(node, parent);
        const loc = (node.loc.end.line - node.loc.start.line + 1);
        const params = node.params ? node.params.length : 0;
        const depth = computeNesting(node);
        const cc = computeCC(node);
        results.push({ file: path.relative(ROOT, file), line: node.loc.start.line, name, loc, params, depth, cc });
      },
      FunctionExpression(node, ancestors) {
        const parent = ancestors[ancestors.length - 2];
        const name = getFuncName(node, parent);
        const loc = (node.loc.end.line - node.loc.start.line + 1);
        const params = node.params ? node.params.length : 0;
        const depth = computeNesting(node);
        const cc = computeCC(node);
        results.push({ file: path.relative(ROOT, file), line: node.loc.start.line, name, loc, params, depth, cc });
      },
      ArrowFunctionExpression(node, ancestors) {
        // Only count if body is block (not concise)
        if (node.body && node.body.type === 'BlockStatement') {
          const parent = ancestors[ancestors.length - 2];
          const name = getFuncName(node, parent);
          const loc = (node.loc.end.line - node.loc.start.line + 1);
          const params = node.params ? node.params.length : 0;
          const depth = computeNesting(node);
          const cc = computeCC(node);
          results.push({ file: path.relative(ROOT, file), line: node.loc.start.line, name, loc, params, depth, cc });
        }
      }
    });
  } catch (e) {
    results.push({ file: path.relative(ROOT, file), error: 'walk failed: ' + String(e), line: 0 });
  }
}

if (jsonOut) {
  console.log(JSON.stringify(results, null, 2));
} else {
  // human readable summary
  const funcs = results.filter(r => !r.isFile && !r.error);
  const filesOver300 = results.filter(r => r.isFile && r.fileLines > 300);
  console.log(`JS files ${results.filter(r => r.isFile).length} funcs ${funcs.length}`);
  console.log(`>30 LOC ${funcs.filter(r => r.loc > 30).length} nesting>4 ${funcs.filter(r => r.depth > 4).length} CC>10 ${funcs.filter(r => r.cc > 10).length} params>4 ${funcs.filter(r => r.params > 4).length}`);
  console.log(`files>300 ${filesOver300.length}`);
  const worst = funcs.filter(r => r.loc > 30).sort((a, b) => b.loc - a.loc).slice(0, 15);
  for (const r of worst) {
    console.log(`${String(r.loc).padStart(4)} loc cc=${String(r.cc).padStart(3)} depth=${String(r.depth).padStart(2)} ${r.file}:${r.line} ${r.name}`);
  }
  // output json to temp for gate
  const outPath = path.join(ROOT, '/tmp/js_metrics.json');
  try { fs.writeFileSync(outPath, JSON.stringify(results, null, 2)); } catch {}
}
