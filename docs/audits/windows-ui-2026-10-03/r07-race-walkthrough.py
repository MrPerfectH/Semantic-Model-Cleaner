from pathlib import Path
import json
from playwright.sync_api import sync_playwright
base=Path('.playwright-mcp/scenarios').resolve();out=Path('docs/audits/windows-ui-2026-10-03')
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
 page=b.new_page(viewport={'width':1366,'height':768});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://127.0.0.1:5107');page.locator('#scopeChip').click()
 held=[]
 def hold(route):held.append((route,route.fetch()))
 page.route('**/api/discover',hold)
 def openfolder(name):
  page.locator('#setupSection').get_by_role('button',name='Open Power BI Project',exact=True).click()
  page.wait_for_function("!document.querySelector('#btnExplorerDone').disabled")
  page.locator('#explorerPathInput').fill(str(base/name));page.locator('#btnExplorerGo').click()
  page.wait_for_function("!document.querySelector('#btnExplorerDone').disabled")
  page.locator('#btnExplorerDone').click();page.wait_for_timeout(100)
 openfolder('one');openfolder('separate')
 assert len(held)==2
 route,response=held[1];route.fulfill(response=response)
 page.wait_for_function("!document.querySelector('#scopeReview').hidden && document.querySelector('#scopeReview').innerText.includes('selected;')")
 route,response=held[0];route.fulfill(response=response);page.wait_for_timeout(200)
 assert 'separate' in page.locator('#projectStatus').inner_text()
 assert '1 connected Report(s) selected; 0 excluded' in page.locator('#scopeReview').inner_text()
 page.unroute('**/api/discover');held=[];page.route('**/api/demo',hold)
 page.locator('#btnLoadDemo').click();page.wait_for_timeout(100);openfolder('one')
 page.wait_for_function("!document.querySelector('#scopeReview').hidden && document.querySelector('#scopeReview').innerText.includes('1 excluded')")
 route,response=held[0];route.fulfill(response=response);page.wait_for_timeout(200)
 assert 'scenarios' in page.locator('#projectStatus').inner_text()
 assert '1 excluded' in page.locator('#scopeReview').inner_text()
 assert not errors
 b.close()
(out/'race-results.json').write_text(json.dumps({'old_project_response_ignored':True,'old_demo_response_ignored':True,'page_errors':errors},indent=2),encoding='utf-8')
print('Project and demo stale-response scenarios passed')
