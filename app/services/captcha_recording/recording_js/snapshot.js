/* Sanitized parent-document checkpoint; no form values, scripts, or opaque tokens. */
(() => {
  try {
    const copy=document.documentElement.cloneNode(true);
    copy.querySelectorAll("script,style,noscript").forEach(x=>x.textContent="[REMOVED]");
    copy.querySelectorAll("input,textarea,select").forEach(x=>{
      x.removeAttribute("value"); if (x.tagName!=="SELECT") x.textContent="";
    });
    copy.querySelectorAll("*").forEach(x=>{
      for (const a of Array.from(x.attributes||[])) {
        if (/value|token|authorization|cookie|password|response/i.test(a.name)) x.setAttribute(a.name,"[REDACTED]");
      }
    });
    const html=copy.outerHTML.replace(/[A-Za-z0-9_-]{80,}/g,"[REDACTED_TOKEN]");
    return {ok:true,url:location.origin+location.pathname,title:document.title,
      viewport:{w:innerWidth,h:innerHeight,x:scrollX,y:scrollY},html};
  } catch (e) { return {ok:false,error:String(e)}; }
})()
