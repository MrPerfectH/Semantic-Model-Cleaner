from pathlib import Path
import os,tempfile,zipfile,subprocess,time,re,json,shutil
from playwright.sync_api import sync_playwright
out=Path('docs/audits/windows-ui-2026-10-05/package');root=Path(tempfile.mkdtemp(prefix='smc auto browser ')).resolve();process=None
try:
 app=root/'App Łódź';app.mkdir();profile=root/'isolated-browser';workspace=root/'empty';workspace.mkdir()
 with zipfile.ZipFile('dist/semantic-model-cleaner-windows-x64-0.4.0b3.zip') as z:z.extractall(app)
 env=os.environ.copy();env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
 env['PATH']=os.environ['SystemRoot']+';'+os.environ['SystemRoot']+'\\System32';env['SMC_USER_DIR']=str(root/'user')
 env['BROWSER']='"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --user-data-dir="'+str(profile)+'" --no-first-run --remote-debugging-port=0 %s'
 with (root/'launcher.log').open('w',encoding='utf-8') as log:
  process=subprocess.Popen([str(app/'Semantic Model Cleaner.exe'),str(workspace),'--port','0'],env=env,cwd=workspace,stdout=log,stderr=subprocess.STDOUT)
 deadline=time.monotonic()+40
 while time.monotonic()<deadline and not (profile/'DevToolsActivePort').exists():time.sleep(.2)
 assert (profile/'DevToolsActivePort').exists(),'No automatic isolated browser detected'
 log=(root/'launcher.log').read_text(encoding='utf-8');base=re.search(r'URL\s*:\s*(http://127\.0\.0\.1:\d+)',log).group(1)
 debugport=(profile/'DevToolsActivePort').read_text().splitlines()[0]
 with sync_playwright() as p:
  browser=p.chromium.connect_over_cdp('http://127.0.0.1:'+debugport)
  deadline=time.monotonic()+20;page=None
  while time.monotonic()<deadline:
   page=next((x for c in browser.contexts for x in c.pages if x.url.startswith(base)),None)
   if page:break
   time.sleep(.2)
  assert page,'Automatic browser did not navigate to launcher URL'
  page.get_by_role('button',name='Try demo',exact=True).filter(visible=True).first.wait_for();page.screenshot(path=str(out/'automatic-browser.png'))
  (out/'automatic-browser.json').write_text(json.dumps({'ok':True,'url':page.url,'browser':'isolated Edge via BROWSER environment override','personal_profile_used':False,'python_on_child_path':False},indent=2))
  browser.close()
 print('Automatic browser launch and welcome page verified')
finally:
 if process:process.terminate();process.wait(timeout=10)
 assert root.is_relative_to(Path(tempfile.gettempdir()).resolve())
 shutil.rmtree(root,ignore_errors=True)
