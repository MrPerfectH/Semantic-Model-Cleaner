from pathlib import Path
import json
from playwright.sync_api import sync_playwright
out=Path('docs/audits/windows-ui-2026-10-05');results=[]
with sync_playwright() as p:
 b=p.chromium.launch(channel='msedge',headless=False,args=['--window-size=1366,900','--window-position=80,80'])
 context=b.new_context(no_viewport=True);page=context.new_page()
 for layout in ('v2','classic'):
  page.goto('http://127.0.0.1:5109/?ui='+layout);page.get_by_role('button',name='Try demo',exact=True).filter(visible=True).first.click();page.wait_for_function("!document.querySelector('#btnAnalyze').disabled");page.locator('#btnAnalyze').click();page.locator('#resultOverview').wait_for(state='visible')
  if layout=='classic':page.locator('#btnToggleSetup').click()
  page.bring_to_front()
  for zoom in (100,):
   page.wait_for_timeout(400)
   metrics=page.evaluate('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})');assert abs(metrics['dpr']-1.5*zoom/100)<.02;page.screenshot(path=str(out/f'r09-{layout}-native-zoom-{zoom}.png'));results.append({'layout':layout,'requested_zoom':zoom,**metrics})
   page.locator('#objectHistoryButton' if layout=='v2' else '#classicPlanHistory').click();page.locator('#objectReviewClose' if layout=='v2' else '#classicPlanClose').click()
 b.close()
(out/'r09-native-scaling.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))

