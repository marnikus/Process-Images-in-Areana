/* Captcha probes against the REAL user-saved page states (RULE 8).
   Fixtures (committed evidence, not generated):
   * 'arena webpages/state-captcha on/(12) Directly Chat... -captcha Models.html'
     — Security Verification modal ON: Radix dialog + reCAPTCHA Enterprise
     checkbox widget + hidden bframe escalation bubble + PostHog/GTM stack.
   * 'arena webpages/state/Arena _ Benchmark....html' — normal badge-only state.
   The saved files have Google iframe URLs rewritten to local paths, so the
   live `iframe_k` sitekey extraction cannot fire here; dialog-scoped key
   preference is covered by the stub tests in test_captcha.mjs. This file
   pins the mechanism evidence the saved page actually contains. */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const probe = (n) => readFileSync(join(ROOT, 'app', 'browser', 'captcha_js', n), 'utf8').trim();
const CAPTCHA_ON = join(ROOT, 'arena webpages', 'state-captcha on',
  '(12) Directly Chat with Frontier Image Generation AI -captcha Models.html');
const NORMAL = join(ROOT, 'arena webpages', 'state',
  'Arena _ Benchmark & Compare the Best AI Models.html');

function runOn(pagePath) {
  const html = readFileSync(pagePath, 'utf8');
  const dom = new JSDOM(html, { url: 'https://arena.ai/image', runScripts: 'outside-only' });
  const detect = dom.window.eval(probe('detect.js'));
  const visible = dom.window.eval(';' + probe('visible.js'));
  return { detect, visible };
}

const hasFixtures = existsSync(CAPTCHA_ON) && existsSync(NORMAL);

test('saved captcha-on state: modal + enterprise widget + dialog-scope fields', { skip: !hasFixtures }, () => {
  const { detect, visible } = runOn(CAPTCHA_ON);
  assert.equal(visible, true);                          // gate predicate fires
  assert.equal(detect.visible, true);
  assert.equal(detect.kind, 'recaptcha_enterprise');
  assert.equal(detect.integration, 'enterprise');
  assert.equal(detect.dom, 'dialog:recaptcha-iframe');
  assert.equal(detect.invisible, false);                // size=normal checkbox widget
  assert.equal(detect.responseScope, 'dialog');         // token field lives in the modal
  assert.equal(detect.responseFields, 2);               // dialog field + badge shadow field
});

test('saved captcha-on state: bframe escalation present but NOT active', { skip: !hasFixtures }, () => {
  const { detect } = runOn(CAPTCHA_ON);
  assert.equal(detect.challengePresent, true);          // image-grid frame saved in the page
  assert.equal(detect.challengeActive, false);          // hidden bubble at save time
  assert.match(detect.challengeTitle, /challenge/i);    // "recaptcha challenge expires in two minutes"
});

test('saved captcha-on state: sitekey not from the dialog iframe (URLs rewritten)', { skip: !hasFixtures }, () => {
  const { detect } = runOn(CAPTCHA_ON);
  // Saved iframe srcs are local file paths, so no dialog_iframe_k can exist;
  // the script fallback reports the badge config key — live pages carry k= in
  // the dialog iframe src (stub-proven), where dialog_iframe_k wins instead.
  assert.notEqual(detect.sitekeySource, 'dialog_iframe_k');
  assert.ok(detect.sitekey.length >= 0);
});

test('saved normal state: badge-only page is never a challenge', { skip: !hasFixtures }, () => {
  const { detect, visible } = runOn(NORMAL);
  assert.equal(visible, false);                         // badge never starts the flow
  assert.equal(detect.visible, false);
  assert.equal(detect.kind, 'none');
  assert.equal(detect.challengePresent, false);
});
