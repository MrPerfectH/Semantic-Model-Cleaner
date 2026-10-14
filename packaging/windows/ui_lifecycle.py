"""Packaged workspace acceptance using a disposable demo and byte-exact recovery."""
from pathlib import Path
from smoke import _review_scope_and_analyze
import hashlib, json, os
from playwright.sync_api import sync_playwright
BASE=os.environ.get('SMC_TEST_URL','http://127.0.0.1:5108')
OUT=Path(os.environ.get('SMC_TEST_EVIDENCE',str(Path(os.environ.get('TEMP', '.')) / 'smc-ui-lifecycle'))); OUT.mkdir(parents=True,exist_ok=True)
def hashes(paths):
 return {str(f):hashlib.sha256(f.read_bytes()).hexdigest() for path in paths for f in Path(path).rglob('*') if f.is_file()}
def shot(page,name):
 page.wait_for_timeout(350);page.screenshot(path=str(OUT/(name+'.png')))
with sync_playwright() as p:
 browser=p.chromium.launch(channel=os.environ.get('SMC_BROWSER_CHANNEL') or None,headless=True); results=[]
 for layout in ('v2',):
  context=browser.new_context(viewport={'width':1366,'height':768});page=context.new_page();errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(BASE+'/?ui='+layout)
  page.get_by_role('button',name='Try demo',exact=True).filter(visible=True).first.click()
  page.wait_for_function("chosenModels.length === 1 && chosenReports.length > 0 && !document.querySelector('#btnAnalyze').disabled")
  paths=page.evaluate('chosenModels.concat(chosenReports).map(x=>x.path)'); before=hashes(paths)
  _review_scope_and_analyze(page);page.locator('#resultOverview').wait_for(state='visible')
  assert 'Safe applies to supported scanned metadata' in page.locator('#resultOverview').inner_text()
  shot(page,'r08-'+layout+'-results')
  # Real item link, queue, cancel a preview, then apply the same queue.
  page.locator('#tableBody .item-link').filter(has_text='Total Orders').click()
  shot(page,'r08-'+layout+'-evidence')
  page.locator('#item-tab-changes').click()
  page.locator('#detailBtnHide').click();page.locator('#detailBtnApply').click()
  prefix='objectReview'
  apply=page.locator('#'+prefix+'Apply');close=page.locator('#'+prefix+'Close')
  apply.wait_for(state='visible');page.wait_for_function('(id)=>!document.getElementById(id).disabled',arg=prefix+'Apply')
  shot(page,'r08-'+layout+'-preview');close.click();assert hashes(paths)==before
  page.locator('#detailBtnApply').click();apply.wait_for(state='visible');page.wait_for_function('(id)=>!document.getElementById(id).disabled',arg=prefix+'Apply');apply.click()
  page.wait_for_function('(id)=>document.getElementById(id).hidden',arg=prefix+'Apply')
  page.wait_for_function('(id)=>!document.getElementById(id).disabled',arg=prefix+'Close')
  assert hashes(paths)!=before
  assert page.evaluate("Array.from(actionStatus.values()).every(x=>!x.startsWith('Pending:'))")
  close.click();page.locator('#objectHistoryButton').click()
  row=page.locator('#objectReviewBody details').filter(has=page.locator('[data-restore-id]')).first
  row.locator('summary').first.click();row.locator('[data-verify-id]').click()
  page.wait_for_function('(id)=>document.getElementById(id).textContent.includes("Files: applied")',arg=prefix+'Status')
  row.locator('[data-restore-id]').click()
  apply.wait_for(state='visible');assert page.locator('#'+prefix+'Body pre').count()>0
  shot(page,'r08-'+layout+'-restore-review');apply.click()
  page.wait_for_function('(id)=>document.getElementById(id).textContent.includes("Original files restored")',arg=prefix+'Status')
  page.wait_for_function('(id)=>!document.getElementById(id).disabled',arg=prefix+'Close')
  assert hashes(paths)==before
  assert page.evaluate('pendingActions.size===0 && actionStatus.size===0')
  close.click();shot(page,'r08-'+layout+'-restored')
  assert not errors,errors
  results.append({'layout':layout,'roundtrip':'byte-exact','files':len(before),'page_errors':errors});context.close()
 browser.close()
 (OUT/'r08-lifecycle.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
 print(json.dumps(results))
