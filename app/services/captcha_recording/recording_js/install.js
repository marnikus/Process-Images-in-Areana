/* Install one bounded MutationObserver for captcha diagnostics.
   Entries are SUMMARIES — path + tag/attrs/child-count/text-length — never
   cloned subtrees: cloning nodes inside the page's own observer callback was
   the one place where recording could visibly slow the captcha page down
   (observation neutrality; snapshots carry the content).
   ideal-size: standalone page agent; splitting breaks Runtime.evaluate contract. */
(() => {
  const KEY = "__arenaCaptchaRecorderV1";
  if (window[KEY] && window[KEY].observer) return {ok:true,reused:true};
  const state = {queue:[], dropped:0, maxQueue:1000, observer:null};
  const SECRET = /value|token|authorization|cookie|password|response/i;
  const clip = (v, n) => String(v == null ? "" : v).slice(0, n)
    .replace(/[A-Za-z0-9_-]{80,}/g, "[REDACTED_TOKEN]");
  const pathOf = (node) => {
    if (!node || node.nodeType !== 1) return "";
    const parts=[]; let cur=node;
    while (cur && cur.nodeType===1 && parts.length<8) {
      let part=cur.tagName.toLowerCase();
      if (cur.id && !/^radix-|^:r/.test(cur.id)) part += "#" + CSS.escape(cur.id);
      else if (cur.getAttribute && cur.getAttribute("role")) part += '[role="' + clip(cur.getAttribute("role"),40) + '"]';
      else if (cur.parentElement) {
        let same=0, index=0;
        const kids=cur.parentElement.children;
        for (let i=0; i<kids.length && i<100; i++) {
          if (kids[i].tagName===cur.tagName) { same++; if (kids[i]===cur) index=same; }
        }
        if (same>1) part += ":nth-of-type(" + index + ")";
      }
      parts.unshift(part); cur=cur.parentElement;
    }
    return parts.join(">");
  };
  const skeleton = (node) => {
    if (!node) return {};
    if (node.nodeType === 3) return {text_len: (node.data || "").length};
    if (node.nodeType !== 1) return {node_type: node.nodeType};
    const attrs={};
    for (const at of Array.from(node.attributes || [])) {
      attrs[at.name] = SECRET.test(at.name) ? "[REDACTED]" : clip(at.value, 60);
    }
    return {tag: node.tagName.toLowerCase(), attrs,
            kids: node.childElementCount || 0,
            text_len: (node.childElementCount ? 0 : (node.textContent || "").length)};
  };
  const push = (change) => {
    if (state.queue.length >= state.maxQueue) { state.dropped++; return; }
    state.queue.push(change);
  };
  state.observer = new MutationObserver((records) => {
    for (const rec of records) {
      if (rec.type === "childList") {
        rec.addedNodes.forEach(n=>push({op:"add",path:pathOf(rec.target),node:skeleton(n)}));
        rec.removedNodes.forEach(n=>push({op:"remove",path:pathOf(rec.target),node:skeleton(n)}));
      } else if (rec.type === "attributes") {
        const name=rec.attributeName || "";
        push({op:"attr",path:pathOf(rec.target),name,
          old:SECRET.test(name)?"[REDACTED]":clip(rec.oldValue,120),
          new:SECRET.test(name)?"[REDACTED]":clip(rec.target.getAttribute(name),120)});
      } else if (rec.type === "characterData") {
        push({op:"text",path:pathOf(rec.target.parentElement),
          old_len:(rec.oldValue||"").length,new_len:(rec.target.data||"").length});
      }
    }
  });
  state.observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,characterData:true,
    attributeOldValue:true,characterDataOldValue:true});
  window[KEY]=state;
  return {ok:true,reused:false};
})()
