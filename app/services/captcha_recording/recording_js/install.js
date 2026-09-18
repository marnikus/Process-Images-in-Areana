/* Install one bounded MutationObserver for captcha diagnostics.
   ideal-size: standalone page agent; splitting breaks Runtime.evaluate contract. */
(() => {
  const KEY = "__arenaCaptchaRecorderV1";
  if (window[KEY] && window[KEY].observer) return {ok:true,reused:true};
  const state = {queue:[], dropped:0, maxQueue:1000, observer:null};
  const clip = (v, n=4096) => String(v == null ? "" : v).slice(0,n)
    .replace(/[A-Za-z0-9_-]{80,}/g,"[REDACTED_TOKEN]");
  const pathOf = (node) => {
    if (!node || node.nodeType !== 1) return "";
    const parts=[]; let cur=node;
    while (cur && cur.nodeType===1 && parts.length<8) {
      let part=cur.tagName.toLowerCase();
      if (cur.id && !/^radix-|^:r/.test(cur.id)) part += "#" + CSS.escape(cur.id);
      else if (cur.getAttribute("role")) part += '[role="' + clip(cur.getAttribute("role"),40) + '"]';
      else if (cur.parentElement) {
        const same=Array.from(cur.parentElement.children).filter(x=>x.tagName===cur.tagName);
        if (same.length>1) part += ":nth-of-type(" + (same.indexOf(cur)+1) + ")";
      }
      parts.unshift(part); cur=cur.parentElement;
    }
    return parts.join(">");
  };
  const scrub = (node) => {
    if (!node || node.nodeType !== 1) return clip(node && node.textContent,4096);
    const copy=node.cloneNode(true);
    copy.querySelectorAll("script,style,noscript").forEach(x=>x.textContent="[REMOVED]");
    copy.querySelectorAll("input,textarea,select").forEach(x=>{
      x.removeAttribute("value"); if (x.tagName!=="SELECT") x.textContent="";
    });
    copy.querySelectorAll("*").forEach(x=>{
      for (const a of Array.from(x.attributes||[])) {
        if (/value|token|authorization|cookie|password|response/i.test(a.name)) x.setAttribute(a.name,"[REDACTED]");
      }
    });
    return clip(copy.outerHTML,4096);
  };
  const push = (change) => {
    if (state.queue.length >= state.maxQueue) { state.dropped++; return; }
    state.queue.push(change);
  };
  state.observer = new MutationObserver((records) => {
    for (const rec of records) {
      if (rec.type === "childList") {
        rec.addedNodes.forEach(n=>push({op:"add",path:pathOf(rec.target),html:scrub(n)}));
        rec.removedNodes.forEach(n=>push({op:"remove",path:pathOf(rec.target),html:scrub(n)}));
      } else if (rec.type === "attributes") {
        const name=rec.attributeName||"";
        const secret=/value|token|authorization|cookie|password|response/i.test(name);
        push({op:"attr",path:pathOf(rec.target),name,
          old:secret?"[REDACTED]":clip(rec.oldValue,1024),
          new:secret?"[REDACTED]":clip(rec.target.getAttribute(name),1024)});
      } else if (rec.type === "characterData") {
        push({op:"text",path:pathOf(rec.target.parentElement),old:clip(rec.oldValue,1024),new:clip(rec.target.data,1024)});
      }
    }
  });
  state.observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,characterData:true,
    attributeOldValue:true,characterDataOldValue:true});
  window[KEY]=state;
  return {ok:true,reused:false};
})()
