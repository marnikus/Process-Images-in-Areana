/* Recording DOM-observer probe — idempotent MutationObserver install +
   buffered flush (self-contained, CDP Runtime.evaluate). Entries are
   SUMMARIES (selector + counts + attr name + text length), never subtree
   serialisation — the snapshots carry the DOM truth. 500-entry cap,
   drop-oldest, so a busy page cannot grow the buffer without bound.
   Recording only observes; it never mutates the page (RULE 20). */
(() => {
  const w = window;
  if (w.__arenaRecMut && w.__arenaRecMutInst) return "already-installed";
  w.__arenaRecMut = w.__arenaRecMut || [];
  const sel = (el) => {
    try {
      if (!el || el.nodeType !== 1) return el ? "#text" : "?";
      let s = el.tagName.toLowerCase();
      if (el.id) return s + "#" + String(el.id).slice(0, 40);
      const cls = (el.className && typeof el.className === "string")
        ? el.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
      if (cls) s += "." + cls.slice(0, 60);
      return s;
    } catch (e) { return "?"; }
  };
  const push = (entry) => {
    const buf = w.__arenaRecMut;
    buf.push(entry);
    if (buf.length > 500) buf.splice(0, buf.length - 500);
  };
  const obs = new MutationObserver((muts) => {
    const now = new Date().toISOString();
    for (const m of muts.slice(0, 60)) {
      if (m.type === "childList") {
        push({ts: now, kind: "mutation", mut: "childList", sel: sel(m.target),
              added: m.addedNodes.length, removed: m.removedNodes.length});
      } else if (m.type === "attributes") {
        push({ts: now, kind: "mutation", mut: "attr", sel: sel(m.target),
              attr: String(m.attributeName || "").slice(0, 40)});
      } else {
        push({ts: now, kind: "mutation", mut: "text", sel: sel(m.target),
              len: String(m.target.nodeValue || "").length});
      }
    }
  });
  try {
    obs.observe(document.documentElement, {childList: true, subtree: true,
      attributes: true, characterData: true});
    w.__arenaRecMutInst = true;
    return "installed";
  } catch (e) { return "install-error: " + String(e).slice(0, 80); }
})()
