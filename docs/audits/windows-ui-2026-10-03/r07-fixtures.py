import json, shutil
from pathlib import Path
base=Path('.playwright-mcp/scenarios');base.mkdir(exist_ok=True)
source=Path('src/semantic_model_cleaner/demo_workspace')
for name in ('one','ambiguous','separate'):
 root=base/name
 if not root.exists(): shutil.copytree(source,root)
root=base/'one';report=next(root.rglob('*.Report'));other=root/'Unrelated.Report'
if not other.exists(): shutil.copytree(report,other)
(other/'definition.pbir').write_text(json.dumps({'datasetReference':{'byPath':{'path':'../Unrelated.SemanticModel'}}}),encoding='utf-8')
root=base/'ambiguous';model=next(root.rglob('*.SemanticModel'));other=model.with_name('Other.SemanticModel')
if not other.exists(): shutil.copytree(model,other)
(base/'invalid').mkdir(exist_ok=True);(base/'invalid'/'Only.pbix').write_bytes(b'placeholder')
