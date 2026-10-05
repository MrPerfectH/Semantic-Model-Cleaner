from pathlib import Path
import base64,json,hashlib,os,uuid
from playwright.sync_api import sync_playwright
BASE=os.environ.get('SMC_TEST_URL','http://127.0.0.1:5117');OUT=Path(os.environ.get('SMC_TEST_EVIDENCE','docs/audits/windows-ui-2026-10-05'))
OUT.mkdir(parents=True,exist_ok=True)
def activate(page,selector):
 target=page.locator(selector).filter(visible=True).first
 for _ in range(220):
  if target.evaluate('(e)=>e===document.activeElement'):
   page.keyboard.press('Enter');return
  page.keyboard.press('Tab')
 raise AssertionError('Unreachable by Tab: '+selector+' at '+page.evaluate('document.activeElement.tagName+":"+document.activeElement.id'))
def screenshot(page,path):
 # Capture the native view: compositor capture clips the image at real Edge zoom.
 session=page.context.new_cdp_session(page)
 data=session.send('Page.captureScreenshot',{'format':'png','fromSurface':False})
 Path(path).write_bytes(base64.b64decode(data['data']));session.detach()

def hashes(paths):return {str(f):hashlib.sha256(f.read_bytes()).hexdigest() for path in paths for f in Path(path).rglob('*') if f.is_file()}
extension=Path('.playwright-mcp/zoom-extension').resolve()
extension.mkdir(parents=True,exist_ok=True)
(extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Isolated SMC zoom verification','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
(extension/'worker.js').write_text('globalThis.setTestZoom=async(factor)=>{const tabs=await chrome.tabs.query({});const targets=tabs.filter(t=>t.url.startsWith("http://127.0.0.1:"));for(const tab of targets)await chrome.tabs.setZoom(tab.id,factor);return await Promise.all(targets.map(t=>chrome.tabs.getZoom(t.id)));};')
results=[]
with sync_playwright() as p:
 for layout in ('v2','classic'):
  for factor in map(float,os.environ.get('SMC_TEST_ZOOM_FACTORS','1.25,1.5').split(',')):
   ctx=p.chromium.launch_persistent_context(str(Path(f'.playwright-mcp/zoom-{layout}-{factor}-{uuid.uuid4().hex}').resolve()),channel='msedge',headless=False,no_viewport=True,args=[f'--disable-extensions-except={extension}',f'--load-extension={extension}','--enable-unsafe-extension-debugging','--window-size=1460,960']);page=ctx.pages[0];errors=[];external=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   def route(r):
    if not r.request.url.startswith(BASE):external.append(r.request.url);r.abort()
    else:r.continue_()
   page.route('**/*',route);page.goto(BASE+'/?ui='+layout)
   worker=ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event('serviceworker')
   worker.evaluate('()=>setTestZoom(1)');baseline_dpr=page.evaluate('devicePixelRatio')
   if os.environ.get('SMC_EXPECT_NATIVE_DPR'):assert baseline_dpr==float(os.environ['SMC_EXPECT_NATIVE_DPR']),baseline_dpr
   actual=worker.evaluate('(factor)=>setTestZoom(factor)',factor)
   page.wait_for_function('(expected)=>Math.abs(devicePixelRatio-expected)<0.01',arg=baseline_dpr*factor)
   metrics=page.evaluate('({dpr:devicePixelRatio,width:innerWidth,height:innerHeight,visualViewportScale:visualViewport.scale})')
   assert actual==[factor],actual
   assert metrics['visualViewportScale']==1

   if layout=='v2':
    activate(page,'#scopeChip');assert page.locator('#scopeDrawer').evaluate('(e)=>e.open')
    activate(page,'#btnBrowseModels');page.locator('#explorerModal[open]').wait_for()
    page.keyboard.press('Escape');page.wait_for_function("!document.querySelector('#explorerModal').open")
    assert page.locator('#scopeDrawer').evaluate('(e)=>e.open')
    assert page.evaluate("document.activeElement.id==='btnBrowseModels'")
    for _ in range(28):
     page.keyboard.press('Tab');assert page.evaluate("document.querySelector('#scopeDrawer').contains(document.activeElement)")
    page.keyboard.press('Escape');page.wait_for_function("!document.querySelector('#scopeDrawer').open")
    assert page.evaluate("document.activeElement.id==='scopeChip'")
    activate(page,'#welcomeCard button:has-text("Try demo")')
   else:activate(page,'#btnLoadDemo')
   page.wait_for_function("!document.querySelector('#btnAnalyze').disabled")
   paths=page.evaluate('chosenModels.concat(chosenReports).map(x=>x.path)');before=hashes(paths)
   activate(page,'#btnAnalyze');page.locator('#resultOverview').wait_for(state='visible')
   if layout=='classic':activate(page,'#btnToggleSetup')
   bounds=page.evaluate('''()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,
     overview:document.querySelector('#resultOverview').getBoundingClientRect().toJSON(),
     header:document.querySelector('.header').getBoundingClientRect().toJSON()})''')
   assert bounds['document'] <= bounds['viewport'] + 1, bounds
   assert bounds['overview']['right'] <= bounds['viewport'] + 1, bounds
   screenshot(page,OUT/f'r09-zoom-{layout}-{factor}-results.png')
   activate(page,'#tableBody .item-link:has-text("Total Orders")')
   if layout=='v2':activate(page,'[data-object-action=changes]')
   activate(page,'#detailBtnHide');activate(page,'#detailBtnApply')
   prefix='objectReview' if layout=='v2' else 'classicPlan'
   page.wait_for_function('(id)=>!document.getElementById(id).disabled && !document.getElementById(id).hidden',arg=prefix+'Apply')
   screenshot(page,OUT/f'r09-zoom-{layout}-{factor}-review.png')
   activate(page,'#'+prefix+'Apply')
   page.wait_for_function('(id)=>document.getElementById(id+"Apply").hidden && !document.getElementById(id+"Close").disabled',arg=prefix)
   activate(page,'#'+prefix+'Close');activate(page,'#objectHistoryButton' if layout=='v2' else '#classicPlanHistory')
   if layout=='v2':
    page.locator('[data-restore-id]').first.wait_for(state='attached')
    # Expand the receipt with the keyboard before reaching its actions.
    activate(page,'#objectReviewBody details:has([data-restore-id]) > summary')
    activate(page,'[data-verify-id]');page.wait_for_function("document.querySelector('#objectReviewStatus').textContent.includes('Files: applied')")
    activate(page,'[data-restore-id]')
   else:activate(page,'[data-plan-command="restore"]')
   page.wait_for_function('(id)=>!document.getElementById(id).hidden',arg=prefix+'Apply')
   activate(page,'#'+prefix+'Apply');page.wait_for_function('(id)=>document.getElementById(id).textContent.includes("Original files restored")',arg=prefix+'Status')
   page.wait_for_function('(id)=>!document.getElementById(id).disabled',arg=prefix+'Close')
   assert hashes(paths)==before;assert not errors,errors;assert not external,external
   results.append({'layout':layout,'zoom':factor,'native_dpr':baseline_dpr,'metrics':metrics,'bounds':bounds,'keyboard_roundtrip':True,'external_requests':external,'errors':errors});ctx.close()
(OUT/'r09-browser-zoom.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results))
