"""Packaged file round trip on the Desktop diagnostic fixture (not visual acceptance)."""
from pathlib import Path
import hashlib, http.cookiejar, json, os, re, subprocess, sys, time, urllib.request, zipfile

root = Path('.playwright-mcp/desktop-v2').resolve()
out = Path('docs/audits/windows-ui-2026-10-05/package')
state_path = out / 'desktop-roundtrip.json'
app = Path('.playwright-mcp/desktop-package').resolve()
archive = Path('dist/semantic-model-cleaner-windows-x64-0.4.0b3.zip')
if not app.exists():
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(app)
env = os.environ.copy()
env.pop('PYTHONPATH', None)
env.pop('PYTHONHOME', None)
env['PATH'] = os.environ['SystemRoot'] + ';' + os.environ['SystemRoot'] + '/System32'
env['SMC_USER_DIR'] = str(app / 'user')
log_path = app / 'desktop-launcher.log'
with log_path.open('w', encoding='utf-8') as log:
    process = subprocess.Popen([str(app / 'Semantic Model Cleaner.exe'), str(root), '--port', '0', '--no-open-browser'], env=env, stdout=log, stderr=subprocess.STDOUT)
try:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        match = re.search(r'URL\s*:\s*(http://127\.0\.0\.1:\d+)', log_path.read_text(encoding='utf-8'))
        if match:
            break
        time.sleep(.2)
    assert match, 'Launcher URL missing'
    base = match.group(1)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    token = json.loads(opener.open(base + '/api/session').read())['token']
    def request(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={'Content-Type':'application/json', 'X-SMC-Token':token})
        result = json.loads(opener.open(req).read())
        assert result.get('ok'), result
        return result
    model = root / 'Synthetic Acceptance.SemanticModel'
    reports = [str(root / name) for name in ('Synthetic Executive.Report', 'Synthetic Operations.Report')]
    def hashes():
        return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and (p.suffix in ('.tmdl', '.json', '.pbir', '.pbism') or p.name == '.platform') and '.pbi' not in p.parts and '.smc' not in p.parts}
    if sys.argv[1] == 'apply':
        before = hashes()
        plan = request('/api/plans', {'model_path':str(model), 'report_paths':reports, 'operations':[{'kind':'actions','actions':[{'action':'delete','table':'Sales','name':'Safe Cleanup Candidate','item_type':'Measure'}]}]})['plan']
        assert hashes() == before
        request('/api/plans/' + plan['id'] + '/apply', {})
        request('/api/plans/' + plan['id'] + '/verify', {})
        after = hashes()
        assert after != before
        assert 'Safe Cleanup Candidate' not in (model / 'definition/tables/Sales.tmdl').read_text(encoding='utf-8')
        state = {'plan_id':plan['id'],'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'before':before,'after':after,'applied_and_verified':True,'runtime_acceptance':False,'runtime_reason':'Baseline report opens but refreshed visuals show query errors before cleaner changes.'}
        state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    else:
        state = json.loads(state_path.read_text(encoding='utf-8'))
        request('/api/plans/' + state['plan_id'] + '/restore', {})
        restored = hashes()
        assert restored == state['before'], 'Restored project metadata differs'
        state['restored_byte_exact'] = True
        state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    print(sys.argv[1] + ' verified')
finally:
    process.terminate()
    process.wait(timeout=10)
