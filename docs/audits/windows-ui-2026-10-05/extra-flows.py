from pathlib import Path
import json,hashlib
from playwright.sync_api import sync_playwright
out=Path('docs/audits/windows-ui-2026-10-05');results=[]
with sync_playwright() as p:
 b=p.chromium.launch(channel='msedge')
 for layout in ('v2','classic'):
  page=b.new_page();page.goto('http://127.0.0.1:5109/?ui='+layout)
  page.get_by_role('button',name='Open Power BI Project',exact=True).filter(visible=True).first.click();page.wait_for_function("!document.querySelector('#btnExplorerDone').disabled")
  path=str(Path('.playwright-mcp/scale').resolve());page.locator('#explorerPathInput').fill(path);page.locator('#btnExplorerGo').click();page.wait_for_function('(p)=>explorerCurrentPath===p && !document.querySelector("#btnExplorerDone").disabled',arg=path);page.locator('#btnExplorerDone').click();page.wait_for_function("!document.querySelector('#btnAnalyze').disabled")
  page.locator('#btnAnalyze').click();cancel=page.get_by_role('button',name='Cancel analysis',exact=True);cancel.wait_for();page.wait_for_function("Array.from(document.querySelectorAll('button')).some(x=>x.textContent==='Cancel analysis'&&!x.disabled)");cancel.click();page.wait_for_function("document.querySelector('#analyzeStatus').textContent.includes('cancelled')")
  assert page.locator('#btnAnalyze').is_enabled();page.screenshot(path=str(out/f'r09-{layout}-cancelled.png'))
  page.locator('#btnLoadDemo').click();page.wait_for_function("!document.querySelector('#btnAnalyze').disabled");page.locator('#btnAnalyze').click();page.locator('#resultOverview').wait_for(state='visible')
  roots=page.evaluate('chosenModels.concat(chosenReports).map(x=>x.path)')
  files=[f for r in roots for f in Path(r).rglob('*') if f.is_file()];before={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
  page.get_by_role('button',name='Review policy',exact=True).click();page.locator('#policyTabNaming').click();page.locator('#policyRuleId').fill('acceptance-rule');page.locator('#policyRulePrefix').fill('QA ');page.locator('#policyAddRule').click();page.locator('#policySaveRules').click();page.wait_for_function("document.querySelector('#policyStatus').textContent.includes('Naming rules saved')")
  assert before=={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
  page.screenshot(path=str(out/f'r09-{layout}-policy-saved.png'));results.append({'layout':layout,'real_job_cancelled':True,'policy_saved_without_model_report_changes':True});page.close()
 b.close()
(out/'r09-extra.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results))
