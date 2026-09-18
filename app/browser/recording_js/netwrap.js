/* Recording network probe — idempotent fetch/XHR wrapper + buffered flush.
   Records page-originated requests ONLY (what the app itself sends — the
   signal that matters for bot-vs-manual diffs). Never records bodies or
   headers (RULE 20); URLs are redacted on the Python side before storage.
   300-entry cap, drop-oldest. */
(() => {
  const w = window;
  if (w.__arenaRecNetInst) return "already-installed";
  w.__arenaRecNet = w.__arenaRecNet || [];
  const push = (entry) => {
    const buf = w.__arenaRecNet;
    buf.push(entry);
    if (buf.length > 300) buf.splice(0, buf.length - 300);
  };
  const urlOf = (u) => { try { return String(typeof u === "string" ? u : (u && u.url) || u); } catch (e) { return "?"; } };
  if (typeof w.fetch === "function" && !w.__arenaRecFetchWrapped) {
    const orig = w.fetch;
    w.fetch = function (input, init) {
      const started = new Date().toISOString();
      const url = urlOf(input);
      const method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
      return orig.apply(this, arguments).then((resp) => {
        push({ts: started, kind: "network", via: "fetch", method, url, status: resp ? resp.status : 0});
        return resp;
      }).catch((err) => {
        push({ts: started, kind: "network", via: "fetch", method, url, status: 0, error: String(err && err.name || "err").slice(0, 30)});
        throw err;
      });
    };
    w.__arenaRecFetchWrapped = true;
  }
  if (w.XMLHttpRequest && !w.__arenaRecXhrWrapped) {
    const proto = w.XMLHttpRequest.prototype;
    const origOpen = proto.open;
    const origSend = proto.send;
    proto.open = function (method, url) {
      this.__arenaRec = {method: String(method || "GET").toUpperCase(), url: urlOf(url)};
      return origOpen.apply(this, arguments);
    };
    proto.send = function () {
      const meta = this.__arenaRec || {method: "GET", url: "?"};
      const started = new Date().toISOString();
      this.addEventListener("loadend", () => {
        push({ts: started, kind: "network", via: "xhr", method: meta.method,
              url: meta.url, status: this.status || 0});
      }, {once: true});
      return origSend.apply(this, arguments);
    };
    w.__arenaRecXhrWrapped = true;
  }
  w.__arenaRecNetInst = true;
  return "installed";
})()
