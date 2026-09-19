"""JS snippets for Arena controller (C3 split)."""
from ..captcha_probes import build_visible_js

JS_FIND_TEXTAREA = """
(() => {
  const sels = ['textarea[name="message"]','textarea[placeholder^="Describe"]','textarea[rows="1"]'];
  for (const sel of sels) { const el=document.querySelector(sel); if(el&&el.offsetParent!==null) return sel; }
  return null;
})
"""

JS_INSERT_PROMPT = """
((promptText) => {
  try {
    const sels=['textarea[name="message"]','textarea[placeholder^="Describe"]','textarea[rows="1"]'];
    let el=null;
    for(const sel of sels){
      const els=document.querySelectorAll(sel);
      for(const cand of els){ if(cand.offsetParent!==null){ el=cand; break; } }
      if(el) break;
    }
    if(!el){
      const any=document.querySelector(sels.join(','));
      return {ok:false,error:any?'textarea hidden':'textarea not found'};
    }
    el.focus();
    const setter=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
    setter.call(el,promptText);
    el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
    el.value=promptText;
    return {ok:true,len:el.value.length};
  } catch(e){return {ok:false,error:String(e)};}
})
"""

JS_SEND_STATE = """
(() => {
  try{
    const els=document.querySelectorAll('button[aria-label="Send message"]');
    if(!els.length) return {found:false,visible:false,enabled:false};
    let visible=false, enabled=false;
    for(const el of els){
      if(el.offsetParent===null) continue;
      visible=true;
      if(!el.disabled){ enabled=true; break; }
    }
    return {found:true,visible:visible,enabled:enabled};
  }catch(e){return {found:false,visible:false,enabled:false};}
})
"""

JS_VERIFY_PROMPT = """
((expected)=>{
  try{
    const el=document.querySelector('textarea[name="message"]');
    if(!el) return {ok:false,error:'not found'};
    return {ok:el.value===expected,actual:el.value};
  }catch(e){return {ok:false,error:String(e)};}
})
"""

JS_CLICK_SEND = """
(() => {
  try{
    const sels=['button[aria-label="Send message"]:not([disabled])','form button[aria-label="Send message"]','button[aria-label="Send message"]'];
    let btn=null; let used=null;
    for(const sel of sels){
      const els=document.querySelectorAll(sel);
      for(const el of els){
        if(el.offsetParent!==null&&!el.disabled){btn=el;used=sel;break;}
      }
      if(btn) break;
    }
    if(!btn) return {ok:false,error:'send not found'};
    btn.focus();
    btn.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
    btn.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
    btn.click();
    return {ok:true,sel:used};
  }catch(e){return {ok:false,error:String(e)};}
})
"""

JS_VERIFY_ATTACHMENT = """
((expectedFilename)=>{
  try{
    const sels=['div.flex.flex-wrap.gap-2 img[alt]','div.flex.flex-wrap.gap-2 img[src^="blob:"]','form img[src^="blob:"]'];
    for(const sel of sels){
      const els=document.querySelectorAll(sel);
      for(const el of els){
        if(el.offsetParent===null) continue;
        const alt=el.getAttribute('alt')||'';
        const src=el.getAttribute('src')||'';
        if(src.startsWith('blob:')) return {found:true,alt,src,matched:'blob'};
        if(alt) return {found:true,alt,src,matched:'alt'};
      }
    }
    return {found:false};
  }catch(e){return {found:false,error:String(e)};}
})
"""

JS_DOWNLOAD_IMAGE = """
async (src) => {
  const tryFetch=async(url)=>{
    try{
      const res=await fetch(url,{credentials:'include',mode:'cors'});
      if(!res.ok) return {ok:false,status:res.status,method:'fetch'};
      const buf=await res.arrayBuffer();
      const first=new Uint8Array(buf.slice(0,100));
      const text=new TextDecoder().decode(first).toLowerCase();
      if(text.includes('<html')||text.includes('<!doctype')) return {ok:false,error:'HTML',method:'fetch'};
      return {ok:true,bytes:Array.from(new Uint8Array(buf)),contentType:res.headers.get('content-type')||'',method:'fetch'};
    }catch(e){return {ok:false,error:e.toString(),method:'fetch'};}
  };
  const tryCanvas=async(url)=>{
    try{
      let imgEl=null;
      const all=document.querySelectorAll('img');
      for(const im of all){if(im.src===url){imgEl=im;break;}}
      if(!imgEl) imgEl=document.querySelector(`img[src="${url}"]`);
      if(!imgEl) return {ok:false,error:'img not found',method:'canvas'};
      if(!imgEl.complete||imgEl.naturalWidth===0){
        await new Promise((res,rej)=>{
          const to=setTimeout(()=>rej('timeout'),5000);
          imgEl.onload=()=>{clearTimeout(to);res();};
          imgEl.onerror=()=>{clearTimeout(to);rej('load error');};
          if(imgEl.complete){clearTimeout(to);res();}
        });
      }
      const canvas=document.createElement('canvas');
      canvas.width=imgEl.naturalWidth||imgEl.width;
      canvas.height=imgEl.naturalHeight||imgEl.height;
      if(canvas.width===0) return {ok:false,error:'zero dim',method:'canvas'};
      const ctx=canvas.getContext('2d');
      ctx.drawImage(imgEl,0,0);
      const dataUrl=canvas.toDataURL('image/png');
      const base64=dataUrl.split(',')[1];
      const binary=atob(base64);
      const bytes=new Uint8Array(binary.length);
      for(let i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);
      return {ok:true,bytes:Array.from(bytes),contentType:'image/png',method:'canvas'};
    }catch(e){return {ok:false,error:e.toString(),method:'canvas'};}
  };
  let r=await tryFetch(src);
  if(r.ok) return r;
  let c=await tryCanvas(src);
  if(c.ok) return c;
  return {ok:false,error:`Fetch ${JSON.stringify(r)} Canvas ${JSON.stringify(c)}`,src};
}
"""

JS_PAGE_READY = """
;(() => {
  const reasons=[];
  const checks=[{sel:'textarea[name="message"]',name:'prompt'},{sel:'button[aria-label="Send message"]',name:'send'},{sel:'input[type="file"]',name:'file'},{sel:'div.no-scrollbar',name:'output'}];
  for(const c of checks){
    const el=document.querySelector(c.sel);
    if(!el) reasons.push(c.name+' not found');
    else if(el.offsetParent===null) reasons.push(c.name+' not visible');
  }
  const dialogs=document.querySelectorAll('div[role="dialog"][data-state="open"]');
  for(const d of dialogs){ if(d.innerText&&d.innerText.includes('Security Verification')) reasons.push('Security dialog'); }
  return {ready:reasons.length===0,reasons};
})()
"""

JS_SECURITY_DIALOG = build_visible_js()

JS_IS_GENERATING = """
;(() => {
  let spinning=false; let count=0; let details=[];
  try{
    const spinners=document.querySelectorAll('div.animate-spin');
    for(const s of spinners){ if(s.offsetParent!==null){spinning=true;count++;details.push({label:'generating'});} }
  }catch(e){}
  return {spinning:spinning,spinCount:count,details:details,isGenerating:spinning};
})()
"""
