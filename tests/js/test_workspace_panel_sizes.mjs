/**
 * RULE 18.2 — the Workspace window's own files stay inside the 150–300 line
 * ideal, and the mount is the only file that knows how the pieces are wired
 * together. One panel = one responsibility per file (audit #3 L9).
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { WEB } from './page_harness.mjs';

const PANEL_DIR = path.join(WEB, 'js', 'panels');

describe('workspace panel file sizes (RULE 18.2)', () => {
  const files = ['workspace.js', 'workspace/bridge.js', 'workspace/render.js',
    'workspace/flow.js'];

  test('every workspace file exists and is inside 150-300 lines', () => {
    for (const rel of files) {
      const full = path.join(PANEL_DIR, rel);
      assert.ok(fs.existsSync(full), `${rel} is missing — the panel is split by responsibility`);
      const lines = fs.readFileSync(full, 'utf8').split('\n').length;
      assert.ok(lines <= 300, `${rel} is ${lines} lines — over the RULE 18.2 ideal (150-300)`);
      assert.ok(lines >= 40, `${rel} is ${lines} lines — a slice this small should be merged`);
    }
  });

  test('the mount file wires the pieces and publishes the panel', () => {
    const mount = fs.readFileSync(path.join(PANEL_DIR, 'workspace.js'), 'utf8');
    assert.ok(mount.includes('window.WorkspacePanel = '), 'published on window (RULE 8 web corollary)');
    assert.ok(mount.includes('function wsInit'), 'the mount owns init');
    assert.ok(!mount.includes('function wsRenderPreview'), 'rendering lives in render.js');
    assert.ok(!mount.includes('function wsRunRestore'), 'the flow lives in flow.js');
  });

  test('each slice keeps its own responsibility header', () => {
    for (const rel of files) {
      const src = fs.readFileSync(path.join(PANEL_DIR, rel), 'utf8');
      assert.ok(src.trimStart().startsWith('/**'), `${rel} has no doc comment`);
    }
  });
});
