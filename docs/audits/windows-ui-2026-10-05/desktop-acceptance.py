"""File-side assertions for the native Power BI beta4 acceptance round trip."""
from pathlib import Path
import hashlib, http.cookiejar, json, sys, urllib.request

root = Path('.playwright-mcp/desktop-v4').resolve()
out = Path('docs/audits/windows-ui-2026-10-05/beta4-desktop')
out.mkdir(parents=True, exist_ok=True)
state_path = out / 'roundtrip.json'
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
base = 'http://127.0.0.1:5117'
token = json.loads(opener.open(base + '/api/session').read())['token']

def request(path, body):
    response = json.loads(opener.open(urllib.request.Request(base + path, data=json.dumps(body).encode(),
        headers={'Content-Type':'application/json', 'X-SMC-Token':token})).read())
    assert response.get('ok'), response
    return response

def hashes():
    return {str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob('*') if path.is_file() and '.pbi' not in path.parts
        and (path.suffix in ('.tmdl','.json','.pbir','.pbism') or path.name == '.platform')}

if sys.argv[1] == 'apply':
    before = hashes()
    model = root / 'Synthetic Acceptance.SemanticModel'
    reports = [str(root / name) for name in ('Synthetic Executive.Report','Synthetic Operations.Report')]
    plan = request('/api/plans', {'model_path':str(model),'report_paths':reports,'operations':[
        {'kind':'actions','actions':[{'action':'delete','table':'Sales','name':'Safe Cleanup Candidate','item_type':'Measure'}]}]})['plan']
    assert hashes() == before
    request('/api/plans/' + plan['id'] + '/apply', {})
    request('/api/plans/' + plan['id'] + '/verify', {})
    after = hashes()
    assert after != before
    assert 'Safe Cleanup Candidate' not in (model / 'definition/tables/Sales.tmdl').read_text(encoding='utf-8')
    release=json.loads(Path('dist/Semantic Model Cleaner/release.json').read_text(encoding='utf-8-sig'))
    archive=Path('dist/semantic-model-cleaner-windows-x64-'+release['version']+'.zip')
    state={'plan_id':plan['id'],'before':before,'after':after,'preview_read_only':True,'applied_and_verified':True,
        'version':release['version'],'source_revision':release['source_revision'],
        'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    state_path.write_text(json.dumps(state,indent=2),encoding='utf-8')
else:
    state=json.loads(state_path.read_text(encoding='utf-8'))
    request('/api/plans/' + state['plan_id'] + '/restore', {})
    assert hashes() == state['before']
    state['byte_exact_restore']=True
    state_path.write_text(json.dumps(state,indent=2),encoding='utf-8')
print(sys.argv[1] + ' passed')
