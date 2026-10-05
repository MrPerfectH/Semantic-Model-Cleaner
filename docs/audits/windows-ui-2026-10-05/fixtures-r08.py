from pathlib import Path
import shutil,sys,json
sys.path.insert(0,'scripts')
from generate_ui_acceptance_fixture import generate_fixture
base=Path('.playwright-mcp/scenarios');base.mkdir(exist_ok=True)
generate_fixture(base/'rich')
shutil.copytree('tests/fixtures/calculation_group_dependencies',base/'incomplete',dirs_exist_ok=True)
model=base/'no-candidates/Only.SemanticModel/definition/tables';model.mkdir(parents=True,exist_ok=True)
(model/'Only.tmdl').write_text("table Only\n\tmeasure Value = 1\n",encoding='utf-8')
report=base/'no-candidates/Only.Report';report.mkdir(parents=True,exist_ok=True)
(report/'definition.pbir').write_text(json.dumps({'version':'4.0','datasetReference':{'byPath':{'path':'../Only.SemanticModel'}}}),encoding='utf-8')
(report/'definition').mkdir(exist_ok=True)
(report/'definition/report.json').write_text(json.dumps({'query':{'Measure':{'Expression':{'SourceRef':{'Entity':'Only'}},'Property':'Value'}}}),encoding='utf-8')
from pathlib import Path
import json
p=Path('.playwright-mcp/scenarios/no-candidates/Only.Report/definition/pages/Page/visuals/Visual/visual.json');p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps({'visual':{'visualType':'card','query':{'queryState':{'Values':{'projections':[{'field':{'Measure':{'Expression':{'SourceRef':{'Entity':'Only'}},'Property':'Value'}}}]}}}}}),encoding='utf-8')
