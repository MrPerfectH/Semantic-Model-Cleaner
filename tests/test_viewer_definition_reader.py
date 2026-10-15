"""Source-preserving Viewer reuse: Unicode, escaped refs, comments and large M."""
import shutil
import subprocess
from pathlib import Path
import pytest
STATIC = Path(__file__).parents[1] / "src/semantic_model_cleaner/static"
@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_source_projection(tmp_path):
    script = tmp_path / "reader.cjs"
    script.write_text("const assert=require('node:assert/strict'),path=require('node:path');\n['viewer-dax-format.js','viewer-code-tokens.js','definition-reader.js'].forEach(f=>require(path.join(process.argv[2],f)));\nconst cases=[\"// zażółć\\nVAR x = 'Ta''ble'[A]]B] /* preserve */ RETURN x + 1\",'IF([量]>0,\"hello \"\"world\"\" !\",BLANK())','-- comment\\n[Å]+1'];\nfor(const source of cases){\n assert.equal(SmcDefinition.tokens(source,'dax').map(t=>t.text).join(''),source);\n const draft=source+'\\n// draft';\n const result=SmcDefinition.presentation(source,'dax',true);\n assert.equal(SmcDefinition.presentation(source,'dax',false).text,source);\n assert.equal(draft,source+'\\n// draft');\n if(source.includes('preserve'))assert(result.text.includes('preserve'));\n}\nconst m='let\\n// zażółć\\n#\"A \"\"quoted\"\"\" = \"你好\",\\n'+Array.from({length:5000},(_,i)=>'v'+i+'=\"'+i+'\"').join(',\\n')+'\\nin #\"A \"\"quoted\"\"\"';\nassert.equal(SmcDefinition.tokens(m,'m').map(t=>t.text).join(''),m);\nassert.deepEqual(SmcDefinition.presentation(m,'m',true),{text:m,formatted:false});\nconst huge='1 + '.repeat(60000)+'1';\nassert.equal(SmcDefinition.presentation(huge,'dax',true).text,huge);\nassert(SmcDefinition.presentation(huge,'dax',true).error);\n", encoding="utf-8")
    result = subprocess.run([shutil.which("node"), str(script), str(STATIC)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
