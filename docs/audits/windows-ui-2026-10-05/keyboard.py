from pathlib import Path
import json,hashlib,os
from playwright.sync_api import sync_playwright
BASE=os.environ.get('SMC_TEST_URL','http://127.0.0.1:5109');OUT=Path('docs/audits/windows-ui-2026-10-05')
def activate(page,selector):
 target=page.locator(selector).filter(visible=True).first
 for _ in range(220):
  if target.evaluate('(e)=>e===document.activeElement'):
   page.keyboard.press('Enter');return
  page.keyboard.press('Tab')
 raise AssertionError('Unreachable by Tab: '+selector+' at '+page.evaluate('document.activeElement.tagName+":"+document.activeElement.id'))
def hashes(paths):return {str(f):hashlib.sha256(f.read_bytes()).hexdigest() for path in paths for f in Path(path).rglob('*') if f.is_file()}
results=[]
with sync_playwright() as p:
 browser=p.chromium.launch(channel='msedge',headless=True)
 for layout in ('v2','classic'):
  for width,height in ((1366,768),(1280,800)):
   ctx=browser.new_context(viewport={'width':width,'height':height});page=ctx.new_page();errors=[];external=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   def route(r):
    if not r.request.url.startswith(BASE):external.append(r.request.url);r.abort()
    else:r.continue_()
   page.route('**/*',route);page.goto(BASE+'/?ui='+layout)
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
   page.screenshot(path=str(OUT/f'r09-{layout}-{width}-results.png'))
   activate(page,'#tableBody .item-link:has-text("Total Orders")')
   if layout=='v2':activate(page,'[data-object-action=changes]')
   activate(page,'#detailBtnHide');activate(page,'#detailBtnApply')
   prefix='objectReview' if layout=='v2' else 'classicPlan'
   page.wait_for_function('(id)=>!document.getElementById(id).disabled && !document.getElementById(id).hidden',arg=prefix+'Apply')
   page.screenshot(path=str(OUT/f'r09-{layout}-{width}-review.png'))
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
   results.append({'layout':layout,'viewport':[width,height],'keyboard_roundtrip':True,'external_requests':external,'errors':errors});ctx.close()
 browser.close()
(OUT/'r09-keyboard.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results))


