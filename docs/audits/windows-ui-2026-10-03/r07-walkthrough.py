from pathlib import Path
import json, hashlib
from playwright.sync_api import sync_playwright
root=Path.cwd();out=root/'docs/audits/windows-ui-2026-10-03';base=root/'.playwright-mcp/scenarios'
def snapshot(): return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in base.rglob('*') if p.is_file()}
before=snapshot();results=[]
def settle(page):page.wait_for_timeout(350)
def shot(page,name):settle(page);page.screenshot(path=str(out/(name+'.png')))
def folder(page,path):
 page.wait_for_function("document.querySelector('#btnExplorerDone').disabled === false")
 page.locator('#explorerPathInput').fill(str(path));page.locator('#btnExplorerGo').click()
 page.wait_for_function("document.querySelector('#btnExplorerDone').disabled === false && document.querySelector('#explorerStatus').innerText === ''")
 page.locator('#btnExplorerDone').click()
def openproject(page,path):
 page.get_by_role('button',name='Open Power BI Project',exact=True).filter(visible=True).first.click();folder(page,path)
def reviewed(page):page.wait_for_function("!document.querySelector('#scopeReview').hidden && document.querySelector('#scopeReview').innerText.includes('connected Report(s) selected')")
def analyze(page):
 page.locator('#btnAnalyze').click();page.wait_for_function("!document.querySelector('#viewToolbar').classList.contains('hidden')")
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
 for layout in ('v2','classic'):
  for scenario in ('one','ambiguous','invalid','separate','demo'):
   print(layout,scenario,flush=True)
   ctx=browser.new_context(viewport={'width':1366,'height':768});page=ctx.new_page();errors=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto('http://127.0.0.1:5107/?ui='+layout);settle(page)
   (out/f'after-{layout}-{scenario}-initial-dom.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
   if scenario=='demo':
    page.get_by_role('button',name='Try demo',exact=True).filter(visible=True).first.click();reviewed(page)
    assert page.locator('#viewToolbar').evaluate("e=>e.classList.contains('hidden')")
    shot(page,f'after-{layout}-demo-scope');analyze(page);shot(page,f'after-{layout}-demo-result')
   elif scenario=='one':
    openproject(page,base/'one');reviewed(page)
    assert '1 connected Report(s) selected; 1 excluded' in page.locator('#scopeReview').inner_text()
    shot(page,f'after-{layout}-project-scope');analyze(page)
   elif scenario=='ambiguous':
    openproject(page,base/'ambiguous');page.locator('#projectModelSelect').wait_for(state='visible')
    assert page.locator('#btnAnalyze').is_disabled();shot(page,f'after-{layout}-ambiguous')
    model=next((base/'ambiguous').rglob('TestModel.SemanticModel'))
    page.locator('#projectModelSelect').select_option(str(model));reviewed(page);analyze(page)
   elif scenario=='invalid':
    openproject(page,base/'invalid');page.wait_for_function("document.querySelector('#projectStatus').innerText.includes('.pbix')")
    assert page.locator('#btnAnalyze').is_disabled();shot(page,f'after-{layout}-invalid')
    page.locator('#setupSection').get_by_role('button',name='Open Power BI Project',exact=True).click()
    page.wait_for_function("document.querySelector('#btnExplorerDone').disabled === false")
    page.locator('#explorerPathInput').fill(str(base/'absent'));page.locator('#btnExplorerGo').click()
    page.wait_for_function("document.querySelector('#explorerStatus').innerText.includes('Unable to open')")
    assert page.locator('#btnExplorerDone').is_disabled();page.locator('#btnExplorerCancel').click()
    page.locator('#btnLoadDemo').click();reviewed(page)
    # Recoverable network error retains scope and offers retry.
    page.route('**/api/demo',lambda route:route.abort())
    page.locator('#btnLoadDemo').click();page.wait_for_function("document.querySelector('#projectStatus').innerText.includes('Could not load')")
    assert page.locator('#btnLoadDemo').is_enabled();assert page.locator('#btnAnalyze').is_disabled();page.unroute('**/api/demo');page.locator('#btnLoadDemo').click();reviewed(page);analyze(page)
   else:
    if layout=='v2':page.locator('#scopeChip').click()
    page.locator('#btnBrowseModels').click();page.wait_for_function("document.querySelector('#btnExplorerDone').disabled === false")
    page.locator('#explorerPathInput').fill(str(base/'separate'/'Models'));page.locator('#btnExplorerGo').click()
    page.locator('.explorer-check').first.wait_for();page.locator('.explorer-check').first.check();page.locator('#btnExplorerDone').click()
    page.locator('#btnBrowseReports').click();page.wait_for_function("document.querySelector('#btnExplorerDone').disabled === false")
    page.locator('#explorerPathInput').fill(str(base/'separate'/'Reports'));page.locator('#btnExplorerGo').click()
    page.locator('.explorer-check').first.wait_for();page.locator('.explorer-check').first.check();page.locator('#btnExplorerDone').click()
    reviewed(page);shot(page,f'after-{layout}-separate-roots');analyze(page)
   assert not errors,errors
   results.append({'layout':layout,'scenario':scenario,'passed':True,'pageErrors':errors});ctx.close()
 browser.close()
assert snapshot()==before
(out/'walkthrough-results.json').write_text(json.dumps({'browser':'Installed Edge on MSI, isolated headless contexts','viewport':'1366x768','source_files_unchanged':True,'results':results},indent=2),encoding='utf-8')
print(json.dumps(results))

