from pathlib import Path
import json
from playwright.sync_api import sync_playwright
out=Path('docs/audits/windows-ui-2026-10-05');results=[]
with sync_playwright() as p:
 browser=p.chromium.launch(channel='msedge',headless=True)
 for layout in ('v2','classic'):
  for case in ('rich','incomplete','no-candidates'):
   ctx=browser.new_context(viewport={'width':1366,'height':768});page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto('http://127.0.0.1:5108/?ui='+layout)
   page.get_by_role('button',name='Open Power BI Project',exact=True).filter(visible=True).first.click()
   page.wait_for_function("!document.querySelector('#btnExplorerDone').disabled")
   page.locator('#explorerPathInput').fill(str(Path('.playwright-mcp/scenarios',case).resolve()));page.locator('#btnExplorerGo').click()
   page.wait_for_function("!document.querySelector('#btnExplorerDone').disabled && document.querySelector('#explorerStatus').innerText === ''")
   page.wait_for_function('(path)=>explorerCurrentPath === path',arg=str(Path('.playwright-mcp/scenarios',case).resolve()))
   page.locator('#btnExplorerDone').click();page.wait_for_function("!document.querySelector('#btnAnalyze').disabled")
   page.locator('#btnAnalyze').click();page.locator('#resultOverview').wait_for(state='visible')
   text=page.locator('#resultOverview').inner_text();print(layout,case,text.encode('ascii','backslashreplace').decode())
   if case=='incomplete':assert 'Incomplete analysis coverage' in text
   if case=='no-candidates':assert 'No Safe cleanup candidates' in text
   if layout=='classic':page.locator('#btnToggleSetup').click()
   if case=='incomplete':page.locator('#analysisLimitationsBanner > summary').click()
   page.wait_for_timeout(350);page.screenshot(path=str(out/f'r08-{layout}-{case}.png'))
   assert not errors,errors
   results.append({'layout':layout,'scenario':case,'overview':text,'errors':errors});ctx.close()
 browser.close()
(out/'r08-scenarios.json').write_text(json.dumps(results,indent=2),encoding='utf-8')

