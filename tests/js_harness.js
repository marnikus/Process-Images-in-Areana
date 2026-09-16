// Execute the production availability probe against a small querySelector DOM port.
const fs = require('fs');
const {probe, fixture} = JSON.parse(fs.readFileSync(0, 'utf8'));
const element = (data = {}) => ({offsetParent: {}, disabled: false, complete: true, innerText: '', ...data});
const nodes = {};
if (fixture.prompt !== false) nodes['textarea[name="message"]'] = element(fixture.prompt);
if (fixture.send !== false) nodes['button[aria-label="Send message"]'] = element(fixture.send);
if (fixture.file !== false) nodes['input[type="file"]'] = element({offsetParent: null});
global.document = {
  querySelector: selector => nodes[selector] || null,
  querySelectorAll: selector => {
    if (selector === 'div.no-scrollbar img') return (fixture.outputs || []).map(element);
    if (selector.includes('animate-spin')) return (fixture.activity || []).map(element);
    if (selector.startsWith('iframe')) return (fixture.captcha || []).map(element);
    if (selector.startsWith('div[role="dialog"]')) return (fixture.dialogs || []).map(element);
    return [];
  }
};
console.log(JSON.stringify(eval(probe)));
