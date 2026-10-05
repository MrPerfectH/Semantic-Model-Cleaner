from pathlib import Path
import json
from playwright.sync_api import sync_playwright
out=Path('docs/audits/windows-ui-2026-10-05')
audit=r'''() => {
 const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
 function bg(e){if(!e)return [255,255,255];let c=rgb(getComputedStyle(e).backgroundColor),a=c.length===4?c[3]:1,b=bg(e.parentElement);return c.length?c.slice(0,3).map((v,i)=>v*a+b[i]*(1-a)):b;}
 function lum(c){return c.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);}
 return Array.from(document.querySelectorAll('.btn:not(:disabled),.badge,.rail-row,.tab-count,th,.result-overview strong,.result-overview p,.result-facts span,.inventory-identity-meta,.object-note,label')).filter(e=>e.getClientRects().length&&!e.closest('[inert]')&&e.textContent.trim()).map(e=>{let s=getComputedStyle(e),fg=rgb(s.color),b=bg(e),f=lum(fg),g=lum(b);return {selector:e.id||e.className||e.tagName,text:e.textContent.trim().slice(0,60),color:s.color,bg:b,ratio:+((Math.max(f,g)+.05)/(Math.min(f,g)+.05)).toFixed(2)};});
}'''
with sync_playwright() as p:
 b=p.chromium.launch(channel='msedge');results=[]
 for layout in ('v2','classic'):
  page=b.new_page(viewport={'width':1280,'height':800});page.goto('http://127.0.0.1:5109/?ui='+layout);page.get_by_role('button',name='Try demo',exact=True).filter(visible=True).first.click();page.wait_for_function("!document.querySelector('#btnAnalyze').disabled");page.locator('#btnAnalyze').click();page.locator('#resultOverview').wait_for(state='visible')
  rows=page.evaluate(audit);fails=[r for r in rows if r['ratio']<4.5];print(layout,json.dumps(fails));results.append({'layout':layout,'measurements':rows,'failures':fails});page.close()
 b.close()
(out/'r09-contrast.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
